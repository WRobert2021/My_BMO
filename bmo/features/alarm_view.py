"""Toolkit-neutral alarm-clock presentation records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlarmViewItem:
    alarm_id: int
    time_text: str
    label: str
    repeat_text: str
    enabled: bool
    ringing: bool = False
    snoozed: bool = False


__all__ = ["AlarmViewItem"]
