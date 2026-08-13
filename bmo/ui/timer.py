"""Touch-friendly, menu-launched countdown timer view."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math
import tkinter as tk
from typing import Any

from bmo.ui.compact_face import CompactFace
from bmo.ui.scrolling import VerticalScrollController


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480


@dataclass(frozen=True)
class TimerViewItem:
    """Display-only snapshot of one active countdown timer."""

    timer_id: int
    label: str | None
    remaining_seconds: float


@dataclass(frozen=True)
class TimerDurationDraft:
    """Touch-editor values for a new timer."""

    hours: int = 0
    minutes: int = 5
    seconds: int = 0

    @property
    def total_seconds(self) -> int:
        return self.hours * 3600 + self.minutes * 60 + self.seconds

    def adjusted(self, field: str, amount: int) -> "TimerDurationDraft":
        values = {
            "hours": self.hours,
            "minutes": self.minutes,
            "seconds": self.seconds,
        }
        if field not in values:
            raise ValueError("unknown timer duration field")
        maximum = 168 if field == "hours" else 59
        values[field] = max(0, min(maximum, values[field] + int(amount)))
        return TimerDurationDraft(**values)


def format_countdown(seconds: float) -> str:
    """Format remaining time without showing zero before expiration."""
    remaining = max(0, math.ceil(seconds))
    days, remaining = divmod(remaining, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, seconds_part = divmod(remaining, 60)
    clock = f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"
    if days:
        noun = "day" if days == 1 else "days"
        return f"{days} {noun}  {clock}"
    if hours:
        return clock
    return f"{minutes:02d}:{seconds_part:02d}"


TimerProvider = Callable[[], Iterable[TimerViewItem]]
TimerCanceller = Callable[[int], bool]
TimerCreator = Callable[[float], bool]


class TimerApp:
    """Show live active timers and allow touch deletion and scrolling."""

    BACKGROUND = "#e7f7ff"
    NAVY = "#102a5e"
    BLUE = "#1578d3"
    WHITE = "#ffffff"
    MUTED = "#58708c"
    DANGER = "#c83a4a"
    GREEN = "#3B8E63"

    LIST_LEFT = 24
    LIST_TOP = 76
    LIST_WIDTH = 752
    LIST_HEIGHT = 380
    ROW_HEIGHT = 78
    ROW_GAP = 10
    ROW_STRIDE = ROW_HEIGHT + ROW_GAP
    REFRESH_MS = 250
    BACK_BOUNDS = (522, 10, 668, 51)
    ADD_BOUNDS = (366, 10, 510, 51)

    def __init__(
        self,
        root: tk.Misc,
        *,
        timer_provider: TimerProvider,
        cancel_timer: TimerCanceller,
        create_timer: TimerCreator,
        on_close: Callable[[], None],
        face_provider: Callable[[], Any | None] | None = None,
    ) -> None:
        self.root = root
        self.timer_provider = timer_provider
        self.cancel_timer = cancel_timer
        self.create_timer = create_timer
        self.on_close = on_close
        self.closed = False
        self.refresh_after_id: str | None = None
        self._header_press: tuple[int, int] | None = None
        self._list_press_x: int | None = None
        self._items: tuple[TimerViewItem, ...] = ()
        self._delete_bounds: dict[int, tuple[int, int, int, int]] = {}
        self._adding = False
        self._duration_draft = TimerDurationDraft()
        self._editor_actions: dict[str, tuple[int, int, int, int]] = {}
        self.scroller = VerticalScrollController(self.LIST_HEIGHT)

        self.canvas = tk.Canvas(
            root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=self.BACKGROUND,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        self.list_canvas = tk.Canvas(
            root,
            width=self.LIST_WIDTH,
            height=self.LIST_HEIGHT,
            bg=self.BACKGROUND,
            highlightthickness=0,
        )
        self.list_canvas.place(
            x=self.LIST_LEFT,
            y=self.LIST_TOP,
            width=self.LIST_WIDTH,
            height=self.LIST_HEIGHT,
        )
        self.canvas.bind("<ButtonPress-1>", self._handle_header_press)
        self.canvas.bind("<ButtonRelease-1>", self._handle_header_release)
        self.list_canvas.bind("<ButtonPress-1>", self._handle_list_press)
        self.list_canvas.bind("<B1-Motion>", self._handle_list_motion)
        self.list_canvas.bind("<ButtonRelease-1>", self._handle_list_release)
        self.list_canvas.bind("<MouseWheel>", self._handle_mouse_wheel)

        self._draw_header()
        self.compact_face = CompactFace(
            root,
            self.canvas,
            face_provider=face_provider,
        )
        self._refresh()

    def _draw_header(self) -> None:
        self.canvas.create_rectangle(0, 0, 800, 62, fill=self.NAVY, outline="")
        self.canvas.create_text(
            24,
            30,
            anchor="w",
            text="TIMERS",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self.count_item = self.canvas.create_text(
            174,
            32,
            anchor="w",
            text="0 ACTIVE",
            fill="#bde7ff",
            font=("Arial", 10, "bold"),
        )
        add_left, add_top, add_right, add_bottom = self.ADD_BOUNDS
        self.canvas.create_rectangle(
            add_left,
            add_top,
            add_right,
            add_bottom,
            fill=self.BLUE,
            outline=self.WHITE,
            width=2,
        )
        self.canvas.create_text(
            (add_left + add_right) // 2,
            (add_top + add_bottom) // 2,
            text="+ ADD TIMER",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 10, "bold"),
        )
        left, top, right, bottom = self.BACK_BOUNDS
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=self.BLUE,
            outline=self.WHITE,
            width=2,
        )
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text="BACK TO MENU",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 10, "bold"),
        )

    def _refresh(self) -> None:
        if self.closed:
            return
        self._items = tuple(self.timer_provider())
        content_height = (
            len(self._items) * self.ROW_STRIDE - self.ROW_GAP
            if self._items
            else 0
        )
        self.scroller.set_content_height(content_height)
        if not getattr(self, "_adding", False):
            self._draw_list()
        self.canvas.itemconfigure(
            self.count_item,
            text=f"{len(self._items)} ACTIVE",
        )
        self.refresh_after_id = self.root.after(self.REFRESH_MS, self._refresh)

    def _draw_list(self) -> None:
        self.list_canvas.delete("all")
        self._delete_bounds.clear()
        if not self._items:
            self.list_canvas.create_text(
                self.LIST_WIDTH // 2,
                self.LIST_HEIGHT // 2 - 12,
                text="NO ACTIVE TIMERS",
                fill=self.NAVY,
                font=("Arial Rounded MT Bold", 22, "bold"),
            )
            self.list_canvas.create_text(
                self.LIST_WIDTH // 2,
                self.LIST_HEIGHT // 2 + 25,
                text="Use a voice command to set one.",
                fill=self.MUTED,
                font=("Arial", 12, "bold"),
            )
            return

        for index, item in enumerate(self._items):
            top = int(index * self.ROW_STRIDE - self.scroller.offset)
            bottom = top + self.ROW_HEIGHT
            if bottom < 0 or top > self.LIST_HEIGHT:
                continue
            self._draw_row(item, top, bottom)
        self._draw_scrollbar()

    def _draw_row(self, item: TimerViewItem, top: int, bottom: int) -> None:
        row_right = self.LIST_WIDTH - 18
        self.list_canvas.create_rectangle(
            0,
            top,
            row_right,
            bottom,
            fill=self.WHITE,
            outline="#98bfd7",
            width=3,
        )
        title = item.label or f"Timer {item.timer_id}"
        subtitle = f"TIMER {item.timer_id}" if item.label else "COUNTDOWN"
        self.list_canvas.create_text(
            20,
            top + 25,
            anchor="w",
            text=title,
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 16, "bold"),
            width=330,
        )
        self.list_canvas.create_text(
            21,
            top + 55,
            anchor="w",
            text=subtitle,
            fill=self.MUTED,
            font=("Arial", 9, "bold"),
        )
        self.list_canvas.create_text(
            480,
            top + self.ROW_HEIGHT // 2,
            text=format_countdown(item.remaining_seconds),
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 21, "bold"),
        )
        delete_bounds = (618, top + 14, 714, bottom - 14)
        self._delete_bounds[item.timer_id] = delete_bounds
        left, button_top, right, button_bottom = delete_bounds
        self.list_canvas.create_rectangle(
            left,
            button_top,
            right,
            button_bottom,
            fill=self.DANGER,
            outline="",
        )
        self.list_canvas.create_text(
            (left + right) // 2,
            (button_top + button_bottom) // 2,
            text="DELETE",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 10, "bold"),
        )

    def _draw_scrollbar(self) -> None:
        if self.scroller.max_offset <= 0:
            return
        track_left = self.LIST_WIDTH - 8
        self.list_canvas.create_rectangle(
            track_left,
            0,
            self.LIST_WIDTH,
            self.LIST_HEIGHT,
            fill="#d0e7f4",
            outline="",
        )
        ratio = self.LIST_HEIGHT / self.scroller.content_height
        thumb_height = max(int(self.LIST_HEIGHT * ratio), 32)
        travel = self.LIST_HEIGHT - thumb_height
        thumb_top = int(travel * self.scroller.offset / self.scroller.max_offset)
        self.list_canvas.create_rectangle(
            track_left,
            thumb_top,
            self.LIST_WIDTH,
            thumb_top + thumb_height,
            fill=self.BLUE,
            outline="",
        )

    @staticmethod
    def _event_point(event: tk.Event) -> tuple[int, int]:
        return int(event.x), int(event.y)

    def _handle_header_press(self, event: tk.Event) -> str:
        self._header_press = self._event_point(event)
        return "break"

    def _handle_header_release(self, event: tk.Event) -> str:
        point = self._event_point(event)
        start = self._header_press
        self._header_press = None
        if start is not None and self._is_tap(start, point):
            if self._adding:
                for action, bounds in tuple(self._editor_actions.items()):
                    if self._point_in_bounds(point, bounds):
                        self._handle_editor_action(action)
                        return "break"
                if self._point_in_bounds(point, self.BACK_BOUNDS):
                    self._close_add_editor()
                return "break"
            if self._point_in_bounds(point, self.BACK_BOUNDS):
                self.close()
            elif self._point_in_bounds(point, self.ADD_BOUNDS):
                self._show_add_editor()
        return "break"

    def _show_add_editor(self) -> None:
        self._adding = True
        self._duration_draft = TimerDurationDraft()
        self.list_canvas.place_forget()
        self._draw_add_editor()

    def _draw_add_editor(self) -> None:
        self.canvas.delete("timer-editor")
        self._editor_actions.clear()
        self.canvas.create_text(
            400,
            104,
            text="SET A NEW TIMER",
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 24, "bold"),
            tags=("timer-editor",),
        )
        for index, (field, label) in enumerate(
            (("hours", "HOURS"), ("minutes", "MINUTES"), ("seconds", "SECONDS"))
        ):
            center = 190 + index * 210
            value = getattr(self._duration_draft, field)
            self.canvas.create_text(
                center,
                213,
                text=f"{value:02d}",
                fill=self.NAVY,
                font=("Arial Rounded MT Bold", 42, "bold"),
                tags=("timer-editor",),
            )
            self.canvas.create_text(
                center,
                256,
                text=label,
                fill=self.MUTED,
                font=("Arial", 10, "bold"),
                tags=("timer-editor",),
            )
            self._draw_editor_button(
                f"{field}:-1",
                (center - 77, 282, center - 7, 344),
                "−",
                self.BLUE,
            )
            self._draw_editor_button(
                f"{field}:1",
                (center + 7, 282, center + 77, 344),
                "+",
                self.BLUE,
            )
        self._draw_editor_button("cancel", (168, 382, 382, 454), "CANCEL", self.NAVY)
        self._draw_editor_button(
            "save",
            (418, 382, 632, 454),
            "START TIMER",
            self.GREEN if self._duration_draft.total_seconds else self.MUTED,
        )

    def _draw_editor_button(
        self,
        action: str,
        bounds: tuple[int, int, int, int],
        label: str,
        color: str,
    ) -> None:
        self._editor_actions[action] = bounds
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=color,
            outline=self.WHITE,
            width=2,
            tags=("timer-editor",),
        )
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text=label,
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 13, "bold"),
            tags=("timer-editor",),
        )

    def _handle_editor_action(self, action: str) -> None:
        if action == "cancel":
            self._close_add_editor()
            return
        if action == "save":
            seconds = self._duration_draft.total_seconds
            if seconds and self.create_timer(float(seconds)):
                self._close_add_editor()
            return
        field, separator, amount = action.partition(":")
        if separator:
            self._duration_draft = self._duration_draft.adjusted(field, int(amount))
            self._draw_add_editor()

    def _close_add_editor(self) -> None:
        self._adding = False
        self.canvas.delete("timer-editor")
        self._editor_actions.clear()
        self.list_canvas.place(
            x=self.LIST_LEFT,
            y=self.LIST_TOP,
            width=self.LIST_WIDTH,
            height=self.LIST_HEIGHT,
        )
        self._refresh_items_now()

    def _handle_list_press(self, event: tk.Event) -> str:
        point = self._event_point(event)
        self._list_press_x = point[0]
        self.scroller.press(point[1])
        return "break"

    def _handle_list_motion(self, event: tk.Event) -> str:
        if self.scroller.drag(int(event.y)):
            self._draw_list()
        return "break"

    def _handle_list_release(self, event: tk.Event) -> str:
        point = self._event_point(event)
        start_x = self._list_press_x
        self._list_press_x = None
        is_tap = self.scroller.release(point[1])
        self._draw_list()
        if is_tap and start_x is not None and abs(start_x - point[0]) <= 18:
            for timer_id, bounds in tuple(self._delete_bounds.items()):
                if self._point_in_bounds(point, bounds):
                    self.cancel_timer(timer_id)
                    self._refresh_items_now()
                    break
        return "break"

    def _handle_mouse_wheel(self, event: tk.Event) -> str:
        direction = -1 if int(event.delta) > 0 else 1
        if self.scroller.scroll_by(direction * self.ROW_STRIDE):
            self._draw_list()
        return "break"

    def _refresh_items_now(self) -> None:
        self._items = tuple(self.timer_provider())
        content_height = (
            len(self._items) * self.ROW_STRIDE - self.ROW_GAP
            if self._items
            else 0
        )
        self.scroller.set_content_height(content_height)
        self._draw_list()
        self.canvas.itemconfigure(
            self.count_item,
            text=f"{len(self._items)} ACTIVE",
        )

    @staticmethod
    def _point_in_bounds(
        point: tuple[int, int],
        bounds: tuple[int, int, int, int],
    ) -> bool:
        left, top, right, bottom = bounds
        return left <= point[0] <= right and top <= point[1] <= bottom

    @staticmethod
    def _is_tap(start: tuple[int, int], end: tuple[int, int]) -> bool:
        return abs(start[0] - end[0]) <= 18 and abs(start[1] - end[1]) <= 18

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
            self.refresh_after_id = None
        self.compact_face.destroy()
        self.list_canvas.destroy()
        self.canvas.destroy()
        self.on_close()
