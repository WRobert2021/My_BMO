"""Persistent digital alarm clock with voice and touch controls."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime, time as clock_time, timedelta
import json
from pathlib import Path
import re
import threading
from typing import Any

from bmo.features.alarm_config import AlarmClockConfig, load_alarm_clock_config
from bmo.features.alarm_store import (
    AlarmPersistenceError,
    AlarmRecord,
    AlarmState,
    AlarmStore,
)
from bmo.features.alarm_view import AlarmViewItem
from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    RuntimeAttention,
    RuntimeAttentionDismissal,
    RuntimeNotification,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)
from bmo.view_factory import NOT_HOSTED, create_hosted_view


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALARM_MENU_ITEM = FeatureMenuItem(
    name="alarm_clock",
    label="Alarm Clock",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "alarm.png",
)
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
LATE_RING_GRACE = timedelta(minutes=5)
WEEKDAY_LOOKUP = {
    **{name.casefold(): index for index, name in enumerate(WEEKDAY_NAMES)},
    **{name[:3].casefold(): index for index, name in enumerate(WEEKDAY_NAMES)},
}
AlarmAppFactory = Callable[..., Any]


def _create_alarm_app(*args: Any, **kwargs: Any) -> Any:
    hosted = create_hosted_view("alarm_clock", args, kwargs)
    if hosted is not NOT_HOSTED:
        return hosted
    from bmo.ui.alarm_clock import AlarmClockApp

    return AlarmClockApp(*args, **kwargs)


def _next_one_time_date(now: datetime, hour: int, minute: int) -> date:
    selected = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now.date() if selected > now else now.date() + timedelta(days=1)


def _parse_time_text(value: object) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError("alarm time must be text")
    text = value.strip().lower().replace(".", "")
    match = re.fullmatch(r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?", text)
    if match is None:
        raise ValueError("alarm time is invalid")
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    meridiem = match.group("meridiem")
    if not 0 <= minute <= 59:
        raise ValueError("alarm minute is invalid")
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError("12-hour alarm time is invalid")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif not 0 <= hour <= 23:
        raise ValueError("24-hour alarm time is invalid")
    return hour, minute


def parse_alarm_time(request: Mapping[str, Any]) -> tuple[int, int]:
    """Parse either an explicit 24-hour pair or a friendly time string."""
    if request.get("time") not in (None, ""):
        return _parse_time_text(request["time"])
    hour = request.get("hour")
    minute = request.get("minute", 0)
    if isinstance(hour, bool) or not isinstance(hour, int):
        raise ValueError("alarm hour is missing")
    if isinstance(minute, bool) or not isinstance(minute, int):
        raise ValueError("alarm minute is invalid")
    meridiem = str(request.get("meridiem") or "").strip().lower().replace(".", "")
    if meridiem:
        return _parse_time_text(f"{hour}:{minute:02d} {meridiem}")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("alarm time is invalid")
    return hour, minute


def parse_weekdays(value: object) -> tuple[int, ...]:
    """Normalize weekday names/numbers plus common daily shortcuts."""
    if value in (None, "", (), []):
        return ()
    if isinstance(value, str):
        normalized = value.casefold().replace("every", " ").strip()
        if normalized in {"day", "daily", "everyday", "all days"}:
            return tuple(range(7))
        if normalized in {"weekday", "weekdays"}:
            return tuple(range(5))
        if normalized in {"weekend", "weekends"}:
            return (5, 6)
        parts: Iterable[object] = re.split(r"[,/&]|\band\b", normalized)
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        raise ValueError("alarm weekdays are invalid")
    days: set[int] = set()
    for raw in parts:
        if isinstance(raw, bool):
            raise ValueError("alarm weekday is invalid")
        if isinstance(raw, int):
            day = raw
        else:
            name = str(raw).strip().casefold()
            if not name:
                continue
            try:
                day = WEEKDAY_LOOKUP[name]
            except KeyError as exc:
                raise ValueError(f"unknown weekday {name}") from exc
        if not 0 <= day <= 6:
            raise ValueError("alarm weekday is invalid")
        days.add(day)
    return tuple(sorted(days))


def format_alarm_time(hour: int, minute: int, use_24_hour: bool) -> str:
    if use_24_hour:
        return f"{hour:02d}:{minute:02d}"
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def format_repeat(weekdays: tuple[int, ...], one_time_date: date | None = None) -> str:
    if weekdays == tuple(range(7)):
        return "Every day"
    if weekdays == tuple(range(5)):
        return "Weekdays"
    if weekdays == (5, 6):
        return "Weekends"
    if weekdays:
        return ", ".join(WEEKDAY_NAMES[day][:3] for day in weekdays)
    if one_time_date is not None:
        return one_time_date.strftime("%a, %b %-d")
    return "One time"


class AlarmClockWorker:
    """One cooperative worker that checks local wall-clock alarms."""

    def __init__(
        self,
        callback: Callable[[datetime], None],
        *,
        now: Callable[[], datetime] = datetime.now,
        interval_seconds: float = 0.5,
    ) -> None:
        self.callback = callback
        self.now = now
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="bmo-alarm-clock",
            daemon=True,
        )

    @property
    def thread(self) -> threading.Thread:
        return self._thread

    def start(self) -> None:
        self._thread.start()

    def check(self) -> None:
        self.callback(self.now())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as exc:
                print(f"[ALARM] Clock check failed: {exc}", flush=True)
            self._stop.wait(self.interval_seconds)

    def close(self) -> None:
        self._stop.set()
        if self._thread.ident is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)


class AlarmClockTool:
    """Own persistent alarms, scheduling, voice operations, and the clock UI."""

    action = "alarm_clock"
    aliases = ("alarm",)
    description = "Set, list, enable, disable, delete, snooze, or dismiss local alarm-clock alarms."
    schemas = (
        '{"action":"alarm_clock","operation":"set","time":"7:30 am","label":"School","weekdays":"weekdays"}',
        '{"action":"alarm_clock","operation":"list"}',
        '{"action":"alarm_clock","operation":"delete|enable|disable","alarm_id":1}',
        '{"action":"alarm_clock","operation":"snooze|dismiss","alarm_id":1}',
    )
    prompt_guidance = (
        "Use alarm_clock for alarms tied to a time of day; use set_timer only for countdown durations.",
        "Preserve AM/PM, labels, and weekday repeats when the user supplies them.",
    )
    prompt_examples = (
        (
            "Set a school alarm for 7:15 AM every weekday.",
            '{"action":"alarm_clock","operation":"set","time":"7:15 am","label":"School","weekdays":"weekdays"}',
        ),
        ("List my alarms.", '{"action":"alarm_clock","operation":"list"}'),
    )

    def __init__(
        self,
        config: AlarmClockConfig,
        runtime_callback: Callable[[RuntimeNotification], None],
        *,
        notify_attention: Callable[[RuntimeAttention], None],
        dismiss_attention: Callable[[RuntimeAttentionDismissal], None],
        now: Callable[[], datetime] = datetime.now,
        app_factory: AlarmAppFactory = _create_alarm_app,
        menu_item: FeatureMenuItem | None = ALARM_MENU_ITEM,
        start_worker: bool = True,
        store: AlarmStore | None = None,
    ) -> None:
        self.config = config
        self.menu_item = menu_item
        self._runtime_callback = runtime_callback
        self._notify_attention = notify_attention
        self._dismiss_attention = dismiss_attention
        self._now = now
        self._app_factory = app_factory
        self._store = store or AlarmStore(config.state_path, default_24_hour=config.use_24_hour)
        self._lock = threading.RLock()
        self._menu_ui: Any | None = None
        self._ringing: dict[int, AlarmRecord] = {}
        self._fired_occurrences: set[tuple[int, str]] = set()
        self._worker = AlarmClockWorker(self._check_due, now=now)
        if start_worker:
            self._worker.start()

    @property
    def worker(self) -> AlarmClockWorker:
        return self._worker

    @property
    def state(self) -> AlarmState:
        with self._lock:
            return self._store.state

    def execute(self, request: ToolRequest) -> ToolResult:
        operation = str(request.get("operation") or "set").strip().lower()
        if operation in {"set", "add", "create", "start", ""}:
            return self._set(request)
        if operation in {"list", "show", "status"}:
            return self._list()
        if operation in {"delete", "remove", "cancel"}:
            return self._delete(request)
        if operation in {"delete_all", "cancel_all", "clear_all"}:
            return self._delete_all()
        if operation in {"enable", "on"}:
            return self._set_enabled(request, True)
        if operation in {"disable", "off"}:
            return self._set_enabled(request, False)
        if operation == "snooze":
            return self._snooze_result(request)
        if operation in {"dismiss", "stop"}:
            return self._dismiss_result(request)
        return ToolResult.direct("I do not recognize that alarm operation.")

    def prepare_model_request(self, request: ToolRequest) -> dict[str, Any] | None:
        operation = str(request.get("operation") or "set").strip().lower()
        allowed = {"set", "list", "delete", "delete_all", "enable", "disable", "snooze", "dismiss"}
        if operation not in allowed:
            return None
        prepared = dict(request)
        prepared["operation"] = operation
        if operation == "set":
            try:
                parse_alarm_time(prepared)
                parse_weekdays(prepared.get("weekdays"))
            except ValueError:
                return None
        return prepared

    def _save(self, state: AlarmState) -> bool:
        try:
            self._store.save(state)
        except (OSError, AlarmPersistenceError) as exc:
            print(f"[ALARM] Could not save alarm data: {type(exc).__name__}", flush=True)
            return False
        return True

    def _set(self, request: Mapping[str, Any]) -> ToolResult:
        try:
            hour, minute = parse_alarm_time(request)
            weekdays = parse_weekdays(request.get("weekdays"))
        except ValueError:
            return ToolResult.direct("Tell me an alarm time, for example, 7:30 AM.")
        label = str(request.get("label") or "Alarm").strip()[:60] or "Alarm"
        with self._lock:
            state = self._store.state
            if len(state.alarms) >= 100:
                return ToolResult.direct("You already have the maximum number of alarms.")
            alarm = AlarmRecord(
                alarm_id=state.next_id,
                hour=hour,
                minute=minute,
                label=label,
                weekdays=weekdays,
                one_time_date=None if weekdays else _next_one_time_date(self._now(), hour, minute),
            )
            saved = self._save(replace(state, alarms=(*state.alarms, alarm), next_id=state.next_id + 1))
        if not saved:
            return ToolResult.direct("Alarm data is read-only, so I could not save that alarm.")
        return ToolResult.direct(
            f"Alarm {alarm.alarm_id} is set for {format_alarm_time(hour, minute, state.use_24_hour)}, {format_repeat(weekdays, alarm.one_time_date)}."
        )

    def _list(self) -> ToolResult:
        with self._lock:
            state = self._store.state
            alarms = state.alarms
        if not alarms:
            return ToolResult.direct("You do not have any alarms set.")
        details = []
        for alarm in alarms:
            status = "on" if alarm.enabled else "off"
            details.append(
                f"Alarm {alarm.alarm_id}, {alarm.label}, {format_alarm_time(alarm.hour, alarm.minute, state.use_24_hour)}, {format_repeat(alarm.weekdays, alarm.one_time_date)}, {status}"
            )
        return ToolResult.direct("; ".join(details) + ".")

    @staticmethod
    def _request_id(request: Mapping[str, Any]) -> int | None:
        raw = request.get("alarm_id", request.get("id"))
        if isinstance(raw, bool):
            return None
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _delete(self, request: Mapping[str, Any]) -> ToolResult:
        alarm_id = self._request_id(request)
        if alarm_id is None:
            return ToolResult.direct("Tell me which alarm number to delete.")
        return ToolResult.direct(
            f"I deleted alarm {alarm_id}." if self._delete_alarm(alarm_id) else f"Alarm {alarm_id} is not available."
        )

    def _delete_all(self) -> ToolResult:
        with self._lock:
            state = self._store.state
            count = len(state.alarms)
            saved = self._save(replace(state, alarms=()))
        if not saved:
            return ToolResult.direct("Alarm data is read-only, so I could not delete alarms.")
        for alarm_id in tuple(self._ringing):
            self._dismiss_ringing(alarm_id)
        return ToolResult.direct(
            "You do not have any alarms to delete." if count == 0 else f"I deleted {count} alarm{'s' if count != 1 else ''}."
        )

    def _set_enabled(self, request: Mapping[str, Any], enabled: bool) -> ToolResult:
        alarm_id = self._request_id(request)
        if alarm_id is None:
            return ToolResult.direct(f"Tell me which alarm number to turn {'on' if enabled else 'off'}.")
        if not self._toggle_alarm(alarm_id, enabled):
            return ToolResult.direct(f"Alarm {alarm_id} is not available.")
        return ToolResult.direct(f"Alarm {alarm_id} is now {'on' if enabled else 'off'}.")

    def _resolve_ringing_id(self, request: Mapping[str, Any]) -> int | None:
        alarm_id = self._request_id(request)
        if alarm_id is not None:
            return alarm_id
        with self._lock:
            return next(iter(self._ringing)) if len(self._ringing) == 1 else None

    def _snooze_result(self, request: Mapping[str, Any]) -> ToolResult:
        alarm_id = self._resolve_ringing_id(request)
        if alarm_id is None:
            return ToolResult.direct("Tell me which ringing alarm to snooze.")
        if not self._snooze_alarm(alarm_id):
            return ToolResult.direct(f"Alarm {alarm_id} is not ringing.")
        return ToolResult.direct(f"I snoozed alarm {alarm_id} for {self.config.snooze_minutes} minutes.")

    def _dismiss_result(self, request: Mapping[str, Any]) -> ToolResult:
        alarm_id = self._resolve_ringing_id(request)
        if alarm_id is None:
            return ToolResult.direct("Tell me which ringing alarm to dismiss.")
        if not self._dismiss_ringing(alarm_id):
            return ToolResult.direct(f"Alarm {alarm_id} is not ringing.")
        return ToolResult.direct(f"Alarm {alarm_id} is dismissed.")

    def _create_from_menu(self, hour: int, minute: int, label: str, weekdays: tuple[int, ...]) -> int | None:
        result = self._set({"hour": hour, "minute": minute, "label": label, "weekdays": weekdays})
        if " is set for " not in result.content:
            return None
        with self._lock:
            return self._store.state.next_id - 1

    def _update_from_menu(self, alarm_id: int, hour: int, minute: int, label: str, weekdays: tuple[int, ...]) -> bool:
        try:
            AlarmRecord(alarm_id, hour, minute, label or "Alarm", weekdays=weekdays)
        except (TypeError, ValueError):
            return False
        with self._lock:
            state = self._store.state
            updated = []
            found = False
            for alarm in state.alarms:
                if alarm.alarm_id != alarm_id:
                    updated.append(alarm)
                    continue
                found = True
                updated.append(
                    AlarmRecord(
                        alarm_id=alarm_id,
                        hour=hour,
                        minute=minute,
                        label=(label or "Alarm").strip()[:60],
                        enabled=alarm.enabled,
                        weekdays=weekdays,
                        one_time_date=None if weekdays else _next_one_time_date(self._now(), hour, minute),
                    )
                )
            return found and self._save(replace(state, alarms=tuple(updated)))

    def _delete_alarm(self, alarm_id: int) -> bool:
        with self._lock:
            state = self._store.state
            alarms = tuple(alarm for alarm in state.alarms if alarm.alarm_id != alarm_id)
            if len(alarms) == len(state.alarms):
                return False
            saved = self._save(replace(state, alarms=alarms))
        if saved:
            self._dismiss_ringing(alarm_id)
        return saved

    def _toggle_alarm(self, alarm_id: int, enabled: bool) -> bool:
        with self._lock:
            state = self._store.state
            updated: list[AlarmRecord] = []
            found = False
            for alarm in state.alarms:
                if alarm.alarm_id != alarm_id:
                    updated.append(alarm)
                    continue
                found = True
                one_time_date = (
                    _next_one_time_date(self._now(), alarm.hour, alarm.minute)
                    if enabled and not alarm.repeating
                    else alarm.one_time_date
                )
                updated.append(alarm.with_enabled(enabled, one_time_date=one_time_date))
            saved = found and self._save(replace(state, alarms=tuple(updated)))
        if saved and not enabled:
            self._dismiss_ringing(alarm_id)
        return saved

    def _set_24_hour(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            return False
        with self._lock:
            return self._save(replace(self._store.state, use_24_hour=enabled))

    def _view_items(self) -> tuple[AlarmViewItem, ...]:
        with self._lock:
            state = self._store.state
            ringing = set(self._ringing)
            return tuple(
                AlarmViewItem(
                    alarm.alarm_id,
                    format_alarm_time(alarm.hour, alarm.minute, state.use_24_hour),
                    alarm.label,
                    format_repeat(alarm.weekdays, alarm.one_time_date),
                    alarm.enabled,
                    alarm.alarm_id in ringing,
                    alarm.snoozed_until is not None,
                )
                for alarm in sorted(state.alarms, key=lambda item: (item.hour, item.minute, item.alarm_id))
            )

    def _editor_alarm(self, alarm_id: int) -> AlarmRecord | None:
        with self._lock:
            return next((alarm for alarm in self._store.state.alarms if alarm.alarm_id == alarm_id), None)

    def _snooze_alarm(self, alarm_id: int) -> bool:
        with self._lock:
            if alarm_id not in self._ringing:
                return False
            state = self._store.state
            snoozed_until = (self._now() + timedelta(minutes=self.config.snooze_minutes)).replace(second=0, microsecond=0)
            alarms = tuple(
                replace(alarm, snoozed_until=snoozed_until)
                if alarm.alarm_id == alarm_id else alarm
                for alarm in state.alarms
            )
            if not self._save(replace(state, alarms=alarms)):
                return False
        self._dismiss_ringing(alarm_id)
        return True

    def _dismiss_ringing(self, alarm_id: int) -> bool:
        with self._lock:
            if self._ringing.pop(alarm_id, None) is None:
                return False
        self._dismiss_attention(RuntimeAttentionDismissal(self.action, f"alarm-{alarm_id}"))
        return True

    def _check_due(self, now: datetime) -> None:
        minute_now = now.replace(second=0, microsecond=0)
        due: list[AlarmRecord] = []
        with self._lock:
            state = self._store.state
            updated: list[AlarmRecord] = []
            changed = False
            for alarm in state.alarms:
                regular_target = datetime.combine(
                    now.date(),
                    clock_time(alarm.hour, alarm.minute),
                )
                if alarm.weekdays and regular_target > minute_now:
                    regular_target -= timedelta(days=1)
                elif not alarm.weekdays and alarm.one_time_date is not None:
                    regular_target = datetime.combine(
                        alarm.one_time_date,
                        clock_time(alarm.hour, alarm.minute),
                    )
                snooze_delay = (
                    minute_now - alarm.snoozed_until
                    if alarm.snoozed_until is not None
                    else None
                )
                regular_delay = minute_now - regular_target
                is_snooze = (
                    snooze_delay is not None
                    and timedelta(0) <= snooze_delay < LATE_RING_GRACE
                )
                is_regular = (
                    alarm.enabled
                    and timedelta(0) <= regular_delay < LATE_RING_GRACE
                    and (
                        regular_target.weekday() in alarm.weekdays
                        if alarm.weekdays
                        else alarm.one_time_date == regular_target.date()
                    )
                )
                target = alarm.snoozed_until if is_snooze else regular_target
                occurrence = (alarm.alarm_id, target.isoformat())
                if (is_snooze or is_regular) and occurrence not in self._fired_occurrences:
                    self._fired_occurrences.add(occurrence)
                    due.append(alarm)
                    changed = True
                    updated.append(
                        replace(
                            alarm,
                            enabled=alarm.enabled if alarm.repeating else False,
                            snoozed_until=None,
                        )
                    )
                else:
                    stale_snooze = (
                        snooze_delay is not None
                        and snooze_delay >= LATE_RING_GRACE
                    )
                    if stale_snooze:
                        changed = True
                        updated.append(replace(alarm, snoozed_until=None))
                    else:
                        updated.append(alarm)
            if changed:
                self._save(replace(state, alarms=tuple(updated)))
            oldest = minute_now - timedelta(days=2)
            self._fired_occurrences = {
                occurrence
                for occurrence in self._fired_occurrences
                if datetime.fromisoformat(occurrence[1]) >= oldest
            }
        for alarm in due:
            self._ring(alarm)

    def _ring(self, alarm: AlarmRecord) -> None:
        with self._lock:
            self._ringing[alarm.alarm_id] = alarm
        message = f"{alarm.label} alarm is ringing."
        self._notify_attention(
            RuntimeAttention(
                source=self.action,
                attention_id=f"alarm-{alarm.alarm_id}",
                message=message,
                acknowledge=lambda alarm_id=alarm.alarm_id: self._dismiss_ringing(alarm_id),
                animation_state="alarm_clock_ringing",
                badge_label="ALARM",
                announce_on_acknowledge=False,
            )
        )
        self._runtime_callback(RuntimeNotification(source=self.action, message=message))

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
                alarm_provider=self._view_items,
                alarm_lookup=self._editor_alarm,
                create_alarm=self._create_from_menu,
                update_alarm=self._update_from_menu,
                delete_alarm=self._delete_alarm,
                toggle_alarm=self._toggle_alarm,
                snooze_alarm=self._snooze_alarm,
                dismiss_alarm=self._dismiss_ringing,
                set_24_hour=self._set_24_hour,
                now=self._now,
                state_provider=lambda: self.state,
                snooze_minutes=self.config.snooze_minutes,
                read_only=self._store.read_only,
                storage_error=self._store.error,
                face_provider=context.current_face,
                on_close=handle_close,
            )
        except Exception:
            self._menu_ui = None
            context.on_close()
            raise

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        text = normalize_direct_text(user_text)
        if text in {"list alarms", "list my alarms", "show alarms", "show my alarms", "what alarms are set"}:
            return {"action": cls.action, "operation": "list"}
        if text in {"delete all alarms", "cancel all alarms", "clear all alarms"}:
            return {"action": cls.action, "operation": "delete_all"}
        simple = re.fullmatch(r"(?:delete|cancel|remove|enable|disable|snooze|dismiss|stop) (?:my )?alarm(?: number)? (?P<id>\d+)", text)
        if simple:
            operation = text.split()[0]
            operation = {"cancel": "delete", "remove": "delete", "stop": "dismiss"}.get(operation, operation)
            return {"action": cls.action, "operation": operation, "alarm_id": simple.group("id")}
        if text in {"snooze alarm", "snooze my alarm", "snooze the alarm"}:
            return {"action": cls.action, "operation": "snooze"}
        if text in {"dismiss alarm", "dismiss my alarm", "stop alarm", "stop the alarm"}:
            return {"action": cls.action, "operation": "dismiss"}
        if not (text.startswith("set ") or text.startswith("wake me ")) or "alarm" not in text and "wake me" not in text:
            return None
        time_match = re.search(r"\b(?:at|for) (\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", text)
        if time_match is None:
            return None
        try:
            _parse_time_text(time_match.group(1))
        except ValueError:
            return None
        action: DirectAction = {"action": cls.action, "operation": "set", "time": time_match.group(1)}
        if "every weekday" in text or "weekdays" in text:
            action["weekdays"] = "weekdays"
        elif "every day" in text or "daily" in text:
            action["weekdays"] = "daily"
        elif "weekends" in text or "every weekend" in text:
            action["weekdays"] = "weekends"
        else:
            named_days = [name for name in WEEKDAY_NAMES if name.casefold() in text]
            if named_days:
                action["weekdays"] = ",".join(named_days)
        label_match = re.search(r"\b(?:called|named) (.+?)(?: every| on |$)", text)
        if label_match:
            action["label"] = label_match.group(1).strip()
        return action

    def close(self) -> None:
        menu_ui = self._menu_ui
        if menu_ui is not None:
            menu_ui.close()
        self._worker.close()
        for alarm_id in tuple(self._ringing):
            self._dismiss_ringing(alarm_id)


def _register_alarm(
    registry: Any,
    config: AlarmClockConfig,
    *,
    start_worker: bool,
    store: AlarmStore | None = None,
) -> None:
    registry.register(
        AlarmClockTool(
            config,
            registry.notify_runtime,
            notify_attention=registry.notify_attention,
            dismiss_attention=registry.dismiss_attention,
            menu_item=ALARM_MENU_ITEM if config.show_in_menu else None,
            start_worker=start_worker,
            store=store,
        )
    )


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    _register_alarm(registry, load_alarm_clock_config(settings), start_worker=True)


def register_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    del settings
    config = AlarmClockConfig(show_in_menu=False)
    _register_alarm(
        registry,
        config,
        start_worker=False,
        store=AlarmStore(None, default_24_hour=config.use_24_hour),
    )


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    if load_alarm_clock_config(settings).show_in_menu:
        registry.register(ALARM_MENU_ITEM)


__all__ = [
    "ALARM_MENU_ITEM",
    "AlarmClockTool",
    "AlarmClockWorker",
    "format_alarm_time",
    "format_repeat",
    "parse_alarm_time",
    "parse_weekdays",
]
