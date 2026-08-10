"""Swipe-navigable menu overlay for BMO's display."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageTk

from bmo.ui.gestures import GestureKind, HorizontalSwipeRecognizer


WINDOW_SIZE = (800, 480)
FACE_BOUNDS = (636, 76, 792, 182)
PAGE_BOUNDS = (24, 76, 612, 448)


@dataclass(frozen=True)
class MenuBounds:
    """Area made available to one menu page."""

    left: int
    top: int
    right: int
    bottom: int


class MenuPage(Protocol):
    """Rendering contract for a page contributed to the menu."""

    name: str

    def draw(self, canvas: tk.Canvas, bounds: MenuBounds) -> None:
        """Draw page-owned content within the supplied bounds."""

    def action_at(
        self,
        point: tuple[int, int],
        bounds: MenuBounds,
    ) -> str | None:
        """Return the selected action name when a tap hits page content."""


@dataclass(frozen=True)
class EmptyMenuPage:
    """Initial menu page, intentionally empty until features add icons."""

    name: str = "main"

    def draw(self, canvas: tk.Canvas, bounds: MenuBounds) -> None:
        del canvas, bounds

    def action_at(
        self,
        point: tuple[int, int],
        bounds: MenuBounds,
    ) -> str | None:
        del point, bounds
        return None


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
    """A page-sized grid of tappable extension-provided menu items."""

    COLUMNS = 3
    ROWS = 2
    CAPACITY = COLUMNS * ROWS
    ICON_SIZE = 118
    HORIZONTAL_PADDING = 10
    VERTICAL_PADDING = 8

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
        self.icon_images: list[ImageTk.PhotoImage] = []

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
    def _tile_bounds(
        cls,
        index: int,
        bounds: MenuBounds,
    ) -> tuple[int, int, int, int]:
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

    def draw(self, canvas: tk.Canvas, bounds: MenuBounds) -> None:
        self.icon_images.clear()
        for index, item in enumerate(self.items):
            self._draw_item(canvas, bounds, index, item)

    def _draw_item(
        self,
        canvas: tk.Canvas,
        bounds: MenuBounds,
        index: int,
        item: IconMenuItem,
    ) -> None:
        left, top, right, bottom = self._tile_bounds(index, bounds)
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=MenuApp.WHITE,
            outline="#98bfd7",
            width=3,
        )
        icon_center_x = (left + right) // 2
        icon_center_y = top + 65
        try:
            with Image.open(item.icon_path) as source:
                icon = source.convert("RGB")
            icon.thumbnail(
                (self.ICON_SIZE, self.ICON_SIZE),
                Image.Resampling.LANCZOS,
            )
            icon_image = ImageTk.PhotoImage(icon)
            self.icon_images.append(icon_image)
            canvas.create_image(
                icon_center_x,
                icon_center_y,
                image=icon_image,
                anchor=tk.CENTER,
            )
        except (OSError, ValueError, tk.TclError):
            canvas.create_rectangle(
                icon_center_x - 45,
                icon_center_y - 45,
                icon_center_x + 45,
                icon_center_y + 45,
                fill=MenuApp.NAVY,
                outline="",
            )
            canvas.create_text(
                icon_center_x,
                icon_center_y,
                text="?",
                fill=MenuApp.WHITE,
                font=("Arial Rounded MT Bold", 42, "bold"),
            )
        canvas.create_text(
            icon_center_x,
            bottom - 20,
            text=item.label,
            fill=MenuApp.NAVY,
            font=("Arial Rounded MT Bold", 11, "bold"),
            width=(right - left) - 10,
        )

    def action_at(
        self,
        point: tuple[int, int],
        bounds: MenuBounds,
    ) -> str | None:
        for index, item in enumerate(self.items):
            left, top, right, bottom = self._tile_bounds(index, bounds)
            if left <= point[0] <= right and top <= point[1] <= bottom:
                return item.name
        return None


class MenuNavigation(str, Enum):
    """Result of moving between menu pages."""

    PAGE = "page"
    FACE = "face"
    UNCHANGED = "unchanged"


class MenuNavigator:
    """Keep ordered menu history independent from the Tk view."""

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


class MenuApp:
    """Draw the menu while keeping BMO's animated face visible."""

    BACKGROUND = "#e7f7ff"
    NAVY = "#102a5e"
    WHITE = "#ffffff"
    MUTED = "#58708c"

    def __init__(
        self,
        root: tk.Misc,
        *,
        on_close: Callable[[], None],
        face_provider: Callable[[], Image.Image | None],
        on_select: Callable[[str], None] | None = None,
        pages: Iterable[MenuPage] = (),
    ) -> None:
        self.root = root
        self.on_close = on_close
        self.face_provider = face_provider
        self.on_select = on_select or (lambda name: None)
        supplied_pages = tuple(pages)
        self.pages: tuple[MenuPage, ...] = supplied_pages or (EmptyMenuPage(),)
        self.navigator = MenuNavigator(len(self.pages))
        self.gesture = HorizontalSwipeRecognizer()
        self.face_after_id: str | None = None
        self.face_image: ImageTk.PhotoImage | None = None
        self.closed = False
        self.selection_pending = False

        self.canvas = tk.Canvas(
            root,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            bg=self.BACKGROUND,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1])
        self.canvas.bind("<ButtonPress-1>", self._handle_press)
        self.canvas.bind("<ButtonRelease-1>", self._handle_release)

        self._draw_static_ui()
        self._draw_page()
        self._refresh_face()

    def _draw_static_ui(self) -> None:
        self.canvas.create_rectangle(
            0,
            0,
            WINDOW_SIZE[0],
            62,
            fill=self.NAVY,
            outline="",
        )
        self.canvas.create_text(
            24,
            30,
            anchor="w",
            text="MENU",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self.canvas.create_rectangle(
            *FACE_BOUNDS,
            fill=self.NAVY,
            outline=self.WHITE,
            width=3,
        )
        self.face_item = self.canvas.create_image(714, 123, anchor=tk.CENTER)
        self.face_fallback_item = self.canvas.create_text(
            714,
            123,
            text="BMO",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 20, "bold"),
        )
        self.canvas.create_text(
            714,
            170,
            text="BMO",
            fill="#bde7ff",
            font=("Arial", 9, "bold"),
        )

    def _draw_page(self) -> None:
        self.canvas.delete("menu-page")
        page = self.pages[self.navigator.page_index]
        existing_items = set(self.canvas.find_all())
        page.draw(self.canvas, MenuBounds(*PAGE_BOUNDS))
        for item in set(self.canvas.find_all()) - existing_items:
            self.canvas.addtag_withtag("menu-page", item)
        if len(self.pages) > 1:
            self.canvas.create_text(
                318,
                462,
                text=f"{self.navigator.page_index + 1} / {len(self.pages)}",
                fill=self.MUTED,
                font=("Arial", 9, "bold"),
                tags=("menu-page",),
            )

    @staticmethod
    def _event_point(event: tk.Event) -> tuple[int, int]:
        return int(event.x), int(event.y)

    def _handle_press(self, event: tk.Event) -> str:
        self.gesture.press(*self._event_point(event))
        return "break"

    def _handle_release(self, event: tk.Event) -> str:
        point = self._event_point(event)
        gesture = self.gesture.release(*point)
        if self.selection_pending:
            return "break"
        if gesture == GestureKind.TAP and self._point_in_face(point):
            self.close()
        elif gesture == GestureKind.TAP:
            page = self.pages[self.navigator.page_index]
            action = page.action_at(point, MenuBounds(*PAGE_BOUNDS))
            if action is not None:
                self.selection_pending = True
                try:
                    self.on_select(action)
                except Exception:
                    self.selection_pending = False
                    raise
        elif gesture == GestureKind.SWIPE_LEFT:
            if self.navigator.swipe_left() == MenuNavigation.PAGE:
                self._draw_page()
        elif gesture == GestureKind.SWIPE_RIGHT:
            if self.navigator.swipe_right() == MenuNavigation.FACE:
                self.close()
            else:
                self._draw_page()
        return "break"

    def finish_selection(self) -> None:
        """Allow another selection after the launched view covers the menu."""
        self.selection_pending = False

    @staticmethod
    def _point_in_face(point: tuple[int, int]) -> bool:
        left, top, right, bottom = FACE_BOUNDS
        return left <= point[0] <= right and top <= point[1] <= bottom

    def _refresh_face(self) -> None:
        if self.closed:
            return
        try:
            face = self.face_provider()
            if face is not None:
                resized = face.convert("RGB").resize(
                    (140, 84),
                    Image.Resampling.LANCZOS,
                )
                self.face_image = ImageTk.PhotoImage(resized)
                self.canvas.itemconfigure(self.face_item, image=self.face_image)
                self.canvas.itemconfigure(
                    self.face_fallback_item,
                    state=tk.HIDDEN,
                )
        except (tk.TclError, ValueError):
            pass
        self.face_after_id = self.root.after(150, self._refresh_face)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.face_after_id:
            try:
                self.root.after_cancel(self.face_after_id)
            except tk.TclError:
                pass
            self.face_after_id = None
        self.canvas.destroy()
        self.on_close()
