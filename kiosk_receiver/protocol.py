"""Versioned, strict JSON contracts for kiosk relay ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from iphone_relay.contracts import MessageEvent, NormalizedEvent, ReactionEvent
from iphone_relay.errors import SourceRecordError
from iphone_relay.timestamps import apple_nanoseconds_to_datetime


PROTOCOL_VERSION = 1
EVENT_PATH = "/v1/events"
RECONCILIATION_PATH = "/v1/reconciliation"
MAX_EVENT_ID_LENGTH = 512
MAX_REQUEST_ID_LENGTH = 128
MAX_STRING_LENGTH = 1_000_000
MAX_RECONCILIATION_CANDIDATES = 20

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_EVENT_KINDS = {"message", "reaction_added", "reaction_removed"}
_DIRECTIONS = {"incoming", "outgoing"}
_SENDER_KINDS = {"remote_handle", "self"}
_MEDIA_CATEGORIES = {"photo", "video", "live_photo", "unknown"}
_AVAILABILITIES = {"available", "missing", "unsafe"}
_COMPONENT_ROLES = {"still", "motion"}
_REACTION_KINDS = {
    "heart",
    "thumbs_up",
    "thumbs_down",
    "haha",
    "emphasize",
    "question",
    "unknown",
}
_RECEIPT_STATUSES = {"present", "missing", "conflict"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ProtocolError(ValueError):
    """A request cannot be accepted under the public wire contract."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class ValidatedEnvelope:
    request_id: str
    event_id: str
    event_kind: str
    event_json: str
    event_digest: str


@dataclass(frozen=True, slots=True)
class ReconciliationCandidate:
    event_id: str
    event_digest: str


@dataclass(frozen=True, slots=True)
class ValidatedReconciliationRequest:
    request_id: str
    candidates: tuple[ReconciliationCandidate, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationReceipt:
    event_id: str
    status: str


@dataclass(frozen=True, slots=True)
class ValidatedReconciliationResponse:
    request_id: str
    receipts: tuple[ReconciliationReceipt, ...]


def event_to_wire_mapping(event: NormalizedEvent) -> dict[str, Any]:
    """Convert a normalized event to the path-free Stage 4 wire shape."""

    common: dict[str, Any] = {
        "schema_version": event.schema_version,
        "event_kind": event.event_kind.value,
        "event_id": event.event_id,
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
                "attachments": [
                    {
                        "attachment_id": attachment.attachment_id,
                        "parent_message_id": attachment.parent_message_id,
                        "transfer_name": attachment.transfer_name,
                        "uti": attachment.uti,
                        "mime_type": attachment.mime_type,
                        "media_category": attachment.media_category.value,
                        "declared_bytes": attachment.declared_bytes,
                        "actual_bytes": attachment.actual_bytes,
                        "availability": attachment.availability.value,
                        "components": [
                            {
                                "component_id": component.component_id,
                                "role": component.role.value,
                                "actual_bytes": component.actual_bytes,
                            }
                            for component in attachment.components
                        ],
                    }
                    for attachment in event.attachments
                ],
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
    raise ProtocolError("unsupported_event", "normalized event type is unsupported")


def encode_event_envelope(event: NormalizedEvent, request_id: str) -> bytes:
    """Encode one event request using deterministic UTF-8 JSON."""

    value = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": _request_id(request_id),
        "event": event_to_wire_mapping(event),
    }
    return _canonical_json(value).encode("utf-8")


def decode_event_envelope(body: bytes) -> ValidatedEnvelope:
    """Strictly validate an event request and return its storage representation."""

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("malformed_json", "request body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("invalid_schema", "request body must be an object")
    _exact_keys(value, {"protocol_version", "request_id", "event"})
    if _integer(value["protocol_version"], "protocol version") != PROTOCOL_VERSION:
        raise ProtocolError(
            "unsupported_protocol_version",
            "protocol version is unsupported",
        )
    request_id = _request_id(value["request_id"])
    event = _event(value["event"])
    event_json = _canonical_json(event)
    return ValidatedEnvelope(
        request_id=request_id,
        event_id=event["event_id"],
        event_kind=event["event_kind"],
        event_json=event_json,
        event_digest=hashlib.sha256(event_json.encode("utf-8")).hexdigest(),
    )


def event_wire_digest(event: NormalizedEvent) -> str:
    """Return the receiver's canonical digest for one path-free event."""

    validated = _event(event_to_wire_mapping(event))
    return hashlib.sha256(_canonical_json(validated).encode("utf-8")).hexdigest()


def encode_reconciliation_request(
    candidates: tuple[ReconciliationCandidate, ...],
    request_id: str,
) -> bytes:
    """Encode one bounded sender receipt-membership request."""

    validated = _reconciliation_candidates(candidates)
    return _canonical_json(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": _request_id(request_id),
            "candidates": [
                {
                    "event_id": candidate.event_id,
                    "event_digest": candidate.event_digest,
                }
                for candidate in validated
            ],
        }
    ).encode("utf-8")


def decode_reconciliation_request(body: bytes) -> ValidatedReconciliationRequest:
    """Strictly decode a bounded receipt-membership request."""

    value = _decode_json_object(body, "reconciliation request")
    _exact_keys(value, {"protocol_version", "request_id", "candidates"})
    if _integer(value["protocol_version"], "protocol version") != PROTOCOL_VERSION:
        raise ProtocolError(
            "unsupported_protocol_version",
            "protocol version is unsupported",
        )
    raw_candidates = value["candidates"]
    if not isinstance(raw_candidates, list):
        raise ProtocolError("invalid_schema", "candidates must be a list")
    candidates = _reconciliation_candidates(tuple(raw_candidates))
    return ValidatedReconciliationRequest(
        request_id=_request_id(value["request_id"]),
        candidates=candidates,
    )


def reconciliation_response_body(
    *,
    request_id: str,
    receipts: tuple[ReconciliationReceipt, ...],
) -> bytes:
    """Encode the receiver's bounded, order-preserving receipt classifications."""

    validated = _reconciliation_receipts(receipts)
    return _canonical_json(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": _request_id(request_id),
            "result": "reconciliation",
            "receipts": [
                {"event_id": receipt.event_id, "status": receipt.status}
                for receipt in validated
            ],
        }
    ).encode("utf-8")


