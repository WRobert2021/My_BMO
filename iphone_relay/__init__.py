"""Read-only, local-first iMessage relay parsing contracts."""

from .contracts import (
    Attachment,
    AttachmentAvailability,
    AttachmentComponent,
    AttachmentComponentRole,
    Direction,
    EventKind,
    MediaCategory,
    MessageEvent,
    ParseIssue,
    ReactionEvent,
    ReactionKind,
    ScanBatch,
    Sender,
    SenderKind,
)
from .errors import (
    AttributedBodyError,
    IMessageParserError,
    SourceDatabaseError,
    SourceRecordError,
    SourceSchemaError,
    UnsafeAttachmentPathError,
)
from .reader import MessagesReader, open_read_only_database
from .timestamps import apple_nanoseconds_to_datetime, apple_seconds_to_datetime

__all__ = [
    "Attachment",
    "AttachmentAvailability",
    "AttachmentComponent",
    "AttachmentComponentRole",
    "AttributedBodyError",
    "Direction",
    "EventKind",
    "IMessageParserError",
    "MediaCategory",
    "MessageEvent",
    "MessagesReader",
    "ParseIssue",
    "ReactionEvent",
    "ReactionKind",
    "ScanBatch",
    "Sender",
    "SenderKind",
    "SourceDatabaseError",
    "SourceRecordError",
    "SourceSchemaError",
    "UnsafeAttachmentPathError",
    "apple_nanoseconds_to_datetime",
    "apple_seconds_to_datetime",
    "open_read_only_database",
]
