"""UI-toolkit-neutral menu items, grid geometry, and swipe navigation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class MenuBounds:
    """Area made available to one menu page."""

    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class IconMenuItem:
    """Presentation metadata for one tappable grid item."""

    name: str
    label: str
    icon_path: Path

    def __post_init__(self) -> None:
        name = str(self.name).strip().lower()
        label = str(self.label).strip()
        if not name:
            raise ValueError("Menu item name cannot be empty.")
        if not label:
            raise ValueError("Menu item label cannot be empty.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "icon_path", Path(self.icon_path))


class IconMenuPage:
    """One fixed-capacity page of ordered icon menu items."""

    COLUMNS = 5
    ROWS = 3
    CAPACITY = COLUMNS * ROWS
    ICON_SIZE = 88
    HORIZONTAL_PADDING = 7
    VERTICAL_PADDING = 6

    def __init__(
        self,
        items: Iterable[IconMenuItem],
        *,
        page_number: int = 1,
    ) -> None:
        self.items = tuple(items)
        if not self.items:
            raise ValueError("An icon menu page needs at least one item.")
        if len(self.items) > self.CAPACITY:
            raise ValueError(
                f"An icon menu page supports at most {self.CAPACITY} items."
            )
        self.name = f"icons-{page_number}"

    @classmethod
    def paginate(
        cls,
        items: Iterable[IconMenuItem],
    ) -> tuple[IconMenuPage, ...]:
        """Group ordered items into fixed-capacity swipeable grid pages."""
        supplied_items = tuple(items)
        return tuple(
            cls(
                supplied_items[offset : offset + cls.CAPACITY],
                page_number=(offset // cls.CAPACITY) + 1,
            )
            for offset in range(0, len(supplied_items), cls.CAPACITY)
        )

    @classmethod
    def tile_bounds(
        cls,
        index: int,
        bounds: MenuBounds,
    ) -> tuple[int, int, int, int]:
        """Return the padded touch bounds for one row-major grid cell."""
        row, column = divmod(index, cls.COLUMNS)
        cell_width = (bounds.right - bounds.left) // cls.COLUMNS
        cell_height = (bounds.bottom - bounds.top) // cls.ROWS
        cell_left = bounds.left + column * cell_width
        cell_top = bounds.top + row * cell_height
        return (
            cell_left + cls.HORIZONTAL_PADDING,
            cell_top + cls.VERTICAL_PADDING,
            cell_left + cell_width - cls.HORIZONTAL_PADDING,
            cell_top + cell_height - cls.VERTICAL_PADDING,
        )

    _tile_bounds = tile_bounds

    def action_at(
        self,
        point: tuple[int, int],
        bounds: MenuBounds,
    ) -> str | None:
        """Return the selected item name when a point hits a grid cell."""
        for index, item in enumerate(self.items):
            left, top, right, bottom = self.tile_bounds(index, bounds)
            if left <= point[0] <= right and top <= point[1] <= bottom:
                return item.name
        return None


class MenuNavigation(str, Enum):
    """Result of moving between menu pages."""

    PAGE = "page"
    FACE = "face"
    UNCHANGED = "unchanged"


class MenuNavigator:
    """Keep ordered menu history independent from a display toolkit."""

    def __init__(self, page_count: int) -> None:
        if page_count < 1:
            raise ValueError("The menu needs at least one page.")
        self.page_count = page_count
        self.page_index = 0

    def swipe_left(self) -> MenuNavigation:
        """Advance to the next page, when one exists."""
        if self.page_index >= self.page_count - 1:
            return MenuNavigation.UNCHANGED
        self.page_index += 1
        return MenuNavigation.PAGE

    def swipe_right(self) -> MenuNavigation:
        """Retrace pages, then return to the full-screen face."""
        if self.page_index == 0:
            return MenuNavigation.FACE
        self.page_index -= 1
        return MenuNavigation.PAGE


__all__ = [
    "IconMenuItem",
    "IconMenuPage",
    "MenuBounds",
    "MenuNavigation",
    "MenuNavigator",
]
