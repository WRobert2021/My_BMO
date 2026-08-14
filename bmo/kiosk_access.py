"""Global quiet-hours policy and parent unlock state for the whole kiosk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from bmo.jsonio import load_json


DEFAULT_QUIET_HOURS_CONFIG_PATH = Path("config/quiet_hours.json")
DEFAULT_SLEEPING_FACE_DIRECTORY = Path("faces/sleeping")


@dataclass(frozen=True)
class QuietHoursConfig:
    """Validated global kiosk quiet-hours settings."""

    enabled: bool = False
    start: time = time(21, 0)
    end: time = time(7, 0)
    weekdays: tuple[int, ...] = tuple(range(7))
    passcode: str = "0000"
    sleeping_face_directory: Path = DEFAULT_SLEEPING_FACE_DIRECTORY

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("quiet-hours enabled must be true or false")
        weekdays = tuple(sorted(set(self.weekdays)))
        if any(not isinstance(day, int) or not 0 <= day <= 6 for day in weekdays):
            raise ValueError("quiet-hours weekdays must contain integers from 0 to 6")
        if not weekdays:
            raise ValueError("quiet-hours weekdays cannot be empty")
        if self.start == self.end:
            raise ValueError("quiet-hours start and end cannot be the same")
        if not isinstance(self.passcode, str) or not self.passcode.isdigit() or len(self.passcode) != 4:
            raise ValueError("quiet-hours passcode must contain exactly four digits")
        object.__setattr__(self, "weekdays", weekdays)
        object.__setattr__(self, "sleeping_face_directory", Path(self.sleeping_face_directory))


def _parse_time(value: object, label: str, default: time) -> time:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"quiet-hours {label} must use HH:MM")
    try:
        return time.fromisoformat(value).replace(second=0, microsecond=0)
    except ValueError as exc:
        raise ValueError(f"quiet-hours {label} must use HH:MM") from exc


def _parse_config(values: Mapping[str, Any]) -> QuietHoursConfig:
    allowed = {
        "enabled",
        "start",
        "end",
        "weekdays",
        "passcode",
        "sleeping_face_directory",
    }
    unknown = set(values).difference(allowed)
    if unknown:
        raise ValueError("unknown quiet-hours setting(s): " + ", ".join(sorted(unknown)))
    enabled = values.get("enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("quiet-hours enabled must be true or false")
    raw_weekdays = values.get("weekdays", list(range(7)))
    if not isinstance(raw_weekdays, list):
        raise ValueError("quiet-hours weekdays must be a list")
    raw_path = values.get("sleeping_face_directory", DEFAULT_SLEEPING_FACE_DIRECTORY)
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        raise ValueError("quiet-hours sleeping_face_directory must be a path")
    return QuietHoursConfig(
        enabled=enabled,
        start=_parse_time(values.get("start"), "start", time(21)),
        end=_parse_time(values.get("end"), "end", time(7)),
        weekdays=tuple(raw_weekdays),
        passcode=str(values.get("passcode", "0000")),
        sleeping_face_directory=Path(raw_path).expanduser(),
    )


def load_quiet_hours_config(
    path: str | Path = DEFAULT_QUIET_HOURS_CONFIG_PATH,
    *,
    reporter: Callable[[str], None] = print,
) -> QuietHoursConfig:
    """Load optional private global quiet-hours configuration."""
    config_path = Path(path)
    if not config_path.exists():
        return QuietHoursConfig()
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            values = load_json(handle)
        if not isinstance(values, Mapping):
            raise ValueError("quiet-hours configuration root must be an object")
        return _parse_config(values)
    except (OSError, TypeError, ValueError) as exc:
        reporter(f"[QUIET HOURS] Could not load {config_path}: {exc}. Disabled.")
        return QuietHoursConfig()


class KioskAccessPolicy:
    """Calculate quiet periods and retain an unlock for only one period."""

    def __init__(
        self,
        config: QuietHoursConfig,
        *,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.now = now
        self._unlocked_period: date | None = None

    def scheduled_period(self, moment: datetime | None = None) -> date | None:
        if not self.config.enabled:
            return None
        current = moment or self.now()
        current_time = current.time().replace(second=0, microsecond=0)
        start, end = self.config.start, self.config.end
        if start < end:
            if start <= current_time < end:
                period_date = current.date()
            else:
                return None
        elif current_time >= start:
            period_date = current.date()
        elif current_time < end:
            period_date = current.date() - timedelta(days=1)
        else:
            return None
        return period_date if period_date.weekday() in self.config.weekdays else None

    def is_locked(self, moment: datetime | None = None) -> bool:
        period = self.scheduled_period(moment)
        if period is None:
            self._unlocked_period = None
            return False
        return period != self._unlocked_period

    def unlock(self, passcode: str, moment: datetime | None = None) -> bool:
        period = self.scheduled_period(moment)
        if period is None or str(passcode) != self.config.passcode:
            return False
        self._unlocked_period = period
        return True
