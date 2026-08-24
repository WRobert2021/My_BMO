"""QML adapter for the persistent alarm-clock feature."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

from PySide6.QtCore import QTimer

from bmo.features.alarm_clock import format_alarm_time
from bmo.qt.views.base import QtHostedView


class QtAlarmClockView(QtHostedView):
    kind = "alarm_clock"
    title = "Alarm Clock"

    def __init__(
        self,
        host: Any,
        *,
        alarm_provider: Any,
        alarm_lookup: Any,
        create_alarm: Any,
        update_alarm: Any,
        delete_alarm: Any,
        toggle_alarm: Any,
        snooze_alarm: Any,
        dismiss_alarm: Any,
        set_24_hour: Any,
        now: Any,
        state_provider: Any,
        snooze_minutes: int,
        read_only: bool,
        storage_error: str,
        face_provider: Any = None,
        on_close: Any,
    ) -> None:
        del face_provider
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
        self.storage_error = storage_error
        self.editing = False
        self.editing_id = 0
        initial = now() + timedelta(hours=1)
        self.hour = initial.hour
        self.minute = 0
        self.label = "Alarm"
        self.weekdays: tuple[int, ...] = ()
        self.error = storage_error
        super().__init__(host, on_close=on_close)
        self._timer = QTimer(host)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def payload(self) -> dict[str, object]:
        now: datetime = self.now()
        state = self.state_provider()
        items = [
            {
                "id": item.alarm_id,
                "time": item.time_text,
                "label": item.label,
                "repeat": item.repeat_text,
                "enabled": item.enabled,
                "ringing": item.ringing,
                "snoozed": item.snoozed,
            }
            for item in self.alarm_provider()
        ]
        ringing = any(bool(item["ringing"]) for item in items)
        return {
            "clock": format_alarm_time(now.hour, now.minute, state.use_24_hour),
            "seconds": f"{now.second:02d}",
            "date": now.strftime("%A, %B %-d"),
            "use24Hour": state.use_24_hour,
            "items": items,
            "ringing": ringing,
            "faceAnimationHook": "alarm_clock_ringing" if ringing else "alarm_clock_idle",
            "editing": self.editing,
            "editingId": self.editing_id,
            "draftHour": self.hour,
            "draftMinute": self.minute,
            "draftTime": format_alarm_time(self.hour, self.minute, state.use_24_hour),
            "draftLabel": self.label,
            "draftWeekdays": list(self.weekdays),
            "snoozeMinutes": self.snooze_minutes,
            "readOnly": self.read_only,
            "error": self.error,
        }

    def _reset_draft(self) -> None:
        initial = self.now() + timedelta(hours=1)
        self.hour = initial.hour
        self.minute = 0
        self.label = "Alarm"
        self.weekdays = ()
        self.editing_id = 0

    def handle_action(self, action: str, value: str) -> None:
        if action == "alarm_add":
            self._reset_draft()
            self.editing = True
            self.error = ""
        elif action == "alarm_edit":
            try:
                alarm_id = int(value)
            except ValueError:
                self.error = "That alarm is no longer available."
            else:
                alarm = self.alarm_lookup(alarm_id)
                if alarm is None:
                    self.error = "That alarm is no longer available."
                else:
                    self.editing = True
                    self.editing_id = alarm.alarm_id
                    self.hour = alarm.hour
                    self.minute = alarm.minute
                    self.label = alarm.label
                    self.weekdays = alarm.weekdays
                    self.error = ""
        elif action == "alarm_editor_cancel":
            self.editing = False
            self._reset_draft()
            self.error = ""
        elif action == "alarm_adjust":
            try:
                change = json.loads(value)
                field = str(change["field"])
                amount = int(change["amount"])
                if field == "hour":
                    self.hour = (self.hour + amount) % 24
                elif field == "minute":
                    total = self.hour * 60 + self.minute + amount
                    total %= 24 * 60
                    self.hour, self.minute = divmod(total, 60)
                else:
                    raise ValueError
                self.error = ""
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.error = "That time is not valid."
        elif action == "alarm_label":
            self.label = value.strip()[:60] or "Alarm"
        elif action == "alarm_weekday":
            try:
                day = int(value)
                if not 0 <= day <= 6:
                    raise ValueError
            except ValueError:
                self.error = "That repeat day is not valid."
            else:
                days = set(self.weekdays)
                if day in days:
                    days.remove(day)
                else:
                    days.add(day)
                self.weekdays = tuple(sorted(days))
                self.error = ""
        elif action == "alarm_save":
            if self.read_only:
                self.error = "Alarm data is read-only."
            elif self.editing_id:
                if self.update_alarm(
                    self.editing_id,
                    self.hour,
                    self.minute,
                    self.label,
                    self.weekdays,
                ):
                    self.editing = False
                    self._reset_draft()
                    self.error = ""
                else:
                    self.error = "BMO could not update that alarm."
            else:
                alarm_id = self.create_alarm(
                    self.hour,
                    self.minute,
                    self.label,
                    self.weekdays,
                )
                if alarm_id is None:
                    self.error = "BMO could not save that alarm."
                else:
                    self.editing = False
                    self._reset_draft()
                    self.error = ""
        elif action in {"alarm_delete", "alarm_toggle", "alarm_snooze", "alarm_dismiss"}:
            try:
                if action == "alarm_toggle":
                    data = json.loads(value)
                    ok = self.toggle_alarm(int(data["id"]), bool(data["enabled"]))
                else:
                    alarm_id = int(value)
                    callback = {
                        "alarm_delete": self.delete_alarm,
                        "alarm_snooze": self.snooze_alarm,
                        "alarm_dismiss": self.dismiss_alarm,
                    }[action]
                    ok = callback(alarm_id)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                ok = False
            self.error = "" if ok else "That alarm is no longer available."
        elif action == "alarm_24_hour":
            enabled = value.strip().lower() == "true"
            self.error = "" if self.set_24_hour(enabled) else "BMO could not save that clock setting."
        else:
            super().handle_action(action, value)
            return
        self.refresh()

    def close(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().close()


__all__ = ["QtAlarmClockView"]
