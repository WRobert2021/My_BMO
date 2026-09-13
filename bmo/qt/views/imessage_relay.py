"""Qt/QML adapter for the private relay feed and contained media viewer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QUrl

from bmo.qt.views.base import QtHostedView


_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])\Z")
_MAX_COMPOSE_ACTION_BYTES = 40 * 1024


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
        feed_provider: Callable[[], Any] | None = None,
        prepare_outbound_text: Callable[..., Any] | None = None,
        confirm_outbound: Callable[..., bool] | None = None,
        cancel_outbound: Callable[[str], None] | None = None,
        outbound_status_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.status_provider = status_provider
        self.reconcile_recent = reconcile_recent
        self.reconcile_month = reconcile_month
        self.feed_provider = feed_provider or (lambda: ())
        self.prepare_outbound_text = prepare_outbound_text
        self.confirm_outbound = confirm_outbound
        self.cancel_outbound = cancel_outbound
        self.outbound_status_provider = outbound_status_provider
        self.error = ""
        self._attachments_by_path: dict[str, dict[str, object]] = {}
        self._selected_attachment_path: str | None = None
        self._reply_targets: dict[str, dict[str, object]] = {}
        self._composer: dict[str, object] | None = None
        self._confirmation: Any | None = None
        self._outbound_state = "idle"
        super().__init__(host, on_close=on_close)

    def payload(self) -> dict[str, object]:
        status = self.status_provider()
        report = dict(status.last_reconciliation or {})
        messages = []
        attachments_by_path: dict[str, dict[str, object]] = {}
        reply_targets: dict[str, dict[str, object]] = {}
        for item in self.feed_provider():
            if is_dataclass(item) and not isinstance(item, type):
                message = asdict(item)
            elif isinstance(item, dict):
                message = dict(item)
            else:
                continue
            for key in ("attachments", "reactions"):
                value = message.get(key)
                if isinstance(value, tuple):
                    message[key] = list(value)
            normalized_attachments: list[dict[str, object]] = []
            for raw_attachment in message.get("attachments", []):
                if not isinstance(raw_attachment, dict):
                    continue
                attachment = dict(raw_attachment)
                path = attachment.get("path")
                if (
                    attachment.get("available") is True
                    and isinstance(path, str)
                    and Path(path).is_absolute()
                ):
                    normalized_path = str(Path(path).resolve(strict=False))
                    attachment["source"] = QUrl.fromLocalFile(normalized_path)
                    attachments_by_path[normalized_path] = attachment
                normalized_attachments.append(attachment)
            message["attachments"] = normalized_attachments
            messages.append(message)
            message_id = message.get("message_id")
            chat_id = message.get("chat_id")
            participants = message.get("participant_ids")
            if (
                isinstance(message_id, str)
                and message_id
                and isinstance(chat_id, str)
                and chat_id
                and isinstance(participants, (tuple, list))
            ):
                recipient_ids = tuple(
                    item for item in participants if isinstance(item, str) and item
                )
                if recipient_ids:
                    reply_targets[message_id] = {
                        "recipient_ids": recipient_ids,
                        "chat_id": chat_id,
                    }
        self._attachments_by_path = attachments_by_path
        self._reply_targets = reply_targets
        if self._selected_attachment_path not in attachments_by_path:
            self._selected_attachment_path = None
        selected_attachment = self._selected_attachment()
        outbound_state = self._outbound_state
        outbound_error_code = None
        if self.outbound_status_provider is not None:
            try:
                outbound_status = self.outbound_status_provider()
                outbound_state = str(outbound_status.state)
                outbound_error_code = outbound_status.error_code
            except Exception:
                outbound_state = "unavailable"
                outbound_error_code = "outbound_status_unavailable"
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
            "phoneBacklogCount": status.phone_backlog_count,
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
            "incomingState": status.incoming_state,
            "incomingMessage": _incoming_message(
                status.incoming_state,
                status.incoming_error_code,
            ),
            "messages": messages,
            "selectedAttachment": selected_attachment,
            "outboundAvailable": self._outbound_available(),
            "composer": self._composer,
            "outboundConfirmation": _confirmation_payload(self._confirmation),
            "outboundState": outbound_state,
            "outboundMessage": _outbound_status_message(
                outbound_state,
                outbound_error_code,
            ),
        }

    def handle_action(self, action: str, value: str) -> None:
        self.error = ""
        if action == "relay_refresh":
            self.refresh()
            return
        if action == "relay_open_attachment":
            self._open_attachment(value)
            return
        if action == "relay_close_attachment":
            self._selected_attachment_path = None
            self.refresh()
            return
        if action == "relay_new_message":
            self._open_new_message()
            return
        if action == "relay_reply":
            self._open_reply(value)
            return
        if action == "relay_cancel_compose":
            self._composer = None
            self.refresh()
            return
        if action == "relay_review_text":
            self._review_text(value)
            return
        if action == "relay_confirm_outbound":
            self._confirm(value)
            return
        if action == "relay_cancel_outbound":
            self._cancel_confirmation(value)
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

    def _open_new_message(self) -> None:
        if not self._outbound_available():
            self.error = "Outbound messaging is unavailable."
        elif self._confirmation is not None:
            self.error = "Finish the current message confirmation first."
        else:
            self._composer = {"mode": "new", "recipient": ""}
        self.refresh()

    def _open_reply(self, message_id: str) -> None:
        target = self._reply_targets.get(message_id)
        if not self._outbound_available():
            self.error = "Outbound messaging is unavailable."
        elif self._confirmation is not None:
            self.error = "Finish the current message confirmation first."
        elif target is None:
            self.error = "That reply target is unavailable."
        else:
            recipients = target["recipient_ids"]
            assert isinstance(recipients, tuple)
            self._composer = {
                "mode": "reply",
                "recipient": ", ".join(recipients),
                "messageId": message_id,
            }
        self.refresh()

    def _review_text(self, value: str) -> None:
        if not self._outbound_available() or self._composer is None:
            self.error = "Outbound messaging is unavailable."
            self.refresh()
            return
        try:
            if len(value.encode("utf-8")) > _MAX_COMPOSE_ACTION_BYTES:
                raise ValueError
            draft = json.loads(value)
            if not isinstance(draft, dict) or set(draft) != {"recipient", "text"}:
                raise ValueError
            recipient = draft["recipient"]
            text = draft["text"]
            if not isinstance(recipient, str) or not isinstance(text, str):
                raise ValueError
            text = text.strip()
            if not text:
                self.error = "Enter a message."
                self.refresh()
                return
            mode = self._composer.get("mode")
            if mode == "reply":
                message_id = self._composer.get("messageId")
                target = self._reply_targets.get(str(message_id))
                if target is None:
                    self.error = "That reply target is unavailable."
                    self.refresh()
                    return
                recipient_ids = target["recipient_ids"]
                chat_id = target["chat_id"]
                reply_to_message_id = str(message_id)
            else:
                recipient_ids = tuple(
                    part.strip() for part in recipient.split(",") if part.strip()
                )
                chat_id = None
                reply_to_message_id = None
            self._confirmation = self.prepare_outbound_text(
                recipient_ids=recipient_ids,
                text=text,
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as exc:
            code = getattr(exc, "code", "outbound_draft_invalid")
            self.error = _outbound_error_message(str(code))
        else:
            self._composer = None
            self._outbound_state = "review"
        self.refresh()

    def _outbound_available(self) -> bool:
        return all(
            callback is not None
            for callback in (
                self.prepare_outbound_text,
                self.confirm_outbound,
                self.cancel_outbound,
                self.outbound_status_provider,
            )
        )

    def _confirm(self, confirmation_id: str) -> None:
        confirmation = _confirmation_payload(self._confirmation)
        if (
            self.confirm_outbound is None
            or confirmation is None
            or confirmation_id != confirmation["confirmation_id"]
        ):
            self.error = "Message confirmation is unavailable."
            self.refresh()
            return
        try:
            started = self.confirm_outbound(confirmation_id, self.refresh)
        except Exception as exc:
            code = getattr(exc, "code", "outbound_send_failed")
            self.error = _outbound_error_message(str(code))
            started = False
        if started:
            self._confirmation = None
            self._outbound_state = "submitting"
        elif not self.error:
            self.error = "Message could not be submitted."
        self.refresh()

    def _cancel_confirmation(self, confirmation_id: str) -> None:
        confirmation = _confirmation_payload(self._confirmation)
        if (
            self.cancel_outbound is None
            or confirmation is None
            or confirmation_id != confirmation["confirmation_id"]
        ):
            self.error = "Message confirmation is unavailable."
        else:
            try:
                self.cancel_outbound(confirmation_id)
            except Exception as exc:
                code = getattr(exc, "code", "outbound_cancel_failed")
                self.error = _outbound_error_message(str(code))
            else:
                self._confirmation = None
                self._outbound_state = "idle"
        self.refresh()

    def _open_attachment(self, value: str) -> None:
        candidate = Path(value)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            resolved = None
        if (
            resolved is None
            or not candidate.is_absolute()
            or candidate.is_symlink()
            or not resolved.is_file()
            or str(resolved) not in self._attachments_by_path
        ):
            self.error = "Attachment is unavailable."
        else:
            self._selected_attachment_path = str(resolved)
        self.refresh()

    def _selected_attachment(self) -> dict[str, object] | None:
        path = self._selected_attachment_path
        if path is None:
            return None
        attachment = self._attachments_by_path.get(path)
        if attachment is None:
            return None
        category = attachment.get("media_category")
        if category not in {"photo", "audio", "video"}:
            return None
        label = attachment.get("label")
        return {
            "path": path,
            "source": QUrl.fromLocalFile(path),
            "label": label if isinstance(label, str) else Path(path).name,
            "mediaCategory": category,
        }

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
        if int(report.get("scheduled", 0)) == 1:
            return "Phone accepted the bounded receipt check."
        observed = int(report.get("candidate_count", 0))
        repaired = int(report.get("requeued_count", 0))
        return f"Checked {observed}; requeued {repaired}."
    messages = {
        "phone_control_not_configured": "Phone reconciliation is pending Stage 12 implementation.",
        "phone_control_config_invalid": "Phone control configuration is unavailable.",
        "phone_control_start_failed": "Phone control could not start.",
        "phone_control_rejected": "Phone rejected the receipt check.",
        "phone_control_response_invalid": "Phone returned an invalid response.",
        "phone_unreachable": "The phone could not be reached.",
        "reconciliation_timeout": "Receipt check timed out.",
        "reconciliation_unavailable": "Receipt check is unavailable.",
        "reconciliation_failed": "Receipt check failed safely.",
        "reconciliation_start_failed": "Receipt check could not start.",
    }
    if state == "failed" or error_code is not None:
        return messages.get(error_code, "Receipt check is unavailable.")
    return "Choose a bounded receipt check."


def _incoming_message(state: str, error_code: str | None) -> str:
    if state == "connected":
        return "Phone relay is connected and the kiosk is listening."
    if state == "waiting":
        messages = {
            "phone_unreachable": "Kiosk is listening; waiting for the phone.",
            "phone_control_response_invalid": "Phone control response was invalid.",
        }
        return messages.get(
            error_code,
            "Kiosk is listening; phone control is not yet available.",
        )
    if state == "ready":
        if error_code == "phone_control_config_invalid":
            return "Kiosk is listening; phone control configuration is unavailable."
        if error_code == "phone_control_start_failed":
            return "Kiosk is listening; phone control could not start."
        return "Kiosk receiver is ready for the phone relay."
    if state == "closed":
        return "Incoming relay is stopped."
    messages = {
        "receiver_config_invalid": "Receiver configuration is unavailable.",
        "receiver_store_unavailable": "Receiver storage is unavailable.",
        "receiver_runtime_failed": "Receiver listener stopped unexpectedly.",
        "receiver_start_failed": "Receiver listener could not start.",
    }
    return messages.get(error_code, "Incoming relay is unavailable.")


def _confirmation_payload(confirmation: Any | None) -> dict[str, object] | None:
    if confirmation is None:
        return None
    if is_dataclass(confirmation) and not isinstance(confirmation, type):
        value = asdict(confirmation)
    elif isinstance(confirmation, dict):
        value = dict(confirmation)
    else:
        return None
    recipients = value.get("recipient_ids")
    if isinstance(recipients, tuple):
        value["recipient_ids"] = list(recipients)
    return value


def _outbound_error_message(code: str) -> str:
    messages = {
        "confirmation_already_pending": "Finish the current message confirmation first.",
        "confirmation_expired": "Message confirmation expired. Review it again.",
        "confirmation_mismatch": "Message confirmation did not match.",
        "outbound_draft_invalid": "Enter a valid recipient and message.",
        "recipient count is outside the supported range": "Enter a recipient.",
    }
    return messages.get(code, "Outbound message could not be prepared safely.")


def _outbound_status_message(state: str, error_code: str | None) -> str:
    if state == "awaiting_confirmation":
        return "Review this message before sending."
    if state in {"queued", "executing", "submitting"}:
        return "Sending message…"
    if state == "sent":
        return "Message accepted by the phone."
    if state == "uncertain":
        return "Message result is uncertain; it will not be sent again automatically."
    if state == "failed":
        messages = {
            "phone_unreachable": "The phone could not be reached.",
            "apple_send_not_enabled": "Phone outbound messaging is not enabled.",
            "outbound_state_unavailable": "Outbound message state is unavailable.",
        }
        return messages.get(error_code, "Message was not sent.")
    if state == "unavailable":
        return "Outbound messaging is unavailable."
    return ""


__all__ = ["QtIMessageRelayView"]
