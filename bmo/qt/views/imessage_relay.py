"""Qt/QML adapter for content-free iMessage Relay status and controls."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import re
from typing import Any

from bmo.qt.views.base import QtHostedView


_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])\Z")


class QtIMessageRelayView(QtHostedView):
    kind = "imessage_relay"
    title = "iMessage Relay"

    def __init__(
        self,
        host: Any,
        *,
        status_provider: Callable[[], Any],
        reconcile_recent: Callable[[Callable[[], None]], bool],
        reconcile_month: Callable[[int, int, Callable[[], None]], bool],
        on_close: Callable[[], None],
    ) -> None:
        self.status_provider = status_provider
        self.reconcile_recent = reconcile_recent
        self.reconcile_month = reconcile_month
        self.error = ""
        super().__init__(host, on_close=on_close)

    def payload(self) -> dict[str, object]:
        status = self.status_provider()
        report = dict(status.last_reconciliation or {})
        return {
            "serviceState": status.service_state,
            "serviceMessage": _service_message(
                status.service_state,
                status.service_error_code,
            ),
            "listening": status.listening,
            "receivedEvents": status.received_events,
            "pendingEvents": status.pending_events,
            "completeAttachments": status.complete_attachments,
            "partialAttachments": status.partial_attachments,
            "reconciliationState": status.reconciliation_state,
            "reconciliationMessage": _reconciliation_message(
                status.reconciliation_state,
                status.reconciliation_error_code,
                report,
            ),
            "canReconcile": status.reconciliation_available,
            "busy": status.reconciliation_state == "running",
            "currentMonth": datetime.now(timezone.utc).strftime("%Y-%m"),
            "error": self.error,
            "healthy": status.service_state == "available",
            "report": report,
        }

    def handle_action(self, action: str, value: str) -> None:
        self.error = ""
        if action == "relay_refresh":
            self.refresh()
            return
        if action == "relay_reconcile_recent":
            self._start(self.reconcile_recent(self.refresh))
            return
        if action == "relay_reconcile_month":
            match = _MONTH.fullmatch(value.strip())
            if match is None:
                self.error = "Enter a UTC month as YYYY-MM."
                self.refresh()
                return
            try:
                started = self.reconcile_month(
                    int(match.group(1)),
                    int(match.group(2)),
                    self.refresh,
                )
            except ValueError:
                self.error = "That UTC month is outside the supported range."
                self.refresh()
                return
            self._start(started)
            return
        super().handle_action(action, value)

    def _start(self, started: bool) -> None:
        if not started:
            status = self.status_provider()
            self.error = (
                "Reconciliation is already running."
                if status.reconciliation_state == "running"
                else "Reconciliation is unavailable."
            )
        self.refresh()


def _service_message(state: str, error_code: str | None) -> str:
    if state == "available":
        return "Receiver is listening."
    if state == "closed":
        return "Receiver is stopped."
    messages = {
        "receiver_config_invalid": "Receiver configuration is unavailable.",
        "receiver_store_unavailable": "Receiver storage is unavailable.",
        "receiver_runtime_failed": "Receiver listener stopped unexpectedly.",
        "receiver_start_failed": "Receiver listener could not start.",
    }
    return messages.get(error_code, "Receiver is unavailable.")


def _reconciliation_message(
    state: str,
    error_code: str | None,
    report: dict[str, object],
) -> str:
    if state == "running":
        return "Checking durable receipts…"
    if state == "complete":
        observed = int(report.get("candidate_count", 0))
        repaired = int(report.get("requeued_count", 0))
        return f"Checked {observed}; requeued {repaired}."
    messages = {
        "relay_config_invalid": "Relay state configuration is unavailable.",
        "relay_state_unavailable": "Relay state is unavailable.",
        "source_not_configured": "Read-only Messages source is not configured.",
        "source_unavailable": "Read-only Messages source is unavailable.",
        "reconciliation_timeout": "Receipt check timed out.",
        "reconciliation_unavailable": "Receipt check is unavailable.",
        "reconciliation_failed": "Receipt check failed safely.",
        "reconciliation_start_failed": "Receipt check could not start.",
    }
    if state == "failed" or error_code is not None:
        return messages.get(error_code, "Receipt check is unavailable.")
    return "Choose a bounded receipt check."


__all__ = ["QtIMessageRelayView"]
