"""Private, durable, idempotent kiosk-side receiver storage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time

from .protocol import ValidatedEnvelope


RECEIVER_SCHEMA_VERSION = 1
RECEIVER_APPLICATION_ID = 0x494D4B52  # ASCII "IMKR"


class ReceiverStoreError(RuntimeError):
    pass


class ReceiverStoreSecurityError(ReceiverStoreError):
    pass


class ReceiverStoreSchemaError(ReceiverStoreError):
    pass


class EventConflictError(ReceiverStoreError):
    pass


class ReplayError(ReceiverStoreError):
    pass


class IngestResult(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ReceiverSummary:
    event_count: int
    last_received_at_ms: int | None


class ReceiverStateStore:
    """Own one kiosk-private SQLite database and serialize its transactions."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = _validated_path(database_path)
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        created = _create_private_file(self.database_path)
        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=5.0,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
            self._initialize_or_validate(created)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA journal_mode = WAL")
        except ReceiverStoreError:
            self.close()
            raise
        except sqlite3.Error as exc:
            self.close()
            raise ReceiverStoreError("receiver database could not be opened") from exc

    def __enter__(self) -> ReceiverStateStore:
        self._require_connection()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()

    def reserve_nonce(
        self,
        *,
        key_id: str,
        nonce: str,
        signed_at_seconds: int,
        now_seconds: int,
        retention_seconds: int,
    ) -> None:
        """Durably reserve an authenticated nonce before request processing."""

        connection = self._require_connection()
        cutoff = now_seconds - retention_seconds
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM authentication_nonces WHERE signed_at_seconds < ?",
                    (cutoff,),
                )
                connection.execute(
                    """
                    INSERT INTO authentication_nonces(
                        key_id, nonce, signed_at_seconds, received_at_seconds
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (key_id, nonce, signed_at_seconds, now_seconds),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                _rollback(connection)
                raise ReplayError("authenticated nonce has already been used") from exc
            except sqlite3.Error as exc:
                _rollback(connection)
                raise ReceiverStoreError("nonce could not be committed") from exc

    def ingest(
        self,
        envelope: ValidatedEnvelope,
        *,
        received_at_ms: int | None = None,
    ) -> IngestResult:
        """Commit exactly one event or identify an identical prior commit."""

        when = _timestamp_ms(received_at_ms)
        connection = self._require_connection()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT event_kind, event_json, event_digest
                    FROM received_events WHERE event_id = ?
                    """,
                    (envelope.event_id,),
                ).fetchone()
                if row is not None:
                    if (
                        row["event_kind"] != envelope.event_kind
                        or row["event_json"] != envelope.event_json
                        or row["event_digest"] != envelope.event_digest
                    ):
                        raise EventConflictError(
                            "event ID is already associated with a different payload"
                        )
                    connection.execute("COMMIT")
                    return IngestResult.DUPLICATE
                connection.execute(
                    """
                    INSERT INTO received_events(
                        event_id, event_kind, event_json, event_digest,
                        first_request_id, received_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.event_id,
                        envelope.event_kind,
                        envelope.event_json,
                        envelope.event_digest,
                        envelope.request_id,
                        when,
                    ),
                )
                connection.execute("COMMIT")
                return IngestResult.ACCEPTED
            except EventConflictError:
                _rollback(connection)
                raise
            except sqlite3.Error as exc:
                _rollback(connection)
                raise ReceiverStoreError("event could not be committed") from exc

    def get_event_json(self, event_id: str) -> str | None:
        connection = self._require_connection()
        with self._lock:
            try:
                row = connection.execute(
                    "SELECT event_json FROM received_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise ReceiverStoreError("event could not be read") from exc
        return str(row["event_json"]) if row is not None else None

    def summary(self) -> ReceiverSummary:
        connection = self._require_connection()
        with self._lock:
            try:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS event_count,
                           MAX(received_at_ms) AS last_received_at_ms
                    FROM received_events
                    """
                ).fetchone()
            except sqlite3.Error as exc:
                raise ReceiverStoreError("receiver status could not be read") from exc
        return ReceiverSummary(
            event_count=int(row["event_count"]),
            last_received_at_ms=(
                int(row["last_received_at_ms"])
                if row["last_received_at_ms"] is not None
                else None
            ),
        )

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise ReceiverStoreError("receiver database is closed")
        return connection

    def _initialize_or_validate(self, created: bool) -> None:
        connection = self._require_connection()
        try:
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if created or (application_id == 0 and user_version == 0 and not tables):
                connection.executescript(
                    f"""
                    BEGIN IMMEDIATE;
                    CREATE TABLE received_events (
                        event_id TEXT PRIMARY KEY NOT NULL,
                        event_kind TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
                        first_request_id TEXT NOT NULL,
                        received_at_ms INTEGER NOT NULL CHECK(received_at_ms >= 0)
                    ) WITHOUT ROWID;
                    CREATE TABLE authentication_nonces (
                        key_id TEXT NOT NULL,
                        nonce TEXT NOT NULL,
                        signed_at_seconds INTEGER NOT NULL,
                        received_at_seconds INTEGER NOT NULL,
                        PRIMARY KEY(key_id, nonce)
                    ) WITHOUT ROWID;
                    CREATE INDEX authentication_nonces_signed_at
                        ON authentication_nonces(signed_at_seconds);
                    PRAGMA application_id = {RECEIVER_APPLICATION_ID};
                    PRAGMA user_version = {RECEIVER_SCHEMA_VERSION};
                    COMMIT;
                    """
                )
                return
            expected = {"received_events", "authentication_nonces"}
            if application_id != RECEIVER_APPLICATION_ID:
                raise ReceiverStoreSchemaError("file is not a receiver database")
            if user_version != RECEIVER_SCHEMA_VERSION:
                raise ReceiverStoreSchemaError("receiver database schema is unsupported")
            if tables != expected:
                raise ReceiverStoreSchemaError("receiver database schema is incomplete")
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise ReceiverStoreSchemaError("receiver database integrity check failed")
        except ReceiverStoreError:
            raise
        except sqlite3.Error as exc:
            raise ReceiverStoreSchemaError("receiver database schema could not be validated") from exc


def _validated_path(value: Path | str) -> Path:
    unresolved = Path(value).expanduser()
    if unresolved.is_symlink():
        raise ReceiverStoreSecurityError("receiver state cannot be a symbolic link")
    path = unresolved.resolve(strict=False)
    if path.name in {"chat.db", "sms.db"}:
        raise ReceiverStoreSecurityError("receiver state cannot use an Apple database path")
    if path.exists():
        if not path.is_file():
            raise ReceiverStoreSecurityError("receiver state must be a regular file")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ReceiverStoreSecurityError("receiver state must not be accessible by group or others")
    return path


def _create_private_file(path: Path) -> bool:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        return False
    descriptor = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    except OSError as exc:
        raise ReceiverStoreSecurityError("receiver state file could not be created") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return True


def _timestamp_ms(value: int | None) -> int:
    result = int(time.time() * 1_000) if value is None else value
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError("timestamp must be a nonnegative integer")
    return result


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass
