"""Toolkit-neutral records exchanged with calendar presentations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time


CALENDAR_COLOR_PALETTE = (
    ("Ocean", "#1578D3"),
    ("Teal", "#16847D"),
    ("Leaf", "#3B8E63"),
    ("Sun", "#E0A800"),
    ("Orange", "#D96B27"),
    ("Coral", "#D9545D"),
    ("Berry", "#A83E7C"),
    ("Purple", "#7051B8"),
    ("Navy", "#29466F"),
    ("Slate", "#607D8B"),
    ("Brown", "#795548"),
    ("Black", "#303030"),
)

CALENDAR_MONTH_COLORS = (
    "#8F2942",
    "#704B9A",
    "#2E8588",
    "#517F9C",
    "#21754F",
    "#A85469",
    "#B52D43",
    "#668C25",
    "#315BA4",
    "#BE6425",
    "#9A741B",
    "#287A74",
)


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


__all__ = [
    "CALENDAR_COLOR_PALETTE",
    "CALENDAR_MONTH_COLORS",
    "CalendarEdit",
    "CalendarViewEvent",
]
