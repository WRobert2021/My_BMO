"""Private, durable, idempotent kiosk-side receiver storage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
from uuid import uuid4

from .protocol import (
    MAX_ATTACHMENT_CHUNK_BYTES,
    ReconciliationCandidate,
    ReconciliationReceipt,
    ValidatedEnvelope,
    ValidatedUploadSessionRequest,
)


RECEIVER_SCHEMA_VERSION = 2
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


class AttachmentStoreError(ReceiverStoreError):
    code = "attachment_storage_unavailable"
    http_status = 503


class AttachmentUnavailableError(AttachmentStoreError):
    code = "attachment_unavailable"
    http_status = 422


class AttachmentSessionError(AttachmentStoreError):
    code = "attachment_session_invalid"
    http_status = 409


class AttachmentOffsetError(AttachmentStoreError):
    code = "attachment_offset_mismatch"
    http_status = 409


class AttachmentDigestError(AttachmentStoreError):
    code = "attachment_digest_mismatch"
    http_status = 409


class IngestResult(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    ATTACHMENTS_PENDING = "attachments_pending"


@dataclass(frozen=True, slots=True)
class ReceiverSummary:
    event_count: int
    last_received_at_ms: int | None
    pending_event_count: int
    partial_attachment_count: int
    complete_attachment_count: int


@dataclass(frozen=True, slots=True)
class AttachmentUploadSession:
    upload_id: str
    next_offset: int
    expected_bytes: int
    complete: bool
    created: bool


@dataclass(frozen=True, slots=True)
class AttachmentChunkResult:
    upload_id: str
    next_offset: int
    complete: bool


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    event_id: str
    blob_id: str
    expected_bytes: int
    received_bytes: int
    content_sha256: str | None
    complete: bool
    storage_path: Path | None


class ReceiverStateStore:
    """Own one kiosk-private SQLite database and serialize its transactions."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = _validated_path(database_path)
        self.attachment_root = self.database_path.parent / (
            self.database_path.name + ".attachments"
        )
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
        """Commit an event only after every required attachment is durable."""

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

                pending = connection.execute(
                    """
                    SELECT event_kind, event_json, event_digest
                    FROM pending_events WHERE event_id = ?
                    """,
                    (envelope.event_id,),
                ).fetchone()
                if pending is not None:
                    if (
                        pending["event_kind"] != envelope.event_kind
                        or pending["event_json"] != envelope.event_json
                        or pending["event_digest"] != envelope.event_digest
                    ):
                        raise EventConflictError(
                            "event ID is already associated with a different pending payload"
                        )
                    incomplete = connection.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM attachment_uploads
                        WHERE event_id = ? AND status != 'complete'
                        """,
                        (envelope.event_id,),
                    ).fetchone()
                    if int(incomplete["count"]) != 0:
                        connection.execute("COMMIT")
                        return IngestResult.ATTACHMENTS_PENDING
                    connection.execute(
                        """
                        INSERT INTO received_events(
                            event_id, event_kind, event_json, event_digest,
                            first_request_id, received_at_ms
                        )
                        SELECT event_id, event_kind, event_json, event_digest,
                               first_request_id, ?
                        FROM pending_events WHERE event_id = ?
                        """,
                        (when, envelope.event_id),
                    )
                    connection.execute(
                        "DELETE FROM pending_events WHERE event_id = ?",
                        (envelope.event_id,),
                    )
                    connection.execute("COMMIT")
                    return IngestResult.ACCEPTED

                if envelope.unavailable_attachment_count:
                    raise AttachmentUnavailableError(
                        "event includes an attachment that cannot be transferred"
                    )
                if envelope.attachment_requirements:
                    connection.execute(
                        """
                        INSERT INTO pending_events(
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
                    for requirement in envelope.attachment_requirements:
                        connection.execute(
                            """
                            INSERT INTO attachment_uploads(
                                event_id, blob_id, expected_bytes,
                                received_bytes, status, updated_at_ms
                            ) VALUES (?, ?, ?, 0, 'awaiting', ?)
                            """,
                            (
                                envelope.event_id,
                                requirement.blob_id,
                                requirement.expected_bytes,
                                when,
                            ),
                        )
                    connection.execute("COMMIT")
                    return IngestResult.ATTACHMENTS_PENDING
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
            except AttachmentStoreError:
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

    def begin_attachment_upload(
        self,
        request: ValidatedUploadSessionRequest,
        *,
        updated_at_ms: int | None = None,
    ) -> AttachmentUploadSession:
        """Create or resume one receiver-owned bounded attachment session."""

        when = _timestamp_ms(updated_at_ms)
        connection = self._require_connection()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                pending = connection.execute(
                    "SELECT 1 FROM pending_events WHERE event_id = ?",
                    (request.event_id,),
                ).fetchone()
                row = connection.execute(
                    """
                    SELECT * FROM attachment_uploads
                    WHERE event_id = ? AND blob_id = ?
                    """,
                    (request.event_id, request.blob_id),
                ).fetchone()
                if pending is None or row is None:
                    raise AttachmentSessionError(
                        "attachment session does not match a pending event manifest"
                    )
                if int(row["expected_bytes"]) != request.expected_bytes:
                    raise AttachmentSessionError(
                        "attachment size does not match the pending manifest"
                    )
                existing_digest = row["content_sha256"]
                if (
                    existing_digest is not None
                    and existing_digest != request.content_sha256
                    and int(row["received_bytes"]) != 0
                ):
                    raise AttachmentDigestError(
                        "attachment digest changed after transfer began"
                    )
                created = row["upload_id"] is None
                upload_id = row["upload_id"] or str(uuid4())
                storage_name = row["storage_name"] or f"{upload_id}.blob"
                _ensure_private_directory(self.attachment_root)
                storage_path = self.attachment_root / storage_name
                _create_private_upload_file(storage_path)
                _normalize_upload_file(storage_path, int(row["received_bytes"]))

                status = str(row["status"])
                received_bytes = int(row["received_bytes"])
                if request.expected_bytes == 0:
                    if request.content_sha256 != hashlib.sha256(b"").hexdigest():
                        raise AttachmentDigestError(
                            "empty attachment digest does not match its content"
                        )
                    status = "complete"
                elif status == "awaiting":
                    status = "partial"
                connection.execute(
                    """
                    UPDATE attachment_uploads
                    SET upload_id = ?, content_sha256 = ?, status = ?,
                        storage_name = ?, updated_at_ms = ?
                    WHERE event_id = ? AND blob_id = ?
                    """,
                    (
                        upload_id,
                        request.content_sha256,
                        status,
                        storage_name,
                        when,
                        request.event_id,
                        request.blob_id,
                    ),
                )
                connection.execute("COMMIT")
                return AttachmentUploadSession(
                    upload_id=upload_id,
                    next_offset=received_bytes,
                    expected_bytes=request.expected_bytes,
                    complete=status == "complete",
                    created=created,
                )
            except AttachmentStoreError:
                _rollback(connection)
                raise
            except (OSError, sqlite3.Error) as exc:
                _rollback(connection)
                raise AttachmentStoreError(
                    "attachment session could not be prepared"
                ) from exc

    def append_attachment_chunk(
        self,
        *,
        upload_id: str,
        offset: int,
        chunk: bytes,
        updated_at_ms: int | None = None,
    ) -> AttachmentChunkResult:
        """Durably append one authenticated chunk and verify at completion."""

        if not isinstance(chunk, bytes) or not 1 <= len(chunk) <= MAX_ATTACHMENT_CHUNK_BYTES:
            raise ValueError("attachment chunk size is outside the supported range")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("attachment chunk offset is invalid")
        when = _timestamp_ms(updated_at_ms)
        connection = self._require_connection()
        with self._lock:
            prior_size: int | None = None
            storage_path: Path | None = None
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM attachment_uploads WHERE upload_id = ?",
                    (upload_id,),
                ).fetchone()
                if row is None or row["storage_name"] is None:
                    raise AttachmentSessionError("attachment upload session does not exist")
                expected_bytes = int(row["expected_bytes"])
                received_bytes = int(row["received_bytes"])
                _ensure_private_directory(self.attachment_root)
                storage_path = _attachment_storage_path(
                    self.attachment_root,
                    str(row["storage_name"]),
                )
                _normalize_upload_file(storage_path, received_bytes)

                if offset < received_bytes:
                    if offset + len(chunk) > received_bytes:
                        raise AttachmentOffsetError(
                            "attachment chunk overlaps the durable offset"
                        )
                    if _read_exact(storage_path, offset, len(chunk)) != chunk:
                        raise AttachmentOffsetError(
                            "replayed attachment chunk does not match durable bytes"
                        )
                    connection.execute("COMMIT")
                    return AttachmentChunkResult(
                        upload_id=upload_id,
                        next_offset=received_bytes,
                        complete=str(row["status"]) == "complete",
                    )
                if offset != received_bytes or offset + len(chunk) > expected_bytes:
                    raise AttachmentOffsetError(
                        "attachment chunk does not match the durable offset"
                    )

                prior_size = received_bytes
                _write_chunk(storage_path, offset, chunk)
                next_offset = offset + len(chunk)
                status = "partial"
                if next_offset == expected_bytes:
                    digest = _sha256_file(storage_path)
                    if digest != row["content_sha256"]:
                        _truncate_upload(storage_path, 0)
                        connection.execute(
                            """
                            UPDATE attachment_uploads
                            SET received_bytes = 0, status = 'partial', updated_at_ms = ?
                            WHERE upload_id = ?
                            """,
                            (when, upload_id),
                        )
                        connection.execute("COMMIT")
                        raise AttachmentDigestError(
                            "completed attachment digest does not match"
                        )
                    status = "complete"
                connection.execute(
                    """
                    UPDATE attachment_uploads
                    SET received_bytes = ?, status = ?, updated_at_ms = ?
                    WHERE upload_id = ?
                    """,
                    (next_offset, status, when, upload_id),
                )
                connection.execute("COMMIT")
                return AttachmentChunkResult(
                    upload_id=upload_id,
                    next_offset=next_offset,
                    complete=status == "complete",
                )
            except AttachmentDigestError:
                raise
            except AttachmentStoreError:
                _rollback(connection)
                raise
            except (OSError, sqlite3.Error) as exc:
                _rollback(connection)
                if prior_size is not None and storage_path is not None:
                    try:
                        _truncate_upload(storage_path, prior_size)
                    except OSError:
                        pass
                raise AttachmentStoreError(
                    "attachment chunk could not be committed"
                ) from exc

    def get_attachment(self, event_id: str, blob_id: str) -> StoredAttachment | None:
        connection = self._require_connection()
        with self._lock:
            try:
                row = connection.execute(
                    """
                    SELECT * FROM attachment_uploads
                    WHERE event_id = ? AND blob_id = ?
                    """,
                    (event_id, blob_id),
                ).fetchone()
            except sqlite3.Error as exc:
                raise ReceiverStoreError("attachment state could not be read") from exc
        if row is None:
            return None
        storage_path = (
            _attachment_storage_path(self.attachment_root, str(row["storage_name"]))
            if row["storage_name"] is not None
            else None
        )
        return StoredAttachment(
            event_id=str(row["event_id"]),
            blob_id=str(row["blob_id"]),
            expected_bytes=int(row["expected_bytes"]),
            received_bytes=int(row["received_bytes"]),
            content_sha256=row["content_sha256"],
            complete=str(row["status"]) == "complete",
            storage_path=storage_path,
        )

    def reconcile_receipts(
        self,
        candidates: tuple[ReconciliationCandidate, ...],
    ) -> tuple[ReconciliationReceipt, ...]:
        """Classify only sender-provided candidates without mutating kiosk history."""

        connection = self._require_connection()
        receipts: list[ReconciliationReceipt] = []
        with self._lock:
            try:
                for candidate in candidates:
                    row = connection.execute(
                        "SELECT event_digest FROM received_events WHERE event_id = ?",
                        (candidate.event_id,),
                    ).fetchone()
                    if row is None:
                        status = "missing"
                    elif row["event_digest"] == candidate.event_digest:
                        status = "present"
                    else:
                        status = "conflict"
                    receipts.append(ReconciliationReceipt(candidate.event_id, status))
            except sqlite3.Error as exc:
                raise ReceiverStoreError("receipts could not be reconciled") from exc
        return tuple(receipts)

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
                pending_row = connection.execute(
                    "SELECT COUNT(*) AS count FROM pending_events"
                ).fetchone()
                attachment_rows = connection.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM attachment_uploads GROUP BY status
                    """
                ).fetchall()
            except sqlite3.Error as exc:
                raise ReceiverStoreError("receiver status could not be read") from exc
        attachment_counts = {
            str(attachment_row["status"]): int(attachment_row["count"])
            for attachment_row in attachment_rows
        }
        return ReceiverSummary(
            event_count=int(row["event_count"]),
            last_received_at_ms=(
                int(row["last_received_at_ms"])
                if row["last_received_at_ms"] is not None
                else None
            ),
            pending_event_count=int(pending_row["count"]),
            partial_attachment_count=(
                attachment_counts.get("awaiting", 0)
                + attachment_counts.get("partial", 0)
            ),
            complete_attachment_count=attachment_counts.get("complete", 0),
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
                    CREATE TABLE pending_events (
                        event_id TEXT PRIMARY KEY NOT NULL,
                        event_kind TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
                        first_request_id TEXT NOT NULL,
                        received_at_ms INTEGER NOT NULL CHECK(received_at_ms >= 0)
                    ) WITHOUT ROWID;
                    CREATE TABLE attachment_uploads (
                        event_id TEXT NOT NULL,
                        blob_id TEXT NOT NULL,
                        expected_bytes INTEGER NOT NULL CHECK(expected_bytes >= 0),
                        content_sha256 TEXT CHECK(
                            content_sha256 IS NULL OR length(content_sha256) = 64
                        ),
                        upload_id TEXT UNIQUE,
                        received_bytes INTEGER NOT NULL CHECK(received_bytes >= 0),
                        status TEXT NOT NULL CHECK(status IN (
                            'awaiting', 'partial', 'complete'
                        )),
                        storage_name TEXT,
                        updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0),
                        PRIMARY KEY(event_id, blob_id)
                    ) WITHOUT ROWID;
                    CREATE INDEX attachment_uploads_status
                        ON attachment_uploads(status, updated_at_ms);
                    PRAGMA application_id = {RECEIVER_APPLICATION_ID};
                    PRAGMA user_version = {RECEIVER_SCHEMA_VERSION};
                    COMMIT;
                    """
                )
                return
            if application_id != RECEIVER_APPLICATION_ID:
                raise ReceiverStoreSchemaError("file is not a receiver database")
            version_one = {"received_events", "authentication_nonces"}
            if user_version == 1 and tables == version_one:
                connection.executescript(
                    f"""
                    BEGIN IMMEDIATE;
                    CREATE TABLE pending_events (
                        event_id TEXT PRIMARY KEY NOT NULL,
                        event_kind TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        event_digest TEXT NOT NULL CHECK(length(event_digest) = 64),
                        first_request_id TEXT NOT NULL,
                        received_at_ms INTEGER NOT NULL CHECK(received_at_ms >= 0)
                    ) WITHOUT ROWID;
                    CREATE TABLE attachment_uploads (
                        event_id TEXT NOT NULL,
                        blob_id TEXT NOT NULL,
                        expected_bytes INTEGER NOT NULL CHECK(expected_bytes >= 0),
                        content_sha256 TEXT CHECK(
                            content_sha256 IS NULL OR length(content_sha256) = 64
                        ),
                        upload_id TEXT UNIQUE,
                        received_bytes INTEGER NOT NULL CHECK(received_bytes >= 0),
                        status TEXT NOT NULL CHECK(status IN (
                            'awaiting', 'partial', 'complete'
                        )),
                        storage_name TEXT,
                        updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0),
                        PRIMARY KEY(event_id, blob_id)
                    ) WITHOUT ROWID;
                    CREATE INDEX attachment_uploads_status
                        ON attachment_uploads(status, updated_at_ms);
                    PRAGMA user_version = {RECEIVER_SCHEMA_VERSION};
                    COMMIT;
                    """
                )
                user_version = RECEIVER_SCHEMA_VERSION
                tables = version_one | {"pending_events", "attachment_uploads"}
            expected = version_one | {"pending_events", "attachment_uploads"}
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


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise AttachmentStoreError("attachment storage cannot be a symbolic link")
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
        if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise AttachmentStoreError("attachment storage must be a private directory")
    except OSError as exc:
        raise AttachmentStoreError("attachment storage directory is unavailable") from exc


