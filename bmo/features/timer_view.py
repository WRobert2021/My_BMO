"""Toolkit-neutral timer view records shared by feature presentations."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TimerViewItem:
    """Display-only snapshot of one active countdown timer."""

    timer_id: int
    label: str | None
    remaining_seconds: float


@dataclass(frozen=True)
class TimerDurationDraft:
    """Toolkit-neutral values for a new countdown."""

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


__all__ = ["TimerDurationDraft", "TimerViewItem", "format_countdown"]
