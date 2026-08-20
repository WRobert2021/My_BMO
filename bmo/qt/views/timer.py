"""QML adapter for the timer feature."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QTimer

from bmo.features.timer_view import TimerDurationDraft, format_countdown
from bmo.qt.views.base import QtHostedView


class QtTimerView(QtHostedView):
    kind = "timer"
    title = "Timers"

    def __init__(
        self,
        host: Any,
        *,
        timer_provider: Any,
        cancel_timer: Any,
        create_timer: Any,
        face_provider: Any = None,
        on_close: Any,
    ) -> None:
        del face_provider
        self.timer_provider = timer_provider
        self.cancel_timer = cancel_timer
        self.create_timer = create_timer
        self.draft = TimerDurationDraft()
        self.adding = False
        self.error = ""
        super().__init__(host, on_close=on_close)
        self._timer = QTimer(host)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def payload(self) -> dict[str, object]:
        items = []
        for timer in self.timer_provider():
            items.append(
                {
                    "id": timer.timer_id,
                    "label": timer.label or f"Timer {timer.timer_id}",
                    "remaining": format_countdown(timer.remaining_seconds),
                }
            )
        return {
            "items": items,
            "adding": self.adding,
            "hours": self.draft.hours,
            "minutes": self.draft.minutes,
            "seconds": self.draft.seconds,
            "error": self.error,
        }

    def handle_action(self, action: str, value: str) -> None:
        if action == "timer_add":
            self.adding = True
            self.error = ""
        elif action == "timer_cancel_add":
            self.adding = False
            self.error = ""
            self.draft = TimerDurationDraft()
        elif action == "timer_adjust":
            try:
                adjustment = json.loads(value)
                self.draft = self.draft.adjusted(
                    str(adjustment["field"]),
                    int(adjustment["amount"]),
                )
                self.error = ""
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.error = "That timer value is not valid."
        elif action == "timer_create":
            if self.draft.total_seconds <= 0:
                self.error = "Choose a time first."
            elif self.create_timer(self.draft.total_seconds):
                self.draft = TimerDurationDraft()
                self.adding = False
                self.error = ""
            else:
                self.error = "BMO could not create that timer."
        elif action == "timer_cancel":
            try:
                self.cancel_timer(int(value))
            except ValueError:
                self.error = "That timer is no longer available."
        else:
            super().handle_action(action, value)
            return
        self.refresh()

    def close(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().close()


__all__ = ["QtTimerView"]