def decode_reconciliation_response(body: bytes) -> ValidatedReconciliationResponse:
    """Strictly decode a successful reconciliation response."""

    value = _decode_json_object(body, "reconciliation response")
    _exact_keys(
        value,
        {"protocol_version", "request_id", "result", "receipts"},
    )
    if _integer(value["protocol_version"], "protocol version") != PROTOCOL_VERSION:
        raise ProtocolError(
            "unsupported_protocol_version",
            "protocol version is unsupported",
        )
    if value["result"] != "reconciliation":
        raise ProtocolError("invalid_schema", "response result is invalid")
    raw_receipts = value["receipts"]
    if not isinstance(raw_receipts, list):
        raise ProtocolError("invalid_schema", "receipts must be a list")
    receipts = _reconciliation_receipts(tuple(raw_receipts))
    return ValidatedReconciliationResponse(
        request_id=_request_id(value["request_id"]),
        receipts=receipts,
    )


def response_body(
    *,
    request_id: str | None,
    result: str,
    status: str | None = None,
    event_id: str | None = None,
    error_code: str | None = None,
) -> bytes:
    value: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "result": result,
    }
    if result == "ack":
        value.update({"status": status, "event_id": event_id})
    else:
        value["error"] = {"code": error_code}
    return _canonical_json(value).encode("utf-8")


