"""Fail-closed extraction of the observed Messages attributed-string archive."""

from __future__ import annotations

from .errors import AttributedBodyError


MAX_ATTRIBUTED_BODY_BYTES = 1_048_576
MAX_TEXT_BYTES = 262_144

# Exact root object prefix observed in both supplied schema-version-85 snapshots.
# This is deliberately allowlisted rather than scanning opaque archive bytes for
# plausible strings. Unsupported typedstream variants fail closed.
OBSERVED_ATTRIBUTED_STRING_PREFIX = (
    b"\x04\x0bstreamtyped"
    b"\x81\xe8\x03\x84\x01@"
    b"\x84\x84\x84\x12NSAttributedString\x00"
    b"\x84\x84\x08NSObject\x00"
    b"\x85\x92"
    b"\x84\x84\x84\x08NSString\x01"
    b"\x94\x84\x01+"
)


def extract_message_text(
    text: object,
    attributed_body: object,
    *,
    has_attachments: bool,
) -> str | None:
    """Prefer the normal text column, then decode the observed typedstream."""

    if text is not None and not isinstance(text, str):
        raise AttributedBodyError("message text must be a string or null")
    if isinstance(text, str) and text:
        if has_attachments and text == "\ufffc":
            return None
        return text
    if attributed_body is None:
        return None
    return extract_attributed_body_text(attributed_body)


def extract_attributed_body_text(value: object) -> str:
    """Decode the root NSString in the exact observed typedstream variant.

    The decoder validates the archive prefix, typedstream integer encoding,
    declared byte bounds, UTF-8, and the following object terminator. It does
    not instantiate archived classes or search for arbitrary strings.
    """

    if not isinstance(value, bytes):
        raise AttributedBodyError("attributedBody must be bytes")
    if len(value) > MAX_ATTRIBUTED_BODY_BYTES:
        raise AttributedBodyError("attributedBody exceeds the size limit")
    if not value.startswith(OBSERVED_ATTRIBUTED_STRING_PREFIX):
        raise AttributedBodyError("unsupported attributedBody typedstream variant")
    offset = len(OBSERVED_ATTRIBUTED_STRING_PREFIX)
    byte_count, offset = _decode_typedstream_integer(value, offset)
    if byte_count < 0 or byte_count > MAX_TEXT_BYTES:
        raise AttributedBodyError("attributedBody text length is unsafe")
    end = offset + byte_count
    if end >= len(value):
        raise AttributedBodyError("attributedBody text is truncated")
    if value[end] != 0x86:
        raise AttributedBodyError("attributedBody root string is unterminated")
    try:
        return value[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AttributedBodyError("attributedBody text is not valid UTF-8") from exc


def _decode_typedstream_integer(value: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(value):
        raise AttributedBodyError("attributedBody is missing a string length")
    marker = value[offset]
    offset += 1
    if marker <= 0x7F:
        return marker, offset
    widths = {0x81: 2, 0x82: 4, 0x83: 8}
    width = widths.get(marker)
    if width is None or offset + width > len(value):
        raise AttributedBodyError("attributedBody has an invalid string length")
    decoded = int.from_bytes(value[offset : offset + width], "little", signed=True)
    return decoded, offset + width
