"""Legacy Tk fallback for the menu-launched alarm clock."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
import tkinter as tk
from typing import Any

from bmo.features.alarm_clock import format_alarm_time
from bmo.features.alarm_store import AlarmRecord, AlarmState
from bmo.features.alarm_view import AlarmViewItem
from bmo.ui.compact_face import CompactFace


class AlarmClockApp:
    """Touch-first alarm controls for the explicit Tk fallback launcher."""

    def __init__(
        self,
        root: tk.Misc,
        *,
        alarm_provider: Callable[[], Iterable[AlarmViewItem]],
        alarm_lookup: Callable[[int], AlarmRecord | None],
        create_alarm: Callable[[int, int, str, tuple[int, ...]], int | None],
        update_alarm: Callable[[int, int, int, str, tuple[int, ...]], bool],
        delete_alarm: Callable[[int], bool],
        toggle_alarm: Callable[[int, bool], bool],
        snooze_alarm: Callable[[int], bool],
        dismiss_alarm: Callable[[int], bool],
        set_24_hour: Callable[[bool], bool],
        now: Callable[[], datetime],
        state_provider: Callable[[], AlarmState],
        snooze_minutes: int,
        read_only: bool,
        storage_error: str,
        on_close: Callable[[], None],
        face_provider: Callable[[], Any | None] | None = None,
    ) -> None:
        self.root = root
        self.alarm_provider = alarm_provider
        self.alarm_lookup = alarm_lookup
        self.create_alarm = create_alarm
        self.update_alarm = update_alarm
        self.delete_alarm = delete_alarm
        self.toggle_alarm = toggle_alarm
        self.snooze_alarm = snooze_alarm
        self.dismiss_alarm = dismiss_alarm
        self.set_24_hour = set_24_hour
        self.now = now
        self.state_provider = state_provider
        self.snooze_minutes = snooze_minutes
        self.read_only = read_only
        self.error = storage_error
        self.on_close = on_close
        self.closed = False
        self.after_id: str | None = None
        self.editing_id = -1
        initial = now() + timedelta(hours=1)
        self.draft_hour = initial.hour
        self.draft_minute = 0
        self.draft_label = "Alarm"
        self.draft_weekdays: set[int] = set()
        self._actions: list[tuple[tuple[int, int, int, int], Callable[[], None]]] = []
        self.canvas = tk.Canvas(root, width=800, height=480, bg="#e9faff", highlightthickness=0)
        self.canvas.place(x=0, y=0, width=800, height=480)
        self.canvas.bind("<ButtonRelease-1>", self._tap)
        self.compact_face = CompactFace(root, self.canvas, face_provider=face_provider)
        self._refresh()

    def _button(self, bounds: tuple[int, int, int, int], label: str, callback: Callable[[], None], color: str = "#1578d3") -> None:
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(left, top, right, bottom, fill=color, outline="white", width=2)
        self.canvas.create_text((left + right) // 2, (top + bottom) // 2, text=label, fill="white", font=("Arial", 10, "bold"))
        self._actions.append((bounds, callback))

    def _refresh(self) -> None:
        if self.closed:
            return
        self._draw()
        self.after_id = self.root.after(500, self._refresh)

    def _draw(self) -> None:
        self.canvas.delete("all")
        self._actions.clear()
        state = self.state_provider()
        current = self.now()
        self.canvas.create_rectangle(0, 0, 800, 62, fill="#102a5e", outline="")
        self.canvas.create_text(22, 30, anchor="w", text="ALARM CLOCK", fill="white", font=("Arial", 23, "bold"))
        self._button((528, 10, 670, 50), "+ NEW ALARM", self._new_alarm, "#3b9b6f")
        self.canvas.create_rectangle(16, 80, 272, 454, fill="#102a5e", outline="#5bc9c2", width=3)
        self.canvas.create_text(144, 148, text=format_alarm_time(current.hour, current.minute, state.use_24_hour), fill="white", font=("Arial", 42, "bold"))
        self.canvas.create_text(144, 192, text=current.strftime("%A, %B %-d"), fill="#c9e9f7", font=("Arial", 15, "bold"))
        self._button((68, 230, 220, 272), "24 HOUR" if not state.use_24_hour else "12 HOUR", lambda: self.set_24_hour(not state.use_24_hour), "#187a85")
        if self.error:
            self.canvas.create_text(144, 320, width=220, text=self.error, fill="#ffd4dc", font=("Arial", 12, "bold"))
        items = tuple(self.alarm_provider())
        if not items:
            self.canvas.create_text(525, 220, width=430, text="No alarms yet. Tap + NEW ALARM to make one!", fill="#58708c", font=("Arial", 18, "bold"))
        for index, item in enumerate(items[:4]):
            top = 78 + index * 91
            self.canvas.create_rectangle(288, top, 780, top + 82, fill="#fff0f4" if item.ringing else "white", outline="#f08aa6" if item.ringing else "#8edbd5", width=3 if item.ringing else 2)
            self.canvas.create_text(304, top + 22, anchor="w", text=item.time_text, fill="#102a5e", font=("Arial", 22, "bold"))
            self.canvas.create_text(304, top + 51, anchor="w", text=f"{item.label} • {item.repeat_text}", fill="#58708c", font=("Arial", 11, "bold"))
            if item.ringing:
                self._button((558, top + 17, 655, top + 64), f"SNOOZE {self.snooze_minutes}m", lambda alarm_id=item.alarm_id: self.snooze_alarm(alarm_id), "#d79b28")
                self._button((663, top + 17, 767, top + 64), "DISMISS", lambda alarm_id=item.alarm_id: self.dismiss_alarm(alarm_id), "#c83a4a")
            else:
                self._button((548, top + 18, 610, top + 63), "ON" if item.enabled else "OFF", lambda alarm_id=item.alarm_id, enabled=item.enabled: self.toggle_alarm(alarm_id, not enabled), "#3b9b6f" if item.enabled else "#9aaab7")
                self._button((618, top + 18, 684, top + 63), "EDIT", lambda alarm_id=item.alarm_id: self._edit_alarm(alarm_id))
                self._button((692, top + 18, 767, top + 63), "DELETE", lambda alarm_id=item.alarm_id: self.delete_alarm(alarm_id), "#c83a4a")
        if self.editing_id >= 0:
            self._draw_editor(state)
        self.compact_face.mount()

    def _draw_editor(self, state: AlarmState) -> None:
        self.canvas.create_rectangle(20, 72, 780, 462, fill="#f9fdff", outline="#5bc9c2", width=4)
        title = "EDIT ALARM" if self.editing_id else "NEW ALARM"
        self.canvas.create_text(42, 103, anchor="w", text=title, fill="#102a5e", font=("Arial", 22, "bold"))
        self.canvas.create_text(250, 180, text=format_alarm_time(self.draft_hour, self.draft_minute, state.use_24_hour), fill="#102a5e", font=("Arial", 42, "bold"))
        self._button((80, 220, 150, 270), "H −", lambda: self._adjust(-60))
        self._button((160, 220, 230, 270), "H +", lambda: self._adjust(60))
        self._button((240, 220, 310, 270), "M −", lambda: self._adjust(-5), "#d79b28")
        self._button((320, 220, 390, 270), "M +", lambda: self._adjust(5), "#d79b28")
        self.canvas.create_text(545, 150, text="REPEAT ON", fill="#58708c", font=("Arial", 13, "bold"))
        self.canvas.create_text(545, 126, text=self.draft_label, fill="#102a5e", font=("Arial", 15, "bold"))
        for day, label in enumerate("MTWTFSS"):
            left = 416 + day * 48
            self._button((left, 180, left + 40, 224), label, lambda selected=day: self._toggle_day(selected), "#5bc9c2" if day in self.draft_weekdays else "#9aaab7")
        self.canvas.create_text(545, 252, text="No days = one time", fill="#58708c", font=("Arial", 12))
        self._button((455, 370, 585, 422), "CANCEL", self._close_editor, "#9aaab7")
        self._button((600, 370, 748, 422), "SAVE ALARM", self._save_editor, "#3b9b6f")

    def _new_alarm(self) -> None:
        initial = self.now() + timedelta(hours=1)
        self.editing_id = 0
        self.draft_hour = initial.hour
        self.draft_minute = 0
        self.draft_label = "Alarm"
        self.draft_weekdays.clear()

    def _edit_alarm(self, alarm_id: int) -> None:
        alarm = self.alarm_lookup(alarm_id)
        if alarm is None:
            return
        self.editing_id = alarm_id
        self.draft_hour = alarm.hour
        self.draft_minute = alarm.minute
        self.draft_label = alarm.label
        self.draft_weekdays = set(alarm.weekdays)

    def _adjust(self, minutes: int) -> None:
        total = (self.draft_hour * 60 + self.draft_minute + minutes) % 1440
        self.draft_hour, self.draft_minute = divmod(total, 60)

    def _toggle_day(self, day: int) -> None:
        if day in self.draft_weekdays:
            self.draft_weekdays.remove(day)
        else:
            self.draft_weekdays.add(day)

    def _save_editor(self) -> None:
        weekdays = tuple(sorted(self.draft_weekdays))
        if self.editing_id:
            self.update_alarm(self.editing_id, self.draft_hour, self.draft_minute, self.draft_label, weekdays)
        else:
            self.create_alarm(self.draft_hour, self.draft_minute, self.draft_label, weekdays)
        self._close_editor()

    def _close_editor(self) -> None:
        self.editing_id = -1

    def _tap(self, event: tk.Event) -> str:
        point = (int(event.x), int(event.y))
        if self.compact_face.contains(point):
            self.close()
            return "break"
        for bounds, callback in reversed(self._actions):
            left, top, right, bottom = bounds
            if left <= point[0] <= right and top <= point[1] <= bottom:
                callback()
                self._draw()
                break
        return "break"

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except tk.TclError:
                pass
        self.compact_face.destroy()
        self.canvas.destroy()
        self.on_close()


__all__ = ["AlarmClockApp"]
