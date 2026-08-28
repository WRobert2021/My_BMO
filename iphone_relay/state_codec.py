"""Strict canonical JSON codec for relay-owned normalized event payloads."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any

from .contracts import (
    Attachment,
    AttachmentAvailability,
    AttachmentComponent,
    AttachmentComponentRole,
    Direction,
    EventKind,
    MediaCategory,
    MessageEvent,
    NormalizedEvent,
    ReactionEvent,
    ReactionKind,
    Sender,
    SenderKind,
)
from .errors import SourceRecordError, StateIntegrityError
from .timestamps import apple_nanoseconds_to_datetime


MAX_EVENT_PAYLOAD_BYTES = 8 * 1024 * 1024


def encode_event(event: NormalizedEvent) -> tuple[str, str]:
    """Return deterministic JSON and its SHA-256 integrity digest."""

    try:
        payload = _event_to_mapping(event)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise StateIntegrityError("normalized event could not be encoded") from exc
    raw = encoded.encode("utf-8")
    if len(raw) > MAX_EVENT_PAYLOAD_BYTES:
        raise StateIntegrityError("normalized event payload exceeds the size limit")
    return encoded, hashlib.sha256(raw).hexdigest()


def decode_event(payload_json: object, expected_digest: object) -> NormalizedEvent:
    """Validate and decode a persisted normalized event payload."""

    if not isinstance(payload_json, str):
        raise StateIntegrityError("stored event payload must be JSON text")
    raw = payload_json.encode("utf-8")
    if len(raw) > MAX_EVENT_PAYLOAD_BYTES:
        raise StateIntegrityError("stored event payload exceeds the size limit")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise StateIntegrityError("stored event digest is invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_digest):
        raise StateIntegrityError("stored event payload failed its integrity check")
    try:
        value = json.loads(
            payload_json,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise StateIntegrityError("stored event payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise StateIntegrityError("stored event payload must be an object")
    return _event_from_mapping(value)


def _event_to_mapping(event: NormalizedEvent) -> dict[str, Any]:
    common: dict[str, Any] = {
        "schema_version": event.schema_version,
        "event_kind": event.event_kind.value,
        "event_id": event.event_id,
        "source_rowid": event.source_rowid,
        "chat_id": event.chat_id,
        "participant_ids": list(event.participant_ids),
        "sender": {
            "kind": event.sender.kind.value,
            "identifier": event.sender.identifier,
        },
        "direction": event.direction.value,
        "timestamp_raw_ns": event.timestamp_raw_ns,
        "timestamp_utc": event.timestamp_utc.astimezone(timezone.utc).isoformat(),
    }
    if isinstance(event, MessageEvent):
        common.update(
            {
                "message_id": event.message_id,
                "text": event.text,
                "attachments": [_attachment_to_mapping(item) for item in event.attachments],
            }
        )
        return common
    if isinstance(event, ReactionEvent):
        common.update(
            {
                "target_message_id": event.target_message_id,
                "target_part": event.target_part,
                "reaction_kind": event.reaction_kind.value,
                "source_reaction_type": event.source_reaction_type,
                "emoji": event.emoji,
                "removed_event_id": event.removed_event_id,
            }
        )
        return common
    raise StateIntegrityError("unsupported normalized event type")


def _attachment_to_mapping(attachment: Attachment) -> dict[str, Any]:
    return {
        "attachment_id": attachment.attachment_id,
        "parent_message_id": attachment.parent_message_id,
        "transfer_name": attachment.transfer_name,
        "uti": attachment.uti,
        "mime_type": attachment.mime_type,
        "media_category": attachment.media_category.value,
        "source_path": attachment.source_path,
        "declared_bytes": attachment.declared_bytes,
        "actual_bytes": attachment.actual_bytes,
        "availability": attachment.availability.value,
        "components": [
            {
                "component_id": component.component_id,
                "role": component.role.value,
                "source_path": component.source_path,
                "actual_bytes": component.actual_bytes,
            }
            for component in attachment.components
        ],
    }


def _event_from_mapping(value: dict[str, Any]) -> NormalizedEvent:
    event_kind = _enum(EventKind, value.get("event_kind"), "event kind")
    common_keys = {
        "schema_version",
        "event_kind",
        "event_id",
        "source_rowid",
        "chat_id",
        "participant_ids",
        "sender",
        "direction",
        "timestamp_raw_ns",
        "timestamp_utc",
    }
    if event_kind is EventKind.MESSAGE:
        _require_exact_keys(value, common_keys | {"message_id", "text", "attachments"})
    else:
        _require_exact_keys(
            value,
            common_keys
            | {
                "target_message_id",
                "target_part",
                "reaction_kind",
                "source_reaction_type",
                "emoji",
                "removed_event_id",
            },
        )

    schema_version = _nonnegative_int(value["schema_version"], "schema version")
    if schema_version != 1:
        raise StateIntegrityError("stored event schema version is unsupported")
    event_id = _nonempty_string(value["event_id"], "event ID")
    source_rowid = _nonnegative_int(value["source_rowid"], "source ROWID")
    chat_id = _nonempty_string(value["chat_id"], "chat ID")
    participants_raw = value["participant_ids"]
    if not isinstance(participants_raw, list):
        raise StateIntegrityError("participant IDs must be a list")
    participant_ids = tuple(
        _nonempty_string(item, "participant ID") for item in participants_raw
    )
    sender_raw = value["sender"]
    if not isinstance(sender_raw, dict):
        raise StateIntegrityError("sender must be an object")
    _require_exact_keys(sender_raw, {"kind", "identifier"})
    sender = Sender(
        kind=_enum(SenderKind, sender_raw["kind"], "sender kind"),
        identifier=_optional_string(sender_raw["identifier"], "sender identifier"),
    )
    direction = _enum(Direction, value["direction"], "direction")
    timestamp_raw_ns = _nonnegative_int(value["timestamp_raw_ns"], "timestamp")
    timestamp_utc = _utc_datetime(value["timestamp_utc"])
    try:
        expected_timestamp = apple_nanoseconds_to_datetime(timestamp_raw_ns)
    except SourceRecordError as exc:
        raise StateIntegrityError("stored source timestamp is invalid") from exc
    if timestamp_utc != expected_timestamp:
        raise StateIntegrityError("stored timestamp does not match its source value")

    common = {
        "schema_version": schema_version,
        "event_kind": event_kind,
        "event_id": event_id,
        "source_rowid": source_rowid,
        "chat_id": chat_id,
        "participant_ids": participant_ids,
        "sender": sender,
        "direction": direction,
        "timestamp_raw_ns": timestamp_raw_ns,
        "timestamp_utc": timestamp_utc,
    }
    if event_kind is EventKind.MESSAGE:
        message_id = _nonempty_string(value["message_id"], "message ID")
        if message_id != event_id:
            raise StateIntegrityError("message ID must match its event ID")
        text = _optional_string(value["text"], "message text")
        attachments_raw = value["attachments"]
        if not isinstance(attachments_raw, list):
            raise StateIntegrityError("attachments must be a list")
        attachments = tuple(
            _attachment_from_mapping(item, message_id) for item in attachments_raw
        )
        if len({item.attachment_id for item in attachments}) != len(attachments):
            raise StateIntegrityError("attachment IDs must be unique within an event")
        return MessageEvent(
            message_id=message_id,
            text=text,
            attachments=attachments,
            **common,
        )

    emoji = _optional_string(value["emoji"], "reaction emoji")
    removed_event_id = _optional_string(
        value["removed_event_id"],
        "removed event ID",
    )
    return ReactionEvent(
        target_message_id=_nonempty_string(value["target_message_id"], "target ID"),
        target_part=_nonnegative_int(value["target_part"], "target part"),
        reaction_kind=_enum(ReactionKind, value["reaction_kind"], "reaction kind"),
        source_reaction_type=_nonnegative_int(
            value["source_reaction_type"],
            "source reaction type",
        ),
        emoji=emoji,
        removed_event_id=removed_event_id,
        **common,
    )


def _attachment_from_mapping(value: object, message_id: str) -> Attachment:
    if not isinstance(value, dict):
        raise StateIntegrityError("attachment must be an object")
    _require_exact_keys(
        value,
        {
            "attachment_id",
            "parent_message_id",
            "transfer_name",
            "uti",
            "mime_type",
            "media_category",
            "source_path",
            "declared_bytes",
            "actual_bytes",
            "availability",
            "components",
        },
    )
    parent_message_id = _nonempty_string(value["parent_message_id"], "parent message ID")
    if parent_message_id != message_id:
        raise StateIntegrityError("attachment parent does not match its message")
    components_raw = value["components"]
    if not isinstance(components_raw, list):
        raise StateIntegrityError("attachment components must be a list")
    components = tuple(_component_from_mapping(item) for item in components_raw)
    if len({item.component_id for item in components}) != len(components):
        raise StateIntegrityError("attachment component IDs must be unique")
    actual_bytes = value["actual_bytes"]
    if actual_bytes is not None:
        actual_bytes = _nonnegative_int(actual_bytes, "attachment actual bytes")
    return Attachment(
        attachment_id=_nonempty_string(value["attachment_id"], "attachment ID"),
        parent_message_id=parent_message_id,
        transfer_name=_optional_string(value["transfer_name"], "transfer name"),
        uti=_optional_string(value["uti"], "attachment UTI"),
        mime_type=_optional_string(value["mime_type"], "attachment MIME type"),
        media_category=_enum(MediaCategory, value["media_category"], "media category"),
        source_path=_optional_string(value["source_path"], "attachment source path"),
        declared_bytes=_nonnegative_int(value["declared_bytes"], "declared bytes"),
        actual_bytes=actual_bytes,
        availability=_enum(
            AttachmentAvailability,
            value["availability"],
            "attachment availability",
        ),
        components=components,
    )


def _component_from_mapping(value: object) -> AttachmentComponent:
    if not isinstance(value, dict):
        raise StateIntegrityError("attachment component must be an object")
    _require_exact_keys(value, {"component_id", "role", "source_path", "actual_bytes"})
    return AttachmentComponent(
        component_id=_nonempty_string(value["component_id"], "component ID"),
        role=_enum(AttachmentComponentRole, value["role"], "component role"),
        source_path=_nonempty_string(value["source_path"], "component source path"),
        actual_bytes=_nonnegative_int(value["actual_bytes"], "component actual bytes"),
    )


def _require_exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise StateIntegrityError("stored event payload fields are invalid")


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise StateIntegrityError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StateIntegrityError(f"{label} must be a string or null")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StateIntegrityError(f"{label} must be a non-negative integer")
    return value


def _enum(enum_type: type[Any], value: object, label: str) -> Any:
    if not isinstance(value, str):
        raise StateIntegrityError(f"{label} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise StateIntegrityError(f"{label} is unsupported") from exc


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise StateIntegrityError("timestamp UTC must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StateIntegrityError("timestamp UTC is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise StateIntegrityError("timestamp UTC must use a zero offset")
    return parsed.astimezone(timezone.utc)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StateIntegrityError("stored event payload has duplicate fields")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    del value
    raise StateIntegrityError("stored event payload contains a non-finite number")
