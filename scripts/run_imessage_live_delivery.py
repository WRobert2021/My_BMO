#!/usr/bin/env python3
"""Run the bounded manual Stage 9 live-delivery acceptance rehearsal."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import secrets
import stat
import sys
import threading
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iphone_relay import (
    MessageEvent,
    MessagesReader,
    RelayStateError,
    RelayStateStore,
    RetryPolicy,
)
from iphone_relay.live_source import LiveSourceError, disposable_messages_snapshot
from iphone_relay.sender import (
    DeliveryDisposition,
    EventTransport,
    HTTPEventTransport,
    RelaySender,
    TransportResponse,
)
from kiosk_receiver import (
    EVENT_PATH,
    ReceiverApplication,
    ReceiverServer,
    ReceiverStateStore,
    ReceiverStoreError,
    RequestAuthenticator,
)


KEY_ID = "stage9-manual-acceptance"
MAX_SCAN_LIMIT = 100
MAX_DELIVERY_ATTEMPTS = 500


class LiveDeliveryError(RuntimeError):
    """A bounded, content-free manual delivery failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DropFirstResponseTransport:
    def __init__(self, inner: EventTransport) -> None:
        self._inner = inner
        self._dropped = False

    def send(self, **kwargs: Any) -> TransportResponse:
        response = self._inner.send(**kwargs)
        if (
            not self._dropped
            and kwargs.get("path", EVENT_PATH) == EVENT_PATH
            and response.status_code in {200, 201}
        ):
            self._dropped = True
            raise TimeoutError("injected lost response")
        return response

    def close(self) -> None:
        self._inner.close()


class _RunningReceiver:
    def __init__(
        self,
        *,
        database_path: Path,
        shared_secret: bytes,
        port: int = 0,
    ) -> None:
        self.store = ReceiverStateStore(database_path)
        application = ReceiverApplication(
            store=self.store,
            authenticator=RequestAuthenticator(
                key_id=KEY_ID,
                shared_secret=shared_secret,
            ),
        )
        try:
            self.server = ReceiverServer(
                ("127.0.0.1", port),
                application,
                max_request_bytes=2 * 1024 * 1024,
                request_timeout_seconds=10,
            )
        except Exception:
            self.store.close()
            raise
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="stage9-manual-receiver",
            daemon=True,
        )
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.store.close()
        if self.thread.is_alive():
            raise LiveDeliveryError("receiver_cleanup_failed")


def _private_work_directory(path: Path) -> Path:
    unresolved = path.expanduser()
    if unresolved.is_symlink():
        raise LiveDeliveryError("work_directory_not_private")
    resolved = unresolved.resolve(strict=False)
    project_root = Path(__file__).resolve().parents[1]
    if resolved == project_root or resolved.is_relative_to(project_root):
        raise LiveDeliveryError("work_directory_inside_repository")
    if not resolved.is_dir():
        raise LiveDeliveryError("work_directory_unavailable")
    if stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise LiveDeliveryError("work_directory_not_private")
    return resolved


def _transport(port: int) -> HTTPEventTransport:
    return HTTPEventTransport(
        f"http://127.0.0.1:{port}",
        timeout_seconds=10,
        allow_insecure_loopback=True,
    )


def _sender(
    store: RelayStateStore,
    transport: EventTransport,
    secret: bytes,
) -> RelaySender:
    return RelaySender(
        store=store,
        transport=transport,
        key_id=KEY_ID,
        shared_secret=secret,
    )


def _discovery_report(batch: object) -> dict[str, Any]:
    event_counts = Counter(event.event_kind.value for event in batch.events)
    attachment_media: Counter[str] = Counter()
    attachment_count = 0
    attachment_bytes = 0
    for event in batch.events:
        if not isinstance(event, MessageEvent):
            continue
        for attachment in event.attachments:
            attachment_count += 1
            attachment_media[attachment.media_category.value] += 1
            if attachment.components:
                attachment_bytes += sum(
                    component.actual_bytes for component in attachment.components
                )
            elif attachment.actual_bytes is not None:
                attachment_bytes += attachment.actual_bytes
    return {
        "rows": batch.scanned_row_count,
        "events": dict(sorted(event_counts.items())),
        "issues": dict(sorted(Counter(issue.code for issue in batch.issues).items())),
        "attachments": attachment_count,
        "attachment_media": dict(sorted(attachment_media.items())),
        "attachment_bytes": attachment_bytes,
    }


