"""Touch-friendly, menu-launched countdown timer view."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math
import tkinter as tk


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480


@dataclass(frozen=True)
class TimerViewItem:
    """Display-only snapshot of one active countdown timer."""

    timer_id: int
    label: str | None
    remaining_seconds: float


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


class VerticalScrollController:
    """Track a finger-driven vertical list offset independently from Tk."""

    def __init__(self, viewport_height: int, *, tap_slop: int = 18) -> None:
        if viewport_height <= 0:
            raise ValueError("Viewport height must be positive.")
        if tap_slop < 0:
            raise ValueError("Tap slop cannot be negative.")
        self.viewport_height = viewport_height
        self.tap_slop = tap_slop
        self.content_height = 0
        self.offset = 0.0
        self._start_y: int | None = None
        self._last_y: int | None = None
        self._dragging = False

    @property
    def max_offset(self) -> float:
        return float(max(self.content_height - self.viewport_height, 0))

    def set_content_height(self, height: int) -> None:
        self.content_height = max(int(height), 0)
        self.offset = min(max(self.offset, 0.0), self.max_offset)

    def press(self, y: int) -> None:
        self._start_y = int(y)
        self._last_y = int(y)
        self._dragging = False

    def drag(self, y: int) -> bool:
        """Move content with the finger and return whether redraw is needed."""
        if self._last_y is None or self._start_y is None:
            return False
        current_y = int(y)
        if abs(current_y - self._start_y) > self.tap_slop:
            self._dragging = True
        previous_offset = self.offset
        self.offset = min(
            max(self.offset + self._last_y - current_y, 0.0),
            self.max_offset,
        )
        self._last_y = current_y
        return not math.isclose(previous_offset, self.offset)

    def release(self, y: int) -> bool:
        """Finish the gesture and return true only for an undragged tap."""
        if self._start_y is None:
            return False
        self.drag(y)
        is_tap = not self._dragging
        self._start_y = None
        self._last_y = None
        self._dragging = False
        return is_tap

    def scroll_by(self, pixels: float) -> bool:
        previous_offset = self.offset
        self.offset = min(
            max(self.offset + pixels, 0.0),
            self.max_offset,
        )
        return not math.isclose(previous_offset, self.offset)


TimerProvider = Callable[[], Iterable[TimerViewItem]]
TimerCanceller = Callable[[int], bool]


class TimerApp:
    """Show live active timers and allow touch deletion and scrolling."""

    BACKGROUND = "#e7f7ff"
    NAVY = "#102a5e"
    BLUE = "#1578d3"
    WHITE = "#ffffff"
    MUTED = "#58708c"
    DANGER = "#c83a4a"

    LIST_LEFT = 24
    LIST_TOP = 76
    LIST_WIDTH = 752
    LIST_HEIGHT = 380
    ROW_HEIGHT = 78
    ROW_GAP = 10
    ROW_STRIDE = ROW_HEIGHT + ROW_GAP
    REFRESH_MS = 250
    BACK_BOUNDS = (638, 10, 784, 51)

    def __init__(
        self,
        root: tk.Misc,
        *,
        timer_provider: TimerProvider,
        cancel_timer: TimerCanceller,
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.timer_provider = timer_provider
        self.cancel_timer = cancel_timer
        self.on_close = on_close
        self.closed = False
        self.refresh_after_id: str | None = None
        self._header_press: tuple[int, int] | None = None
        self._list_press_x: int | None = None
        self._items: tuple[TimerViewItem, ...] = ()
        self._delete_bounds: dict[int, tuple[int, int, int, int]] = {}
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
            if self._point_in_bounds(point, self.BACK_BOUNDS):
                self.close()
        return "break"

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
        self.list_canvas.destroy()
        self.canvas.destroy()
        self.on_close()
