"""Immutable normalized records emitted by the Stage 2 iMessage parser."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Direction(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class SenderKind(StrEnum):
    REMOTE_HANDLE = "remote_handle"
    SELF = "self"


class EventKind(StrEnum):
    MESSAGE = "message"
    REACTION_ADDED = "reaction_added"
    REACTION_REMOVED = "reaction_removed"


class ReactionKind(StrEnum):
    HEART = "heart"
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    HAHA = "haha"
    EMPHASIZE = "emphasize"
    QUESTION = "question"
    UNKNOWN = "unknown"


class MediaCategory(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    LIVE_PHOTO = "live_photo"
    UNKNOWN = "unknown"


class AttachmentAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNSAFE = "unsafe"


class AttachmentComponentRole(StrEnum):
    STILL = "still"
    MOTION = "motion"


@dataclass(frozen=True, slots=True)
class Sender:
    kind: SenderKind
    identifier: str | None


@dataclass(frozen=True, slots=True)
class AttachmentComponent:
    component_id: str
    role: AttachmentComponentRole
    source_path: str
    actual_bytes: int


@dataclass(frozen=True, slots=True)
class Attachment:
    attachment_id: str
    parent_message_id: str
    transfer_name: str | None
    uti: str | None
    mime_type: str | None
    media_category: MediaCategory
    source_path: str | None
    declared_bytes: int
    actual_bytes: int | None
    availability: AttachmentAvailability
    components: tuple[AttachmentComponent, ...] = ()


@dataclass(frozen=True, slots=True)
class MessageEvent:
    schema_version: int
    event_kind: EventKind
    event_id: str
    message_id: str
    source_rowid: int
    chat_id: str
    participant_ids: tuple[str, ...]
    sender: Sender
    direction: Direction
    timestamp_raw_ns: int
    timestamp_utc: datetime
    text: str | None
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True, slots=True)
class ReactionEvent:
    schema_version: int
    event_kind: EventKind
    event_id: str
    source_rowid: int
    chat_id: str
    participant_ids: tuple[str, ...]
    sender: Sender
    direction: Direction
    timestamp_raw_ns: int
    timestamp_utc: datetime
    target_message_id: str
    target_part: int
    reaction_kind: ReactionKind
    source_reaction_type: int
    emoji: str | None = None
    removed_event_id: str | None = None


NormalizedEvent = MessageEvent | ReactionEvent


@dataclass(frozen=True, slots=True)
class ParseIssue:
    source_rowid: int | None
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ScanBatch:
    events: tuple[NormalizedEvent, ...]
    issues: tuple[ParseIssue, ...]
    scanned_row_count: int
    scanned_through_rowid: int

