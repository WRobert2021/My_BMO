"""Validated, atomic persistence for alarm-clock state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from bmo.jsonio import atomic_write_json, load_json


STATE_VERSION = 1
MAX_STATE_BYTES = 512 * 1024


class AlarmPersistenceError(RuntimeError):
    """Raised when alarm state cannot be safely loaded or saved."""


@dataclass(frozen=True, slots=True)
class AlarmRecord:
    """One local alarm and its optional recurrence/snooze state."""

    alarm_id: int
    hour: int
    minute: int
    label: str = "Alarm"
    enabled: bool = True
    weekdays: tuple[int, ...] = ()
    one_time_date: date | None = None
    snoozed_until: datetime | None = None

    def __post_init__(self) -> None:
        if isinstance(self.alarm_id, bool) or not isinstance(self.alarm_id, int) or self.alarm_id < 1:
            raise ValueError("alarm id must be a positive integer")
        if isinstance(self.hour, bool) or not isinstance(self.hour, int) or not 0 <= self.hour <= 23:
            raise ValueError("alarm hour must be from 0 to 23")
        if isinstance(self.minute, bool) or not isinstance(self.minute, int) or not 0 <= self.minute <= 59:
            raise ValueError("alarm minute must be from 0 to 59")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("alarm label cannot be empty")
        label = self.label.strip()
        if len(label) > 60:
            raise ValueError("alarm label is too long")
        object.__setattr__(self, "label", label)
        if not isinstance(self.enabled, bool):
            raise TypeError("alarm enabled must be boolean")
        if not isinstance(self.weekdays, tuple):
            raise TypeError("alarm weekdays must be a tuple")
        weekdays = tuple(sorted(set(self.weekdays)))
        if any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in weekdays):
            raise ValueError("alarm weekdays must be numbers from 0 to 6")
        object.__setattr__(self, "weekdays", weekdays)
        if self.one_time_date is not None and type(self.one_time_date) is not date:
            raise TypeError("one-time alarm date must be a date")
        if self.snoozed_until is not None and type(self.snoozed_until) is not datetime:
            raise TypeError("alarm snooze value must be a datetime")
        if weekdays and self.one_time_date is not None:
            raise ValueError("repeating alarms cannot have a one-time date")

    @property
    def repeating(self) -> bool:
        return bool(self.weekdays)

    def with_enabled(self, enabled: bool, *, one_time_date: date | None = None) -> AlarmRecord:
        return replace(
            self,
            enabled=enabled,
            one_time_date=None if self.repeating else one_time_date,
            snoozed_until=None,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.alarm_id,
            "hour": self.hour,
            "minute": self.minute,
            "label": self.label,
            "enabled": self.enabled,
            "weekdays": list(self.weekdays),
            "one_time_date": self.one_time_date.isoformat() if self.one_time_date else None,
            "snoozed_until": self.snoozed_until.isoformat(timespec="minutes") if self.snoozed_until else None,
        }


@dataclass(frozen=True, slots=True)
class AlarmState:
    alarms: tuple[AlarmRecord, ...] = ()
    next_id: int = 1
    use_24_hour: bool = False


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AlarmPersistenceError(f"{label} has invalid fields")


def _parse_optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AlarmPersistenceError("alarm date must be a string or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AlarmPersistenceError("alarm date is invalid") from exc


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AlarmPersistenceError("alarm snooze must be a string or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AlarmPersistenceError("alarm snooze is invalid") from exc
    if parsed.tzinfo is not None:
        raise AlarmPersistenceError("alarm snooze must use local time")
    return parsed


def decode_alarm_state(value: object, *, default_24_hour: bool = False) -> AlarmState:
    if not isinstance(value, Mapping):
        raise AlarmPersistenceError("alarm state root must be an object")
    _exact_keys(value, {"version", "next_id", "use_24_hour", "alarms"}, "alarm state")
    if value["version"] != STATE_VERSION:
        raise AlarmPersistenceError("alarm state version is unsupported")
    next_id = value["next_id"]
    use_24_hour = value["use_24_hour"]
    alarms_value = value["alarms"]
    if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id < 1:
        raise AlarmPersistenceError("alarm next_id is invalid")
    if not isinstance(use_24_hour, bool):
        raise AlarmPersistenceError("alarm use_24_hour is invalid")
    if not isinstance(alarms_value, list) or len(alarms_value) > 100:
        raise AlarmPersistenceError("alarm list is invalid")
    alarms: list[AlarmRecord] = []
    ids: set[int] = set()
    for raw in alarms_value:
        if not isinstance(raw, Mapping):
            raise AlarmPersistenceError("alarm record must be an object")
        _exact_keys(
            raw,
            {"id", "hour", "minute", "label", "enabled", "weekdays", "one_time_date", "snoozed_until"},
            "alarm record",
        )
        weekdays = raw["weekdays"]
        if not isinstance(weekdays, list):
            raise AlarmPersistenceError("alarm weekdays must be a list")
        try:
            alarm = AlarmRecord(
                alarm_id=raw["id"],
                hour=raw["hour"],
                minute=raw["minute"],
                label=raw["label"],
                enabled=raw["enabled"],
                weekdays=tuple(weekdays),
                one_time_date=_parse_optional_date(raw["one_time_date"]),
                snoozed_until=_parse_optional_datetime(raw["snoozed_until"]),
            )
        except (TypeError, ValueError) as exc:
            raise AlarmPersistenceError(str(exc)) from exc
        if alarm.alarm_id in ids:
            raise AlarmPersistenceError("alarm ids must be unique")
        ids.add(alarm.alarm_id)
        alarms.append(alarm)
    if ids and next_id <= max(ids):
        raise AlarmPersistenceError("alarm next_id must exceed every alarm id")
    return AlarmState(tuple(alarms), next_id, use_24_hour)


class AlarmStore:
    """Load and atomically replace one private alarm state file."""

    def __init__(self, path: Path | None, *, default_24_hour: bool = False) -> None:
        self.path = path
        self.read_only = False
        self.error = ""
        self.state = AlarmState(use_24_hour=default_24_hour)
        if path is not None and path.exists():
            try:
                if path.stat().st_size > MAX_STATE_BYTES:
                    raise AlarmPersistenceError("alarm state is too large")
                with path.open("r", encoding="utf-8") as handle:
                    self.state = decode_alarm_state(
                        load_json(handle), default_24_hour=default_24_hour
                    )
            except (OSError, ValueError, AlarmPersistenceError) as exc:
                self.read_only = True
                self.error = f"Alarm data could not be loaded ({type(exc).__name__})."

    def save(self, state: AlarmState) -> None:
        if self.read_only:
            raise AlarmPersistenceError("alarm data is read-only")
        if self.path is not None:
            atomic_write_json(
                self.path,
                {
                    "version": STATE_VERSION,
                    "next_id": state.next_id,
                    "use_24_hour": state.use_24_hour,
                    "alarms": [alarm.to_json() for alarm in state.alarms],
                },
            )
        self.state = state


__all__ = [
    "AlarmPersistenceError",
    "AlarmRecord",
    "AlarmState",
    "AlarmStore",
    "decode_alarm_state",
]
