"""Private durable kiosk state for replay-safe outbound commands."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time

from .protocol import OutboundCommand, OutboundCommandAck, encode_command


OUTBOUND_APPLICATION_ID = 0x494D4B4F  # IMKO
OUTBOUND_SCHEMA_VERSION = 1

_TERMINAL_STATES = frozenset({"sent", "failed"})
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SAFE_ERROR = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class OutboundStateError(RuntimeError):
    """Kiosk outbound state is unsafe, unavailable, or inconsistent."""


@dataclass(frozen=True, slots=True)
class OutboundCommandRecord:
    command_id: str
    command_kind: str
    command_json: str
    command_digest: str
    state: str
    attempt_count: int
    last_request_id: str | None
    error_code: str | None
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class OutboundStateSummary:
    total_commands: int
    queued_commands: int
    executing_commands: int
    sent_commands: int
    failed_commands: int
    uncertain_commands: int


class OutboundStateStore:
    """Serialize a private SQLite outbox and preserve commands before network use."""

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
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA journal_mode = WAL")
        except OutboundStateError:
            self.close()
            raise
        except sqlite3.Error as exc:
            self.close()
            raise OutboundStateError("outbound database could not be opened") from exc

    def __enter__(self) -> OutboundStateStore:
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

    def enqueue(
        self,
        command: OutboundCommand,
        *,
        now_ms: int | None = None,
    ) -> OutboundCommandRecord:
        command_bytes = encode_command(command)
        command_json = command_bytes.decode("utf-8")
        command_digest = hashlib.sha256(command_bytes).hexdigest()
        timestamp = _timestamp_ms(now_ms)
        connection = self._require_connection()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM outbound_commands WHERE command_id = ?",
                    (command.command_id,),
                ).fetchone()
                if row is not None:
                    if not _constant_digest(str(row["command_digest"]), command_digest):
                        raise OutboundStateError(
                            "outbound command ID conflicts with different content"
                        )
                    connection.execute("COMMIT")
                    return _record(row)
                connection.execute(
                    """
                    INSERT INTO outbound_commands(
                        command_id, command_kind, command_json, command_digest,
                        state, attempt_count, last_request_id, error_code,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, 'queued', 0, NULL, NULL, ?, ?)
                    """,
                    (
                        command.command_id,
                        command.kind,
                        command_json,
                        command_digest,
                        timestamp,
                        timestamp,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM outbound_commands WHERE command_id = ?",
                    (command.command_id,),
                ).fetchone()
                connection.execute("COMMIT")
                assert row is not None
                return _record(row)
            except OutboundStateError:
                _rollback(connection)
                raise
            except sqlite3.Error as exc:
                _rollback(connection)
                raise OutboundStateError("outbound command could not be queued") from exc

    def record_attempt(
        self,
        command_id: str,
        request_id: str,
        *,
        now_ms: int | None = None,
    ) -> OutboundCommandRecord:
        _token(command_id, "command ID")
        _token(request_id, "request ID")
        timestamp = _timestamp_ms(now_ms)
        connection = self._require_connection()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state FROM outbound_commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                if row is None:
                    raise OutboundStateError("outbound command does not exist")
                if str(row["state"]) in _TERMINAL_STATES:
                    raise OutboundStateError("terminal outbound command cannot be retried")
                connection.execute(
                    """
                    UPDATE outbound_commands
                    SET state = 'executing',
                        attempt_count = attempt_count + 1,
                        last_request_id = ?, updated_at_ms = ?
                    WHERE command_id = ?
                    """,
                    (request_id, timestamp, command_id),
                )
                result = connection.execute(
                    "SELECT * FROM outbound_commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                connection.execute("COMMIT")
                assert result is not None
                return _record(result)
            except OutboundStateError:
                _rollback(connection)
                raise
            except sqlite3.Error as exc:
                _rollback(connection)
                raise OutboundStateError("outbound attempt could not be recorded") from exc

    def apply_ack(
        self,
        ack: OutboundCommandAck,
        *,
        now_ms: int | None = None,
    ) -> OutboundCommandRecord:
        if not isinstance(ack, OutboundCommandAck):
            raise TypeError("ack must be an OutboundCommandAck")
        timestamp = _timestamp_ms(now_ms)
        connection = self._require_connection()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state FROM outbound_commands WHERE command_id = ?",
                    (ack.command_id,),
                ).fetchone()
                if row is None:
                    raise OutboundStateError("outbound command does not exist")
                prior_state = str(row["state"])
                if prior_state in _TERMINAL_STATES and prior_state != ack.command_state:
                    raise OutboundStateError("terminal outbound command state cannot regress")
                connection.execute(
                    """
                    UPDATE outbound_commands
                    SET state = ?, error_code = ?, updated_at_ms = ?
                    WHERE command_id = ?
                    """,
                    (ack.command_state, ack.error_code, timestamp, ack.command_id),
                )
                result = connection.execute(
                    "SELECT * FROM outbound_commands WHERE command_id = ?",
                    (ack.command_id,),
                ).fetchone()
                connection.execute("COMMIT")
                assert result is not None
                return _record(result)
            except OutboundStateError:
                _rollback(connection)
                raise
            except sqlite3.Error as exc:
                _rollback(connection)
                raise OutboundStateError("outbound ACK could not be committed") from exc

    def mark_uncertain(
        self,
        command_id: str,
        error_code: str,
        *,
        now_ms: int | None = None,
    ) -> OutboundCommandRecord:
        _token(command_id, "command ID")
        if not isinstance(error_code, str) or not _SAFE_ERROR.fullmatch(error_code):
            raise ValueError("error code is invalid")
        return self.apply_ack(
            OutboundCommandAck(
                command_id=command_id,
                status="status",
                command_state="uncertain",
                error_code=error_code,
            ),
            now_ms=now_ms,
        )

    def get(self, command_id: str) -> OutboundCommandRecord | None:
        _token(command_id, "command ID")
        connection = self._require_connection()
        with self._lock:
            try:
                row = connection.execute(
                    "SELECT * FROM outbound_commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise OutboundStateError("outbound command could not be read") from exc
        return None if row is None else _record(row)

    def pending(self, limit: int = 20) -> tuple[OutboundCommandRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("outbound pending limit is invalid")
        connection = self._require_connection()
        with self._lock:
            try:
                rows = connection.execute(
                    """
                    SELECT * FROM outbound_commands
                    WHERE state IN ('queued', 'executing', 'uncertain')
                    ORDER BY created_at_ms ASC, command_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise OutboundStateError("outbound pending commands could not be read") from exc
        return tuple(_record(row) for row in rows)

    def summary(self) -> OutboundStateSummary:
        connection = self._require_connection()
        with self._lock:
            try:
                rows = connection.execute(
                    "SELECT state, COUNT(*) AS count FROM outbound_commands GROUP BY state"
                ).fetchall()
            except sqlite3.Error as exc:
                raise OutboundStateError("outbound summary could not be read") from exc
        counts = {str(row["state"]): int(row["count"]) for row in rows}
        return OutboundStateSummary(
            total_commands=sum(counts.values()),
            queued_commands=counts.get("queued", 0),
            executing_commands=counts.get("executing", 0),
            sent_commands=counts.get("sent", 0),
            failed_commands=counts.get("failed", 0),
            uncertain_commands=counts.get("uncertain", 0),
        )

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
                    CREATE TABLE outbound_commands (
                        command_id TEXT PRIMARY KEY NOT NULL,
                        command_kind TEXT NOT NULL CHECK(command_kind IN (
                            'text', 'media', 'reaction'
                        )),
                        command_json TEXT NOT NULL,
                        command_digest TEXT NOT NULL CHECK(length(command_digest) = 64),
                        state TEXT NOT NULL CHECK(state IN (
                            'queued', 'executing', 'sent', 'failed', 'uncertain'
                        )),
                        attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
                        last_request_id TEXT,
                        error_code TEXT,
                        created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
                        updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
                    ) WITHOUT ROWID;
                    CREATE INDEX outbound_commands_state
                        ON outbound_commands(state, created_at_ms, command_id);
                    PRAGMA application_id = {OUTBOUND_APPLICATION_ID};
                    PRAGMA user_version = {OUTBOUND_SCHEMA_VERSION};
                    COMMIT;
                    """
                )
                return
            if application_id != OUTBOUND_APPLICATION_ID:
                raise OutboundStateError("file is not an outbound command database")
            if user_version != OUTBOUND_SCHEMA_VERSION:
                raise OutboundStateError("outbound database schema is unsupported")
            if tables != {"outbound_commands"}:
                raise OutboundStateError("outbound database schema is incomplete")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise OutboundStateError("outbound database integrity check failed")
        except OutboundStateError:
            raise
        except sqlite3.Error as exc:
            raise OutboundStateError("outbound database schema could not be validated") from exc

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise OutboundStateError("outbound database is closed")
        return connection


def _record(row: sqlite3.Row) -> OutboundCommandRecord:
    return OutboundCommandRecord(
        command_id=str(row["command_id"]),
        command_kind=str(row["command_kind"]),
        command_json=str(row["command_json"]),
        command_digest=str(row["command_digest"]),
        state=str(row["state"]),
        attempt_count=int(row["attempt_count"]),
        last_request_id=(
            str(row["last_request_id"]) if row["last_request_id"] is not None else None
        ),
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
    )


def _validated_path(value: Path | str) -> Path:
    unresolved = Path(value).expanduser()
    if unresolved.is_symlink():
        raise OutboundStateError("outbound state cannot be a symbolic link")
    path = unresolved.resolve(strict=False)
    if path.name in {"chat.db", "sms.db"}:
        raise OutboundStateError("outbound state cannot use an Apple database path")
    if path.exists():
        if not path.is_file():
            raise OutboundStateError("outbound state must be a regular file")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise OutboundStateError(
                "outbound state must not be accessible by group or others"
            )
    return path


def _create_private_file(path: Path) -> bool:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise OutboundStateError("outbound state directory is unavailable") from exc
    if path.exists():
        return False
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    except OSError as exc:
        raise OutboundStateError("outbound state file could not be created") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return True


def _timestamp_ms(value: int | None) -> int:
    result = int(time.time() * 1_000) if value is None else value
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError("timestamp must be a nonnegative integer")
    return result


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def _constant_digest(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


__all__ = [
    "OUTBOUND_APPLICATION_ID",
    "OUTBOUND_SCHEMA_VERSION",
    "OutboundCommandRecord",
    "OutboundStateError",
    "OutboundStateStore",
    "OutboundStateSummary",
]
