"""Exact Apple-reference timestamp conversion for Messages source values."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from iphone_relay.errors import SourceRecordError


APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
APPLE_TO_UNIX_SECONDS = 978_307_200


def apple_nanoseconds_to_datetime(value: object) -> datetime:
    """Convert integer nanoseconds since 2001 UTC without float rounding."""

    raw = _required_nonnegative_integer(value, "message timestamp")
    seconds, nanoseconds = divmod(raw, 1_000_000_000)
    try:
        return APPLE_EPOCH + timedelta(
            seconds=seconds,
            microseconds=nanoseconds // 1_000,
        )
    except OverflowError as exc:
        raise SourceRecordError(
            "message timestamp is outside the supported range"
        ) from exc


def apple_seconds_to_datetime(value: object) -> datetime:
    """Convert integer seconds since 2001 UTC."""

    raw = _required_nonnegative_integer(value, "attachment timestamp")
    try:
        return APPLE_EPOCH + timedelta(seconds=raw)
    except OverflowError as exc:
        raise SourceRecordError(
            "attachment timestamp is outside the supported range"
        ) from exc


def _required_nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceRecordError(f"{label} must be a non-negative integer")
    return value