def _attachment_storage_path(root: Path, storage_name: str) -> Path:
    if (
        not storage_name
        or Path(storage_name).name != storage_name
        or storage_name in {".", ".."}
    ):
        raise AttachmentStoreError("attachment storage name is invalid")
    return root / storage_name


def _create_private_upload_file(path: Path) -> None:
    if path.is_symlink():
        raise AttachmentStoreError("attachment upload cannot be a symbolic link")
    if path.exists():
        if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise AttachmentStoreError("attachment upload file is not private")
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    except OSError as exc:
        raise AttachmentStoreError("attachment upload file could not be created") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _normalize_upload_file(path: Path, durable_bytes: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise AttachmentStoreError("attachment upload file is unavailable")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AttachmentStoreError("attachment upload file is not private")
    actual_bytes = path.stat().st_size
    if actual_bytes < durable_bytes:
        raise AttachmentStoreError("attachment upload is shorter than durable state")
    if actual_bytes > durable_bytes:
        _truncate_upload(path, durable_bytes)


def _write_chunk(path: Path, offset: int, chunk: bytes) -> None:
    with path.open("r+b", buffering=0) as stream:
        stream.seek(offset)
        written = stream.write(chunk)
        if written != len(chunk):
            raise OSError("attachment chunk write was incomplete")
        os.fsync(stream.fileno())


def _read_exact(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb", buffering=0) as stream:
        stream.seek(offset)
        return stream.read(length)


def _truncate_upload(path: Path, length: int) -> None:
    with path.open("r+b", buffering=0) as stream:
        stream.truncate(length)
        os.fsync(stream.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        while True:
            chunk = stream.read(MAX_ATTACHMENT_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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