def _decode_json_object(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("malformed_json", f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("invalid_schema", f"{label} must be an object")
    return value


def _reconciliation_candidates(
    values: tuple[object, ...],
) -> tuple[ReconciliationCandidate, ...]:
    if not 1 <= len(values) <= MAX_RECONCILIATION_CANDIDATES:
        raise ProtocolError(
            "invalid_schema",
            "candidate count is outside the supported range",
        )
    result: list[ReconciliationCandidate] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, ReconciliationCandidate):
            candidate = value
        else:
            if not isinstance(value, dict):
                raise ProtocolError("invalid_schema", "candidate must be an object")
            _exact_keys(value, {"event_id", "event_digest"})
            candidate = ReconciliationCandidate(
                event_id=_string(
                    value["event_id"],
                    "event ID",
                    maximum=MAX_EVENT_ID_LENGTH,
                ),
                event_digest=_digest(value["event_digest"]),
            )
        event_id = _string(
            candidate.event_id,
            "event ID",
            maximum=MAX_EVENT_ID_LENGTH,
        )
        digest = _digest(candidate.event_digest)
        if event_id in seen:
            raise ProtocolError("invalid_schema", "candidate event IDs must be unique")
        seen.add(event_id)
        result.append(ReconciliationCandidate(event_id, digest))
    return tuple(result)


def _reconciliation_receipts(
    values: tuple[object, ...],
) -> tuple[ReconciliationReceipt, ...]:
    if not 1 <= len(values) <= MAX_RECONCILIATION_CANDIDATES:
        raise ProtocolError(
            "invalid_schema",
            "receipt count is outside the supported range",
        )
    result: list[ReconciliationReceipt] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, ReconciliationReceipt):
            receipt = value
        else:
            if not isinstance(value, dict):
                raise ProtocolError("invalid_schema", "receipt must be an object")
            _exact_keys(value, {"event_id", "status"})
            receipt = ReconciliationReceipt(
                event_id=_string(
                    value["event_id"],
                    "event ID",
                    maximum=MAX_EVENT_ID_LENGTH,
                ),
                status=_choice(value["status"], _RECEIPT_STATUSES, "receipt status"),
            )
        event_id = _string(
            receipt.event_id,
            "event ID",
            maximum=MAX_EVENT_ID_LENGTH,
        )
        status = _choice(receipt.status, _RECEIPT_STATUSES, "receipt status")
        if event_id in seen:
            raise ProtocolError("invalid_schema", "receipt event IDs must be unique")
        seen.add(event_id)
        result.append(ReconciliationReceipt(event_id, status))
    return tuple(result)


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProtocolError("invalid_schema", "event digest is invalid")
    return value


def _event(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("invalid_schema", "event must be an object")
    kind = _choice(value.get("event_kind"), _EVENT_KINDS, "event kind")
    common = {
        "schema_version",
        "event_kind",
        "event_id",
        "chat_id",
        "participant_ids",
        "sender",
        "direction",
        "timestamp_raw_ns",
        "timestamp_utc",
    }
    if kind == "message":
        _exact_keys(value, common | {"message_id", "text", "attachments"})
    else:
        _exact_keys(
            value,
            common
            | {
                "target_message_id",
                "target_part",
                "reaction_kind",
                "source_reaction_type",
                "emoji",
                "removed_event_id",
            },
        )
    if _integer(value["schema_version"], "event schema version") != 1:
        raise ProtocolError("unsupported_event_version", "event version is unsupported")
    event_id = _string(value["event_id"], "event ID", maximum=MAX_EVENT_ID_LENGTH)
    _string(value["chat_id"], "chat ID")
    participants = value["participant_ids"]
    if not isinstance(participants, list):
        raise ProtocolError("invalid_schema", "participant IDs must be a list")
    participant_ids = [_string(participant, "participant ID") for participant in participants]
    if len(set(participant_ids)) != len(participant_ids):
        raise ProtocolError("invalid_schema", "participant IDs must be unique")
    sender = value["sender"]
    if not isinstance(sender, dict):
        raise ProtocolError("invalid_schema", "sender must be an object")
    _exact_keys(sender, {"kind", "identifier"})
    _choice(sender["kind"], _SENDER_KINDS, "sender kind")
    _optional_string(sender["identifier"], "sender identifier")
    _choice(value["direction"], _DIRECTIONS, "direction")
    timestamp_raw_ns = _nonnegative_integer(value["timestamp_raw_ns"], "timestamp")
    timestamp = _string(value["timestamp_utc"], "UTC timestamp", maximum=64)
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("invalid_schema", "timestamp is invalid") from exc
    if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp):
        raise ProtocolError("invalid_schema", "timestamp must identify UTC")
    try:
        expected_timestamp = apple_nanoseconds_to_datetime(timestamp_raw_ns)
    except SourceRecordError as exc:
        raise ProtocolError("invalid_schema", "source timestamp is invalid") from exc
    if parsed_timestamp.astimezone(timezone.utc) != expected_timestamp:
        raise ProtocolError("invalid_schema", "UTC timestamp does not match its source value")

    if kind == "message":
        message_id = _string(value["message_id"], "message ID")
        if message_id != event_id:
            raise ProtocolError("invalid_schema", "message ID must equal event ID")
        _optional_string(value["text"], "message text")
        attachments = value["attachments"]
        if not isinstance(attachments, list):
            raise ProtocolError("invalid_schema", "attachments must be a list")
        attachment_ids: set[str] = set()
        for attachment in attachments:
            attachment_id = _attachment(attachment, message_id)
            if attachment_id in attachment_ids:
                raise ProtocolError("invalid_schema", "attachment IDs must be unique")
            attachment_ids.add(attachment_id)
    else:
        _string(value["target_message_id"], "target message ID")
        _nonnegative_integer(value["target_part"], "target part")
        _choice(value["reaction_kind"], _REACTION_KINDS, "reaction kind")
        _nonnegative_integer(value["source_reaction_type"], "source reaction type")
        _optional_string(value["emoji"], "reaction emoji")
        _optional_string(value["removed_event_id"], "removed event ID")
    return value


