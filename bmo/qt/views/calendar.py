"""QML adapter for the local calendar feature."""

from __future__ import annotations

import json
from datetime import date, time, timedelta
from typing import Any

from bmo.features.calendar_view import CalendarEdit
from bmo.qt.views.base import QtHostedView


class QtCalendarView(QtHostedView):
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
        self.selected_event: Any | None = None
        self.mode = "day"
        self.error = ""
        super().__init__(host, on_close=on_close)

    def _events(self) -> tuple[Any, ...]:
        return tuple(self.event_provider(self.selected_date, self.selected_date))

    @staticmethod
    def _time_label(event: Any) -> str:
        if event.all_day:
            return "All day"
        if event.start_time is None:
            return ""
        return event.start_time.strftime("%-I:%M %p")

    def payload(self) -> dict[str, object]:
        events = self._events()
        if self.selected_event not in events:
            selected_id = getattr(self.selected_event, "occurrence_id", "")
            self.selected_event = next(
                (event for event in events if event.occurrence_id == selected_id),
                None,
            )
        return {
            "mode": self.mode,
            "date": self.selected_date.isoformat(),
            "dateLabel": self.selected_date.strftime("%A, %B %-d, %Y"),
            "events": [
                {
                    "id": event.occurrence_id,
                    "name": event.name,
                    "time": self._time_label(event),
                    "color": event.color,
                    "category": event.category,
                    "notes": event.notes,
                    "readOnly": event.read_only,
                    "frequency": event.frequency,
                }
                for event in events
            ],
            "selectedId": getattr(self.selected_event, "occurrence_id", ""),
            "selectedReadOnly": bool(
                self.selected_event is not None and self.selected_event.read_only
            ),
            "categories": list(self.categories),
            "error": self.error,
            "editor": self._editor_payload(),
        }

    def handle_action(self, action: str, value: str) -> None:
        self.error = ""
        if action == "calendar_previous":
            self.selected_date -= timedelta(days=1)
            self.selected_event = None
        elif action == "calendar_next":
            self.selected_date += timedelta(days=1)
            self.selected_event = None
        elif action == "calendar_today":
            self.selected_date = self.today_provider()
            self.selected_event = None
        elif action == "calendar_select":
            self.selected_event = next(
                (event for event in self._events() if event.occurrence_id == value),
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
            self.mode = "day"
        elif action == "calendar_save":
            self._save_editor(value)
        elif action == "calendar_delete" and self.selected_event is not None:
            if self.selected_event.read_only:
                self.error = "Built-in holidays are read-only."
            else:
                try:
                    scope = "occurrence" if value == "occurrence" else "series"
                    self.delete_event(self.selected_event, scope)
                    self.selected_event = None
                except (OSError, ValueError) as exc:
                    self.error = str(exc) or "BMO could not delete that event."
        elif action == "calendar_announce":
            summary = self.summary_provider(self.selected_date, self.selected_date)
            self.announce(summary, None)
        else:
            super().handle_action(action, value)
            return
        self.refresh()

    def _editor_payload(self) -> dict[str, object]:
        event = self.selected_event
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
            "color": getattr(event, "color", "#1578d3"),
            "category": getattr(
                event,
                "category",
                self.categories[0] if self.categories else "general",
            ),
            "notes": getattr(event, "notes", ""),
            "frequency": getattr(event, "frequency", "none"),
            "recurring": bool(event is not None and event.frequency != "none"),
        }

    @staticmethod
    def _optional_time(value: object, *, all_day: bool) -> time | None:
        if all_day:
            return None
        return time.fromisoformat(str(value).strip())

    def _save_editor(self, value: str) -> None:
        try:
            values = json.loads(value)
            name = str(values.get("name", "")).strip()
            if not name:
                raise ValueError("Enter an event name.")
            category = str(values.get("category", "")).strip()
            if category not in self.categories:
                category = self.categories[0] if self.categories else "general"
            all_day = bool(values.get("allDay", True))
            start_date = date.fromisoformat(str(values.get("date", self.selected_date)))
            frequency = str(values.get("frequency", "none")).strip().lower()
            if frequency not in {"none", "daily", "weekly", "monthly", "yearly"}:
                raise ValueError("Choose a supported repeat option.")
            edit = CalendarEdit(
                name=name,
                start_date=start_date,
                all_day=all_day,
                start_time=self._optional_time(values.get("startTime", "09:00"), all_day=all_day),
                end_time=self._optional_time(values.get("endTime", "10:00"), all_day=all_day),
                color=str(values.get("color", "#1578d3")),
                category=category,
                notes=str(values.get("notes", "")).strip(),
                frequency=frequency,
                weekdays=(start_date.weekday(),) if frequency == "weekly" else (),
                recurrence_end_date=None,
                recurrence_count=None,
                monthly_overflow="last_day",
            )
            scope = "occurrence" if values.get("scope") == "occurrence" else "series"
            self.save_event(edit, self.selected_event, scope)
            self.selected_date = start_date
            self.selected_event = None
            self.mode = "day"
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.error = str(exc) or "BMO could not save that event."


__all__ = ["QtCalendarView"]
