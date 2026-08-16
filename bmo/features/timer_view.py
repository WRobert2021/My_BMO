"""Toolkit-neutral timer view records shared by feature presentations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimerViewItem:
    """Display-only snapshot of one active countdown timer."""

    timer_id: int
    label: str | None
    remaining_seconds: float


__all__ = ["TimerViewItem"]
