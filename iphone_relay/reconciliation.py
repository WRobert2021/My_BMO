"""Stage 6 bounded source lookback and durable receipt reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import http.client
import socket
import time
from typing import Callable
from uuid import uuid4

from kiosk_receiver.auth import sign_request
from kiosk_receiver.protocol import (
    MAX_RECONCILIATION_CANDIDATES,
    RECONCILIATION_PATH,
    ProtocolError,
    ReconciliationCandidate,
    ReconciliationReceipt,
    decode_reconciliation_response,
    encode_reconciliation_request,
    event_wire_digest,
)

from .reader import MessagesReader
from .sender import EventTransport, MAX_RESPONSE_BYTES, TransportResponse
from .state import QueueStatus, RelayStateStore
from .timestamps import APPLE_EPOCH


class ReconciliationWindowKind(StrEnum):
    RECENT = "recent"
    CALENDAR_MONTH = "calendar_month"


@dataclass(frozen=True, slots=True)
class ReconciliationWindow:
    kind: ReconciliationWindowKind
    start_timestamp_raw_ns: int
    end_timestamp_raw_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReconciliationWindowKind):
            raise ValueError("reconciliation window kind is invalid")
        for value, label in (
            (self.start_timestamp_raw_ns, "window start timestamp"),
            (self.end_timestamp_raw_ns, "window end timestamp"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 9_223_372_036_854_775_807
            ):
                raise ValueError(f"{label} is outside the supported range")
        if self.end_timestamp_raw_ns <= self.start_timestamp_raw_ns:
            raise ValueError("reconciliation window end must follow its start")

    @classmethod
    def recent(
        cls,
        *,
        end_utc: datetime,
        days: int = 7,
    ) -> ReconciliationWindow:
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ValueError("recent reconciliation days must be from 1 through 31")
        end = _utc(end_utc)
        start = end - timedelta(days=days)
        return cls(
            ReconciliationWindowKind.RECENT,
            _apple_nanoseconds(start),
            _apple_nanoseconds(end),
        )

    @classmethod
    def calendar_month(cls, *, year: int, month: int) -> ReconciliationWindow:
        if isinstance(year, bool) or not isinstance(year, int) or not 2001 <= year <= 9998:
            raise ValueError("reconciliation year is outside the supported range")
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError("reconciliation month must be from 1 through 12")
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (
            datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=timezone.utc)
        )
        return cls(
            ReconciliationWindowKind.CALENDAR_MONTH,
            _apple_nanoseconds(start),
            _apple_nanoseconds(end),
        )

    def contains(self, timestamp_raw_ns: int) -> bool:
        return self.start_timestamp_raw_ns <= timestamp_raw_ns < self.end_timestamp_raw_ns


class ReconciliationError(RuntimeError):
    """A reconciliation page failed without changing delivery state."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    window_kind: ReconciliationWindowKind
    source_rows_scanned: int
    source_events_observed: int
    source_events_inserted: int
    source_issue_count: int
    request_count: int
    candidate_count: int
    present_count: int
    missing_count: int
    conflict_count: int
    requeued_count: int
    confirmed_count: int


