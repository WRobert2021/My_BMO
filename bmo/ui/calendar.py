"""Touch-friendly day, month, year, and event-editor calendar views."""

from __future__ import annotations

import calendar
from collections.abc import Callable, Iterable
from datetime import date, time, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Literal

from PIL import Image

from bmo.features.calendar_view import CalendarEdit, CalendarViewEvent
from bmo.ui.compact_face import CompactFace
from bmo.ui.scrolling import VerticalScrollController


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480

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
BACKGROUND = "#EAF8F8"
INK = "#16324F"
MUTED = "#5D7185"
WHITE = "#FFFFFF"
NAVY = "#12325B"
TEAL = "#087B79"
BLUE = "#376FBA"
RED = "#B93643"
MONTH_COLORS = (
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


EventProvider = Callable[[date, date], Iterable[CalendarViewEvent]]
EventSaver = Callable[
    [CalendarEdit, CalendarViewEvent | None, Literal["occurrence", "series"]],
    None,
]
EventDeleter = Callable[
    [CalendarViewEvent, Literal["occurrence", "series"]],
    None,
]
SummaryProvider = Callable[[date, date], str]
Announcement = Callable[[str, Callable[[], None] | None], bool]


def month_dot_positions(
    left: float,
    top: float,
    right: float,
    bottom: float,
    event_count: int,
) -> tuple[tuple[float, float], ...]:
    """Return bounded month-dot centers, starting beside the day number."""
    if event_count <= 0:
        return ()
    radius = 4
    step_x = 13
    step_y = 14
    positions = []
    for column in range(4):
        x_value = left + 43 + column * step_x
        if x_value + radius <= right - 5:
            positions.append((x_value, top + 12))
    y_value = top + 30
    while y_value + radius <= bottom - 5:
        x_value = left + 13
        while x_value + radius <= right - 5:
            positions.append((x_value, y_value))
            x_value += step_x
        y_value += step_y
    return tuple(positions[:event_count])


class CalendarApp:
    """Render an 800x480 calendar above its originating touch menu."""

    DAY_LIST_TOP = 112
    DAY_LIST_HEIGHT = 292
    DAY_ROW_HEIGHT = 64
    DAY_ROW_GAP = 8
    DAY_ROW_STRIDE = DAY_ROW_HEIGHT + DAY_ROW_GAP
    def __init__(
        self,
        root: tk.Misc,
        *,
        event_provider: EventProvider,
        save_event: EventSaver,
        delete_event: EventDeleter,
        summary_provider: SummaryProvider,
        categories: tuple[str, ...],
        face_provider: Callable[[], Image.Image | None],
        announce: Announcement,
        on_close: Callable[[], None],
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self.root = root
        self.event_provider = event_provider
        self.save_event = save_event
        self.delete_event = delete_event
        self.summary_provider = summary_provider
        self.categories = categories
        self.announce = announce
        self.on_close = on_close
        self.today_provider = today_provider
        self.selected_date = today_provider()
        self.visible_month = self.selected_date.replace(day=1)
        self.visible_year = self.selected_date.year
        self.closed = False
        self.view = "day"
        self._controls: list[tk.Widget] = []
        self._actions: list[tuple[tuple[int, int, int, int], Callable[[], None]]] = []
        self._day_events: tuple[CalendarViewEvent, ...] = ()
        self._day_event_bounds: list[tuple[tuple[int, int, int, int], CalendarViewEvent]] = []
        self._month_day_bounds: list[tuple[tuple[int, int, int, int], date]] = []
        self._year_month_bounds: list[tuple[tuple[int, int, int, int], int]] = []
        self._editor_event: CalendarViewEvent | None = None
        self._editor_color = BLUE
        self.scroller = VerticalScrollController(self.DAY_LIST_HEIGHT)
        self.day_canvas: tk.Canvas | None = None

        self.canvas = tk.Canvas(
            root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=BACKGROUND,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        self.canvas.bind("<ButtonPress-1>", self._handle_press)
        self.canvas.bind("<B1-Motion>", self._handle_motion)
        self.canvas.bind("<ButtonRelease-1>", self._handle_release)
        self.canvas.bind("<MouseWheel>", self._handle_mouse_wheel)
        self._press_point: tuple[int, int] | None = None
        self.compact_face = CompactFace(
            root,
            self.canvas,
            face_provider=face_provider,
            auto_mount=False,
        )
        self._show_day()

    @staticmethod
    def _font(size: int, *, bold: bool = False) -> tuple[str, int, str]:
        return ("Arial Rounded MT Bold", size, "bold" if bold else "normal")

    @staticmethod
    def _contains(bounds: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
        left, top, right, bottom = bounds
        return left <= point[0] <= right and top <= point[1] <= bottom

    @staticmethod
    def _contrast(color: str) -> str:
        try:
            red, green, blue = (
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
            )
        except (ValueError, TypeError):
            return WHITE
        return INK if 0.299 * red + 0.587 * green + 0.114 * blue > 165 else WHITE

    def _clear_view(self) -> None:
        self.compact_face.unmount()
        if self.day_canvas is not None:
            self.day_canvas.destroy()
            self.day_canvas = None
        self.canvas.delete("all")
        for control in self._controls:
            control.destroy()
        self._controls.clear()
        self._actions.clear()
        self._day_event_bounds.clear()
        self._month_day_bounds.clear()
        self._year_month_bounds.clear()

    def _draw_button(
        self,
        bounds: tuple[int, int, int, int],
        text: str,
        action: Callable[[], None],
        *,
        color: str = NAVY,
        font_size: int = 9,
    ) -> None:
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(*bounds, fill=color, outline=WHITE, width=2)
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text=text,
            fill=self._contrast(color),
            justify=tk.CENTER,
            font=self._font(font_size, bold=True),
        )
        self._actions.append((bounds, action))

    def _draw_header(
        self,
        title: str,
        subtitle: str,
        level_actions: tuple[tuple[str, Callable[[], None]], ...] = (),
    ) -> None:
        accent = MONTH_COLORS[self.selected_date.month - 1]
        self.canvas.create_rectangle(0, 0, 800, 64, fill=accent, outline="")
        self.canvas.create_text(
            18,
            10,
            anchor="nw",
            text=title,
            fill=WHITE,
            font=self._font(19, bold=True),
        )
        self.canvas.create_text(
            20,
            42,
            anchor="w",
            text=subtitle,
            fill=WHITE,
            font=self._font(8, bold=True),
        )
        x_value = 354
        for label, action in level_actions:
            self._draw_button((x_value, 10, x_value + 76, 53), label, action, font_size=8)
            x_value += 82
        self._draw_button((x_value, 10, x_value + 68, 53), "TODAY", self._go_today, color=TEAL, font_size=8)
        x_value += 74
        self._draw_button((x_value, 10, x_value + 62, 53), "MENU", self.close, font_size=8)
        self.compact_face.mount()

    def _show_day(self) -> None:
        self.view = "day"
        self._clear_view()
        self._draw_header(
            "BMO CALENDAR",
            self.selected_date.strftime("DAY VIEW  •  %B %Y").upper(),
            (("MONTH", self._show_month), ("YEAR", self._show_year)),
        )
        self.day_canvas = tk.Canvas(
            self.root,
            width=560,
            height=self.DAY_LIST_HEIGHT,
            bg=BACKGROUND,
            highlightthickness=0,
        )
        self.day_canvas.place(
            x=222,
            y=self.DAY_LIST_TOP,
            width=560,
            height=self.DAY_LIST_HEIGHT,
        )
        self.day_canvas.bind("<ButtonPress-1>", self._handle_day_press)
        self.day_canvas.bind("<B1-Motion>", self._handle_day_motion)
        self.day_canvas.bind("<ButtonRelease-1>", self._handle_day_release)
        self.day_canvas.bind("<MouseWheel>", self._handle_day_mouse_wheel)
        accent = MONTH_COLORS[self.selected_date.month - 1]
        self.canvas.create_rectangle(16, 76, 206, 404, fill=accent, outline="")
        self.canvas.create_text(
            111,
            100,
            text=self.selected_date.strftime("%A").upper(),
            fill=WHITE,
            font=self._font(14, bold=True),
        )
        self.canvas.create_text(
            111,
            174,
            text=str(self.selected_date.day),
            fill=WHITE,
            font=self._font(65, bold=True),
        )
        self.canvas.create_text(
            111,
            235,
            text=self.selected_date.strftime("%B").upper(),
            fill=WHITE,
            font=self._font(17, bold=True),
        )
        # Today lives in the header; day navigation always remains two arrows.
        self._draw_button((38, 286, 101, 344), "‹", lambda: self._move_day(-1), font_size=22)
        self._draw_button((121, 286, 184, 344), "›", lambda: self._move_day(1), font_size=22)

        self._day_events = tuple(self.event_provider(self.selected_date, self.selected_date))
        self.canvas.create_text(
            226,
            82,
            anchor="nw",
            text=f"{len(self._day_events)} SCHEDULED ITEM{'S' if len(self._day_events) != 1 else ''}",
            fill=INK,
            font=self._font(13, bold=True),
        )
        content_height = max(
            len(self._day_events) * self.DAY_ROW_STRIDE - self.DAY_ROW_GAP,
            0,
        )
        self.scroller.set_content_height(content_height)
        self._draw_day_rows()
        self._draw_button((16, 420, 166, 466), "+ ADD EVENT", self._show_new_event, color=TEAL)
        self._draw_button((178, 420, 358, 466), "ASK BMO SUMMARY", self._speak_day_summary, color=BLUE)

    def _draw_day_rows(self) -> None:
        target = self.day_canvas
        if target is None:
            return
        target.delete("all")
        self._day_event_bounds.clear()
        if not self._day_events:
            target.create_rectangle(
                0,
                0,
                560,
                self.DAY_LIST_HEIGHT,
                fill=WHITE,
                outline="#A9CACA",
                width=2,
            )
            target.create_text(
                280,
                self.DAY_LIST_HEIGHT // 2,
                text="A WIDE-OPEN DAY!\nAdd something worth looking forward to.",
                fill=INK,
                justify=tk.CENTER,
                font=self._font(15, bold=True),
            )
            return
        for index, event in enumerate(self._day_events):
            top = int(index * self.DAY_ROW_STRIDE - self.scroller.offset)
            bottom = top + self.DAY_ROW_HEIGHT
            if bottom < 0 or top > self.DAY_LIST_HEIGHT:
                continue
            visible_top = max(top, 0)
            visible_bottom = min(bottom, self.DAY_LIST_HEIGHT)
            bounds = (0, visible_top, 548, visible_bottom)
            target.create_rectangle(
                0,
                top,
                548,
                bottom,
                fill=WHITE,
                outline="#A9CACA",
                width=2,
            )
            target.create_rectangle(
                0,
                top,
                12,
                bottom,
                fill=event.color,
                outline="",
            )
            target.create_text(
                26,
                top + 15,
                anchor="w",
                text=event.name,
                width=360,
                fill=INK,
                font=self._font(12, bold=True),
            )
            target.create_text(
                26,
                top + 44,
                anchor="w",
                text=f"{event.category}  •  {self._format_event_time(event)}",
                fill=MUTED,
                font=self._font(9),
            )
            target.create_text(
                516,
                top + 32,
                text="VIEW" if event.read_only else "EDIT",
                fill=event.color,
                font=self._font(9, bold=True),
            )
            self._day_event_bounds.append((bounds, event))
        if self.scroller.max_offset > 0:
            ratio = self.DAY_LIST_HEIGHT / self.scroller.content_height
            thumb_height = max(int(self.DAY_LIST_HEIGHT * ratio), 30)
            travel = self.DAY_LIST_HEIGHT - thumb_height
            thumb_top = int(travel * self.scroller.offset / self.scroller.max_offset)
            target.create_rectangle(
                552,
                0,
                560,
                self.DAY_LIST_HEIGHT,
                fill="#CBE1E1",
                outline="",
            )
            target.create_rectangle(
                552,
                thumb_top,
                560,
                thumb_top + thumb_height,
                fill=TEAL,
                outline="",
            )

    @staticmethod
    def _format_event_time(event: CalendarViewEvent) -> str:
        if event.all_day:
            return "ALL DAY"
        assert event.start_time is not None
        start = event.start_time.strftime("%I:%M %p").lstrip("0")
        if event.end_time is None:
            return start
        end = event.end_time.strftime("%I:%M %p").lstrip("0")
        return f"{start} – {end}"

    def _move_day(self, amount: int) -> None:
        self.selected_date += timedelta(days=amount)
        self.visible_month = self.selected_date.replace(day=1)
        self.visible_year = self.selected_date.year
        self.scroller.offset = 0
        self._show_day()

    def _show_month(self) -> None:
        self.view = "month"
        self._clear_view()
        self.selected_date = self.visible_month
        self._draw_header(
            self.visible_month.strftime("%B %Y").upper(),
            "MONTH VIEW  •  TAP A DAY TO OPEN IT",
            (("YEAR", self._show_year),),
        )
        self._draw_button((18, 73, 132, 112), "‹ MONTH", lambda: self._move_month(-1))
        self._draw_button((142, 73, 256, 112), "MONTH ›", lambda: self._move_month(1))
        grid_left, grid_top, grid_right, grid_bottom = 18, 120, 782, 466
        self.canvas.create_rectangle(
            grid_left,
            grid_top,
            grid_right,
            grid_bottom,
            fill=WHITE,
            outline="#A9CACA",
        )
        cell_width = (grid_right - grid_left) / 7
        header_height = 30
        row_height = (grid_bottom - grid_top - header_height) / 6
        accent = MONTH_COLORS[self.visible_month.month - 1]
        for index, name in enumerate(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")):
            self.canvas.create_text(
                grid_left + index * cell_width + cell_width / 2,
                grid_top + 15,
                text=name,
                fill=accent,
                font=self._font(8, bold=True),
            )
        weeks = calendar.Calendar(firstweekday=calendar.MONDAY).monthdatescalendar(
            self.visible_month.year,
            self.visible_month.month,
        )
        while len(weeks) < 6:
            last = weeks[-1][-1]
            weeks.append([last + timedelta(days=index) for index in range(1, 8)])
        query_start, query_end = weeks[0][0], weeks[5][-1]
        event_map: dict[date, list[CalendarViewEvent]] = {}
        for event in self.event_provider(query_start, query_end):
            event_map.setdefault(event.occurrence_date, []).append(event)
        today = self.today_provider()
        for row_index, week in enumerate(weeks[:6]):
            for column_index, cell_date in enumerate(week):
                left = grid_left + column_index * cell_width
                top = grid_top + header_height + row_index * row_height
                right = left + cell_width
                bottom = top + row_height
                in_month = cell_date.month == self.visible_month.month
                fill = "#FFF1B8" if cell_date == today else (WHITE if in_month else "#EEF3F3")
                self.canvas.create_rectangle(left, top, right, bottom, fill=fill, outline="#D3E1E1")
                self.canvas.create_text(
                    left + 9,
                    top + 7,
                    anchor="nw",
                    text=str(cell_date.day),
                    fill=INK if in_month else "#94A5A9",
                    font=self._font(9, bold=in_month),
                )
                events = event_map.get(cell_date, [])
                positions = month_dot_positions(left, top, right, bottom, len(events))
                visible_count = len(positions)
                overflow = len(events) - visible_count
                if overflow and visible_count:
                    visible_count -= 1
                    overflow += 1
                for event, (x_value, y_value) in zip(events[:visible_count], positions):
                    self.canvas.create_oval(
                        x_value - 4,
                        y_value - 4,
                        x_value + 4,
                        y_value + 4,
                        fill=event.color,
                        outline="",
                    )
                if overflow and positions:
                    x_value, y_value = positions[visible_count]
                    self.canvas.create_text(
                        x_value,
                        y_value,
                        text=f"+{overflow}",
                        fill=MUTED,
                        font=self._font(7, bold=True),
                    )
                self._month_day_bounds.append(
                    ((int(left), int(top), int(right), int(bottom)), cell_date)
                )

    def _move_month(self, amount: int) -> None:
        index = self.visible_month.year * 12 + self.visible_month.month - 1 + amount
        year, month_zero = divmod(index, 12)
        self.visible_month = date(year, month_zero + 1, 1)
        self.visible_year = year
        self._show_month()

    def _show_year(self) -> None:
        self.view = "year"
        self._clear_view()
        self.selected_date = date(self.visible_year, 1, 1)
        self._draw_header(str(self.visible_year), "YEAR VIEW  •  TAP A MONTH TO OPEN IT")
        self._draw_button((18, 73, 126, 112), "‹ YEAR", lambda: self._move_year(-1))
        self._draw_button((136, 73, 244, 112), "YEAR ›", lambda: self._move_year(1))
        occurrences = tuple(
            self.event_provider(date(self.visible_year, 1, 1), date(self.visible_year, 12, 31))
        )
        counts = {
            month: sum(1 for item in occurrences if item.occurrence_date.month == month)
            for month in range(1, 13)
        }
        for month_number in range(1, 13):
            row, column = divmod(month_number - 1, 4)
            left = 18 + column * 191
            top = 122 + row * 111
            right = left + 180
            bottom = top + 99
            color = MONTH_COLORS[month_number - 1]
            self.canvas.create_rectangle(left, top, right, bottom, fill=color, outline=WHITE, width=3)
            self.canvas.create_text(
                (left + right) // 2,
                top + 29,
                text=calendar.month_abbr[month_number].upper(),
                fill=self._contrast(color),
                font=self._font(16, bold=True),
            )
            count = counts[month_number]
            self.canvas.create_text(
                (left + right) // 2,
                top + 61,
                text=f"{count} event{'s' if count != 1 else ''}",
                fill=self._contrast(color),
                font=self._font(9, bold=True),
            )
            self._year_month_bounds.append(((left, top, right, bottom), month_number))

    def _move_year(self, amount: int) -> None:
        self.visible_year += amount
        self._show_year()

    def _go_today(self) -> None:
        self.selected_date = self.today_provider()
        self.visible_month = self.selected_date.replace(day=1)
        self.visible_year = self.selected_date.year
        self.scroller.offset = 0
        self._show_day()

    def _show_new_event(self) -> None:
        self._show_editor(None)

    def _show_editor(self, event: CalendarViewEvent | None) -> None:
        self.view = "editor"
        self._editor_event = event
        self._editor_color = event.color if event else BLUE
        self._clear_view()
        self._draw_header(
            "VIEW EVENT" if event and event.read_only else ("EDIT EVENT" if event else "ADD EVENT"),
            (event.occurrence_date if event else self.selected_date).strftime("%A, %B %d, %Y").upper(),
            (("CANCEL", self._show_day),),
        )
        read_only = bool(event and event.read_only)
        self._editor_read_only = read_only
        self.name_var = tk.StringVar(value=event.name if event else "")
        self.category_var = tk.StringVar(value=event.category if event else self.categories[0])
        self.date_var = tk.StringVar(value=(event.occurrence_date if event else self.selected_date).isoformat())
        self.all_day_var = tk.BooleanVar(value=event.all_day if event else False)
        self.start_var = tk.StringVar(value=self._time_entry(event.start_time if event else time(9)))
        self.end_var = tk.StringVar(value=self._time_entry(event.end_time if event else time(10)))
        self.frequency_var = tk.StringVar(value=event.frequency if event else "none")
        self.repeat_end_kind_var = tk.StringVar(
            value="On date" if event and event.recurrence_end_date else ("After count" if event and event.recurrence_count else "Never")
        )
        self.repeat_end_value_var = tk.StringVar(
            value=(
                event.recurrence_end_date.isoformat()
                if event and event.recurrence_end_date
                else str(event.recurrence_count or "") if event else ""
            )
        )
        self.overflow_var = tk.StringVar(value=event.monthly_overflow if event else "last_day")
        self.weekday_vars = {
            weekday: tk.BooleanVar(value=bool(event and weekday in event.weekdays))
            for weekday in range(7)
        }
        self._label("EVENT NAME", 18, 77)
        self.name_entry = self._entry(self.name_var, 18, 98, 360, 34, read_only)
        self._label("CATEGORY", 18, 139)
        self.category_box = self._combo(self.category_var, self.categories, 18, 160, 360, 34, read_only)
        self._label("DATE (YYYY-MM-DD)", 18, 201)
        self.date_entry = self._entry(self.date_var, 18, 222, 210, 34, read_only)
        self.all_day_check = tk.Checkbutton(
            self.root,
            text="ALL DAY",
            variable=self.all_day_var,
            bg=BACKGROUND,
            fg=INK,
            activebackground=BACKGROUND,
            font=self._font(9, bold=True),
            state=tk.DISABLED if read_only else tk.NORMAL,
        )
        self.all_day_check.place(x=244, y=221)
        self._controls.append(self.all_day_check)
        self._label("FROM", 18, 263)
        self._label("TO", 202, 263)
        self.start_entry = self._entry(self.start_var, 18, 284, 166, 34, read_only)
        self.end_entry = self._entry(self.end_var, 202, 284, 176, 34, read_only)
        self._label("EVENT COLOR", 18, 325)
        self.color_swatch = tk.Label(self.root, bg=self._editor_color, highlightbackground=INK, highlightthickness=2)
        self.color_swatch.place(x=18, y=347, width=54, height=35)
        self._controls.append(self.color_swatch)
        if not read_only:
            self._draw_button((84, 347, 378, 382), "CHOOSE FROM COLOR PALETTE…", self._choose_color)

        self._label("REPEAT", 410, 77)
        self.frequency_box = self._combo(
            self.frequency_var,
            ("none", "weekly", "monthly", "yearly"),
            410,
            98,
            370,
            34,
            read_only,
        )
        self.repeat_frame = tk.Frame(self.root, bg=BACKGROUND)
        self.repeat_frame.place(x=410, y=139, width=370, height=82)
        self._controls.append(self.repeat_frame)
        self._label("REPEAT ENDS", 410, 224)
        self.repeat_end_box = self._combo(
            self.repeat_end_kind_var,
            ("Never", "On date", "After count"),
            410,
            245,
            180,
            34,
            read_only,
        )
        self.repeat_end_entry = self._entry(
            self.repeat_end_value_var,
            602,
            245,
            178,
            34,
            read_only,
        )
        self._label("NOTES (NOT SPOKEN BY DEFAULT)", 410, 286)
        self.notes_text = tk.Text(
            self.root,
            wrap=tk.WORD,
            font=self._font(10),
            relief=tk.FLAT,
            highlightbackground="#9FC5C6",
            highlightthickness=2,
        )
        self.notes_text.place(x=410, y=307, width=370, height=75)
        self._controls.append(self.notes_text)
        if event:
            self.notes_text.insert("1.0", event.notes)
        if read_only:
            self.notes_text.configure(state=tk.DISABLED)
        else:
            self._draw_button((620, 417, 780, 466), "SAVE EVENT", self._save_editor, color=TEAL)
            if event:
                self._draw_button((472, 417, 610, 466), "DELETE", self._delete_editor, color=RED)
        self.frequency_var.trace_add("write", self._refresh_repeat_controls)
        self.all_day_var.trace_add("write", self._refresh_time_controls)
        self.repeat_end_kind_var.trace_add("write", self._refresh_repeat_end_control)
        self._refresh_repeat_controls()
        self._refresh_time_controls()
        self._refresh_repeat_end_control()

    def _label(self, text: str, x: int, y: int) -> None:
        label = tk.Label(self.root, text=text, bg=BACKGROUND, fg=INK, font=self._font(8, bold=True))
        label.place(x=x, y=y)
        self._controls.append(label)

    def _entry(
        self,
        variable: tk.StringVar,
        x: int,
        y: int,
        width: int,
        height: int,
        disabled: bool,
    ) -> tk.Entry:
        entry = tk.Entry(
            self.root,
            textvariable=variable,
            font=self._font(10),
            relief=tk.FLAT,
            highlightbackground="#9FC5C6",
            highlightthickness=2,
            state=tk.DISABLED if disabled else tk.NORMAL,
        )
        entry.place(x=x, y=y, width=width, height=height)
        self._controls.append(entry)
        return entry

    def _combo(
        self,
        variable: tk.StringVar,
        values: tuple[str, ...],
        x: int,
        y: int,
        width: int,
        height: int,
        disabled: bool,
    ) -> ttk.Combobox:
        combo = ttk.Combobox(
            self.root,
            textvariable=variable,
            values=values,
            state="disabled" if disabled else "readonly",
            font=self._font(9),
        )
        combo.place(x=x, y=y, width=width, height=height)
        self._controls.append(combo)
        return combo

    @staticmethod
    def _time_entry(value: time | None) -> str:
        return value.strftime("%H:%M") if value else ""

    def _choose_color(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Choose an event color")
        dialog.configure(bg=BACKGROUND)
        dialog.geometry("620x320")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(
            dialog,
            text="CHOOSE AN EVENT COLOR",
            bg=BACKGROUND,
            fg=INK,
            font=self._font(16, bold=True),
        ).pack(pady=(18, 10))
        grid = tk.Frame(dialog, bg=BACKGROUND)
        grid.pack(padx=18, pady=4, fill=tk.BOTH, expand=True)

        def choose(color: str) -> None:
            self._editor_color = color
            self.color_swatch.configure(bg=color)
            dialog.grab_release()
            dialog.destroy()

        for index, (name, color) in enumerate(CALENDAR_COLOR_PALETTE):
            button = tk.Button(
                grid,
                text=name.upper(),
                bg=color,
                fg=self._contrast(color),
                activebackground=color,
                activeforeground=self._contrast(color),
                command=lambda selected=color: choose(selected),
                font=self._font(9, bold=True),
                relief=tk.FLAT,
            )
            button.grid(
                row=index // 4,
                column=index % 4,
                padx=6,
                pady=6,
                sticky="nsew",
            )
        for column in range(4):
            grid.grid_columnconfigure(column, weight=1)
        for row in range(3):
            grid.grid_rowconfigure(row, weight=1)

    def _refresh_repeat_controls(self, *_args) -> None:
        for child in self.repeat_frame.winfo_children():
            child.destroy()
        frequency = self.frequency_var.get()
        if frequency == "weekly":
            tk.Label(
                self.repeat_frame,
                text="REPEAT ON",
                bg=BACKGROUND,
                fg=INK,
                font=self._font(8, bold=True),
            ).pack(anchor="w")
            row = tk.Frame(self.repeat_frame, bg=BACKGROUND)
            row.pack(anchor="w")
            for weekday, name in enumerate(("M", "T", "W", "T", "F", "S", "S")):
                tk.Checkbutton(
                    row,
                    text=name,
                    variable=self.weekday_vars[weekday],
                    bg=BACKGROUND,
                    activebackground=BACKGROUND,
                    font=self._font(8, bold=True),
                    state=tk.DISABLED if self._editor_read_only else tk.NORMAL,
                ).pack(side=tk.LEFT, padx=(0, 5))
        elif frequency == "monthly":
            tk.Label(
                self.repeat_frame,
                text="WHEN THIS DAY IS MISSING",
                bg=BACKGROUND,
                fg=INK,
                font=self._font(8, bold=True),
            ).pack(anchor="w")
            ttk.Combobox(
                self.repeat_frame,
                textvariable=self.overflow_var,
                values=("last_day", "skip"),
                state="disabled" if self._editor_read_only else "readonly",
                font=self._font(9),
            ).pack(fill=tk.X, pady=5)
        else:
            text = (
                "Repeats on this month and date each year."
                if frequency == "yearly"
                else "Repeat controls appear only when relevant."
            )
            tk.Label(
                self.repeat_frame,
                text=text,
                bg=BACKGROUND,
                fg=MUTED,
                font=self._font(9),
            ).pack(anchor="w", pady=18)
        repeat_state = "disabled" if frequency == "none" else "readonly"
        if self._editor_read_only:
            repeat_state = "disabled"
        self.repeat_end_box.configure(state=repeat_state)

    def _refresh_time_controls(self, *_args) -> None:
        disabled = self.all_day_var.get() or self._editor_read_only
        self.start_entry.configure(state=tk.DISABLED if disabled else tk.NORMAL)
        self.end_entry.configure(state=tk.DISABLED if disabled else tk.NORMAL)

    def _refresh_repeat_end_control(self, *_args) -> None:
        enabled = (
            not self._editor_read_only
            and
            self.frequency_var.get() != "none"
            and self.repeat_end_kind_var.get() != "Never"
        )
        self.repeat_end_entry.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _parse_editor(self) -> CalendarEdit | None:
        try:
            name = self.name_var.get().strip()
            if not name:
                raise ValueError("Please give the event a name.")
            start_date = date.fromisoformat(self.date_var.get().strip())
            all_day = self.all_day_var.get()
            start_time = None if all_day else time.fromisoformat(self.start_var.get().strip())
            end_text = self.end_var.get().strip()
            end_time = None if all_day or not end_text else time.fromisoformat(end_text)
            if start_time and end_time and end_time <= start_time:
                raise ValueError("The end time must be after the start time.")
            frequency = self.frequency_var.get()
            weekdays = (
                tuple(day for day, variable in self.weekday_vars.items() if variable.get())
                if frequency == "weekly"
                else ()
            )
            if frequency == "weekly" and not weekdays:
                weekdays = (start_date.weekday(),)
            end_kind = self.repeat_end_kind_var.get()
            recurrence_end_date = None
            recurrence_count = None
            if frequency != "none" and end_kind == "On date":
                recurrence_end_date = date.fromisoformat(self.repeat_end_value_var.get().strip())
                if recurrence_end_date < start_date:
                    raise ValueError("The repeat end date cannot precede the event.")
            elif frequency != "none" and end_kind == "After count":
                recurrence_count = int(self.repeat_end_value_var.get().strip())
                if recurrence_count < 1:
                    raise ValueError("The repeat count must be positive.")
            return CalendarEdit(
                name=name,
                start_date=start_date,
                all_day=all_day,
                start_time=start_time,
                end_time=end_time,
                color=self._editor_color,
                category=self.category_var.get(),
                notes=self.notes_text.get("1.0", tk.END).strip(),
                frequency=frequency,
                weekdays=weekdays,
                recurrence_end_date=recurrence_end_date,
                recurrence_count=recurrence_count,
                monthly_overflow=self.overflow_var.get(),
            )
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Check this event", str(exc), parent=self.root)
            return None

    def _save_editor(self) -> None:
        edit = self._parse_editor()
        if edit is None:
            return
        event = self._editor_event
        if event is not None and event.frequency != "none":
            self._choose_scope(
                "Apply this edit to…",
                lambda scope: self._save_with_scope(edit, event, scope),
            )
        else:
            self._save_with_scope(edit, event, "series")

    def _save_with_scope(
        self,
        edit: CalendarEdit,
        event: CalendarViewEvent | None,
        scope: Literal["occurrence", "series"],
    ) -> None:
        try:
            self.save_event(edit, event, scope)
        except Exception as exc:
            messagebox.showerror("Could not save", str(exc), parent=self.root)
            return
        self.selected_date = edit.start_date
        self.visible_month = edit.start_date.replace(day=1)
        self.visible_year = edit.start_date.year
        self._show_day()

    def _delete_editor(self) -> None:
        event = self._editor_event
        if event is None:
            return
        if event.frequency != "none":
            self._choose_scope(
                "Delete from…",
                lambda scope: self._delete_with_scope(event, scope),
            )
        elif messagebox.askyesno(
            "Delete event?",
            f'Delete “{event.name}”?',
            parent=self.root,
        ):
            self._delete_with_scope(event, "series")

    def _delete_with_scope(
        self,
        event: CalendarViewEvent,
        scope: Literal["occurrence", "series"],
    ) -> None:
        try:
            self.delete_event(event, scope)
        except Exception as exc:
            messagebox.showerror("Could not delete", str(exc), parent=self.root)
            return
        self._show_day()

    def _choose_scope(
        self,
        title: str,
        callback: Callable[[Literal["occurrence", "series"]], None],
    ) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("520x205")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=BACKGROUND)
        tk.Label(
            dialog,
            text=title,
            bg=BACKGROUND,
            fg=INK,
            font=self._font(17, bold=True),
        ).pack(pady=(23, 10))
        tk.Label(
            dialog,
            text="This item belongs to a repeating series.",
            bg=BACKGROUND,
            fg=MUTED,
            font=self._font(10),
        ).pack(pady=(0, 22))
        row = tk.Frame(dialog, bg=BACKGROUND)
        row.pack()

        def choose(scope: Literal["occurrence", "series"]) -> None:
            dialog.grab_release()
            dialog.destroy()
            callback(scope)

        for text, scope, color in (
            ("ONLY THIS OCCURRENCE", "occurrence", BLUE),
            ("ENTIRE SERIES", "series", RED),
        ):
            label = tk.Label(
                row,
                text=text,
                bg=color,
                fg=self._contrast(color),
                padx=12,
                pady=12,
                cursor="hand2",
                font=self._font(9, bold=True),
            )
            label.pack(side=tk.LEFT, padx=6)
            label.bind("<Button-1>", lambda _event, selected=scope: choose(selected))

    def _speak_day_summary(self) -> None:
        text = self.summary_provider(self.selected_date, self.selected_date)
        self.announce(text, None)

    def _handle_press(self, event: tk.Event) -> str:
        point = int(event.x), int(event.y)
        self._press_point = point
        return "break"

    def _handle_motion(self, event: tk.Event) -> str:
        return "break"

    def _handle_release(self, event: tk.Event) -> str:
        point = int(event.x), int(event.y)
        press = self._press_point
        self._press_point = None
        if press is None:
            return "break"
        if abs(point[0] - press[0]) > 20 or abs(point[1] - press[1]) > 20:
            return "break"
        for bounds, action in reversed(self._actions):
            if self._contains(bounds, point):
                action()
                return "break"
        if self.view == "month":
            for bounds, selected in self._month_day_bounds:
                if self._contains(bounds, point):
                    self.selected_date = selected
                    self.visible_month = selected.replace(day=1)
                    self.visible_year = selected.year
                    self.scroller.offset = 0
                    self._show_day()
                    break
        elif self.view == "year":
            for bounds, month_number in self._year_month_bounds:
                if self._contains(bounds, point):
                    self.visible_month = date(self.visible_year, month_number, 1)
                    self.selected_date = self.visible_month
                    self._show_month()
                    break
        return "break"

    def _handle_mouse_wheel(self, event: tk.Event) -> str:
        return "break"

    def _handle_day_press(self, event: tk.Event) -> str:
        self._press_point = int(event.x), int(event.y)
        self.scroller.press(int(event.y))
        return "break"

    def _handle_day_motion(self, event: tk.Event) -> str:
        if self.scroller.drag(int(event.y)):
            self._draw_day_rows()
        return "break"

    def _handle_day_release(self, event: tk.Event) -> str:
        point = int(event.x), int(event.y)
        press = self._press_point
        self._press_point = None
        if press is None:
            return "break"
        if not self.scroller.release(point[1]):
            self._draw_day_rows()
            return "break"
        for bounds, selected in self._day_event_bounds:
            if self._contains(bounds, point):
                self._show_editor(selected)
                break
        return "break"

    def _handle_day_mouse_wheel(self, event: tk.Event) -> str:
        if self.scroller.scroll_by(-float(event.delta) / 3):
            self._draw_day_rows()
        return "break"

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.compact_face.destroy()
        for control in self._controls:
            control.destroy()
        self._controls.clear()
        if self.day_canvas is not None:
            self.day_canvas.destroy()
            self.day_canvas = None
        self.canvas.destroy()
        self.on_close()