def _fault_attempt(
    *,
    store: RelayStateStore,
    transport: EventTransport,
    secret: bytes,
    now_ms: int,
) -> tuple[str, str | None]:
    with _sender(store, transport, secret) as sender:
        result = sender.deliver_once(now_ms=now_ms)
    return result.disposition.value, result.error_code


def run_live_delivery(
    *,
    messages_root: Path,
    work_directory: Path,
    scan_limit: int = MAX_SCAN_LIMIT,
    delivery_limit: int = MAX_DELIVERY_ATTEMPTS,
) -> dict[str, Any]:
    """Run one bounded live-source acceptance pass with durable restarts."""

    if isinstance(scan_limit, bool) or not 3 <= scan_limit <= MAX_SCAN_LIMIT:
        raise LiveDeliveryError("scan_limit_invalid")
    if (
        isinstance(delivery_limit, bool)
        or not 3 <= delivery_limit <= MAX_DELIVERY_ATTEMPTS
    ):
        raise LiveDeliveryError("delivery_limit_invalid")
    work = _private_work_directory(work_directory)
    relay_path = work / "relay.db"
    receiver_path = work / "receiver.db"
    secret = secrets.token_bytes(32)
    wrong_secret = secrets.token_bytes(32)
    policy = RetryPolicy(
        initial_delay_ms=1,
        multiplier=2,
        max_delay_ms=8,
        max_attempts=10,
        lease_duration_ms=1_000,
    )

    receiver: _RunningReceiver | None = None
    relay_store: RelayStateStore | None = None
    try:
        with disposable_messages_snapshot(messages_root) as snapshot:
            relay_store = RelayStateStore(relay_path, retry_policy=policy)
            cursor = relay_store.source_cursor()
            reader = MessagesReader(
                snapshot.database_path,
                messages_root=snapshot.messages_root,
            )
            batch = reader.scan(after_rowid=cursor, limit=scan_limit)
            if batch.issues:
                raise LiveDeliveryError("source_parse_issues")
            if batch.scanned_row_count == 0:
                raise LiveDeliveryError("no_new_source_rows")
            next_page = reader.scan(
                after_rowid=batch.scanned_through_rowid,
                limit=1,
            )
            if next_page.scanned_row_count:
                raise LiveDeliveryError("backlog_exceeds_scan_limit")
            if len(batch.events) < 3 and relay_store.summary().acknowledged_count == 0:
                raise LiveDeliveryError("fault_matrix_requires_three_events")
            relay_store.commit_scan(batch, expected_after_rowid=cursor, now_ms=0)
            discovered = _discovery_report(batch)

            receiver = _RunningReceiver(
                database_path=receiver_path,
                shared_secret=secret,
            )
            port = receiver.port
            initial_receiver_events = receiver.store.summary().event_count
            faults: dict[str, dict[str, str | None]] = {}

            if initial_receiver_events == 0:
                disposition, code = _fault_attempt(
                    store=relay_store,
                    transport=_transport(port),
                    secret=wrong_secret,
                    now_ms=0,
                )
                if code != "invalid_signature":
                    raise LiveDeliveryError("authentication_failure_not_observed")
                faults["authentication"] = {
                    "disposition": disposition,
                    "error_code": code,
                }

                disposition, code = _fault_attempt(
                    store=relay_store,
                    transport=_DropFirstResponseTransport(_transport(port)),
                    secret=secret,
                    now_ms=0,
                )
                if code != "ack_timeout":
                    raise LiveDeliveryError("lost_ack_not_observed")
                committed_after_lost_ack = receiver.store.summary().event_count
                if committed_after_lost_ack != 1:
                    raise LiveDeliveryError("lost_ack_commit_count_invalid")
                faults["lost_ack"] = {
                    "disposition": disposition,
                    "error_code": code,
                }

                receiver.close()
                receiver = None
                disposition, code = _fault_attempt(
                    store=relay_store,
                    transport=_transport(port),
                    secret=secret,
                    now_ms=0,
                )
                if code != "transport_unavailable":
                    raise LiveDeliveryError("receiver_offline_not_observed")
                faults["receiver_offline"] = {
                    "disposition": disposition,
                    "error_code": code,
                }

                relay_store.close()
                relay_store = None
                receiver = _RunningReceiver(
                    database_path=receiver_path,
                    shared_secret=secret,
                    port=port,
                )
                relay_store = RelayStateStore(relay_path, retry_policy=policy)

            attempts = 0
            acknowledged_attempts = 0
            with _sender(relay_store, _transport(receiver.port), secret) as sender:
                while attempts < delivery_limit:
                    result = sender.deliver_once(now_ms=1_000 + attempts)
                    if result.disposition is DeliveryDisposition.IDLE:
                        break
                    attempts += 1
                    if result.disposition is DeliveryDisposition.ACKNOWLEDGED:
                        acknowledged_attempts += 1
                    elif result.error_code is not None:
                        raise LiveDeliveryError("backlog_delivery_failed")
                else:
                    raise LiveDeliveryError("delivery_limit_exceeded")

            relay_summary = relay_store.summary()
            receiver_summary = receiver.store.summary()
            if (
                relay_summary.pending_count
                or relay_summary.dead_letter_count
                or relay_summary.issue_count
                or receiver_summary.pending_event_count
                or receiver_summary.partial_attachment_count
                or relay_summary.acknowledged_count != receiver_summary.event_count
            ):
                raise LiveDeliveryError("durable_summary_mismatch")

            receiver.close()
            receiver = _RunningReceiver(
                database_path=receiver_path,
                shared_secret=secret,
                port=port,
            )
            reopened_receiver = receiver.store.summary()
            if reopened_receiver != receiver_summary:
                raise LiveDeliveryError("receiver_restart_mismatch")

            relay_store.close()
            relay_store = RelayStateStore(relay_path, retry_policy=policy)
            reopened_relay = relay_store.summary()
            if reopened_relay != relay_summary:
                raise LiveDeliveryError("relay_restart_mismatch")

            return {
                "status": "pass",
                "platform": {
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "physical_pi_required": True,
                },
                "source": {
                    "database_opened_directly": False,
                    "trio_stable": True,
                },
                "discovery": discovered,
                "faults": faults,
                "delivery": {
                    "attempts": attempts,
                    "acknowledged_attempts": acknowledged_attempts,
                    "acknowledged_events": reopened_relay.acknowledged_count,
                    "receiver_events": reopened_receiver.event_count,
                    "complete_attachments": reopened_receiver.complete_attachment_count,
                    "pending_events": reopened_receiver.pending_event_count,
                    "partial_attachments": reopened_receiver.partial_attachment_count,
                },
                "restart": {
                    "receiver": True,
                    "relay": True,
                },
            }
    finally:
        if receiver is not None:
            receiver.close()
        if relay_store is not None:
            relay_store.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "messages_root",
        type=Path,
        help="read-only mount of /var/mobile/Library/SMS",
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="existing private directory outside the repository",
    )
    parser.add_argument("--scan-limit", type=int, default=MAX_SCAN_LIMIT)
    parser.add_argument("--delivery-limit", type=int, default=MAX_DELIVERY_ATTEMPTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_live_delivery(
            messages_root=args.messages_root,
            work_directory=args.work_directory,
            scan_limit=args.scan_limit,
            delivery_limit=args.delivery_limit,
        )
    except KeyboardInterrupt:
        report = {"status": "interrupted"}
        exit_status = 130
    except (LiveDeliveryError, LiveSourceError, RelayStateError, ReceiverStoreError) as exc:
        report = {"status": "failed", "error_code": getattr(exc, "code", "state_error")}
        exit_status = 1
    except Exception:
        report = {"status": "failed", "error_code": "unexpected_delivery_error"}
        exit_status = 1
    else:
        exit_status = 0
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
