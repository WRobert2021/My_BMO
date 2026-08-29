"""Read-only normalization of rows from a macOS Messages database."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
from typing import Iterator

from .attachments import normalize_attachment
from .attributed_body import extract_message_text
from .contracts import (
    Attachment,
    AttachmentAvailability,
    Direction,
    EventKind,
    MessageEvent,
    NormalizedEvent,
    ParseIssue,
    ReactionEvent,
    ReactionKind,
    ScanBatch,
    Sender,
    SenderKind,
)
from .errors import (
    AttributedBodyError,
    SourceDatabaseError,
    SourceRecordError,
    SourceSchemaError,
)
from .timestamps import apple_nanoseconds_to_datetime


SCHEMA_VERSION = 1
MAX_SCAN_LIMIT = 1_000

_TARGET_PATTERN = re.compile(r"p:(?P<part>\d+)/(?P<guid>.+)", re.DOTALL)
_ADDED_REACTIONS = {
    2000: ReactionKind.HEART,
    2001: ReactionKind.THUMBS_UP,
    2002: ReactionKind.THUMBS_DOWN,
    2003: ReactionKind.HAHA,
    2004: ReactionKind.EMPHASIZE,
    2005: ReactionKind.QUESTION,
}
_REMOVED_REACTIONS = {
    # Stage 1 directly observed this removal type only. Other values remain
    # explicit UNKNOWN values until a local fixture proves their semantics.
    3001: ReactionKind.THUMBS_UP,
}

_REQUIRED_COLUMNS = {
    "message": {
        "guid",
        "text",
        "attributedBody",
        "handle_id",
        "service",
        "account_guid",
        "date",
        "is_from_me",
        "associated_message_guid",
        "associated_message_type",
        "associated_message_range_location",
        "associated_message_range_length",
        "reply_to_guid",
    },
    "handle": {"id", "service"},
    "chat": {"guid", "service_name"},
    "chat_message_join": {"chat_id", "message_id"},
    "chat_handle_join": {"chat_id", "handle_id"},
    "attachment": {
        "guid",
        "filename",
        "uti",
        "mime_type",
        "transfer_name",
        "total_bytes",
    },
    "message_attachment_join": {"message_id", "attachment_id"},
}


@contextmanager
def open_read_only_database(database_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a SQLite database through a mandatory read-only URI."""

    path = Path(database_path).expanduser().resolve(strict=False)
    if not path.is_file():
        raise SourceDatabaseError("Messages database does not exist or is not a file")

    uri = f"{path.as_uri()}?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        yield connection
    except sqlite3.Error as exc:
        raise SourceDatabaseError("Could not read the Messages database") from exc
    finally:
        if connection is not None:
            connection.close()


