"""Strict, path-free Stage 13 outbound command wire contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Mapping, TypeAlias

from bmo.jsonio import loads_json


OUTBOUND_PROTOCOL_VERSION = 1
OUTBOUND_COMMAND_SCHEMA_VERSION = 1
OUTBOUND_COMMAND_PATH = "/v1/outbound/commands"
OUTBOUND_STATUS_PATH = "/v1/outbound/status"
MAX_OUTBOUND_REQUEST_BYTES = 64 * 1024
MAX_TEXT_BYTES = 32 * 1024
MAX_RECIPIENTS = 32
MAX_MEDIA_ITEMS = 10
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024

_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_STABLE_IDENTIFIER = re.compile(r"[\x21-\x7e]{1,1024}\Z")
_PHONE_HANDLE = re.compile(r"\+[1-9][0-9]{1,14}\Z")
_EMAIL_HANDLE = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z"
)
_MIME_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}\Z"
)
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ERROR = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")

_REACTIONS = frozenset(
    {"heart", "thumbs_up", "thumbs_down", "haha", "emphasize", "question"}
)
_COMMAND_STATES = frozenset({"queued", "executing", "sent", "failed", "uncertain"})
_ACK_STATUSES = frozenset({"accepted", "duplicate", "status"})


class OutboundProtocolError(ValueError):
    """An outbound command or response violates the fixed wire contract."""


@dataclass(frozen=True, slots=True)
class OutboundDestination:
    """An explicit recipient set with optional existing-chat/reply context."""

    recipient_ids: tuple[str, ...]
    chat_id: str | None = None
    reply_to_message_id: str | None = None

    def __post_init__(self) -> None:
        recipients = tuple(_handle(item) for item in self.recipient_ids)
        if not 1 <= len(recipients) <= MAX_RECIPIENTS:
            raise OutboundProtocolError("recipient count is outside the supported range")
        if len(set(recipients)) != len(recipients):
            raise OutboundProtocolError("recipient identifiers must be unique")
        object.__setattr__(self, "recipient_ids", recipients)
        if self.chat_id is not None:
            _stable_identifier(self.chat_id, "chat ID")
        if self.reply_to_message_id is not None:
            _stable_identifier(self.reply_to_message_id, "reply target")
            if self.chat_id is None:
                raise OutboundProtocolError("a reply target requires an explicit chat ID")


@dataclass(frozen=True, slots=True)
class OutboundMediaReference:
    """Path-free metadata for one kiosk-to-phone staged photo or video."""

    blob_id: str
    transfer_name: str
    media_category: str
    mime_type: str
    expected_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _token(self.blob_id, "blob ID")
        if (
            not isinstance(self.transfer_name, str)
            or not self.transfer_name
            or len(self.transfer_name.encode("utf-8")) > 255
            or "/" in self.transfer_name
            or "\\" in self.transfer_name
            or self.transfer_name in {".", ".."}
            or any(ord(character) < 32 for character in self.transfer_name)
        ):
            raise OutboundProtocolError("media transfer name is invalid")
        if self.media_category not in {"photo", "video"}:
            raise OutboundProtocolError("media category is unsupported")
        if not isinstance(self.mime_type, str) or not _MIME_TYPE.fullmatch(self.mime_type):
            raise OutboundProtocolError("media MIME type is invalid")
        expected_prefix = "image/" if self.media_category == "photo" else "video/"
        if not self.mime_type.startswith(expected_prefix):
            raise OutboundProtocolError("media MIME type does not match its category")
        if (
            isinstance(self.expected_bytes, bool)
            or not isinstance(self.expected_bytes, int)
            or not 1 <= self.expected_bytes <= MAX_MEDIA_BYTES
        ):
            raise OutboundProtocolError("media byte count is outside the supported range")
        if not isinstance(self.sha256, str) or not _HEX_DIGEST.fullmatch(self.sha256):
            raise OutboundProtocolError("media digest is invalid")


@dataclass(frozen=True, slots=True)
class OutboundTextCommand:
    command_id: str
    created_at_utc: str
    destination: OutboundDestination
    text: str
    kind: str = "text"

    def __post_init__(self) -> None:
        _common_command(self.command_id, self.created_at_utc, self.destination)
        _text(self.text, optional=False)
        if self.kind != "text":
            raise OutboundProtocolError("text command kind is invalid")


@dataclass(frozen=True, slots=True)
class OutboundMediaCommand:
    command_id: str
    created_at_utc: str
    destination: OutboundDestination
    media: tuple[OutboundMediaReference, ...]
    text: str | None = None
    kind: str = "media"

    def __post_init__(self) -> None:
        _common_command(self.command_id, self.created_at_utc, self.destination)
        media = tuple(self.media)
        if not 1 <= len(media) <= MAX_MEDIA_ITEMS:
            raise OutboundProtocolError("media item count is outside the supported range")
        if not all(isinstance(item, OutboundMediaReference) for item in media):
            raise OutboundProtocolError("media entries are invalid")
        if len({item.blob_id for item in media}) != len(media):
            raise OutboundProtocolError("media blob IDs must be unique")
        object.__setattr__(self, "media", media)
        _text(self.text, optional=True)
        if self.kind != "media":
            raise OutboundProtocolError("media command kind is invalid")


@dataclass(frozen=True, slots=True)
class OutboundReactionCommand:
    command_id: str
    created_at_utc: str
    destination: OutboundDestination
    target_message_id: str
    target_part: int
    reaction_kind: str
    operation: str
    kind: str = "reaction"

    def __post_init__(self) -> None:
        _common_command(self.command_id, self.created_at_utc, self.destination)
        _stable_identifier(self.target_message_id, "reaction target")
        if (
            isinstance(self.target_part, bool)
            or not isinstance(self.target_part, int)
            or not 0 <= self.target_part <= 10_000
        ):
            raise OutboundProtocolError("reaction target part is invalid")
        if self.reaction_kind not in _REACTIONS:
            raise OutboundProtocolError("reaction kind is unsupported")
        if self.operation not in {"add", "remove"}:
            raise OutboundProtocolError("reaction operation is unsupported")
        if self.kind != "reaction":
            raise OutboundProtocolError("reaction command kind is invalid")


OutboundCommand: TypeAlias = (
    OutboundTextCommand | OutboundMediaCommand | OutboundReactionCommand
)


@dataclass(frozen=True, slots=True)
class OutboundCommandAck:
    command_id: str
    status: str
    command_state: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        _token(self.command_id, "command ID")
        if self.status not in _ACK_STATUSES:
            raise OutboundProtocolError("outbound ACK status is invalid")
        if self.command_state not in _COMMAND_STATES:
            raise OutboundProtocolError("outbound ACK command state is invalid")
        if self.command_state in {"failed", "uncertain"}:
            if (
                not isinstance(self.error_code, str)
                or not _SAFE_ERROR.fullmatch(self.error_code)
            ):
                raise OutboundProtocolError("outbound ACK error code is invalid")
        elif self.error_code is not None:
            raise OutboundProtocolError(
                "successful outbound ACK cannot contain an error code"
            )


def encode_submit_request(*, request_id: str, command: OutboundCommand) -> bytes:
    """Encode one canonical command submission without filesystem paths."""

    body = _canonical_json(
        {
            "command": command_to_mapping(command),
            "protocol_version": OUTBOUND_PROTOCOL_VERSION,
            "request_id": _token(request_id, "request ID"),
        }
    )
    if len(body) > MAX_OUTBOUND_REQUEST_BYTES:
        raise OutboundProtocolError("outbound request exceeds the size limit")
    return body


def encode_command(command: OutboundCommand) -> bytes:
    """Encode only the canonical durable command object."""

    body = _canonical_json(command_to_mapping(command))
    if len(body) > MAX_OUTBOUND_REQUEST_BYTES:
        raise OutboundProtocolError("outbound command exceeds the size limit")
    return body


def decode_submit_request(body: bytes) -> tuple[str, OutboundCommand]:
    """Decode a strict command request for shared-vector and phone tests."""

    value = _decode_object(body)
    if set(value) != {"command", "protocol_version", "request_id"}:
        raise OutboundProtocolError("outbound request fields are invalid")
    if value.get("protocol_version") != OUTBOUND_PROTOCOL_VERSION:
        raise OutboundProtocolError("outbound protocol version is unsupported")
    request_id = _token(value.get("request_id"), "request ID")
    return request_id, command_from_mapping(value.get("command"))


def encode_status_request(*, request_id: str, command_id: str) -> bytes:
    body = _canonical_json(
        {
            "action": "status",
            "command_id": _token(command_id, "command ID"),
            "protocol_version": OUTBOUND_PROTOCOL_VERSION,
            "request_id": _token(request_id, "request ID"),
        }
    )
    if len(body) > MAX_OUTBOUND_REQUEST_BYTES:
        raise OutboundProtocolError("outbound status request exceeds the size limit")
    return body


def decode_status_request(body: bytes) -> tuple[str, str]:
    value = _decode_object(body)
    if set(value) != {"action", "command_id", "protocol_version", "request_id"}:
        raise OutboundProtocolError("outbound status request fields are invalid")
    if (
        value.get("action") != "status"
        or value.get("protocol_version") != OUTBOUND_PROTOCOL_VERSION
    ):
        raise OutboundProtocolError("outbound status request is invalid")
    return (
        _token(value.get("request_id"), "request ID"),
        _token(value.get("command_id"), "command ID"),
    )


def encode_command_response(*, request_id: str, ack: OutboundCommandAck) -> bytes:
    if not isinstance(ack, OutboundCommandAck):
        raise TypeError("ack must be an OutboundCommandAck")
    value: dict[str, object] = {
        "command_id": ack.command_id,
        "command_state": ack.command_state,
        "protocol_version": OUTBOUND_PROTOCOL_VERSION,
        "request_id": _token(request_id, "request ID"),
        "result": "ack",
        "status": ack.status,
    }
    if ack.error_code is not None:
        value["error_code"] = ack.error_code
    return _canonical_json(value)


def decode_command_response(
    body: bytes,
    *,
    expected_request_id: str,
    expected_command_id: str,
) -> OutboundCommandAck:
    value = _decode_object(body)
    common = {
        "command_id",
        "command_state",
        "protocol_version",
        "request_id",
        "result",
        "status",
    }
    state = value.get("command_state")
    expected = common | ({"error_code"} if state in {"failed", "uncertain"} else set())
    if set(value) != expected:
        raise OutboundProtocolError("outbound response fields are invalid")
    if (
        value.get("protocol_version") != OUTBOUND_PROTOCOL_VERSION
        or value.get("request_id") != _token(expected_request_id, "request ID")
        or value.get("command_id") != _token(expected_command_id, "command ID")
        or value.get("result") != "ack"
        or value.get("status") not in _ACK_STATUSES
        or state not in _COMMAND_STATES
    ):
        raise OutboundProtocolError("outbound response identity is invalid")
    error_code = value.get("error_code")
    if state in {"failed", "uncertain"}:
        if not isinstance(error_code, str) or not _SAFE_ERROR.fullmatch(error_code):
            raise OutboundProtocolError("outbound response error code is invalid")
    else:
        error_code = None
    return OutboundCommandAck(
        command_id=expected_command_id,
        status=str(value["status"]),
        command_state=str(state),
        error_code=error_code,
    )


def command_to_mapping(command: OutboundCommand) -> dict[str, object]:
    if not isinstance(
        command,
        (OutboundTextCommand, OutboundMediaCommand, OutboundReactionCommand),
    ):
        raise TypeError("command has an unsupported type")
    value: dict[str, object] = {
        "command_id": command.command_id,
        "created_at_utc": command.created_at_utc,
        "destination": _destination_mapping(command.destination),
        "kind": command.kind,
        "schema_version": OUTBOUND_COMMAND_SCHEMA_VERSION,
    }
    if isinstance(command, OutboundTextCommand):
        value["text"] = command.text
    elif isinstance(command, OutboundMediaCommand):
        value["media"] = [
            {
                "blob_id": item.blob_id,
                "expected_bytes": item.expected_bytes,
                "media_category": item.media_category,
                "mime_type": item.mime_type,
                "sha256": item.sha256,
                "transfer_name": item.transfer_name,
            }
            for item in command.media
        ]
        value["text"] = command.text
    else:
        value.update(
            {
                "operation": command.operation,
                "reaction_kind": command.reaction_kind,
                "target_message_id": command.target_message_id,
                "target_part": command.target_part,
            }
        )
    return value


def command_from_mapping(value: object) -> OutboundCommand:
    if not isinstance(value, dict):
        raise OutboundProtocolError("outbound command must be an object")
    common = {"command_id", "created_at_utc", "destination", "kind", "schema_version"}
    if value.get("schema_version") != OUTBOUND_COMMAND_SCHEMA_VERSION:
        raise OutboundProtocolError("outbound command version is unsupported")
    destination = _destination_from_mapping(value.get("destination"))
    common_arguments = {
        "command_id": value.get("command_id"),
        "created_at_utc": value.get("created_at_utc"),
        "destination": destination,
    }
    kind = value.get("kind")
    if kind == "text":
        if set(value) != common | {"text"}:
            raise OutboundProtocolError("text command fields are invalid")
        return OutboundTextCommand(text=value.get("text"), **common_arguments)  # type: ignore[arg-type]
    if kind == "media":
        if set(value) != common | {"media", "text"}:
            raise OutboundProtocolError("media command fields are invalid")
        media_value = value.get("media")
        if not isinstance(media_value, list):
            raise OutboundProtocolError("media command entries are invalid")
        media = tuple(_media_from_mapping(item) for item in media_value)
        return OutboundMediaCommand(
            media=media,
            text=value.get("text"),
            **common_arguments,  # type: ignore[arg-type]
        )
    if kind == "reaction":
        reaction_fields = {
            "operation",
            "reaction_kind",
            "target_message_id",
            "target_part",
        }
        if set(value) != common | reaction_fields:
            raise OutboundProtocolError("reaction command fields are invalid")
        return OutboundReactionCommand(
            target_message_id=value.get("target_message_id"),
            target_part=value.get("target_part"),
            reaction_kind=value.get("reaction_kind"),
            operation=value.get("operation"),
            **common_arguments,  # type: ignore[arg-type]
        )
    raise OutboundProtocolError("outbound command kind is unsupported")


def _destination_mapping(destination: OutboundDestination) -> dict[str, object]:
    if not isinstance(destination, OutboundDestination):
        raise TypeError("destination must be an OutboundDestination")
    return {
        "chat_id": destination.chat_id,
        "recipient_ids": list(destination.recipient_ids),
        "reply_to_message_id": destination.reply_to_message_id,
    }


def _destination_from_mapping(value: object) -> OutboundDestination:
    if not isinstance(value, dict) or set(value) != {
        "chat_id",
        "recipient_ids",
        "reply_to_message_id",
    }:
        raise OutboundProtocolError("outbound destination fields are invalid")
    recipients = value.get("recipient_ids")
    if not isinstance(recipients, list):
        raise OutboundProtocolError("recipient identifiers must be an array")
    return OutboundDestination(
        tuple(recipients),  # type: ignore[arg-type]
        chat_id=value.get("chat_id"),  # type: ignore[arg-type]
        reply_to_message_id=value.get("reply_to_message_id"),  # type: ignore[arg-type]
    )


def _media_from_mapping(value: object) -> OutboundMediaReference:
    if not isinstance(value, dict) or set(value) != {
        "blob_id",
        "expected_bytes",
        "media_category",
        "mime_type",
        "sha256",
        "transfer_name",
    }:
        raise OutboundProtocolError("media reference fields are invalid")
    return OutboundMediaReference(**value)  # type: ignore[arg-type]


def _decode_object(body: bytes) -> dict[str, Any]:
    if not isinstance(body, bytes) or not body or len(body) > MAX_OUTBOUND_REQUEST_BYTES:
        raise OutboundProtocolError("outbound JSON body is invalid")
    try:
        value = loads_json(body)
    except (TypeError, UnicodeError, ValueError, RecursionError) as exc:
        raise OutboundProtocolError("outbound JSON body is invalid") from exc
    if not isinstance(value, dict):
        raise OutboundProtocolError("outbound JSON body must be an object")
    return value


def _common_command(
    command_id: object,
    created_at_utc: object,
    destination: object,
) -> None:
    _token(command_id, "command ID")
    _utc_timestamp(created_at_utc)
    if not isinstance(destination, OutboundDestination):
        raise OutboundProtocolError("outbound destination is invalid")


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise OutboundProtocolError(f"{label} is invalid")
    return value


def _stable_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _STABLE_IDENTIFIER.fullmatch(value):
        raise OutboundProtocolError(f"{label} is invalid")
    return value


def _handle(value: object) -> str:
    if not isinstance(value, str) or not (
        _PHONE_HANDLE.fullmatch(value) or _EMAIL_HANDLE.fullmatch(value)
    ):
        raise OutboundProtocolError("recipient identifier is not canonical")
    return value


def _utc_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise OutboundProtocolError("command timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OutboundProtocolError("command timestamp is invalid") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
        or parsed.microsecond
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise OutboundProtocolError("command timestamp must be canonical UTC seconds")
    return value


def _text(value: object, *, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_TEXT_BYTES
    ):
        raise OutboundProtocolError("message text is invalid")
    return value


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeError, ValueError, RecursionError) as exc:
        raise OutboundProtocolError("outbound value cannot be encoded") from exc


__all__ = [
    "MAX_MEDIA_BYTES",
    "MAX_MEDIA_ITEMS",
    "MAX_OUTBOUND_REQUEST_BYTES",
    "MAX_RECIPIENTS",
    "MAX_TEXT_BYTES",
    "OUTBOUND_COMMAND_PATH",
    "OUTBOUND_COMMAND_SCHEMA_VERSION",
    "OUTBOUND_PROTOCOL_VERSION",
    "OUTBOUND_STATUS_PATH",
    "OutboundCommand",
    "OutboundCommandAck",
    "OutboundDestination",
    "OutboundMediaCommand",
    "OutboundMediaReference",
    "OutboundProtocolError",
    "OutboundReactionCommand",
    "OutboundTextCommand",
    "command_from_mapping",
    "command_to_mapping",
    "decode_status_request",
    "decode_command_response",
    "decode_submit_request",
    "encode_command",
    "encode_command_response",
    "encode_status_request",
    "encode_submit_request",
]