def _attachment(value: object, message_id: str) -> str:
    if not isinstance(value, dict):
        raise ProtocolError("invalid_schema", "attachment must be an object")
    _exact_keys(
        value,
        {
            "attachment_id",
            "parent_message_id",
            "transfer_name",
            "uti",
            "mime_type",
            "media_category",
            "declared_bytes",
            "actual_bytes",
            "availability",
            "components",
        },
    )
    attachment_id = _string(value["attachment_id"], "attachment ID")
    if _string(value["parent_message_id"], "parent message ID") != message_id:
        raise ProtocolError("invalid_schema", "attachment parent does not match message")
    _optional_string(value["transfer_name"], "transfer name")
    _optional_string(value["uti"], "attachment UTI")
    _optional_string(value["mime_type"], "attachment MIME type")
    _choice(value["media_category"], _MEDIA_CATEGORIES, "media category")
    _nonnegative_integer(value["declared_bytes"], "declared byte count")
    _optional_nonnegative_integer(value["actual_bytes"], "actual byte count")
    availability = _choice(value["availability"], _AVAILABILITIES, "availability")
    if availability == "available" and value["actual_bytes"] is None:
        raise ProtocolError("invalid_schema", "available attachment needs an actual size")
    components = value["components"]
    if not isinstance(components, list):
        raise ProtocolError("invalid_schema", "attachment components must be a list")
    component_ids: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise ProtocolError("invalid_schema", "attachment component must be an object")
        _exact_keys(component, {"component_id", "role", "actual_bytes"})
        component_id = _string(component["component_id"], "component ID")
        if component_id in component_ids:
            raise ProtocolError("invalid_schema", "component IDs must be unique")
        component_ids.add(component_id)
        _choice(component["role"], _COMPONENT_ROLES, "component role")
        _nonnegative_integer(component["actual_bytes"], "component byte count")
    return attachment_id


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProtocolError("invalid_schema", "value cannot be encoded as JSON") from exc


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate_field", "JSON object has a duplicate field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ProtocolError("invalid_schema", "non-finite numbers are not supported")


def _exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ProtocolError("invalid_schema", "object fields do not match the schema")


def _request_id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_REQUEST_ID.fullmatch(value):
        raise ProtocolError("invalid_schema", "request ID is invalid")
    return value


def _string(value: object, label: str, *, maximum: int = MAX_STRING_LENGTH) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ProtocolError("invalid_schema", f"{label} is invalid")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError("invalid_schema", f"{label} must be an integer")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    result = _integer(value, label)
    if result < 0 or result > 9_223_372_036_854_775_807:
        raise ProtocolError("invalid_schema", f"{label} is outside the supported range")
    return result


def _optional_nonnegative_integer(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_integer(value, label)


def _choice(value: object, choices: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ProtocolError("invalid_schema", f"{label} is unsupported")
    return value
