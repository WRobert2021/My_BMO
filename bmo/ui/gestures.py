"""Small, UI-independent recognizers for touch gestures."""

from __future__ import annotations

from enum import Enum


class GestureKind(str, Enum):
    """Touch gestures used by the face and menu views."""

    TAP = "tap"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    OTHER = "other"


class HorizontalSwipeRecognizer:
    """Classify a press/release pair without depending on Tkinter."""

    def __init__(
        self,
        *,
        minimum_distance: int = 60,
        tap_slop: int = 24,
    ) -> None:
        if minimum_distance <= 0:
            raise ValueError("Swipe distance must be positive.")
        if tap_slop < 0 or tap_slop >= minimum_distance:
            raise ValueError("Tap slop must be smaller than swipe distance.")
        self.minimum_distance = minimum_distance
        self.tap_slop = tap_slop
        self._start: tuple[int, int] | None = None

    def press(self, x: int, y: int) -> None:
        """Remember the beginning of a possible tap or swipe."""
        self._start = (x, y)

    def release(self, x: int, y: int) -> GestureKind:
        """Classify and clear the current gesture."""
        start = self._start
        self._start = None
        if start is None:
            return GestureKind.OTHER

        delta_x = x - start[0]
        delta_y = y - start[1]
        if abs(delta_x) <= self.tap_slop and abs(delta_y) <= self.tap_slop:
            return GestureKind.TAP
        if (
            abs(delta_x) >= self.minimum_distance
            and abs(delta_x) > abs(delta_y)
        ):
            if delta_x < 0:
                return GestureKind.SWIPE_LEFT
            return GestureKind.SWIPE_RIGHT
        return GestureKind.OTHER
