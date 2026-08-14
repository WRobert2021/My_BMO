"""Read-only voice calendar, editable touch view, and daily attentions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
import threading
from typing import Any, Literal

from bmo.features.calendar_config import CalendarConfig, load_calendar_config
from bmo.features.calendar_store import (
    CalendarEvent,
    CalendarOccurrence,
    CalendarStore,
    RecurrenceRule,
    built_in_us_holidays,
    expand_events,
)
from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    RuntimeAttention,
    RuntimeAttentionDismissal,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)
from bmo.ui.calendar import CalendarApp, CalendarEdit, CalendarViewEvent


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CALENDAR_MENU_ITEM = FeatureMenuItem(
    name="get_calendar",
    label="Calendar",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "calendar.png",
)
CALENDAR_TERMS = ("calendar", "schedule", "scheduled", "plan", "agenda")
READ_TERMS = (
    "what",
    "whats",
    "what's",
    "show",
    "tell",
    "anything",
    "do i have",
    "am i",
)
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
CalendarAppFactory = Callable[..., CalendarApp]


class CalendarMidnightWorker:
    """Refresh attentions at startup and whenever the system date changes."""

    def __init__(
        self,
        callback: Callable[[date], None],
        *,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.callback = callback
        self.now = now
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="bmo-calendar-midnight",
            daemon=True,
        )
        self._last_date: date | None = None

    @property
    def thread(self) -> threading.Thread:
        return self._thread

    def start(self) -> None:
        self._thread.start()

    def check(self) -> bool:
        current_date = self.now().date()
        if current_date == self._last_date:
            return False
        self.callback(current_date)
        self._last_date = current_date
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as exc:
                print(f"[CALENDAR] Could not refresh today's items: {exc}", flush=True)
            self._stop.wait(30.0)

    def close(self) -> None:
        self._stop.set()
        if self._thread.ident is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)


class CalendarTool:
    """Own calendar persistence, queries, menu UI, and daily notices."""

    action = "get_calendar"
    aliases = ("calendar", "schedule", "plan")
    description = "Read upcoming items from the local calendar. Calendar changes require the touch menu."
    schemas = (
        '{"action":"get_calendar","period":"today|tomorrow|this_week|next_week|this_weekend|this_month"}',
        '{"action":"get_calendar","date":"YYYY-MM-DD"}',
    )
    prompt_guidance = (
        "Use get_calendar only to read the calendar; never use it to add, edit, delete, move, or acknowledge an item.",
        "Calendar changes must be made through the touch menu.",
    )
    prompt_examples = (
        ("What's on my schedule tomorrow?", '{"action":"get_calendar","period":"tomorrow"}'),
        ("What is planned next week?", '{"action":"get_calendar","period":"next_week"}'),
    )

    def __init__(
        self,
        config: CalendarConfig,
        *,
        notify_attention: Callable[[RuntimeAttention], None],
        dismiss_attention: Callable[[RuntimeAttentionDismissal], None],
        now: Callable[[], datetime] = datetime.now,
        app_factory: CalendarAppFactory = CalendarApp,
        menu_item: FeatureMenuItem | None = CALENDAR_MENU_ITEM,
        start_worker: bool = True,
    ) -> None:
        self.config = config
        self.store = CalendarStore(config.data_directory)
        self._notify_attention = notify_attention
        self._dismiss_attention = dismiss_attention
        self._now = now
        self._app_factory = app_factory
        self.menu_item = menu_item
        self._menu_ui: CalendarApp | None = None
        self._published_ids: set[str] = set()
        self._worker = CalendarMidnightWorker(self._publish_attentions, now=now)
        if start_worker:
            self._worker.start()

    @property
    def worker(self) -> CalendarMidnightWorker:
        return self._worker

    def _all_events(self, start: date, end: date) -> tuple[CalendarEvent, ...]:
        events = list(self.store.events())
        if self.config.built_in_us_holidays:
            for year in range(start.year, end.year + 1):
                events.extend(built_in_us_holidays(year))
        return tuple(events)

    def occurrences(self, start: date, end: date) -> tuple[CalendarOccurrence, ...]:
        return expand_events(self._all_events(start, end), start, end)

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            start, end, label = self._request_range(request)
            return ToolResult.direct(self.summary(start, end, label=label))
        except ValueError:
            return ToolResult.direct(
                "I can check today, tomorrow, this weekend, this week, next week, this month, or a specific date."
            )

    def prepare_model_request(self, request: ToolRequest) -> dict[str, Any] | None:
        operation = str(request.get("operation") or "read").strip().lower()
        if operation not in {"", "read", "list", "show", "summary"}:
            return None
        prepared = dict(request)
        prepared["action"] = self.action
        if "date" in prepared:
            try:
                date.fromisoformat(str(prepared["date"]))
            except ValueError:
                return None
            return prepared
        period = str(prepared.get("period") or "today").strip().lower()
        if period not in {
            "today",
            "tomorrow",
            "this_week",
            "next_week",
            "this_weekend",
            "this_month",
        }:
            return None
        prepared["period"] = period
        return prepared

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        text = normalize_direct_text(user_text)
        if not any(term in text for term in CALENDAR_TERMS):
            return None
        # The read requirement keeps "schedule lunch tomorrow" out of this tool.
        if not any(term in text for term in READ_TERMS):
            return None
        period = self._period_from_text(text)
        if period is None:
            return None
        return {"action": self.action, **period}

    def _period_from_text(self, text: str) -> dict[str, str] | None:
        for phrase, period in (
            ("next week", "next_week"),
            ("this weekend", "this_weekend"),
            ("weekend", "this_weekend"),
            ("this week", "this_week"),
            ("this month", "this_month"),
            ("tomorrow", "tomorrow"),
            ("today", "today"),
        ):
            if phrase in text:
                return {"period": period}
        for name, weekday in WEEKDAYS.items():
            if re.search(rf"\b{name}\b", text):
                current = self._now().date()
                delta = (weekday - current.weekday()) % 7
                if "next " + name in text:
                    delta = delta + 7 if delta else 7
                return {"date": (current + timedelta(days=delta)).isoformat()}
        iso_date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
        if iso_date:
            return {"date": iso_date.group(0)}
        return {"period": "today"}

    def _request_range(self, request: ToolRequest) -> tuple[date, date, str]:
        if request.get("date"):
            selected = date.fromisoformat(str(request["date"]))
            return selected, selected, self._speakable_date(selected)
        current = self._now().date()
        period = str(request.get("period") or "today").strip().lower()
        if period == "today":
            return current, current, "today"
        if period == "tomorrow":
            tomorrow = current + timedelta(days=1)
            return tomorrow, tomorrow, "tomorrow"
        monday = current - timedelta(days=current.weekday())
        if period == "this_week":
            return monday, monday + timedelta(days=6), "this week"
        if period == "next_week":
            start = monday + timedelta(days=7)
            return start, start + timedelta(days=6), "next week"
        if period == "this_weekend":
            start = monday + timedelta(days=5)
            if start < current:
                start += timedelta(days=7)
            return start, start + timedelta(days=1), "this weekend"
        if period == "this_month":
            start = current.replace(day=1)
            if current.month == 12:
                next_month = date(current.year + 1, 1, 1)
            else:
                next_month = date(current.year, current.month + 1, 1)
            return start, next_month - timedelta(days=1), "this month"
        raise ValueError("unsupported calendar period")

    def summary(self, start: date, end: date, *, label: str | None = None) -> str:
        occurrences = self.occurrences(start, end)
        range_label = label or (
            self._speakable_date(start)
            if start == end
            else f"{start.strftime('%B %-d')} through {end.strftime('%B %-d')}"
        )
        if not occurrences:
            return f"Your schedule is clear for {range_label}."
        items = []
        for occurrence in occurrences[:8]:
            event = occurrence.event
            when = "all day" if event.all_day else self._speakable_time_range(
                event.start_time,
                event.end_time,
            )
            day = "" if start == end else occurrence.occurrence_date.strftime("%A") + ", "
            item = f"{day}{event.name} at {when}" if not event.all_day else f"{day}{event.name}, {when}"
            if self.config.speak_notes and event.notes:
                item += f". Note: {event.notes}"
            items.append(item)
        if len(items) == 1:
            detail = items[0]
        else:
            detail = "; ".join(items[:-1]) + f"; and {items[-1]}"
        extra = len(occurrences) - len(items)
        suffix = f" There are {extra} more items." if extra else ""
        prefix = (
            f"On {range_label}"
            if start == end and range_label not in {"today", "tomorrow"}
            else f"For {range_label}"
        )
        separator = " " if prefix.startswith("On ") else ", "
        return f"{prefix}{separator}you have {detail}.{suffix}"

    @staticmethod
    def _speakable_date(value: date) -> str:
        day = value.day
        if 10 < day % 100 < 14:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{value.strftime('%A %B')} {day}{suffix}"

    @staticmethod
    def _speakable_time(value: time | None) -> str:
        if value is None:
            return "an unspecified time"
        hour = value.strftime("%I").lstrip("0")
        suffix = value.strftime("%p").lower()
        if value.minute == 0:
            return f"{hour} o'clock {suffix}"
        return f"{hour}:{value.minute:02d} {suffix}"

    @classmethod
    def _speakable_time_range(
        cls,
        start: time | None,
        end: time | None,
    ) -> str:
        spoken = cls._speakable_time(start)
        if end is not None:
            spoken += f" to {cls._speakable_time(end)}"
        return spoken

    def _publish_attentions(self, selected_date: date) -> None:
        occurrences = self.occurrences(selected_date, selected_date)
        current = {
            occurrence.occurrence_id: occurrence
            for occurrence in occurrences
            if not self.store.is_acknowledged(occurrence.occurrence_id)
        }
        for attention_id in self._published_ids.difference(current):
            self._dismiss_attention(RuntimeAttentionDismissal(self.action, attention_id))
        for attention_id, occurrence in current.items():
            event = occurrence.event
            self._notify_attention(
                RuntimeAttention(
                    source=self.action,
                    attention_id=attention_id,
                    message=self._acknowledgement_message(occurrence),
                    acknowledge=lambda selected=occurrence: self._acknowledge(selected),
                    overlay_kind=event.overlay or event.category.casefold(),
                    overlay_path=self._overlay_path(event.overlay),
                )
            )
        self._published_ids = set(current)

    def _acknowledgement_message(self, occurrence: CalendarOccurrence) -> str:
        event = occurrence.event
        when = "all day" if event.all_day else self._speakable_time_range(
            event.start_time,
            event.end_time,
        )
        message = f"Today: {event.name}, {when}."
        if self.config.speak_notes and event.notes:
            message += f" Note: {event.notes}"
        return message

    def _acknowledge(self, occurrence: CalendarOccurrence) -> bool:
        self.store.acknowledge(occurrence.occurrence_id)
        self._dismiss_attention(
            RuntimeAttentionDismissal(self.action, occurrence.occurrence_id)
        )
        self._published_ids.discard(occurrence.occurrence_id)
        return True

    def _overlay_path(self, overlay: str | None) -> Path | None:
        if not overlay:
            return None
        direct = self.config.overlay_directory / f"{overlay}.png"
        if direct.is_file():
            return direct
        directory = self.config.overlay_directory / overlay
        if directory.is_dir():
            try:
                return next(path for path in sorted(directory.glob("*.png")) if path.is_file())
            except StopIteration:
                return None
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        if self._menu_ui is not None:
            return

        def handle_close() -> None:
            context.cancel_announcements()
            self._menu_ui = None
            context.on_close()

        try:
            self._menu_ui = self._app_factory(
                context.master,
                event_provider=self._view_events,
                save_event=self._save_from_menu,
                delete_event=self._delete_from_menu,
                summary_provider=lambda start, end: self.summary(start, end),
                categories=self.config.categories,
                face_provider=context.current_face,
                announce=lambda text, done: context.announce(text, done),
                on_close=handle_close,
                today_provider=lambda: self._now().date(),
            )
        except Exception:
            self._menu_ui = None
            context.on_close()
            raise

    def _view_events(self, start: date, end: date) -> tuple[CalendarViewEvent, ...]:
        return tuple(self._to_view(occurrence) for occurrence in self.occurrences(start, end))

    @staticmethod
    def _to_view(occurrence: CalendarOccurrence) -> CalendarViewEvent:
        event = occurrence.event
        rule = event.recurrence
        return CalendarViewEvent(
            event_id=event.event_id,
            occurrence_id=occurrence.occurrence_id,
            name=event.name,
            occurrence_date=occurrence.occurrence_date,
            all_day=event.all_day,
            start_time=event.start_time,
            end_time=event.end_time,
            color=event.color,
            category=event.category,
            notes=event.notes,
            frequency=rule.frequency,
            weekdays=rule.weekdays,
            recurrence_end_date=rule.end_date,
            recurrence_count=rule.count,
            monthly_overflow=rule.monthly_overflow,
            read_only=event.read_only,
        )

    @staticmethod
    def _event_from_edit(edit: CalendarEdit, *, event_id: str) -> CalendarEvent:
        return CalendarEvent(
            event_id=event_id,
            name=edit.name,
            start_date=edit.start_date,
            all_day=edit.all_day,
            start_time=edit.start_time,
            end_time=edit.end_time,
            color=edit.color,
            category=edit.category,
            notes=edit.notes,
            recurrence=RecurrenceRule(
                frequency=edit.frequency,
                weekdays=edit.weekdays,
                end_date=edit.recurrence_end_date,
                count=edit.recurrence_count,
                monthly_overflow=edit.monthly_overflow,
            ),
        )

    def _save_from_menu(
        self,
        edit: CalendarEdit,
        selected: CalendarViewEvent | None,
        scope: Literal["occurrence", "series"],
    ) -> None:
        if selected is None:
            self.store.create(
                name=edit.name,
                start_date=edit.start_date,
                all_day=edit.all_day,
                start_time=edit.start_time,
                end_time=edit.end_time,
                color=edit.color,
                category=edit.category,
                notes=edit.notes,
                recurrence=RecurrenceRule(
                    frequency=edit.frequency,
                    weekdays=edit.weekdays,
                    end_date=edit.recurrence_end_date,
                    count=edit.recurrence_count,
                    monthly_overflow=edit.monthly_overflow,
                ),
            )
        else:
            if selected.read_only:
                raise ValueError("Built-in holidays are read-only.")
            replacement = self._event_from_edit(edit, event_id=selected.event_id)
            if scope == "occurrence" and selected.frequency != "none":
                self.store.override_occurrence(
                    selected.event_id,
                    selected.occurrence_date,
                    replacement,
                )
            else:
                existing = next(
                    event for event in self.store.events() if event.event_id == selected.event_id
                )
                self.store.update_series(
                    replace(
                        replacement,
                        excluded_dates=existing.excluded_dates,
                        parent_event_id=existing.parent_event_id,
                    )
                )
        self._publish_attentions(self._now().date())

    def _delete_from_menu(
        self,
        selected: CalendarViewEvent,
        scope: Literal["occurrence", "series"],
    ) -> None:
        if selected.read_only:
            raise ValueError("Built-in holidays are read-only.")
        if scope == "occurrence" and selected.frequency != "none":
            self.store.exclude_occurrence(selected.event_id, selected.occurrence_date)
        else:
            self.store.delete_series(selected.event_id)
        self._publish_attentions(self._now().date())

    def close(self) -> None:
        if self._menu_ui is not None:
            self._menu_ui.close()
        self._worker.close()
        for attention_id in tuple(self._published_ids):
            self._dismiss_attention(RuntimeAttentionDismissal(self.action, attention_id))
        self._published_ids.clear()


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register the independently configured local calendar feature."""
    config = load_calendar_config(settings)
    registry.register(
        CalendarTool(
            config,
            notify_attention=registry.notify_attention,
            dismiss_attention=registry.dismiss_attention,
            menu_item=CALENDAR_MENU_ITEM if config.show_in_menu else None,
        )
    )


def register_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register Calendar routing metadata without starting its date worker."""
    config = load_calendar_config(settings)
    registry.register(
        CalendarTool(
            config,
            notify_attention=registry.notify_attention,
            dismiss_attention=registry.dismiss_attention,
            menu_item=CALENDAR_MENU_ITEM if config.show_in_menu else None,
            start_worker=False,
        )
    )
