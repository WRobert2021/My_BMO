"""Relay-owned durable discovery, retry, acknowledgement, and dead-letter state."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Iterator
from uuid import uuid4

from .contracts import NormalizedEvent, ParseIssue, ScanBatch
from .errors import (
    CursorConflictError,
    RelayStateError,
    StateClosedError,
    StateDatabaseError,
    StateIntegrityError,
    StateSchemaError,
    StateSecurityError,
    StateTransitionError,
)
from .state_codec import decode_event, encode_event


STATE_SCHEMA_VERSION = 1
STATE_APPLICATION_ID = 0x494D524C  # ASCII "IMRL"
DEFAULT_SOURCE_KEY = "messages"
MAX_SOURCE_KEY_LENGTH = 64
MAX_ERROR_CODE_LENGTH = 64
MAX_ISSUE_CODE_LENGTH = 64
MAX_ISSUE_DETAIL_LENGTH = 512
MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
MAX_RECONCILIATION_PAGE_SIZE = 20

_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_APPLE_DATABASE_NAMES = {
    "chat.db",
    "chat.db-shm",
    "chat.db-wal",
    "sms.db",
    "sms.db-shm",
    "sms.db-wal",
}


class QueueStatus(StrEnum):
    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    RETRY_WAIT = "retry_wait"
    ACKNOWLEDGED = "acknowledged"
    DEAD_LETTER = "dead_letter"


class AttemptOutcome(StrEnum):
    IN_FLIGHT = "in_flight"
    FAILED = "failed"
    ACKNOWLEDGED = "acknowledged"
    LEASE_EXPIRED = "lease_expired"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    initial_delay_ms: int = 30_000
    multiplier: int = 2
    max_delay_ms: int = 15 * 60_000
    max_attempts: int = 5
    lease_duration_ms: int = 60_000

    def __post_init__(self) -> None:
        for name in (
            "initial_delay_ms",
            "multiplier",
            "max_delay_ms",
            "max_attempts",
            "lease_duration_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
            if value > MAX_SQLITE_INTEGER:
                raise ValueError(f"{name} exceeds SQLite's integer range")
        if self.max_delay_ms < self.initial_delay_ms:
            raise ValueError("max_delay_ms cannot be less than initial_delay_ms")

    def delay_after_attempt(self, attempt_count: int) -> int:
        if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
            raise ValueError("attempt_count must be a positive integer")
        if attempt_count <= 0:
            raise ValueError("attempt_count must be a positive integer")
        if self.multiplier == 1:
            return self.initial_delay_ms
        delay = self.initial_delay_ms
        for _ in range(attempt_count - 1):
            if delay >= self.max_delay_ms:
                return self.max_delay_ms
            delay = min(delay * self.multiplier, self.max_delay_ms)
        return delay


@dataclass(frozen=True, slots=True)
class QueueEntry:
    event: NormalizedEvent
    status: QueueStatus
    attempt_count: int
    retry_cycle_attempt_count: int
    discovered_at_ms: int
    next_attempt_at_ms: int | None
    last_attempt_at_ms: int | None
    last_error_code: str | None
    acknowledged_at_ms: int | None
    dead_lettered_at_ms: int | None


@dataclass(frozen=True, slots=True)
class AttemptLease:
    attempt_id: str
    event: NormalizedEvent
    attempt_number: int
    started_at_ms: int
    lease_expires_at_ms: int


@dataclass(frozen=True, slots=True)
class DeliveryAttemptRecord:
    attempt_id: str
    event_id: str
    attempt_number: int
    started_at_ms: int
    finished_at_ms: int | None
    outcome: AttemptOutcome
    error_code: str | None


@dataclass(frozen=True, slots=True)
class StoredIssue:
    source_key: str
    source_rowid: int | None
    code: str
    detail: str
    first_seen_at_ms: int
    last_seen_at_ms: int
    occurrence_count: int


@dataclass(frozen=True, slots=True)
class StateSummary:
    source_key: str
    scanned_through_rowid: int
    queued_count: int
    in_flight_count: int
    retry_wait_count: int
    acknowledged_count: int
    dead_letter_count: int
    issue_count: int

    @property
    def pending_count(self) -> int:
        return self.queued_count + self.in_flight_count + self.retry_wait_count


@dataclass(frozen=True, slots=True)
class ReconciliationCommitResult:
    scanned_row_count: int
    observed_event_count: int
    inserted_event_count: int
    issue_count: int


class RelayStateStore:
    """Own one private SQLite database for relay discovery and delivery state."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.database_path = _validated_state_path(database_path)
        self.retry_policy = retry_policy or RetryPolicy()
        self._connection: sqlite3.Connection | None = None
        created = _create_private_file_if_missing(self.database_path)
        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=5.0,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
            self._initialize_or_validate_schema(created=created)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA journal_mode = WAL")
        except RelayStateError:
            self.close()
            raise
        except sqlite3.Error as exc:
            self.close()
            raise StateDatabaseError("relay state database could not be opened") from exc

    def __enter__(self) -> RelayStateStore:
        self._require_connection()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            connection.close()

    def source_cursor(self, source_key: str = DEFAULT_SOURCE_KEY) -> int:
        source_key = _validated_name(source_key, "source key", MAX_SOURCE_KEY_LENGTH)
        row = self._execute_read_one(
            "SELECT scanned_through_rowid FROM source_cursors WHERE source_key = ?",
            (source_key,),
        )
        return int(row["scanned_through_rowid"]) if row is not None else 0

    def commit_scan(
        self,
        batch: ScanBatch,
        *,
        expected_after_rowid: int,
        source_key: str = DEFAULT_SOURCE_KEY,
        now_ms: int | None = None,
    ) -> None:
        """Atomically persist a parser batch and its source observation cursor."""

        source_key = _validated_name(source_key, "source key", MAX_SOURCE_KEY_LENGTH)
        expected_after_rowid = _nonnegative_int(expected_after_rowid, "expected cursor")
        observed_at_ms = _timestamp_ms(now_ms)
        _validate_scan_batch(batch, expected_after_rowid)

        encoded_events: list[tuple[NormalizedEvent, str, str]] = []
        for event in batch.events:
            payload_json, payload_digest = encode_event(event)
            decoded = decode_event(payload_json, payload_digest)
            if decoded != event:
                raise StateIntegrityError("normalized event failed its canonical round trip")
            encoded_events.append((event, payload_json, payload_digest))

        with self._transaction() as connection:
            cursor_row = connection.execute(
                "SELECT scanned_through_rowid FROM source_cursors WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            current_cursor = int(cursor_row["scanned_through_rowid"]) if cursor_row else 0
            replay = (
                expected_after_rowid < current_cursor
                and batch.scanned_through_rowid <= current_cursor
            )
            if expected_after_rowid != current_cursor and not replay:
                raise CursorConflictError("scan was based on a stale source cursor")

            inserted_count = 0
            for event, payload_json, payload_digest in encoded_events:
                existing = connection.execute(
                    """
                    SELECT source_rowid, event_kind, payload_sha256
                    FROM relay_events
                    WHERE event_id = ?
                    """,
                    (event.event_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        int(existing["source_rowid"]) != event.source_rowid
                        or existing["event_kind"] != event.event_kind.value
                        or existing["payload_sha256"] != payload_digest
                    ):
                        raise StateIntegrityError(
                            "stable event ID conflicts with previously stored content"
                        )
                    continue
                connection.execute(
                    """
                    INSERT INTO relay_events(
                        event_id, source_rowid, event_kind, payload_json,
                        payload_sha256, status, discovered_at_ms,
                        next_attempt_at_ms, attempt_count,
                        retry_cycle_attempt_count
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 0, 0)
                    """,
                    (
                        event.event_id,
                        event.source_rowid,
                        event.event_kind.value,
                        payload_json,
                        payload_digest,
                        observed_at_ms,
                        observed_at_ms,
                    ),
                )
                inserted_count += 1

            for issue in batch.issues:
                self._store_issue(connection, source_key, issue, observed_at_ms)

            if not replay:
                connection.execute(
                    """
                    INSERT INTO source_cursors(source_key, scanned_through_rowid, updated_at_ms)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_key) DO UPDATE SET
                        scanned_through_rowid = excluded.scanned_through_rowid,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (source_key, batch.scanned_through_rowid, observed_at_ms),
                )
            connection.execute(
                """
                INSERT INTO scan_commits(
                    source_key, expected_after_rowid, scanned_through_rowid,
                    scanned_row_count, discovered_event_count, issue_count,
                    inserted_event_count, replay, committed_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_key,
                    expected_after_rowid,
                    batch.scanned_through_rowid,
                    batch.scanned_row_count,
                    len(batch.events),
                    len(batch.issues),
                    inserted_count,
                    int(replay),
                    observed_at_ms,
                ),
            )

    def commit_reconciliation_batch(
        self,
        batch: ScanBatch,
        *,
        expected_after_rowid: int,
        start_timestamp_raw_ns: int,
        end_timestamp_raw_ns: int,
        source_key: str = DEFAULT_SOURCE_KEY,
        now_ms: int | None = None,
    ) -> ReconciliationCommitResult:
        """Persist one bounded lookback page without advancing the live cursor."""

        source_key = _validated_name(source_key, "source key", MAX_SOURCE_KEY_LENGTH)
        expected_after_rowid = _nonnegative_int(expected_after_rowid, "expected cursor")
        start = _nonnegative_int(start_timestamp_raw_ns, "window start timestamp")
        end = _nonnegative_int(end_timestamp_raw_ns, "window end timestamp")
        if end <= start:
            raise StateIntegrityError("reconciliation window end must follow its start")
        observed_at_ms = _timestamp_ms(now_ms)
        _validate_reconciliation_batch(
            batch,
            expected_after_rowid=expected_after_rowid,
            start_timestamp_raw_ns=start,
            end_timestamp_raw_ns=end,
        )

        encoded_events: list[tuple[NormalizedEvent, str, str]] = []
        for event in batch.events:
            payload_json, payload_digest = encode_event(event)
            if decode_event(payload_json, payload_digest) != event:
                raise StateIntegrityError(
                    "reconciliation event failed its canonical round trip"
                )
            encoded_events.append((event, payload_json, payload_digest))

        inserted_count = 0
        with self._transaction() as connection:
            for event, payload_json, payload_digest in encoded_events:
                existing = connection.execute(
                    """
                    SELECT source_rowid, event_kind, payload_sha256
                    FROM relay_events WHERE event_id = ?
                    """,
                    (event.event_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        int(existing["source_rowid"]) != event.source_rowid
                        or existing["event_kind"] != event.event_kind.value
                        or existing["payload_sha256"] != payload_digest
                    ):
                        raise StateIntegrityError(
                            "stable event ID conflicts with reconciled content"
                        )
                    continue
                connection.execute(
                    """
                    INSERT INTO relay_events(
                        event_id, source_rowid, event_kind, payload_json,
                        payload_sha256, status, discovered_at_ms,
                        next_attempt_at_ms, attempt_count,
                        retry_cycle_attempt_count
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 0, 0)
                    """,
                    (
                        event.event_id,
                        event.source_rowid,
                        event.event_kind.value,
                        payload_json,
                        payload_digest,
                        observed_at_ms,
                        observed_at_ms,
                    ),
                )
                inserted_count += 1
            for issue in batch.issues:
                self._store_issue(connection, source_key, issue, observed_at_ms)

        return ReconciliationCommitResult(
            scanned_row_count=batch.scanned_row_count,
            observed_event_count=len(batch.events),
            inserted_event_count=inserted_count,
            issue_count=len(batch.issues),
        )

    def claim_next(self, *, now_ms: int | None = None) -> AttemptLease | None:
        """Lease the oldest eligible event for one delivery attempt."""

        claimed_at_ms = _timestamp_ms(now_ms)
        with self._transaction() as connection:
            self._expire_leases(connection, claimed_at_ms)
            row = connection.execute(
                """
                SELECT *
                FROM relay_events
                WHERE status IN ('queued', 'retry_wait')
                  AND next_attempt_at_ms <= ?
                ORDER BY source_rowid ASC, discovered_at_ms ASC, event_id ASC
                LIMIT 1
                """,
                (claimed_at_ms,),
            ).fetchone()
            if row is None:
                return None
            attempt_number = int(row["attempt_count"]) + 1
            retry_cycle_attempt_count = int(row["retry_cycle_attempt_count"]) + 1
            attempt_id = str(uuid4())
            lease_expires_at_ms = _bounded_add(
                claimed_at_ms,
                self.retry_policy.lease_duration_ms,
                "lease expiration",
            )
            connection.execute(
                """
                INSERT INTO delivery_attempts(
                    attempt_id, event_id, attempt_number, started_at_ms, outcome
                ) VALUES (?, ?, ?, ?, 'in_flight')
                """,
                (attempt_id, row["event_id"], attempt_number, claimed_at_ms),
            )
            connection.execute(
                """
                UPDATE relay_events
                SET status = 'in_flight', attempt_count = ?,
                    retry_cycle_attempt_count = ?,
                    last_attempt_at_ms = ?, current_attempt_id = ?,
                    lease_expires_at_ms = ?, last_error_code = NULL
                WHERE event_id = ?
                """,
                (
                    attempt_number,
                    retry_cycle_attempt_count,
                    claimed_at_ms,
                    attempt_id,
                    lease_expires_at_ms,
                    row["event_id"],
                ),
            )
            event = decode_event(row["payload_json"], row["payload_sha256"])
            return AttemptLease(
                attempt_id=attempt_id,
                event=event,
                attempt_number=attempt_number,
                started_at_ms=claimed_at_ms,
                lease_expires_at_ms=lease_expires_at_ms,
            )

    def record_failure(
        self,
        attempt_id: str,
        *,
        error_code: str,
        now_ms: int | None = None,
    ) -> QueueEntry:
        """Finish an attempt as failed and schedule retry or dead-letter it."""

        attempt_id = _validated_identifier(attempt_id, "attempt ID")
        error_code = _validated_name(error_code, "error code", MAX_ERROR_CODE_LENGTH)
        failed_at_ms = _timestamp_ms(now_ms)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT a.outcome, e.*
                FROM delivery_attempts AS a
                JOIN relay_events AS e ON e.event_id = a.event_id
                WHERE a.attempt_id = ?
                """,
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise StateTransitionError("delivery attempt does not exist")
            if row["status"] == QueueStatus.ACKNOWLEDGED.value:
                return self._entry_from_row(row)
            if row["outcome"] != AttemptOutcome.IN_FLIGHT.value:
                return self._entry_from_row(row)
            if (
                row["status"] != QueueStatus.IN_FLIGHT.value
                or row["current_attempt_id"] != attempt_id
            ):
                raise StateTransitionError("delivery attempt is no longer current")

            connection.execute(
                """
                UPDATE delivery_attempts
                SET finished_at_ms = ?, outcome = 'failed', error_code = ?
                WHERE attempt_id = ?
                """,
                (failed_at_ms, error_code, attempt_id),
            )
            retry_cycle_attempt_count = int(row["retry_cycle_attempt_count"])
            if retry_cycle_attempt_count >= self.retry_policy.max_attempts:
                connection.execute(
                    """
                    UPDATE relay_events
                    SET status = 'dead_letter', next_attempt_at_ms = NULL,
                        current_attempt_id = NULL, lease_expires_at_ms = NULL,
                        last_error_code = ?, dead_lettered_at_ms = ?
                    WHERE event_id = ?
                    """,
                    (error_code, failed_at_ms, row["event_id"]),
                )
            else:
                next_attempt_at_ms = (
                    _bounded_add(
                        failed_at_ms,
                        self.retry_policy.delay_after_attempt(
                            retry_cycle_attempt_count
                        ),
                        "next retry timestamp",
                    )
                )
                connection.execute(
                    """
                    UPDATE relay_events
                    SET status = 'retry_wait', next_attempt_at_ms = ?,
                        current_attempt_id = NULL, lease_expires_at_ms = NULL,
                        last_error_code = ?
                    WHERE event_id = ?
                    """,
                    (next_attempt_at_ms, error_code, row["event_id"]),
                )
            updated = connection.execute(
                "SELECT * FROM relay_events WHERE event_id = ?",
                (row["event_id"],),
            ).fetchone()
            return self._entry_from_row(updated)

    def requeue_dead_letter(
        self,
        event_id: str,
        *,
        now_ms: int | None = None,
    ) -> QueueEntry:
        """Begin a fresh bounded retry cycle while preserving attempt history."""

        event_id = _validated_identifier(event_id, "event ID")
        requeued_at_ms = _timestamp_ms(now_ms)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM relay_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise StateTransitionError("dead-letter event does not exist")
            if row["status"] != QueueStatus.DEAD_LETTER.value:
                raise StateTransitionError("only a dead-letter event can be requeued")
            connection.execute(
                """
                UPDATE relay_events
                SET status = 'queued', next_attempt_at_ms = ?,
                    retry_cycle_attempt_count = 0, last_error_code = NULL,
                    dead_lettered_at_ms = NULL
                WHERE event_id = ?
                """,
                (requeued_at_ms, event_id),
            )
            updated = connection.execute(
                "SELECT * FROM relay_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return self._entry_from_row(updated)

    def requeue_acknowledged_for_reconciliation(
        self,
        event_id: str,
        *,
        now_ms: int | None = None,
    ) -> bool:
        """Selectively queue an acknowledged event reported missing by the kiosk."""

        event_id = _validated_identifier(event_id, "event ID")
        requeued_at_ms = _timestamp_ms(now_ms)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status FROM relay_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise StateTransitionError("reconciled event does not exist")
            if row["status"] != QueueStatus.ACKNOWLEDGED.value:
                return False
            connection.execute(
                """
                UPDATE relay_events
                SET status = 'queued', next_attempt_at_ms = ?,
                    retry_cycle_attempt_count = 0, last_error_code = NULL,
                    acknowledged_at_ms = NULL, dead_lettered_at_ms = NULL
                WHERE event_id = ? AND status = 'acknowledged'
                """,
                (requeued_at_ms, event_id),
            )
            return True

    def acknowledge(
        self,
        event_id: str,
        *,
        now_ms: int | None = None,
    ) -> QueueEntry:
        """Persist a stable-ID ACK; duplicate and late ACKs are idempotent."""

        event_id = _validated_identifier(event_id, "event ID")
        acknowledged_at_ms = _timestamp_ms(now_ms)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM relay_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise StateTransitionError("acknowledged event does not exist")
            if row["status"] == QueueStatus.ACKNOWLEDGED.value:
                return self._entry_from_row(row)
            if int(row["attempt_count"]) == 0:
                raise StateTransitionError("event cannot be acknowledged before an attempt")

            latest_attempt = connection.execute(
                """
                SELECT attempt_id
                FROM delivery_attempts
                WHERE event_id = ?
                ORDER BY attempt_number DESC
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE delivery_attempts
                SET finished_at_ms = ?, outcome = 'acknowledged', error_code = NULL
                WHERE attempt_id = ?
                """,
                (acknowledged_at_ms, latest_attempt["attempt_id"]),
            )
            connection.execute(
                """
                UPDATE relay_events
                SET status = 'acknowledged', next_attempt_at_ms = NULL,
                    current_attempt_id = NULL, lease_expires_at_ms = NULL,
                    last_error_code = NULL, acknowledged_at_ms = ?,
                    dead_lettered_at_ms = NULL
                WHERE event_id = ?
                """,
                (acknowledged_at_ms, event_id),
            )
            updated = connection.execute(
                "SELECT * FROM relay_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return self._entry_from_row(updated)

    def get_entry(self, event_id: str) -> QueueEntry | None:
        event_id = _validated_identifier(event_id, "event ID")
        row = self._execute_read_one(
            "SELECT * FROM relay_events WHERE event_id = ?",
            (event_id,),
        )
        return self._entry_from_row(row) if row is not None else None

    def list_entries(
        self,
        *,
        status: QueueStatus | None = None,
    ) -> tuple[QueueEntry, ...]:
        if status is not None and not isinstance(status, QueueStatus):
            raise ValueError("status must be a QueueStatus or null")
        if status is None:
            rows = self._execute_read_all(
                "SELECT * FROM relay_events ORDER BY source_rowid, event_id",
                (),
            )
        else:
            rows = self._execute_read_all(
                """
                SELECT * FROM relay_events
                WHERE status = ?
                ORDER BY source_rowid, event_id
                """,
                (status.value,),
            )
        return tuple(self._entry_from_row(row) for row in rows)

    def list_entries_page(
        self,
        *,
        after_source_rowid: int = 0,
        after_event_id: str = "",
        limit: int = MAX_RECONCILIATION_PAGE_SIZE,
    ) -> tuple[QueueEntry, ...]:
        """Return one keyset-paginated page without loading the full queue."""

        after_rowid = _nonnegative_int(after_source_rowid, "page source ROWID")
        if not isinstance(after_event_id, str) or len(after_event_id) > 256:
            raise StateIntegrityError("page event ID is invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RECONCILIATION_PAGE_SIZE
        ):
            raise ValueError(
                f"page limit must be from 1 through {MAX_RECONCILIATION_PAGE_SIZE}"
            )
        rows = self._execute_read_all(
            """
            SELECT * FROM relay_events
            WHERE source_rowid > ?
               OR (source_rowid = ? AND event_id > ?)
            ORDER BY source_rowid, event_id
            LIMIT ?
            """,
            (after_rowid, after_rowid, after_event_id, limit),
        )
        return tuple(self._entry_from_row(row) for row in rows)

    def list_issues(
        self,
        *,
        source_key: str = DEFAULT_SOURCE_KEY,
    ) -> tuple[StoredIssue, ...]:
        source_key = _validated_name(source_key, "source key", MAX_SOURCE_KEY_LENGTH)
        rows = self._execute_read_all(
            """
            SELECT * FROM parse_issues
            WHERE source_key = ?
            ORDER BY source_rowid, issue_id
            """,
            (source_key,),
        )
        return tuple(
            StoredIssue(
                source_key=row["source_key"],
                source_rowid=None if row["source_rowid"] == -1 else row["source_rowid"],
                code=row["code"],
                detail=row["detail"],
                first_seen_at_ms=row["first_seen_at_ms"],
                last_seen_at_ms=row["last_seen_at_ms"],
                occurrence_count=row["occurrence_count"],
            )
            for row in rows
        )

    def list_attempts(
        self,
        event_id: str | None = None,
    ) -> tuple[DeliveryAttemptRecord, ...]:
        if event_id is None:
            rows = self._execute_read_all(
                """
                SELECT * FROM delivery_attempts
                ORDER BY started_at_ms, event_id, attempt_number
                """,
                (),
            )
        else:
            event_id = _validated_identifier(event_id, "event ID")
            rows = self._execute_read_all(
                """
                SELECT * FROM delivery_attempts
                WHERE event_id = ?
                ORDER BY attempt_number
                """,
                (event_id,),
            )
        return tuple(
            DeliveryAttemptRecord(
                attempt_id=row["attempt_id"],
                event_id=row["event_id"],
                attempt_number=row["attempt_number"],
                started_at_ms=row["started_at_ms"],
                finished_at_ms=row["finished_at_ms"],
                outcome=AttemptOutcome(row["outcome"]),
                error_code=row["error_code"],
            )
            for row in rows
        )

    def summary(self, source_key: str = DEFAULT_SOURCE_KEY) -> StateSummary:
        source_key = _validated_name(source_key, "source key", MAX_SOURCE_KEY_LENGTH)
        status_rows = self._execute_read_all(
            "SELECT status, COUNT(*) AS count FROM relay_events GROUP BY status",
            (),
        )
        counts = {row["status"]: int(row["count"]) for row in status_rows}
        issue_row = self._execute_read_one(
            "SELECT COUNT(*) AS count FROM parse_issues WHERE source_key = ?",
            (source_key,),
        )
        return StateSummary(
            source_key=source_key,
            scanned_through_rowid=self.source_cursor(source_key),
            queued_count=counts.get(QueueStatus.QUEUED.value, 0),
            in_flight_count=counts.get(QueueStatus.IN_FLIGHT.value, 0),
            retry_wait_count=counts.get(QueueStatus.RETRY_WAIT.value, 0),
            acknowledged_count=counts.get(QueueStatus.ACKNOWLEDGED.value, 0),
            dead_letter_count=counts.get(QueueStatus.DEAD_LETTER.value, 0),
            issue_count=int(issue_row["count"]),
        )

    def _expire_leases(self, connection: sqlite3.Connection, now_ms: int) -> None:
        rows = connection.execute(
            """
            SELECT * FROM relay_events
            WHERE status = 'in_flight' AND lease_expires_at_ms <= ?
            ORDER BY source_rowid
            """,
            (now_ms,),
        ).fetchall()
        for row in rows:
            attempt_id = row["current_attempt_id"]
            connection.execute(
                """
                UPDATE delivery_attempts
                SET finished_at_ms = ?, outcome = 'lease_expired',
                    error_code = 'lease_expired'
                WHERE attempt_id = ? AND outcome = 'in_flight'
                """,
                (now_ms, attempt_id),
            )
            retry_cycle_attempt_count = int(row["retry_cycle_attempt_count"])
            if retry_cycle_attempt_count >= self.retry_policy.max_attempts:
                connection.execute(
                    """
                    UPDATE relay_events
                    SET status = 'dead_letter', next_attempt_at_ms = NULL,
                        current_attempt_id = NULL, lease_expires_at_ms = NULL,
                        last_error_code = 'lease_expired', dead_lettered_at_ms = ?
                    WHERE event_id = ?
                    """,
                    (now_ms, row["event_id"]),
                )
            else:
                connection.execute(
                    """
                    UPDATE relay_events
                    SET status = 'retry_wait', next_attempt_at_ms = ?,
                        current_attempt_id = NULL, lease_expires_at_ms = NULL,
                        last_error_code = 'lease_expired'
                    WHERE event_id = ?
                    """,
                    (
                        _bounded_add(
                            now_ms,
                            self.retry_policy.delay_after_attempt(
                                retry_cycle_attempt_count
                            ),
                            "next retry timestamp",
                        ),
                        row["event_id"],
                    ),
                )

    @staticmethod
    def _store_issue(
        connection: sqlite3.Connection,
        source_key: str,
        issue: ParseIssue,
        now_ms: int,
    ) -> None:
        if not isinstance(issue, ParseIssue):
            raise StateIntegrityError("scan issue has an invalid type")
        source_rowid = -1 if issue.source_rowid is None else _nonnegative_int(
            issue.source_rowid,
            "issue source ROWID",
        )
        code = _validated_name(issue.code, "issue code", MAX_ISSUE_CODE_LENGTH)
        if not isinstance(issue.detail, str) or not issue.detail:
            raise StateIntegrityError("issue detail must be a non-empty string")
        if len(issue.detail) > MAX_ISSUE_DETAIL_LENGTH:
            raise StateIntegrityError("issue detail exceeds the size limit")
        connection.execute(
            """
            INSERT INTO parse_issues(
                source_key, source_rowid, code, detail,
                first_seen_at_ms, last_seen_at_ms, occurrence_count
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(source_key, source_rowid, code, detail) DO UPDATE SET
                last_seen_at_ms = excluded.last_seen_at_ms,
                occurrence_count = parse_issues.occurrence_count + 1
            """,
            (source_key, source_rowid, code, issue.detail, now_ms, now_ms),
        )

    def _entry_from_row(self, row: sqlite3.Row) -> QueueEntry:
        return QueueEntry(
            event=decode_event(row["payload_json"], row["payload_sha256"]),
            status=QueueStatus(row["status"]),
            attempt_count=int(row["attempt_count"]),
            retry_cycle_attempt_count=int(row["retry_cycle_attempt_count"]),
            discovered_at_ms=int(row["discovered_at_ms"]),
            next_attempt_at_ms=row["next_attempt_at_ms"],
            last_attempt_at_ms=row["last_attempt_at_ms"],
            last_error_code=row["last_error_code"],
            acknowledged_at_ms=row["acknowledged_at_ms"],
            dead_lettered_at_ms=row["dead_lettered_at_ms"],
        )

    def _initialize_or_validate_schema(self, *, created: bool) -> None:
        connection = self._require_connection()
        try:
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StateSchemaError("relay state schema could not be inspected") from exc
        tables = {row["name"] for row in table_rows}
        if user_version == 0 and not tables:
            self._create_schema(connection)
            return
        if created or application_id != STATE_APPLICATION_ID:
            raise StateSchemaError("database is not a recognized relay state store")
        if user_version != STATE_SCHEMA_VERSION:
            raise StateSchemaError("relay state schema version is unsupported")
        self._validate_schema_shape(connection)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        try:
            connection.executescript(
                f"""
                BEGIN IMMEDIATE;
                CREATE TABLE source_cursors (
                    source_key TEXT PRIMARY KEY,
                    scanned_through_rowid INTEGER NOT NULL CHECK(scanned_through_rowid >= 0),
                    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
                );
                CREATE TABLE relay_events (
                    event_id TEXT PRIMARY KEY,
                    source_rowid INTEGER NOT NULL CHECK(source_rowid >= 0),
                    event_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'queued', 'in_flight', 'retry_wait', 'acknowledged', 'dead_letter'
                    )),
                    discovered_at_ms INTEGER NOT NULL CHECK(discovered_at_ms >= 0),
                    next_attempt_at_ms INTEGER,
                    attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
                    retry_cycle_attempt_count INTEGER NOT NULL
                        CHECK(retry_cycle_attempt_count >= 0),
                    last_attempt_at_ms INTEGER,
                    current_attempt_id TEXT,
                    lease_expires_at_ms INTEGER,
                    last_error_code TEXT,
                    acknowledged_at_ms INTEGER,
                    dead_lettered_at_ms INTEGER
                );
                CREATE TABLE delivery_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES relay_events(event_id),
                    attempt_number INTEGER NOT NULL CHECK(attempt_number > 0),
                    started_at_ms INTEGER NOT NULL CHECK(started_at_ms >= 0),
                    finished_at_ms INTEGER,
                    outcome TEXT NOT NULL CHECK(outcome IN (
                        'in_flight', 'failed', 'acknowledged', 'lease_expired'
                    )),
                    error_code TEXT,
                    UNIQUE(event_id, attempt_number)
                );
                CREATE TABLE parse_issues (
                    issue_id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    source_rowid INTEGER NOT NULL CHECK(source_rowid >= -1),
                    code TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    first_seen_at_ms INTEGER NOT NULL CHECK(first_seen_at_ms >= 0),
                    last_seen_at_ms INTEGER NOT NULL CHECK(last_seen_at_ms >= 0),
                    occurrence_count INTEGER NOT NULL CHECK(occurrence_count > 0),
                    UNIQUE(source_key, source_rowid, code, detail)
                );
                CREATE TABLE scan_commits (
                    scan_id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    expected_after_rowid INTEGER NOT NULL CHECK(expected_after_rowid >= 0),
                    scanned_through_rowid INTEGER NOT NULL CHECK(scanned_through_rowid >= 0),
                    scanned_row_count INTEGER NOT NULL CHECK(scanned_row_count >= 0),
                    discovered_event_count INTEGER NOT NULL CHECK(discovered_event_count >= 0),
                    issue_count INTEGER NOT NULL CHECK(issue_count >= 0),
                    inserted_event_count INTEGER NOT NULL CHECK(inserted_event_count >= 0),
                    replay INTEGER NOT NULL CHECK(replay IN (0, 1)),
                    committed_at_ms INTEGER NOT NULL CHECK(committed_at_ms >= 0)
                );
                CREATE INDEX relay_events_delivery_order
                    ON relay_events(status, next_attempt_at_ms, source_rowid);
                CREATE INDEX delivery_attempts_event
                    ON delivery_attempts(event_id, attempt_number);
                PRAGMA application_id = {STATE_APPLICATION_ID};
                PRAGMA user_version = {STATE_SCHEMA_VERSION};
                COMMIT;
                """
            )
        except sqlite3.Error as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise StateSchemaError("relay state schema could not be created") from exc

    @staticmethod
    def _validate_schema_shape(connection: sqlite3.Connection) -> None:
        expected = {
            "source_cursors": {"source_key", "scanned_through_rowid", "updated_at_ms"},
            "relay_events": {
                "event_id",
                "source_rowid",
                "event_kind",
                "payload_json",
                "payload_sha256",
                "status",
                "discovered_at_ms",
                "next_attempt_at_ms",
                "attempt_count",
                "retry_cycle_attempt_count",
                "last_attempt_at_ms",
                "current_attempt_id",
                "lease_expires_at_ms",
                "last_error_code",
                "acknowledged_at_ms",
                "dead_lettered_at_ms",
            },
            "delivery_attempts": {
                "attempt_id",
                "event_id",
                "attempt_number",
                "started_at_ms",
                "finished_at_ms",
                "outcome",
                "error_code",
            },
            "parse_issues": {
                "issue_id",
                "source_key",
                "source_rowid",
                "code",
                "detail",
                "first_seen_at_ms",
                "last_seen_at_ms",
                "occurrence_count",
            },
            "scan_commits": {
                "scan_id",
                "source_key",
                "expected_after_rowid",
                "scanned_through_rowid",
                "scanned_row_count",
                "discovered_event_count",
                "issue_count",
                "inserted_event_count",
                "replay",
                "committed_at_ms",
            },
        }
        try:
            for table, columns in expected.items():
                rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
                if not rows or not columns.issubset({row["name"] for row in rows}):
                    raise StateSchemaError("relay state schema is incomplete")
            quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()[0]
        except sqlite3.Error as exc:
            raise StateSchemaError("relay state schema could not be validated") from exc
        if quick_check != "ok":
            raise StateSchemaError("relay state database failed its integrity check")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._require_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except RelayStateError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise StateDatabaseError("relay state transaction failed") from exc
        except BaseException:
            connection.rollback()
            raise

    def _execute_read_one(
        self,
        sql: str,
        parameters: tuple[object, ...],
    ) -> sqlite3.Row | None:
        try:
            return self._require_connection().execute(sql, parameters).fetchone()
        except sqlite3.Error as exc:
            raise StateDatabaseError("relay state could not be read") from exc

    def _execute_read_all(
        self,
        sql: str,
        parameters: tuple[object, ...],
    ) -> list[sqlite3.Row]:
        try:
            return self._require_connection().execute(sql, parameters).fetchall()
        except sqlite3.Error as exc:
            raise StateDatabaseError("relay state could not be read") from exc

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise StateClosedError("relay state store is closed")
        return self._connection


def _validated_state_path(value: Path | str) -> Path:
    unresolved = Path(value).expanduser()
    if unresolved.is_symlink():
        raise StateSecurityError("relay state path cannot be a symbolic link")
    path = unresolved.resolve(strict=False)
    if path.name.lower() in _APPLE_DATABASE_NAMES:
        raise StateSecurityError("relay state cannot target Apple's Messages database")
    if not path.parent.is_dir():
        raise StateSecurityError("relay state parent directory does not exist")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise StateSecurityError("relay state path must be a regular file")
    if path.exists():
        permissions = stat.S_IMODE(path.stat().st_mode)
        if permissions & 0o077:
            raise StateSecurityError("relay state file permissions must be private")
    return path


def _create_private_file_if_missing(path: Path) -> bool:
    if path.exists():
        return False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError as exc:
        raise StateDatabaseError("relay state file could not be created") from exc
    os.close(descriptor)
    return True


def _validate_scan_batch(batch: ScanBatch, expected_after_rowid: int) -> None:
    if not isinstance(batch, ScanBatch):
        raise StateIntegrityError("scan batch has an invalid type")
    scanned_row_count = _nonnegative_int(batch.scanned_row_count, "scanned row count")
    scanned_through = _nonnegative_int(
        batch.scanned_through_rowid,
        "scanned-through ROWID",
    )
    if scanned_row_count == 0 and scanned_through != expected_after_rowid:
        raise StateIntegrityError("empty scan batch cannot advance the source cursor")
    if scanned_row_count > 0 and scanned_through <= expected_after_rowid:
        raise StateIntegrityError("non-empty scan batch must advance its observation cursor")
    if len(batch.events) > scanned_row_count:
        raise StateIntegrityError("scan batch contains more events than source rows")
    seen_ids: set[str] = set()
    seen_rowids: set[int] = set()
    for event in batch.events:
        if not hasattr(event, "event_id") or not hasattr(event, "source_rowid"):
            raise StateIntegrityError("scan event has an invalid type")
        if event.event_id in seen_ids:
            raise StateIntegrityError("scan batch contains a duplicate event ID")
        seen_ids.add(event.event_id)
        if event.source_rowid in seen_rowids:
            raise StateIntegrityError("scan batch contains multiple events for one source row")
        seen_rowids.add(event.source_rowid)
        if not expected_after_rowid < event.source_rowid <= scanned_through:
            raise StateIntegrityError("scan event lies outside its source cursor range")
    for issue in batch.issues:
        if not isinstance(issue, ParseIssue):
            raise StateIntegrityError("scan issue has an invalid type")
        if issue.source_rowid is not None and not (
            expected_after_rowid < issue.source_rowid <= scanned_through
        ):
            raise StateIntegrityError("scan issue lies outside its source cursor range")


def _validate_reconciliation_batch(
    batch: ScanBatch,
    *,
    expected_after_rowid: int,
    start_timestamp_raw_ns: int,
    end_timestamp_raw_ns: int,
) -> None:
    _validate_scan_batch(batch, expected_after_rowid)
    for event in batch.events:
        if not start_timestamp_raw_ns <= event.timestamp_raw_ns < end_timestamp_raw_ns:
            raise StateIntegrityError("reconciliation event lies outside its time window")


def _validated_name(value: object, label: str, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or _SAFE_NAME.fullmatch(value) is None
    ):
        raise StateIntegrityError(f"{label} is invalid")
    return value


def _validated_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise StateIntegrityError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SQLITE_INTEGER
    ):
        raise StateIntegrityError(f"{label} must be a non-negative integer")
    return value


def _bounded_add(left: int, right: int, label: str) -> int:
    result = left + right
    if result > MAX_SQLITE_INTEGER:
        raise StateIntegrityError(f"{label} exceeds SQLite's integer range")
    return result


def _timestamp_ms(value: int | None) -> int:
    if value is None:
        return time.time_ns() // 1_000_000
    return _nonnegative_int(value, "timestamp")
