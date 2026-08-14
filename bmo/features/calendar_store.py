"""Validated calendar records, recurrence expansion, holidays, and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, time, timedelta
import calendar as month_calendar
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from bmo.jsonio import atomic_write_json, load_json


SCHEMA_VERSION = 1
ACKNOWLEDGEMENT_SCHEMA_VERSION = 1
VALID_FREQUENCIES = frozenset({"none", "weekly", "monthly", "yearly"})
VALID_MONTHLY_OVERFLOW = frozenset({"last_day", "skip"})
DEFAULT_CATEGORIES = (
    "Personal",
    "Family",
    "School",
    "Appointment",
    "Holiday",
    "Other",
)


class CalendarDataError(ValueError):
    """Raised when calendar data is unsafe to load or persist."""


def _require_date(value: object, label: str) -> date:
    if type(value) is not date:
        raise CalendarDataError(f"{label} must be a date")
    return value


@dataclass(frozen=True)
class RecurrenceRule:
    """A bounded recurrence rule owned by one calendar event."""

    frequency: str = "none"
    weekdays: tuple[int, ...] = ()
    end_date: date | None = None
    count: int | None = None
    monthly_overflow: str = "last_day"

    def __post_init__(self) -> None:
        frequency = str(self.frequency).strip().lower()
        if frequency not in VALID_FREQUENCIES:
            raise CalendarDataError(f"unsupported recurrence frequency: {frequency}")
        try:
            raw_weekdays = tuple(self.weekdays)
        except TypeError as exc:
            raise CalendarDataError(
                "recurrence weekdays must be a sequence"
            ) from exc
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 6
            for value in raw_weekdays
        ):
            raise CalendarDataError("recurrence weekdays must be integers from 0 to 6")
        weekdays = tuple(sorted(set(raw_weekdays)))
        if frequency != "weekly" and weekdays:
            raise CalendarDataError("recurrence weekdays are only valid for weekly events")
        if self.end_date is not None:
            _require_date(self.end_date, "recurrence end_date")
        if self.count is not None and (
            isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1
        ):
            raise CalendarDataError("recurrence count must be a positive integer")
        overflow = str(self.monthly_overflow).strip().lower()
        if overflow not in VALID_MONTHLY_OVERFLOW:
            raise CalendarDataError("monthly overflow must be last_day or skip")
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "weekdays", weekdays)
        object.__setattr__(self, "monthly_overflow", overflow)

    def to_json(self) -> dict[str, Any]:
        return {
            "frequency": self.frequency,
            "weekdays": list(self.weekdays),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "count": self.count,
            "monthly_overflow": self.monthly_overflow,
        }

    @classmethod
    def from_json(cls, value: object) -> RecurrenceRule:
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise CalendarDataError("event recurrence must be an object")
        weekdays = value.get("weekdays", [])
        if not isinstance(weekdays, list):
            raise CalendarDataError("recurrence weekdays must be a list")
        return cls(
            frequency=str(value.get("frequency", "none")),
            weekdays=tuple(weekdays),
            end_date=_optional_date(value.get("end_date"), "recurrence end_date"),
            count=value.get("count"),
            monthly_overflow=str(value.get("monthly_overflow", "last_day")),
        )


@dataclass(frozen=True)
class CalendarEvent:
    """One persisted calendar event or one occurrence override."""

    event_id: str
    name: str
    start_date: date
    all_day: bool = False
    start_time: time | None = None
    end_time: time | None = None
    color: str = "#4D87D9"
    category: str = "Personal"
    notes: str = ""
    recurrence: RecurrenceRule = field(default_factory=RecurrenceRule)
    excluded_dates: tuple[date, ...] = ()
    parent_event_id: str | None = None
    read_only: bool = False
    overlay: str | None = None

    def __post_init__(self) -> None:
        event_id = str(self.event_id).strip()
        name = str(self.name).strip()
        category = str(self.category).strip()
        notes = str(self.notes)
        if not event_id:
            raise CalendarDataError("event id cannot be empty")
        if not name:
            raise CalendarDataError("event name cannot be empty")
        if not category:
            raise CalendarDataError("event category cannot be empty")
        _require_date(self.start_date, "event start_date")
        if not isinstance(self.all_day, bool):
            raise CalendarDataError("event all_day must be a boolean")
        if self.start_time is not None and type(self.start_time) is not time:
            raise CalendarDataError("event start_time must be a time")
        if self.end_time is not None and type(self.end_time) is not time:
            raise CalendarDataError("event end_time must be a time")
        if self.all_day and (self.start_time is not None or self.end_time is not None):
            raise CalendarDataError("all-day events cannot include times")
        if not self.all_day and self.start_time is None:
            raise CalendarDataError("timed events require a start time")
        if self.end_time is not None and self.start_time is not None:
            if self.end_time <= self.start_time:
                raise CalendarDataError("event end time must be after its start time")
        color = str(self.color).strip().upper()
        if len(color) != 7 or not color.startswith("#"):
            raise CalendarDataError("event color must use #RRGGBB")
        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise CalendarDataError("event color must use #RRGGBB") from exc
        try:
            raw_exclusions = tuple(self.excluded_dates)
        except TypeError as exc:
            raise CalendarDataError(
                "excluded dates must be a sequence"
            ) from exc
        for value in raw_exclusions:
            _require_date(value, "excluded dates")
        if not isinstance(self.recurrence, RecurrenceRule):
            raise CalendarDataError("event recurrence must be a RecurrenceRule")
        if not isinstance(self.read_only, bool):
            raise CalendarDataError("event read_only must be a boolean")
        exclusions = tuple(sorted(set(raw_exclusions)))
        parent = str(self.parent_event_id).strip() if self.parent_event_id else None
        overlay = str(self.overlay).strip() if self.overlay else None
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "color", color)
        object.__setattr__(self, "excluded_dates", exclusions)
        object.__setattr__(self, "parent_event_id", parent)
        object.__setattr__(self, "overlay", overlay)

    @property
    def repeating(self) -> bool:
        return self.recurrence.frequency != "none"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "name": self.name,
            "start_date": self.start_date.isoformat(),
            "all_day": self.all_day,
            "start_time": _format_time(self.start_time),
            "end_time": _format_time(self.end_time),
            "color": self.color,
            "category": self.category,
            "notes": self.notes,
            "recurrence": self.recurrence.to_json(),
            "excluded_dates": [value.isoformat() for value in self.excluded_dates],
            "parent_event_id": self.parent_event_id,
            "overlay": self.overlay,
        }

    @classmethod
    def from_json(cls, value: object) -> CalendarEvent:
        if not isinstance(value, Mapping):
            raise CalendarDataError("each event must be an object")
        excluded_dates = value.get("excluded_dates", [])
        if not isinstance(excluded_dates, list):
            raise CalendarDataError("excluded dates must be a list")
        return cls(
            event_id=_required_string(value.get("id"), "event id"),
            name=_required_string(value.get("name"), "event name"),
            start_date=_required_date(value.get("start_date"), "event start_date"),
            all_day=value.get("all_day", False),
            start_time=_optional_time(value.get("start_time"), "event start_time"),
            end_time=_optional_time(value.get("end_time"), "event end_time"),
            color=str(value.get("color", "#4D87D9")),
            category=str(value.get("category", "Personal")),
            notes=str(value.get("notes", "")),
            recurrence=RecurrenceRule.from_json(value.get("recurrence")),
            excluded_dates=tuple(
                _required_date(item, "excluded date")
                for item in excluded_dates
            ),
            parent_event_id=value.get("parent_event_id"),
            overlay=value.get("overlay"),
        )


@dataclass(frozen=True)
class CalendarOccurrence:
    """One concrete event occurrence within a requested date range."""

    event: CalendarEvent
    occurrence_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.event, CalendarEvent):
            raise CalendarDataError("occurrence event must be a CalendarEvent")
        _require_date(self.occurrence_date, "occurrence date")

    @property
    def occurrence_id(self) -> str:
        return f"{self.event.event_id}@{self.occurrence_date.isoformat()}"


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CalendarDataError(f"{label} must be a non-empty string")
    return value.strip()


def _required_date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise CalendarDataError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarDataError(f"{label} must be an ISO date") from exc


def _optional_date(value: object, label: str) -> date | None:
    if value is None:
        return None
    return _required_date(value, label)


def _optional_time(value: object, label: str) -> time | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CalendarDataError(f"{label} must be an ISO time")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise CalendarDataError(f"{label} must be an ISO time") from exc
    return parsed.replace(second=0, microsecond=0)


def _format_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_json(
        path,
        value,
        indent=2,
        ensure_ascii=False,
        replace=os.replace,
    )


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return load_json(handle)


class CalendarStore:
    """Own calendar JSON and per-occurrence acknowledgment persistence."""

    def __init__(self, data_directory: str | Path) -> None:
        self.data_directory = Path(data_directory).expanduser()
        self.events_path = self.data_directory / "events.json"
        self.acknowledgements_path = self.data_directory / "acknowledgements.json"
        self._events: tuple[CalendarEvent, ...] = ()
        self._acknowledged: set[str] = set()
        self._loaded = False
        self._read_only_error: str | None = None

    @property
    def read_only_error(self) -> str | None:
        return self._read_only_error

    def load(self) -> None:
        if self._loaded:
            return
        events: tuple[CalendarEvent, ...] = ()
        acknowledgements: set[str] = set()
        errors = []
        if self.events_path.exists():
            try:
                value = _read_json(self.events_path)
                if not isinstance(value, Mapping) or value.get("version") != SCHEMA_VERSION:
                    raise CalendarDataError("unsupported calendar event schema")
                raw_events = value.get("events")
                if not isinstance(raw_events, list):
                    raise CalendarDataError("calendar events must be a list")
                events = tuple(CalendarEvent.from_json(item) for item in raw_events)
                identifiers = [event.event_id for event in events]
                if len(identifiers) != len(set(identifiers)):
                    raise CalendarDataError("calendar event ids must be unique")
            except (OSError, TypeError, ValueError) as exc:
                errors.append(f"events: {exc}")
        if self.acknowledgements_path.exists():
            try:
                value = _read_json(self.acknowledgements_path)
                if (
                    not isinstance(value, Mapping)
                    or value.get("version") != ACKNOWLEDGEMENT_SCHEMA_VERSION
                ):
                    raise CalendarDataError("unsupported acknowledgement schema")
                raw_acknowledged = value.get("acknowledged")
                if not isinstance(raw_acknowledged, list) or not all(
                    isinstance(item, str) and item for item in raw_acknowledged
                ):
                    raise CalendarDataError("acknowledged ids must be strings")
                acknowledgements = set(raw_acknowledged)
            except (OSError, TypeError, ValueError) as exc:
                errors.append(f"acknowledgements: {exc}")
        self._events = events
        self._acknowledged = acknowledgements
        self._read_only_error = "; ".join(errors) or None
        self._loaded = True

    def events(self) -> tuple[CalendarEvent, ...]:
        self.load()
        return self._events

    def replace_events(self, events: Iterable[CalendarEvent]) -> None:
        self.load()
        if self._read_only_error:
            raise CalendarDataError(
                "calendar data is read-only until its malformed file is repaired"
            )
        try:
            supplied = tuple(events)
        except TypeError as exc:
            raise CalendarDataError(
                "calendar events must be an iterable of CalendarEvent values"
            ) from exc
        if not all(isinstance(event, CalendarEvent) for event in supplied):
            raise CalendarDataError("calendar events must be CalendarEvent values")
        identifiers = [event.event_id for event in supplied]
        if len(identifiers) != len(set(identifiers)):
            raise CalendarDataError("calendar event ids must be unique")
        _atomic_write_json(
            self.events_path,
            {"version": SCHEMA_VERSION, "events": [event.to_json() for event in supplied]},
        )
        self._events = supplied

    def add(self, event: CalendarEvent) -> CalendarEvent:
        self.replace_events((*self.events(), event))
        return event

    def create(self, **values: Any) -> CalendarEvent:
        return self.add(CalendarEvent(event_id=str(uuid4()), **values))

    def update_series(self, event: CalendarEvent) -> CalendarEvent:
        found = False
        updated = []
        for existing in self.events():
            if existing.event_id == event.event_id:
                updated.append(event)
                found = True
            else:
                updated.append(existing)
        if not found:
            raise KeyError(event.event_id)
        self.replace_events(updated)
        return event

    def delete_series(self, event_id: str) -> bool:
        existing = self.events()
        retained = tuple(event for event in existing if event.event_id != event_id)
        if len(retained) == len(existing):
            return False
        self.replace_events(retained)
        return True

    def exclude_occurrence(self, event_id: str, occurrence_date: date) -> CalendarEvent:
        _require_date(occurrence_date, "occurrence date")
        event = next((item for item in self.events() if item.event_id == event_id), None)
        if event is None:
            raise KeyError(event_id)
        updated = replace(
            event,
            excluded_dates=tuple(sorted((*event.excluded_dates, occurrence_date))),
        )
        return self.update_series(updated)

    def override_occurrence(
        self,
        event_id: str,
        occurrence_date: date,
        replacement: CalendarEvent,
    ) -> CalendarEvent:
        _require_date(occurrence_date, "occurrence date")
        events = list(self.events())
        source_index = next(
            (index for index, item in enumerate(events) if item.event_id == event_id),
            None,
        )
        if source_index is None:
            raise KeyError(event_id)
        source = events[source_index]
        events[source_index] = replace(
            source,
            excluded_dates=tuple(sorted((*source.excluded_dates, occurrence_date))),
        )
        override = replace(
            replacement,
            event_id=str(uuid4()),
            recurrence=RecurrenceRule(),
            parent_event_id=event_id,
        )
        # Commit the series exception and its replacement together. A crash can
        # therefore never leave an excluded occurrence without its override.
        self.replace_events((*events, override))
        return override

    def is_acknowledged(self, occurrence_id: str) -> bool:
        self.load()
        return occurrence_id in self._acknowledged

    def acknowledge(self, occurrence_id: str) -> None:
        self.load()
        if self._read_only_error:
            raise CalendarDataError(
                "calendar data is read-only until its malformed file is repaired"
            )
        if not isinstance(occurrence_id, str) or not occurrence_id.strip():
            raise CalendarDataError(
                "acknowledgement id must be a non-empty string"
            )
        occurrence_id = occurrence_id.strip()
        updated = set(self._acknowledged)
        updated.add(occurrence_id)
        _atomic_write_json(
            self.acknowledgements_path,
            {
                "version": ACKNOWLEDGEMENT_SCHEMA_VERSION,
                "acknowledged": sorted(updated),
            },
        )
        self._acknowledged = updated


def occurrence_dates(
    event: CalendarEvent,
    start: date,
    end: date,
) -> tuple[date, ...]:
    """Expand one event inclusively without iterating beyond the query range."""
    if not isinstance(event, CalendarEvent):
        raise CalendarDataError("event must be a CalendarEvent")
    _require_date(start, "range start")
    _require_date(end, "range end")
    if end < start:
        return ()
    rule = event.recurrence
    if rule.frequency == "none":
        candidates = (event.start_date,)
    elif rule.frequency == "weekly":
        weekdays = rule.weekdays or (event.start_date.weekday(),)
        candidates_list = []
        cursor = max(start, event.start_date)
        while cursor <= end:
            if cursor.weekday() in weekdays:
                candidates_list.append(cursor)
            cursor += timedelta(days=1)
        candidates = tuple(candidates_list)
    elif rule.frequency == "monthly":
        candidates_list = []
        cursor = date(max(start, event.start_date).year, max(start, event.start_date).month, 1)
        while cursor <= end:
            last_day = month_calendar.monthrange(cursor.year, cursor.month)[1]
            if event.start_date.day <= last_day:
                candidate = date(cursor.year, cursor.month, event.start_date.day)
            elif rule.monthly_overflow == "last_day":
                candidate = date(cursor.year, cursor.month, last_day)
            else:
                candidate = None
            if candidate is not None:
                candidates_list.append(candidate)
            cursor = _add_month(cursor)
        candidates = tuple(candidates_list)
    else:
        candidates_list = []
        for year in range(max(start.year, event.start_date.year), end.year + 1):
            try:
                candidate = date(year, event.start_date.month, event.start_date.day)
            except ValueError:
                if rule.monthly_overflow == "last_day":
                    candidate = date(
                        year,
                        event.start_date.month,
                        month_calendar.monthrange(year, event.start_date.month)[1],
                    )
                else:
                    continue
            candidates_list.append(candidate)
        candidates = tuple(candidates_list)

    bounded = []
    exclusions = set(event.excluded_dates)
    for candidate in candidates:
        if candidate < event.start_date or candidate < start or candidate > end:
            continue
        if rule.end_date is not None and candidate > rule.end_date:
            continue
        if candidate in exclusions:
            continue
        if rule.count is not None:
            ordinal = _occurrence_ordinal(event, candidate)
            if ordinal > rule.count:
                continue
        bounded.append(candidate)
    return tuple(bounded)


def _add_month(value: date) -> date:
    index = value.year * 12 + value.month
    year, month_zero = divmod(index, 12)
    return date(year, month_zero + 1, 1)


def _occurrence_ordinal(event: CalendarEvent, candidate: date) -> int:
    rule = event.recurrence
    if rule.frequency == "weekly":
        weekdays = rule.weekdays or (event.start_date.weekday(),)
        elapsed_days = (candidate - event.start_date).days
        full_weeks, remaining_days = divmod(elapsed_days, 7)
        count = full_weeks * len(weekdays)
        start_weekday = event.start_date.weekday()
        count += sum(
            (start_weekday + offset) % 7 in weekdays
            for offset in range(remaining_days + 1)
        )
        return count
    if rule.frequency == "monthly":
        month_count = (
            (candidate.year - event.start_date.year) * 12
            + candidate.month
            - event.start_date.month
            + 1
        )
        day = event.start_date.day
        if rule.monthly_overflow == "last_day" or day <= 28:
            return month_count
        if day == 29:
            first_year, last_year = _month_year_span(
                event.start_date,
                candidate,
                month_calendar.FEBRUARY,
            )
            february_count = max(0, last_year - first_year + 1)
            leap_count = _count_leap_years(first_year, last_year)
            return month_count - (february_count - leap_count)
        invalid_months = (
            (month_calendar.FEBRUARY,)
            if day == 30
            else (
                month_calendar.FEBRUARY,
                month_calendar.APRIL,
                month_calendar.JUNE,
                month_calendar.SEPTEMBER,
                month_calendar.NOVEMBER,
            )
        )
        return month_count - sum(
            _count_month_in_span(event.start_date, candidate, month)
            for month in invalid_months
        )
    if rule.frequency == "yearly":
        if (
            rule.monthly_overflow == "skip"
            and event.start_date.month == month_calendar.FEBRUARY
            and event.start_date.day == 29
        ):
            return _count_leap_years(event.start_date.year, candidate.year)
        return candidate.year - event.start_date.year + 1
    return 1


def _month_year_span(
    start: date,
    end: date,
    month: int,
) -> tuple[int, int]:
    return (
        start.year + (start.month > month),
        end.year - (end.month < month),
    )


def _count_month_in_span(start: date, end: date, month: int) -> int:
    first_year, last_year = _month_year_span(start, end, month)
    return max(0, last_year - first_year + 1)


def _count_leap_years(first_year: int, last_year: int) -> int:
    if last_year < first_year:
        return 0
    return month_calendar.leapdays(first_year, last_year + 1)


def expand_events(
    events: Iterable[CalendarEvent],
    start: date,
    end: date,
) -> tuple[CalendarOccurrence, ...]:
    values = [
        CalendarOccurrence(event, occurrence_date)
        for event in events
        for occurrence_date in occurrence_dates(event, start, end)
    ]
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.occurrence_date,
                not item.event.all_day,
                item.event.start_time or time.min,
                item.event.name.casefold(),
            ),
        )
    )


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (occurrence - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, month_calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def easter_sunday(year: int) -> date:
    """Return Gregorian Easter for the supplied year."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def built_in_us_holidays(year: int) -> tuple[CalendarEvent, ...]:
    """Return requested common US holidays as read-only yearly events."""
    easter = easter_sunday(year)
    values = (
        ("New Year's Day", date(year, 1, 1), "#2D8B82", "new_year"),
        ("Valentine's Day", date(year, 2, 14), "#D94F83", "valentines"),
        ("St. Patrick's Day", date(year, 3, 17), "#2D8B57", "st_patricks"),
        ("April Fool's Day", date(year, 4, 1), "#7A55A4", "april_fools"),
        ("Good Friday", easter - timedelta(days=2), "#6B71B8", "good_friday"),
        ("Easter", easter, "#C65C9D", "easter"),
        ("Cinco de Mayo", date(year, 5, 5), "#C94D37", "cinco_de_mayo"),
        ("Mother's Day", _nth_weekday(year, 5, month_calendar.SUNDAY, 2), "#D94F83", "mothers_day"),
        ("Memorial Day", _last_weekday(year, 5, month_calendar.MONDAY), "#12325B", "memorial_day"),
        ("Father's Day", _nth_weekday(year, 6, month_calendar.SUNDAY, 3), "#376FBA", "fathers_day"),
        ("Fourth of July", date(year, 7, 4), "#C83E49", "fourth_of_july"),
        ("Columbus Day", _nth_weekday(year, 10, month_calendar.MONDAY, 2), "#C66D2D", "columbus_day"),
        ("Halloween", date(year, 10, 31), "#C65B1C", "halloween"),
        ("Veterans Day", date(year, 11, 11), "#12325B", "veterans_day"),
        ("Thanksgiving", _nth_weekday(year, 11, month_calendar.THURSDAY, 4), "#C66D2D", "thanksgiving"),
        ("Christmas Eve", date(year, 12, 24), "#2D7B4C", "christmas_eve"),
        ("Christmas Day", date(year, 12, 25), "#BE3445", "christmas"),
        ("New Year's Eve", date(year, 12, 31), "#65459A", "new_years_eve"),
    )
    return tuple(
        CalendarEvent(
            event_id=f"holiday:{overlay}:{year}",
            name=name,
            start_date=holiday_date,
            all_day=True,
            color=color,
            category="Holiday",
            recurrence=RecurrenceRule(),
            read_only=True,
            overlay=overlay,
        )
        for name, holiday_date, color, overlay in values
    )
