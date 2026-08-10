"""Swipe-navigable menu overlay for BMO's display."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
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


@dataclass(frozen=True)
class EmptyMenuPage:
    """Initial menu page, intentionally empty until features add icons."""

    name: str = "main"

    def draw(self, canvas: tk.Canvas, bounds: MenuBounds) -> None:
        del canvas, bounds


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
        pages: Iterable[MenuPage] = (),
    ) -> None:
        self.root = root
        self.on_close = on_close
        self.face_provider = face_provider
        supplied_pages = tuple(pages)
        self.pages: tuple[MenuPage, ...] = supplied_pages or (EmptyMenuPage(),)
        self.navigator = MenuNavigator(len(self.pages))
        self.gesture = HorizontalSwipeRecognizer()
        self.face_after_id: str | None = None
        self.face_image: ImageTk.PhotoImage | None = None
        self.closed = False

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
        if gesture == GestureKind.TAP and self._point_in_face(point):
            self.close()
        elif gesture == GestureKind.SWIPE_LEFT:
            if self.navigator.swipe_left() == MenuNavigation.PAGE:
                self._draw_page()
        elif gesture == GestureKind.SWIPE_RIGHT:
            if self.navigator.swipe_right() == MenuNavigation.FACE:
                self.close()
            else:
                self._draw_page()
        return "break"

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
