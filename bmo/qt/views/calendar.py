"""QML adapter for the local calendar feature."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date, time, timedelta
import json
import re
from typing import Any, Literal

from bmo.features.calendar_view import (
    CALENDAR_COLOR_PALETTE,
    CALENDAR_MONTH_COLORS,
    CalendarEdit,
)
from bmo.qt.views.base import QtHostedView


_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_WEEKDAY_LABELS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_MONTH_DOT_CAPACITY = 10


class QtCalendarView(QtHostedView):
    """Translate calendar-owned records and callbacks into a QML view model."""

    kind = "calendar"
    title = "Calendar"

    def __init__(
        self,
        host: Any,
        *,
        event_provider: Any,
        save_event: Any,
        delete_event: Any,
        summary_provider: Any,
        categories: Any,
        announce: Any,
        on_close: Any,
        today_provider: Any = date.today,
        face_provider: Any = None,
    ) -> None:
        del face_provider
        self.event_provider = event_provider
        self.save_event = save_event
        self.delete_event = delete_event
        self.summary_provider = summary_provider
        self.categories = tuple(categories)
        self.announce = announce
        self.today_provider = today_provider
        self.selected_date = today_provider()
        self.visible_month = self.selected_date.replace(day=1)
        self.visible_year = self.selected_date.year
        self.selected_event: Any | None = None
        self.mode = "day"
        self.error = ""
        self._scope_kind: Literal["save", "delete"] | None = None
        self._pending_edit: CalendarEdit | None = None
        super().__init__(host, on_close=on_close)

    def _events(self, start: date, end: date) -> tuple[Any, ...]:
        return tuple(self.event_provider(start, end))

    def _day_events(self) -> tuple[Any, ...]:
        return self._events(self.selected_date, self.selected_date)

    @staticmethod
    def _time_label(event: Any) -> str:
        if event.all_day:
            return "All day"
        if event.start_time is None:
            return "Time not set"
        start = event.start_time.strftime("%I:%M %p").lstrip("0")
        if event.end_time is None:
            return start
        end = event.end_time.strftime("%I:%M %p").lstrip("0")
        return f"{start} – {end}"

    @staticmethod
    def _date_label(value: date) -> str:
        return f"{value.strftime('%A, %B')} {value.day}, {value.year}"

    @staticmethod
    def _month_start(value: date, amount: int) -> date:
        index = value.year * 12 + value.month - 1 + amount
        year, month_zero = divmod(index, 12)
        return date(year, month_zero + 1, 1)

    def _navigation_label(self) -> str:
        if self.mode == "month":
            return self.visible_month.strftime("%B %Y")
        if self.mode == "year":
            return str(self.visible_year)
        return (
            f"{self.selected_date.strftime('%a, %b')} "
            f"{self.selected_date.day}, {self.selected_date.year}"
        )

    def _accent_color(self) -> str:
        month = (
            self.visible_month.month
            if self.mode == "month"
            else self.selected_date.month
        )
        return CALENDAR_MONTH_COLORS[month - 1]

    def _serialize_event(self, event: Any) -> dict[str, object]:
        return {
            "id": event.occurrence_id,
            "name": event.name,
            "time": self._time_label(event),
            "color": event.color,
            "category": event.category,
            "notes": event.notes,
            "readOnly": event.read_only,
            "frequency": event.frequency,
            "recurring": event.frequency != "none",
        }

    def _month_payload(self) -> list[dict[str, object]]:
        weeks = calendar.Calendar(firstweekday=calendar.MONDAY).monthdatescalendar(
            self.visible_month.year,
            self.visible_month.month,
        )
        while len(weeks) < 6:
            last = weeks[-1][-1]
            weeks.append([last + timedelta(days=index) for index in range(1, 8)])
        days = tuple(day for week in weeks[:6] for day in week)
        event_map: dict[date, list[Any]] = {}
        for event in self._events(days[0], days[-1]):
            event_map.setdefault(event.occurrence_date, []).append(event)
        today = self.today_provider()
        payload = []
        for day in days:
            events = event_map.get(day, [])
            if len(events) <= _MONTH_DOT_CAPACITY:
                visible = events
                overflow = 0
            else:
                visible = events[: _MONTH_DOT_CAPACITY - 1]
                overflow = len(events) - len(visible)
            payload.append(
                {
                    "date": day.isoformat(),
                    "day": day.day,
                    "inMonth": day.month == self.visible_month.month,
                    "today": day == today,
                    "selected": day == self.selected_date,
                    "dots": [event.color for event in visible],
                    "overflow": overflow,
                }
            )
        return payload

    def _year_payload(self) -> list[dict[str, object]]:
        occurrences = self._events(
            date(self.visible_year, 1, 1),
            date(self.visible_year, 12, 31),
        )
        counts = {
            month: sum(
                occurrence.occurrence_date.month == month
                for occurrence in occurrences
            )
            for month in range(1, 13)
        }
        today = self.today_provider()
        return [
            {
                "month": month,
                "label": calendar.month_abbr[month].upper(),
                "eventCount": counts[month],
                "color": CALENDAR_MONTH_COLORS[month - 1],
                "current": today.year == self.visible_year and today.month == month,
            }
            for month in range(1, 13)
        ]

    def payload(self) -> dict[str, object]:
        events = self._day_events()
        selected_id = getattr(self.selected_event, "occurrence_id", "")
        self.selected_event = next(
            (event for event in events if event.occurrence_id == selected_id),
            None,
        )
        return {
            "mode": self.mode,
            "date": self.selected_date.isoformat(),
            "dateLabel": self._date_label(self.selected_date),
            "monthLabel": self.selected_date.strftime("%B").upper(),
            "navigationLabel": self._navigation_label(),
            "accentColor": self._accent_color(),
            "events": [self._serialize_event(event) for event in events],
            "monthDays": self._month_payload() if self.mode == "month" else [],
            "yearMonths": self._year_payload() if self.mode == "year" else [],
            "weekdayLabels": list(_WEEKDAY_LABELS),
            "selectedId": getattr(self.selected_event, "occurrence_id", ""),
            "selectedReadOnly": bool(
                self.selected_event is not None and self.selected_event.read_only
            ),
            "selectedRecurring": bool(
                self.selected_event is not None
                and self.selected_event.frequency != "none"
            ),
            "categories": list(self.categories),
            "colorPalette": [
                {"name": name, "color": color}
                for name, color in CALENDAR_COLOR_PALETTE
            ],
            "error": self.error,
            "editor": self._editor_payload(),
            "scopeKind": self._scope_kind or "",
            "scopePrompt": self._scope_prompt(),
        }

    def handle_action(self, action: str, value: str) -> None:
        self.error = ""
        try:
            if action == "calendar_previous":
                self._move(-1)
            elif action == "calendar_next":
                self._move(1)
            elif action == "calendar_today":
                self._set_selected_date(self.today_provider())
                self.mode = "day"
            elif action == "calendar_show_day":
                self.mode = "day"
            elif action == "calendar_show_month":
                self.visible_month = self.selected_date.replace(day=1)
                self.mode = "month"
            elif action == "calendar_show_year":
                self.visible_year = self.selected_date.year
                self.mode = "year"
            elif action == "calendar_open_date":
                self._set_selected_date(date.fromisoformat(value))
                self.mode = "day"
            elif action == "calendar_open_month":
                month = int(value)
                if not 1 <= month <= 12:
                    raise ValueError("Calendar month must be from 1 to 12.")
                self.visible_month = date(self.visible_year, month, 1)
                self.selected_date = self.visible_month
                self.selected_event = None
                self.mode = "month"
            elif action == "calendar_select":
                self.selected_event = next(
                    (event for event in self._day_events() if event.occurrence_id == value),
                    None,
                )
            elif action == "calendar_add":
                self.selected_event = None
                self.mode = "editor"
            elif action == "calendar_edit" and self.selected_event is not None:
                if self.selected_event.read_only:
                    self.error = "Built-in holidays are read-only."
                else:
                    self.mode = "editor"
            elif action == "calendar_cancel_edit":
                self._clear_scope()
                self.mode = "day"
            elif action in {"calendar_request_save", "calendar_save"}:
                self._request_save(value)
            elif action == "calendar_request_delete":
                self._request_delete()
            elif action == "calendar_delete" and self.selected_event is not None:
                self._delete_with_scope(
                    "occurrence" if value == "occurrence" else "series"
                )
            elif action == "calendar_scope":
                self._complete_scope(
                    "occurrence" if value == "occurrence" else "series"
                )
            elif action == "calendar_scope_cancel":
                return_mode = "editor" if self._scope_kind == "save" else "day"
                self._clear_scope()
                self.mode = return_mode
            elif action == "calendar_announce":
                summary = self.summary_provider(self.selected_date, self.selected_date)
                self.announce(summary, None)
            else:
                super().handle_action(action, value)
                return
        except (OSError, TypeError, ValueError) as exc:
            self.error = str(exc) or "BMO could not update the calendar."
        self.refresh()

    def _move(self, amount: int) -> None:
        self.selected_event = None
        if self.mode == "month":
            self.visible_month = self._month_start(self.visible_month, amount)
            self.visible_year = self.visible_month.year
            self.selected_date = self.visible_month
        elif self.mode == "year":
            self.visible_year += amount
            self.selected_date = date(self.visible_year, 1, 1)
            self.visible_month = self.selected_date
        else:
            self._set_selected_date(self.selected_date + timedelta(days=amount))

    def _set_selected_date(self, value: date) -> None:
        self.selected_date = value
        self.visible_month = value.replace(day=1)
        self.visible_year = value.year
        self.selected_event = None

    def _editor_payload(self) -> dict[str, object]:
        event = self.selected_event
        end_kind = "never"
        end_value = ""
        if event is not None and event.recurrence_end_date is not None:
            end_kind = "date"
            end_value = event.recurrence_end_date.isoformat()
        elif event is not None and event.recurrence_count is not None:
            end_kind = "count"
            end_value = str(event.recurrence_count)
        return {
            "name": getattr(event, "name", ""),
            "date": getattr(event, "occurrence_date", self.selected_date).isoformat(),
            "allDay": bool(getattr(event, "all_day", True)),
            "startTime": (
                event.start_time.strftime("%H:%M")
                if event is not None and event.start_time is not None
                else "09:00"
            ),
            "endTime": (
                event.end_time.strftime("%H:%M")
                if event is not None and event.end_time is not None
                else "10:00"
            ),
            "color": getattr(event, "color", CALENDAR_COLOR_PALETTE[0][1]),
            "category": getattr(
                event,
                "category",
                self.categories[0] if self.categories else "general",
            ),
            "notes": getattr(event, "notes", ""),
            "frequency": getattr(event, "frequency", "none"),
            "weekdays": list(getattr(event, "weekdays", ())),
            "repeatEndKind": end_kind,
            "repeatEndValue": end_value,
            "monthlyOverflow": getattr(event, "monthly_overflow", "last_day"),
            "recurring": bool(event is not None and event.frequency != "none"),
            "editing": event is not None,
        }

    @staticmethod
    def _optional_time(value: object, *, all_day: bool) -> time | None:
        if all_day:
            return None
        return time.fromisoformat(str(value).strip())

    @staticmethod
    def _weekday_values(value: object) -> tuple[int, ...]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
            raise ValueError("Choose at least one weekday for a weekly event.")
        weekdays = tuple(sorted({int(day) for day in value}))
        if any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("Weekdays must be between Monday and Sunday.")
        return weekdays

    def _parse_editor(self, value: str) -> CalendarEdit:
        values = json.loads(value)
        if not isinstance(values, dict):
            raise ValueError("Calendar editor data must be an object.")
        name = str(values.get("name", "")).strip()
        if not name:
            raise ValueError("Enter an event name.")
        category = str(values.get("category", "")).strip()
        if category not in self.categories:
            category = self.categories[0] if self.categories else "general"
        all_day_value = values.get("allDay", True)
        if not isinstance(all_day_value, bool):
            raise ValueError("All day must be turned on or off.")
        start_date = date.fromisoformat(str(values.get("date", self.selected_date)))
        frequency = str(values.get("frequency", "none")).strip().lower()
        if frequency not in {"none", "weekly", "monthly", "yearly"}:
            raise ValueError("Choose a supported repeat option.")
        weekdays = (
            self._weekday_values(values.get("weekdays", ()))
            if frequency == "weekly"
            else ()
        )
        if frequency == "weekly" and not weekdays:
            weekdays = (start_date.weekday(),)
        end_kind = str(values.get("repeatEndKind", "never")).strip().lower()
        end_value = str(values.get("repeatEndValue", "")).strip()
        recurrence_end_date = None
        recurrence_count = None
        if frequency != "none" and end_kind == "date":
            recurrence_end_date = date.fromisoformat(end_value)
            if recurrence_end_date < start_date:
                raise ValueError("The repeat end date cannot precede the event.")
        elif frequency != "none" and end_kind == "count":
            recurrence_count = int(end_value)
            if recurrence_count < 1:
                raise ValueError("The repeat count must be positive.")
        elif end_kind != "never":
            raise ValueError("Choose when the repeat should end.")
        overflow = str(values.get("monthlyOverflow", "last_day")).strip().lower()
        if overflow not in {"last_day", "skip"}:
            raise ValueError("Choose how short months should behave.")
        color = str(values.get("color", CALENDAR_COLOR_PALETTE[0][1])).upper()
        if _COLOR_PATTERN.fullmatch(color) is None:
            raise ValueError("Choose an event color.")
        return CalendarEdit(
            name=name,
            start_date=start_date,
            all_day=all_day_value,
            start_time=self._optional_time(
                values.get("startTime", "09:00"),
                all_day=all_day_value,
            ),
            end_time=self._optional_time(
                values.get("endTime", "10:00"),
                all_day=all_day_value,
            ),
            color=color,
            category=category,
            notes=str(values.get("notes", "")).strip(),
            frequency=frequency,
            weekdays=weekdays,
            recurrence_end_date=recurrence_end_date,
            recurrence_count=recurrence_count,
            monthly_overflow=overflow,
        )

    def _request_save(self, value: str) -> None:
        try:
            edit = self._parse_editor(value)
            values = json.loads(value)
            explicit_scope = values.get("scope") if isinstance(values, dict) else None
            if explicit_scope in {"occurrence", "series"}:
                self._save_with_scope(edit, explicit_scope)
            elif self.selected_event is not None and self.selected_event.frequency != "none":
                self._pending_edit = edit
                self._scope_kind = "save"
                self.mode = "scope"
            else:
                self._save_with_scope(edit, "series")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.error = str(exc) or "BMO could not save that event."

    def _request_delete(self) -> None:
        event = self.selected_event
        if event is None:
            self.error = "Choose an event first."
        elif event.read_only:
            self.error = "Built-in holidays are read-only."
        elif event.frequency != "none":
            self._scope_kind = "delete"
            self._pending_edit = None
            self.mode = "scope"
        else:
            self._delete_with_scope("series")

    def _scope_prompt(self) -> str:
        event_name = getattr(self.selected_event, "name", "this event")
        if self._scope_kind == "save":
            return f"Should BMO change only this {event_name} or the whole series?"
        if self._scope_kind == "delete":
            return f"Should BMO delete only this {event_name} or the whole series?"
        return ""

    def _complete_scope(self, scope: Literal["occurrence", "series"]) -> None:
        scope_kind = self._scope_kind
        pending_edit = self._pending_edit
        self._clear_scope()
        if scope_kind == "save" and pending_edit is not None:
            self.mode = "editor"
            self._save_with_scope(pending_edit, scope)
        elif scope_kind == "delete":
            self.mode = "day"
            self._delete_with_scope(scope)
        else:
            self.error = "That calendar choice expired. Please try again."
            self.mode = "day"

    def _save_with_scope(
        self,
        edit: CalendarEdit,
        scope: Literal["occurrence", "series"],
    ) -> None:
        self.save_event(edit, self.selected_event, scope)
        self._set_selected_date(edit.start_date)
        self.mode = "day"

    def _delete_with_scope(self, scope: Literal["occurrence", "series"]) -> None:
        event = self.selected_event
        if event is None:
            self.error = "Choose an event first."
            return
        if event.read_only:
            self.error = "Built-in holidays are read-only."
            return
        try:
            self.delete_event(event, scope)
            self.selected_event = None
            self.mode = "day"
        except (OSError, ValueError) as exc:
            self.error = str(exc) or "BMO could not delete that event."

    def _clear_scope(self) -> None:
        self._scope_kind = None
        self._pending_edit = None


__all__ = ["QtCalendarView"]
