"""UI-independent bounded vertical drag scrolling shared by touch views."""

from __future__ import annotations

import math


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
        self.offset = min(max(self.offset + pixels, 0.0), self.max_offset)
        return not math.isclose(previous_offset, self.offset)
