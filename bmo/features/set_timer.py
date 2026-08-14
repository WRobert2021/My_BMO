"""Non-blocking timers backed by one condition-driven scheduler thread."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import heapq
import math
from pathlib import Path
import re
import threading
import time
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    RuntimeCallback,
    RuntimeAttention,
    RuntimeAttentionDismissal,
    RuntimeNotification,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)
from bmo.ui.timer import TimerApp, TimerViewItem


DEFAULT_MAX_TIMERS = 20
DEFAULT_MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIMER_MENU_ITEM = FeatureMenuItem(
    name="set_timer",
    label="Timers",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "timer.png",
)
TimerAppFactory = Callable[..., TimerApp]

_SMALL_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "couple": 2,
}
_NUMBER_TOKENS = tuple(
    _SMALL_NUMBERS
) + ("a", "an", "and", "hundred", "thousand", "half", "quarter")
_NUMBER_PATTERN = "|".join(sorted(_NUMBER_TOKENS, key=len, reverse=True))
_QUANTITY_PATTERN = (
    rf"(?:\d+(?:\.\d+)?|"
    rf"(?:{_NUMBER_PATTERN})(?:\s+(?:{_NUMBER_PATTERN}))*)"
)
_UNIT_PATTERN = r"seconds?|secs?|minutes?|mins?|hours?|hrs?|days?"
_DURATION_PART = re.compile(
    rf"(?<![\w.-])(?P<quantity>{_QUANTITY_PATTERN})\s+"
    rf"(?P<unit>{_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
_TRAILING_FRACTION = re.compile(
    rf"(?P<quantity>{_QUANTITY_PATTERN})\s+"
    rf"(?P<unit>{_UNIT_PATTERN})\s+and\s+(?:a\s+)?"
    r"(?P<fraction>half|quarter)\b",
    re.IGNORECASE,
)
_UNIT_SECONDS = {
    "second": 1,
    "sec": 1,
    "minute": 60,
    "min": 60,
    "hour": 3600,
    "hr": 3600,
    "day": 86400,
}


class TimerCapacityError(RuntimeError):
    """Raised when the configured active-timer limit is reached."""


@dataclass(frozen=True)
class ScheduledTimer:
    """One active timer stored by the scheduler."""

    timer_id: int
    deadline: float
    duration_seconds: float
    label: str | None = None


def _parse_number_words(words: str) -> float:
    tokens = words.lower().split()
    fraction = 0.0
    if "half" in tokens:
        fraction += 0.5
    if "quarter" in tokens:
        fraction += 0.25

    whole_tokens = [
        token
        for token in tokens
        if token not in {"and", "half", "quarter", "a", "an"}
    ]
    if not whole_tokens:
        if fraction:
            return fraction
        if "a" in tokens or "an" in tokens:
            return 1.0
        raise ValueError("duration quantity is missing")

    total = 0
    current = 0
    for token in whole_tokens:
        if token in _SMALL_NUMBERS:
            current += _SMALL_NUMBERS[token]
        elif token == "hundred":
            current = max(current, 1) * 100
        elif token == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            raise ValueError(f"unsupported number word: {token}")
    return float(total + current) + fraction


def _parse_quantity(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return _parse_number_words(value)


def parse_duration(value: object) -> float:
    """Parse a numeric second count or a natural compound duration."""
    if isinstance(value, bool):
        raise ValueError("duration must not be a boolean")
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value or "").lower()
        if re.search(r"\b(?:minus|negative)\b|(?:^|\s)-\s*\d", text):
            raise ValueError("duration must be positive")
        text = text.replace("-", " ")
        text = re.sub(r"\b(half|quarter)\s+of\s+an?\b", r"\1", text)
        text = _TRAILING_FRACTION.sub(
            lambda match: (
                f"{match.group('quantity')} {match.group('unit')} "
                f"{match.group('fraction')} {match.group('unit')}"
            ),
            text,
        )
        seconds = 0.0
        matches = tuple(_DURATION_PART.finditer(text))
        if not matches:
            raise ValueError("duration needs a number and time unit")
        for match in matches:
            quantity = _parse_quantity(match.group("quantity"))
            unit = match.group("unit").lower().rstrip("s")
            seconds += quantity * _UNIT_SECONDS[unit]

    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("duration must be positive")
    return seconds


def format_duration(seconds: float) -> str:
    """Return a compact, speakable representation of a duration."""
    if not math.isfinite(seconds) or seconds <= 0:
        return "0 seconds"
    rounded = round(seconds)
    if math.isclose(seconds, rounded, abs_tol=1e-9):
        remaining = int(rounded)
        parts = []
        for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
            count, remaining = divmod(remaining, size)
            if count:
                parts.append(f"{count} {unit}{'' if count == 1 else 's'}")
        if remaining or not parts:
            parts.append(
                f"{remaining} second{'' if remaining == 1 else 's'}"
            )
        return " ".join(parts)
    return f"{seconds:g} seconds"


class TimerScheduler:
    """Schedule all timers on one priority queue and one worker thread."""

    def __init__(
        self,
        callback: Callable[[ScheduledTimer], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        max_timers: int = DEFAULT_MAX_TIMERS,
    ) -> None:
        self._callback = callback
        self._clock = clock
        self._max_timers = max_timers
        self._condition = threading.Condition()
        self._heap: list[tuple[float, int, ScheduledTimer]] = []
        self._active: dict[int, ScheduledTimer] = {}
        self._next_id = 1
        self._thread: threading.Thread | None = None
        self._stopped = False

    @property
    def thread(self) -> threading.Thread | None:
        """Expose the single scheduler thread for lifecycle verification."""
        with self._condition:
            return self._thread

    def schedule(self, duration_seconds: float, label: str | None) -> ScheduledTimer:
        """Add a timer and wake the worker if its next deadline changed."""
        with self._condition:
            if self._stopped:
                raise RuntimeError("timer scheduler is closed")
            if len(self._active) >= self._max_timers:
                raise TimerCapacityError("active timer limit reached")
            timer = ScheduledTimer(
                timer_id=self._next_id,
                deadline=self._clock() + duration_seconds,
                duration_seconds=duration_seconds,
                label=label,
            )
            self._next_id += 1
            self._active[timer.timer_id] = timer
            heapq.heappush(
                self._heap,
                (timer.deadline, timer.timer_id, timer),
            )
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="bmo-timer-scheduler",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify()
            return timer

    def active_timers(self) -> tuple[ScheduledTimer, ...]:
        """Return active timers ordered by deadline and identifier."""
        with self._condition:
            return tuple(
                sorted(
                    self._active.values(),
                    key=lambda timer: (timer.deadline, timer.timer_id),
                )
            )

    def cancel(self, timer_id: int) -> ScheduledTimer | None:
        """Cancel one timer by its stable user-facing identifier."""
        with self._condition:
            timer = self._active.pop(timer_id, None)
            if timer is not None:
                self._heap = [
                    entry for entry in self._heap if entry[2] is not timer
                ]
                heapq.heapify(self._heap)
                self._condition.notify()
            return timer

    def cancel_all(self) -> tuple[ScheduledTimer, ...]:
        """Cancel every active timer."""
        with self._condition:
            timers = tuple(
                sorted(self._active.values(), key=lambda timer: timer.timer_id)
            )
            self._active.clear()
            self._heap.clear()
            self._condition.notify()
            return timers

    def notify_clock_changed(self) -> None:
        """Wake the worker after an injected test clock advances."""
        with self._condition:
            self._condition.notify()

    def close(self) -> None:
        """Cancel pending timers, wake the worker, and wait for it to exit."""
        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            self._active.clear()
            self._heap.clear()
            thread = self._thread
            self._condition.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def _discard_cancelled(self) -> None:
        while self._heap:
            timer = self._heap[0][2]
            if self._active.get(timer.timer_id) is timer:
                return
            heapq.heappop(self._heap)

    def _run(self) -> None:
        while True:
            due: list[ScheduledTimer] = []
            with self._condition:
                while not self._stopped:
                    self._discard_cancelled()
                    if not self._heap:
                        self._condition.wait()
                        continue
                    delay = self._heap[0][0] - self._clock()
                    if delay > 0:
                        self._condition.wait(timeout=delay)
                        continue
                    now = self._clock()
                    while self._heap and self._heap[0][0] <= now:
                        timer = heapq.heappop(self._heap)[2]
                        if self._active.pop(timer.timer_id, None) is timer:
                            due.append(timer)
                    break
                if self._stopped:
                    return

            for timer in due:
                with self._condition:
                    if self._stopped:
                        return
                try:
                    self._callback(timer)
                except Exception as exc:
                    print(
                        f"[TIMER] Expiration callback failed: {exc}",
                        flush=True,
                    )


class SetTimerTool:
    """Set, inspect, and cancel multiple non-blocking timers."""

    action = "set_timer"
    aliases = ("timer",)
    description = "Set, list, or cancel one or more countdown timers."
    schemas = (
        '{"action":"set_timer","duration":"natural duration"}',
        '{"action":"set_timer","operation":"cancel","timer_id":"number"}',
        '{"action":"set_timer","operation":"cancel_all"}',
        '{"action":"set_timer","operation":"list"}',
    )
    prompt_guidance = (
        "Use set_timer for countdown timers and preserve natural duration text.",
        "For cancellation, use operation cancel with a timer_id when named, "
        "or operation cancel_all when the user asks to cancel every timer.",
    )
    prompt_examples = (
        (
            "Set a timer for one hour and ten minutes.",
            '{"action":"set_timer","duration":"one hour and ten minutes"}',
        ),
        (
            "Cancel timer 2.",
            '{"action":"set_timer","operation":"cancel","timer_id":"2"}',
        ),
    )

    def __init__(
        self,
        runtime_callback: RuntimeCallback,
        *,
        notify_attention: Callable[[RuntimeAttention], None] | None = None,
        dismiss_attention: Callable[[RuntimeAttentionDismissal], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_timers: int = DEFAULT_MAX_TIMERS,
        max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS,
        app_factory: TimerAppFactory = TimerApp,
        menu_item: FeatureMenuItem | None = TIMER_MENU_ITEM,
    ) -> None:
        self._runtime_callback = runtime_callback
        self._notify_attention = notify_attention or (lambda _attention: None)
        self._dismiss_attention = dismiss_attention or (lambda _dismissal: None)
        self._clock = clock
        self._max_duration_seconds = max_duration_seconds
        self._app_factory = app_factory
        self.menu_item = menu_item
        self._menu_ui: TimerApp | None = None
        self._expired: dict[int, ScheduledTimer] = {}
        self.scheduler = TimerScheduler(
            self._timer_expired,
            clock=clock,
            max_timers=max_timers,
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        operation = str(request.get("operation") or "set").lower().strip()
        if operation in {"cancel_all", "clear", "clear_all"}:
            return self._cancel_all()
        if operation in {"cancel", "stop", "remove"}:
            return self._cancel(request)
        if operation in {"list", "status", "show"}:
            return self._list()
        if operation not in {"", "set", "start"}:
            return ToolResult.success("I do not recognize that timer operation.")
        return self._set(request)

    @staticmethod
    def normalize_request(request: ToolRequest) -> dict[str, Any]:
        normalized = dict(request)
        operation = str(request.get("operation") or "").lower().strip()
        if operation:
            normalized["operation"] = operation
        return normalized

    def close(self) -> None:
        menu_ui = self._menu_ui
        if menu_ui is not None:
            menu_ui.close()
        self.scheduler.close()
        for timer_id in tuple(self._expired):
            self._dismiss_attention(
                RuntimeAttentionDismissal(self.action, f"timer-{timer_id}")
            )
        self._expired.clear()

    def open_menu(self, context: FeatureMenuContext) -> None:
        """Open the timer list only through its registered menu contribution."""
        if self._menu_ui is not None:
            return

        def handle_close() -> None:
            self._menu_ui = None
            context.on_close()

        try:
            self._menu_ui = self._app_factory(
                context.master,
                timer_provider=self._menu_timer_items,
                cancel_timer=self._cancel_from_menu,
                create_timer=self._create_from_menu,
                face_provider=context.current_face,
                on_close=handle_close,
            )
        except Exception:
            self._menu_ui = None
            context.on_close()
            raise

    def _menu_timer_items(self) -> tuple[TimerViewItem, ...]:
        now = self._clock()
        return tuple(
            TimerViewItem(
                timer_id=timer.timer_id,
                label=timer.label,
                remaining_seconds=max(timer.deadline - now, 0.0),
            )
            for timer in self.scheduler.active_timers()
        )

    def _cancel_from_menu(self, timer_id: int) -> bool:
        return self.scheduler.cancel(timer_id) is not None

    def _create_from_menu(self, duration_seconds: float) -> bool:
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(float(duration_seconds))
            or not 0 < float(duration_seconds) <= self._max_duration_seconds
        ):
            return False
        try:
            self.scheduler.schedule(float(duration_seconds), None)
        except (TimerCapacityError, RuntimeError):
            return False
        return True

    def _set(self, request: ToolRequest) -> ToolResult:
        raw_duration = request.get("duration_seconds")
        explicit_seconds = raw_duration is not None
        if not explicit_seconds:
            raw_duration = (
                request.get("duration")
                or request.get("value")
                or request.get("query")
            )
        try:
            if explicit_seconds and isinstance(raw_duration, bool):
                raise ValueError("duration must not be a boolean")
            duration_seconds = parse_duration(
                float(raw_duration) if explicit_seconds else raw_duration
            )
        except (TypeError, ValueError):
            return ToolResult.success(
                "Tell me how long the timer should run, for example, 10 minutes."
            )
        if duration_seconds > self._max_duration_seconds:
            return ToolResult.success(
                "Timers can be at most "
                f"{format_duration(self._max_duration_seconds)}."
            )

        label = str(request.get("label") or "").strip()[:60] or None
        try:
            timer = self.scheduler.schedule(duration_seconds, label)
        except TimerCapacityError:
            return ToolResult.success(
                "You already have the maximum number of active timers."
            )
        except RuntimeError:
            return ToolResult.success("The timer service is shutting down.")

        name = f"Timer {timer.timer_id}"
        if label:
            name += f" ({label})"
        return ToolResult.success(
            f"{name} is set for {format_duration(duration_seconds)}."
        )

    def _cancel(self, request: ToolRequest) -> ToolResult:
        raw_timer_id = request.get("timer_id") or request.get("id")
        if raw_timer_id not in (None, ""):
            timer_id = _parse_timer_id(raw_timer_id)
            if timer_id is None:
                return ToolResult.success("Tell me which timer number to cancel.")
            timer = self.scheduler.cancel(timer_id)
            if timer is None:
                return ToolResult.success(f"Timer {timer_id} is not active.")
            return ToolResult.success(f"I canceled timer {timer_id}.")

        raw_duration = request.get("duration")
        if raw_duration:
            try:
                duration = parse_duration(raw_duration)
            except ValueError:
                return ToolResult.success("Tell me which timer to cancel.")
            matches = [
                timer
                for timer in self.scheduler.active_timers()
                if math.isclose(timer.duration_seconds, duration, abs_tol=1e-9)
            ]
            if len(matches) == 1:
                self.scheduler.cancel(matches[0].timer_id)
                return ToolResult.success(
                    f"I canceled timer {matches[0].timer_id}."
                )
            if not matches:
                return ToolResult.success(
                    f"There is no active {format_duration(duration)} timer."
                )
            return ToolResult.success(
                "More than one timer has that duration. Tell me the timer number."
            )

        active = self.scheduler.active_timers()
        if not active:
            return ToolResult.success("There are no active timers to cancel.")
        if len(active) > 1:
            return ToolResult.success(
                f"You have {len(active)} active timers. Tell me a timer number, "
                "or ask me to cancel all timers."
            )
        self.scheduler.cancel(active[0].timer_id)
        return ToolResult.success(f"I canceled timer {active[0].timer_id}.")

    def _cancel_all(self) -> ToolResult:
        cancelled = self.scheduler.cancel_all()
        if not cancelled:
            return ToolResult.success("There are no active timers to cancel.")
        noun = "timer" if len(cancelled) == 1 else "timers"
        return ToolResult.success(f"I canceled {len(cancelled)} {noun}.")

    def _list(self) -> ToolResult:
        active = self.scheduler.active_timers()
        if not active:
            return ToolResult.success("There are no active timers.")
        now = self._clock()
        descriptions = []
        for timer in active:
            name = f"Timer {timer.timer_id}"
            if timer.label:
                name += f" ({timer.label})"
            remaining = max(timer.deadline - now, 0.0)
            descriptions.append(f"{name}: {format_duration(remaining)} remaining")
        return ToolResult.success("; ".join(descriptions) + ".")

    def _timer_expired(self, timer: ScheduledTimer) -> None:
        name = f"Timer {timer.timer_id}"
        if timer.label:
            name += f" ({timer.label})"
        self._expired[timer.timer_id] = timer
        self._notify_attention(
            RuntimeAttention(
                source=self.action,
                attention_id=f"timer-{timer.timer_id}",
                message=f"{name} is done.",
                acknowledge=lambda timer_id=timer.timer_id: self._acknowledge_expired(
                    timer_id
                ),
                animation_state="alarm",
                badge_label="TIMER",
                announce_on_acknowledge=False,
            )
        )
        self._runtime_callback(
            RuntimeNotification(
                source=self.action,
                message=f"{name} is done.",
            )
        )

    def _acknowledge_expired(self, timer_id: int) -> bool:
        if self._expired.pop(timer_id, None) is None:
            return False
        self._dismiss_attention(
            RuntimeAttentionDismissal(self.action, f"timer-{timer_id}")
        )
        return True

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        normalized = normalize_direct_text(user_text)
        if normalized in {
            "cancel all timers",
            "stop all timers",
            "clear all timers",
            "turn off all timers",
        }:
            return {"action": cls.action, "operation": "cancel_all"}
        if normalized in {
            "list timers",
            "list my timers",
            "what timers are running",
            "show my timers",
        }:
            return {"action": cls.action, "operation": "list"}

        cancel_id = re.fullmatch(
            r"(?:cancel|stop|remove|delete) (?:my |the )?timer"
            r"(?: number| #)? (?P<timer_id>[a-z\d -]+)",
            normalized,
        )
        if cancel_id:
            timer_id = _parse_timer_id(cancel_id.group("timer_id"))
            if timer_id is not None:
                return {
                    "action": cls.action,
                    "operation": "cancel",
                    "timer_id": str(timer_id),
                }

        cancel_duration = re.fullmatch(
            r"(?:cancel|stop|remove|delete) (?:my |the )?"
            r"(?P<duration>.+) timer",
            normalized,
        )
        if cancel_duration:
            duration = cancel_duration.group("duration")
            try:
                parse_duration(duration)
            except ValueError:
                pass
            else:
                return {
                    "action": cls.action,
                    "operation": "cancel",
                    "duration": duration,
                }

        if normalized in {
            "cancel timer",
            "cancel my timer",
            "cancel the timer",
            "stop timer",
            "stop my timer",
            "stop the timer",
        }:
            return {"action": cls.action, "operation": "cancel"}

        set_for = re.fullmatch(
            r"(?:please )?(?:set|start)(?: me)? (?:a |an |another )?"
            r"(?:(?P<label>.+?) )?timer (?:for|of) (?P<duration>.+)",
            normalized,
        )
        if set_for:
            duration = set_for.group("duration")
            label = set_for.group("label")
            duration, parsed_label = _split_duration_label(duration)
            label = parsed_label or label
            try:
                parse_duration(duration)
            except ValueError:
                return None
            action = {"action": cls.action, "duration": duration}
            if label:
                action["label"] = label
            return action

        duration_timer = re.fullmatch(
            r"(?:please )?(?:set|start)(?: me)? (?:a |an |another )?"
            r"(?P<duration>.+?) timer(?: (?:called|named) (?P<label>.+))?",
            normalized,
        )
        if duration_timer:
            duration = duration_timer.group("duration")
            try:
                parse_duration(duration)
            except ValueError:
                return None
            action = {"action": cls.action, "duration": duration}
            label = duration_timer.group("label")
            if label:
                action["label"] = label
            return action

        timer_for = re.fullmatch(r"timer for (?P<duration>.+)", normalized)
        if timer_for:
            duration = timer_for.group("duration")
            try:
                parse_duration(duration)
            except ValueError:
                return None
            return {"action": cls.action, "duration": duration}
        return None


def _split_duration_label(duration: str) -> tuple[str, str | None]:
    parts = re.split(r"\s+(?:called|named)\s+", duration, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip() or None
    return duration, None


def _parse_timer_id(value: object) -> int | None:
    text = str(value).lower().strip().replace("-", " ")
    try:
        parsed = float(text)
    except ValueError:
        try:
            parsed = _parse_number_words(text)
        except ValueError:
            return None
    if not parsed.is_integer() or parsed <= 0:
        return None
    return int(parsed)


def _integer_setting(
    settings: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        raw_value = settings.get(name, default)
        if isinstance(raw_value, bool):
            raise TypeError
        value = int(raw_value)
    except (OverflowError, TypeError, ValueError):
        print(f"[CONFIG] {name} must be an integer; using {default}.", flush=True)
        return default
    return min(max(value, minimum), maximum)


def _duration_setting(settings: Mapping[str, Any]) -> float:
    try:
        raw_value = settings.get(
            "max_duration_seconds",
            DEFAULT_MAX_DURATION_SECONDS,
        )
        if isinstance(raw_value, bool):
            raise TypeError
        value = float(raw_value)
    except (OverflowError, TypeError, ValueError):
        print(
            "[CONFIG] max_duration_seconds must be numeric; using 604800.",
            flush=True,
        )
        return float(DEFAULT_MAX_DURATION_SECONDS)
    if not math.isfinite(value):
        return float(DEFAULT_MAX_DURATION_SECONDS)
    return min(max(value, 1.0), 31 * 24 * 60 * 60.0)


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register timers with the registry-owned runtime callback."""
    max_timers = _integer_setting(
        settings,
        "max_timers",
        DEFAULT_MAX_TIMERS,
        minimum=1,
        maximum=100,
    )
    show_in_menu = settings.get("show_in_menu", True)
    if not isinstance(show_in_menu, bool):
        raise TypeError("timer show_in_menu must be true or false")
    registry.register(
        SetTimerTool(
            registry.notify_runtime,
            notify_attention=registry.notify_attention,
            dismiss_attention=registry.dismiss_attention,
            max_timers=max_timers,
            max_duration_seconds=_duration_setting(settings),
            menu_item=TIMER_MENU_ITEM if show_in_menu else None,
        )
    )