class MessagesReader:
    """Scan and normalize iMessage rows without mutating the source database."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        messages_root: Path | str | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.messages_root = (
            Path(messages_root).expanduser().resolve(strict=False)
            if messages_root is not None
            else self.database_path.expanduser().resolve(strict=False).parent
        )

    def scan(self, *, after_rowid: int = 0, limit: int = 100) -> ScanBatch:
        """Return the next normalized batch after a source insertion cursor."""

        return self._scan(after_rowid=after_rowid, limit=limit)

    def scan_window(
        self,
        *,
        start_timestamp_raw_ns: int,
        end_timestamp_raw_ns: int,
        after_rowid: int = 0,
        limit: int = 100,
    ) -> ScanBatch:
        """Return one bounded page from an explicit half-open source-time window."""

        start = _nonnegative_scan_integer(
            start_timestamp_raw_ns,
            "window start timestamp",
        )
        end = _nonnegative_scan_integer(
            end_timestamp_raw_ns,
            "window end timestamp",
        )
        if end <= start:
            raise ValueError("window end timestamp must be after its start")
        return self._scan(
            after_rowid=after_rowid,
            limit=limit,
            start_timestamp_raw_ns=start,
            end_timestamp_raw_ns=end,
        )

    def _scan(
        self,
        *,
        after_rowid: int,
        limit: int,
        start_timestamp_raw_ns: int | None = None,
        end_timestamp_raw_ns: int | None = None,
    ) -> ScanBatch:
        after_rowid, limit = _scan_arguments(after_rowid, limit)

        with open_read_only_database(self.database_path) as connection:
            self._validate_schema(connection)
            connection.execute("BEGIN")
            selection = "ROWID > ? AND service = 'iMessage'"
            parameters: tuple[object, ...]
            if start_timestamp_raw_ns is None:
                parameters = (after_rowid, limit)
            else:
                selection += " AND date >= ? AND date < ?"
                parameters = (
                    after_rowid,
                    start_timestamp_raw_ns,
                    end_timestamp_raw_ns,
                    limit,
                )
            rows = connection.execute(
                f"""
                SELECT
                    ROWID, guid, text, attributedBody, handle_id, service,
                    account_guid, date, is_from_me, associated_message_guid,
                    associated_message_type, associated_message_range_location,
                    associated_message_range_length, reply_to_guid
                FROM message NOT INDEXED
                WHERE {selection}
                ORDER BY ROWID ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

            events: list[NormalizedEvent] = []
            issues: list[ParseIssue] = []
            for row in rows:
                source_rowid = _required_int(row["ROWID"], "message ROWID is invalid")
                try:
                    event, event_issues = self._normalize_row(connection, row)
                except SourceRecordError as exc:
                    issues.append(
                        ParseIssue(
                            source_rowid=source_rowid,
                            code="message_invalid",
                            detail=str(exc),
                        )
                    )
                    continue
                if event is not None:
                    events.append(event)
                issues.extend(event_issues)

            scanned_through = (
                _required_int(rows[-1]["ROWID"], "message ROWID is invalid")
                if rows
                else after_rowid
            )
            connection.rollback()

        return ScanBatch(
            events=tuple(events),
            issues=tuple(issues),
            scanned_row_count=len(rows),
            scanned_through_rowid=scanned_through,
        )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        for table, required in _REQUIRED_COLUMNS.items():
            try:
                rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            except sqlite3.Error as exc:
                raise SourceSchemaError("Messages database schema could not be inspected") from exc
            actual = {row["name"] for row in rows}
            if not rows or not required.issubset(actual):
                raise SourceSchemaError(f"Messages database is missing required {table} fields")

    def _normalize_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> tuple[NormalizedEvent | None, list[ParseIssue]]:
        source_rowid = _required_int(row["ROWID"], "message ROWID is invalid")
        message_id = _required_string(row["guid"], "message GUID is invalid")
        direction = _direction(row["is_from_me"])
        timestamp_raw_ns = _required_int(row["date"], "message timestamp is invalid")
        timestamp_utc = apple_nanoseconds_to_datetime(timestamp_raw_ns)
        chat_id, participant_ids = self._chat_context(connection, source_rowid)
        sender = self._sender(connection, row, direction)
        associated_type = _required_int(
            row["associated_message_type"],
            "associated message type is invalid",
        )

        common = {
            "schema_version": SCHEMA_VERSION,
            "event_id": message_id,
            "source_rowid": source_rowid,
            "chat_id": chat_id,
            "participant_ids": participant_ids,
            "sender": sender,
            "direction": direction,
            "timestamp_raw_ns": timestamp_raw_ns,
            "timestamp_utc": timestamp_utc,
        }

        if associated_type != 0:
            return self._normalize_reaction(row, associated_type, common), []

        # The relay scope is incoming messages. Outgoing reaction events remain
        # above because they are necessary for faithful reaction state.
        if direction is Direction.OUTGOING:
            return None, []

        attachments, issues, has_attachment_join = self._attachments(
            connection,
            source_rowid,
            message_id,
        )
        try:
            text = extract_message_text(
                text=row["text"],
                attributed_body=row["attributedBody"],
                has_attachments=has_attachment_join,
            )
        except AttributedBodyError as exc:
            text = None
            issues.append(
                ParseIssue(
                    source_rowid=source_rowid,
                    code="text_decode_failed",
                    detail=str(exc),
                )
            )

        return (
            MessageEvent(
                event_kind=EventKind.MESSAGE,
                message_id=message_id,
                text=text,
                attachments=attachments,
                **common,
            ),
            issues,
        )

    @staticmethod
    def _chat_context(
        connection: sqlite3.Connection,
        source_rowid: int,
    ) -> tuple[str, tuple[str, ...]]:
        chats = connection.execute(
            """
            SELECT c.ROWID, c.guid
            FROM chat_message_join AS cmj
            JOIN chat AS c ON c.ROWID = cmj.chat_id
            WHERE cmj.message_id = ? AND c.service_name = 'iMessage'
            ORDER BY c.ROWID ASC
            """,
            (source_rowid,),
        ).fetchall()
        if len(chats) != 1:
            raise SourceRecordError("message must belong to exactly one iMessage chat")

        chat_rowid = _required_int(chats[0]["ROWID"], "chat ROWID is invalid")
        chat_id = _required_string(chats[0]["guid"], "chat GUID is invalid")
        participant_rows = connection.execute(
            """
            SELECT h.id
            FROM chat_handle_join AS chj
            JOIN handle AS h ON h.ROWID = chj.handle_id
            WHERE chj.chat_id = ? AND h.service = 'iMessage'
            ORDER BY h.ROWID ASC
            """,
            (chat_rowid,),
        ).fetchall()
        participants = tuple(
            _required_string(item["id"], "chat participant handle is invalid")
            for item in participant_rows
        )
        return chat_id, participants

    @staticmethod
    def _sender(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        direction: Direction,
    ) -> Sender:
        if direction is Direction.OUTGOING:
            account_guid = row["account_guid"]
            if account_guid is not None and not isinstance(account_guid, str):
                raise SourceRecordError("outgoing account identifier is invalid")
            return Sender(kind=SenderKind.SELF, identifier=account_guid or None)

        handle_id = _required_int(row["handle_id"], "incoming handle reference is invalid")
        handles = connection.execute(
            """
            SELECT id
            FROM handle
            WHERE ROWID = ? AND service = 'iMessage'
            """,
            (handle_id,),
        ).fetchall()
        if len(handles) != 1:
            raise SourceRecordError("incoming sender must resolve to one iMessage handle")
        return Sender(
            kind=SenderKind.REMOTE_HANDLE,
            identifier=_required_string(handles[0]["id"], "incoming sender handle is invalid"),
        )

    @staticmethod
    def _normalize_reaction(
        row: sqlite3.Row,
        associated_type: int,
        common: dict[str, object],
    ) -> ReactionEvent:
        target = row["associated_message_guid"]
        if not isinstance(target, str):
            raise SourceRecordError("reaction target is invalid")
        match = _TARGET_PATTERN.fullmatch(target)
        if match is None:
            raise SourceRecordError("reaction target does not match the observed Messages format")

        if 2000 <= associated_type < 3000:
            event_kind = EventKind.REACTION_ADDED
            reaction_kind = _ADDED_REACTIONS.get(associated_type, ReactionKind.UNKNOWN)
            removed_event_id = None
        elif 3000 <= associated_type < 4000:
            event_kind = EventKind.REACTION_REMOVED
            reaction_kind = _REMOVED_REACTIONS.get(associated_type, ReactionKind.UNKNOWN)
            reply_to_guid = row["reply_to_guid"]
            if reply_to_guid is not None and not isinstance(reply_to_guid, str):
                raise SourceRecordError("removed reaction reference is invalid")
            removed_event_id = reply_to_guid or None
        else:
            raise SourceRecordError("associated message type is not a supported reaction range")

        return ReactionEvent(
            event_kind=event_kind,
            target_message_id=match.group("guid"),
            target_part=int(match.group("part")),
            reaction_kind=reaction_kind,
            source_reaction_type=associated_type,
            emoji=None,
            removed_event_id=removed_event_id,
            **common,
        )

    def _attachments(
        self,
        connection: sqlite3.Connection,
        source_rowid: int,
        message_id: str,
    ) -> tuple[tuple[Attachment, ...], list[ParseIssue], bool]:
        rows = connection.execute(
            """
            SELECT
                a.ROWID, a.guid, a.filename, a.uti, a.mime_type,
                a.transfer_name, a.total_bytes
            FROM message_attachment_join AS maj
            JOIN attachment AS a ON a.ROWID = maj.attachment_id
            WHERE maj.message_id = ?
            ORDER BY a.ROWID ASC
            """,
            (source_rowid,),
        ).fetchall()
        attachments: list[Attachment] = []
        issues: list[ParseIssue] = []
        for attachment_row in rows:
            try:
                attachment = normalize_attachment(
                    attachment_row,
                    parent_message_id=message_id,
                    messages_root=self.messages_root,
                )
            except SourceRecordError as exc:
                issues.append(
                    ParseIssue(
                        source_rowid=source_rowid,
                        code="attachment_invalid",
                        detail=str(exc),
                    )
                )
                continue
            except OSError:
                issues.append(
                    ParseIssue(
                        source_rowid=source_rowid,
                        code="attachment_unavailable",
                        detail="attachment filesystem metadata could not be read",
                    )
                )
                continue
            attachments.append(attachment)
            if attachment.availability is not AttachmentAvailability.AVAILABLE:
                issues.append(
                    ParseIssue(
                        source_rowid=source_rowid,
                        code=f"attachment_{attachment.availability.value}",
                        detail="attachment path could not be used safely",
                    )
                )
        return tuple(attachments), issues, bool(rows)


def _scan_arguments(after_rowid: object, limit: object) -> tuple[int, int]:
    if (
        isinstance(after_rowid, bool)
        or not isinstance(after_rowid, int)
        or after_rowid < 0
    ):
        raise ValueError("after_rowid must be a non-negative integer")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_SCAN_LIMIT
    ):
        raise ValueError(f"limit must be an integer from 1 through {MAX_SCAN_LIMIT}")
    return after_rowid, limit


def _nonnegative_scan_integer(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 9_223_372_036_854_775_807
    ):
        raise ValueError(f"{label} must be a supported non-negative integer")
    return value


def _required_string(value: object, message: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceRecordError(message)
    return value


def _required_int(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceRecordError(message)
    return value


def _direction(value: object) -> Direction:
    if value == 0:
        return Direction.INCOMING
    if value == 1:
        return Direction.OUTGOING
    raise SourceRecordError("message direction is invalid")
