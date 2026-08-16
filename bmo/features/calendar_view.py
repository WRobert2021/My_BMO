"""Toolkit-neutral records exchanged with calendar presentations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True)
class CalendarViewEvent:
    """Presentation-ready snapshot of one concrete calendar occurrence."""

    event_id: str
    occurrence_id: str
    name: str
    occurrence_date: date
    all_day: bool
    start_time: time | None
    end_time: time | None
    color: str
    category: str
    notes: str = ""
    frequency: str = "none"
    weekdays: tuple[int, ...] = ()
    recurrence_end_date: date | None = None
    recurrence_count: int | None = None
    monthly_overflow: str = "last_day"
    read_only: bool = False


@dataclass(frozen=True)
class CalendarEdit:
    """Validated editor fields sent back to the calendar feature."""

    name: str
    start_date: date
    all_day: bool
    start_time: time | None
    end_time: time | None
    color: str
    category: str
    notes: str
    frequency: str
    weekdays: tuple[int, ...]
    recurrence_end_date: date | None
    recurrence_count: int | None
    monthly_overflow: str


__all__ = ["CalendarEdit", "CalendarViewEvent"]