class RelayReconciler:
    """Re-scan a bounded window and selectively repair missing kiosk receipts."""

    def __init__(
        self,
        *,
        reader: MessagesReader,
        store: RelayStateStore,
        transport: EventTransport,
        key_id: str,
        shared_secret: bytes,
        page_size: int = MAX_RECONCILIATION_CANDIDATES,
        clock: Callable[[], float] = time.time,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= MAX_RECONCILIATION_CANDIDATES
        ):
            raise ValueError(
                "reconciliation page size must be from 1 through "
                f"{MAX_RECONCILIATION_CANDIDATES}"
            )
        sign_request(
            shared_secret,
            key_id=key_id,
            method="POST",
            path=RECONCILIATION_PATH,
            timestamp=0,
            nonce="reconciliation-validation",
        )
        self.reader = reader
        self.store = store
        self.transport = transport
        self.key_id = key_id
        self._shared_secret = shared_secret
        self.page_size = page_size
        self._clock = clock
        self._identifier_factory = identifier_factory or (lambda: str(uuid4()))

    def reconcile(
        self,
        window: ReconciliationWindow,
        *,
        now_ms: int | None = None,
    ) -> ReconciliationReport:
        if not isinstance(window, ReconciliationWindow):
            raise ValueError("window must be a ReconciliationWindow")

        source_rows = 0
        source_events = 0
        source_inserted = 0
        source_issues = 0
        after_rowid = 0
        while True:
            batch = self.reader.scan_window(
                start_timestamp_raw_ns=window.start_timestamp_raw_ns,
                end_timestamp_raw_ns=window.end_timestamp_raw_ns,
                after_rowid=after_rowid,
                limit=self.page_size,
            )
            if batch.scanned_row_count == 0:
                break
            committed = self.store.commit_reconciliation_batch(
                batch,
                expected_after_rowid=after_rowid,
                start_timestamp_raw_ns=window.start_timestamp_raw_ns,
                end_timestamp_raw_ns=window.end_timestamp_raw_ns,
                now_ms=now_ms,
            )
            source_rows += committed.scanned_row_count
            source_events += committed.observed_event_count
            source_inserted += committed.inserted_event_count
            source_issues += committed.issue_count
            after_rowid = batch.scanned_through_rowid

        request_count = 0
        candidate_count = 0
        present_count = 0
        missing_count = 0
        conflict_count = 0
        requeued_count = 0
        confirmed_count = 0
        page_after_rowid = 0
        page_after_event_id = ""
        while True:
            entries = self.store.list_entries_page(
                after_source_rowid=page_after_rowid,
                after_event_id=page_after_event_id,
                limit=self.page_size,
            )
            if not entries:
                break
            selected = tuple(
                entry for entry in entries if window.contains(entry.event.timestamp_raw_ns)
            )
            if selected:
                candidates = tuple(
                    ReconciliationCandidate(
                        event_id=entry.event.event_id,
                        event_digest=event_wire_digest(entry.event),
                    )
                    for entry in selected
                )
                receipts = self._request(candidates)
                request_count += 1
                candidate_count += len(candidates)
                for entry, receipt in zip(selected, receipts, strict=True):
                    if receipt.status == "present":
                        present_count += 1
                        if (
                            entry.status is not QueueStatus.ACKNOWLEDGED
                            and entry.attempt_count > 0
                        ):
                            self.store.acknowledge(entry.event.event_id, now_ms=now_ms)
                            confirmed_count += 1
                    elif receipt.status == "missing":
                        missing_count += 1
                        if self.store.requeue_acknowledged_for_reconciliation(
                            entry.event.event_id,
                            now_ms=now_ms,
                        ):
                            requeued_count += 1
                    else:
                        conflict_count += 1
            last = entries[-1]
            page_after_rowid = last.event.source_rowid
            page_after_event_id = last.event.event_id

        return ReconciliationReport(
            window_kind=window.kind,
            source_rows_scanned=source_rows,
            source_events_observed=source_events,
            source_events_inserted=source_inserted,
            source_issue_count=source_issues,
            request_count=request_count,
            candidate_count=candidate_count,
            present_count=present_count,
            missing_count=missing_count,
            conflict_count=conflict_count,
            requeued_count=requeued_count,
            confirmed_count=confirmed_count,
        )

    def _request(
        self,
        candidates: tuple[ReconciliationCandidate, ...],
    ) -> tuple[ReconciliationReceipt, ...]:
        request_id = self._identifier_factory()
        nonce = self._identifier_factory()
        try:
            body = encode_reconciliation_request(candidates, request_id)
            headers = sign_request(
                self._shared_secret,
                key_id=self.key_id,
                method="POST",
                path=RECONCILIATION_PATH,
                timestamp=int(self._clock()),
                nonce=nonce,
                body=body,
            )
            headers.update(
                {"Content-Type": "application/json", "Accept": "application/json"}
            )
            response = self.transport.send(
                path=RECONCILIATION_PATH,
                body=body,
                headers=headers,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise ReconciliationError("reconciliation_timeout") from exc
        except (ConnectionError, OSError) as exc:
            raise ReconciliationError("reconciliation_unavailable") from exc
        except (ProtocolError, ValueError, http.client.HTTPException) as exc:
            raise ReconciliationError("reconciliation_request_invalid") from exc
        return _validated_response(
            response,
            expected_request_id=request_id,
            expected_candidates=candidates,
        )


def _validated_response(
    response: TransportResponse,
    *,
    expected_request_id: str,
    expected_candidates: tuple[ReconciliationCandidate, ...],
) -> tuple[ReconciliationReceipt, ...]:
    if response.status_code != 200 or len(response.body) > MAX_RESPONSE_BYTES:
        raise ReconciliationError("reconciliation_rejected")
    content_type = next(
        (
            value
            for name, value in response.headers.items()
            if name.lower() == "content-type"
        ),
        "",
    )
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise ReconciliationError("malformed_reconciliation_response")
    try:
        decoded = decode_reconciliation_response(response.body)
    except ProtocolError as exc:
        raise ReconciliationError("malformed_reconciliation_response") from exc
    expected_ids = tuple(candidate.event_id for candidate in expected_candidates)
    received_ids = tuple(receipt.event_id for receipt in decoded.receipts)
    if decoded.request_id != expected_request_id or received_ids != expected_ids:
        raise ReconciliationError("reconciliation_response_mismatch")
    return decoded.receipts


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("reconciliation datetime must identify UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError("reconciliation datetime must identify UTC")
    return value.astimezone(timezone.utc)


def _apple_nanoseconds(value: datetime) -> int:
    instant = _utc(value)
    if instant < APPLE_EPOCH:
        raise ValueError("reconciliation window predates the Apple epoch")
    delta = instant - APPLE_EPOCH
    result = (
        delta.days * 86_400 * 1_000_000_000
        + delta.seconds * 1_000_000_000
        + delta.microseconds * 1_000
    )
    if result > 9_223_372_036_854_775_807:
        raise ValueError("reconciliation timestamp exceeds the supported range")
    return result
