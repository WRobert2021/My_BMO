"""Fullscreen sleeping-BMO quiet-hours cover with a touch PIN keypad."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageTk


class QuietHoursOverlay:
    """Cover every kiosk control until a parent unlocks the active period."""

    NAVY = "#0B1D3A"
    DARK_BLUE = "#102A52"
    MOON = "#F6E9A8"
    WHITE = "#FFFFFF"
    MUTED = "#A9C2E5"
    TEAL = "#59C7BB"
    RED = "#C9414E"

    def __init__(
        self,
        root: tk.Misc,
        *,
        sleeping_face_directory: Path,
        unlock: Callable[[str], bool],
    ) -> None:
        self.root = root
        self.sleeping_face_directory = Path(sleeping_face_directory)
        self.unlock = unlock
        self.visible = False
        self.entered = ""
        self.face_image: ImageTk.PhotoImage | None = None
        self.actions: list[tuple[tuple[int, int, int, int], Callable[[], None]]] = []
        self.canvas = tk.Canvas(
            root,
            width=800,
            height=480,
            bg=self.NAVY,
            highlightthickness=0,
        )
        self.canvas.bind("<Button-1>", self._handle_tap)

    @staticmethod
    def _font(size: int, *, bold: bool = False) -> tuple[str, int, str]:
        return ("Arial Rounded MT Bold", size, "bold" if bold else "normal")

    def show(self) -> None:
        if not self.visible:
            self.visible = True
            self.entered = ""
            self._draw()
            self.canvas.place(x=0, y=0, width=800, height=480)
        # Canvas.lift is an alias for raising a canvas item, not the widget.
        self.canvas.tk.call("raise", self.canvas._w)

    def hide(self) -> None:
        if not self.visible:
            return
        self.visible = False
        self.entered = ""
        self.canvas.place_forget()

    def _draw(self, error: bool = False) -> None:
        self.canvas.delete("all")
        self.actions.clear()
        self.canvas.create_oval(48, 34, 118, 104, fill=self.MOON, outline="")
        self.canvas.create_oval(75, 24, 133, 86, fill=self.NAVY, outline="")
        for x_value, y_value in ((170, 46), (228, 88), (690, 52), (744, 112), (613, 91)):
            self.canvas.create_text(x_value, y_value, text="✦", fill=self.MUTED, font=self._font(14))
        self.canvas.create_text(
            400,
            34,
            text="BMO IS SLEEPING",
            fill=self.WHITE,
            font=self._font(25, bold=True),
        )
        self.canvas.create_text(
            400,
            68,
            text="Quiet hours are active. A parent can unlock the kiosk.",
            fill=self.MUTED,
            font=self._font(11),
        )
        if not self._draw_sleeping_asset():
            self._draw_sleeping_fallback()
        self.canvas.create_text(
            565,
            119,
            text="PARENT PIN",
            fill=self.WHITE,
            font=self._font(12, bold=True),
        )
        pin_text = "● " * len(self.entered) + "○ " * (4 - len(self.entered))
        self.canvas.create_text(
            565,
            150,
            text=pin_text.strip(),
            fill=self.RED if error else self.MOON,
            font=self._font(18, bold=True),
        )
        for index, digit in enumerate("123456789"):
            row, column = divmod(index, 3)
            left = 455 + column * 74
            top = 177 + row * 61
            self._button((left, top, left + 62, top + 50), digit, lambda value=digit: self._digit(value))
        self._button((455, 360, 517, 410), "CLEAR", self._clear, color=self.RED, font_size=8)
        self._button((529, 360, 591, 410), "0", lambda: self._digit("0"))
        self._button((603, 360, 665, 410), "⌫", self._backspace)
        self.canvas.create_text(
            565,
            443,
            text="The kiosk unlock lasts until this quiet period ends.",
            fill=self.MUTED,
            font=self._font(8),
        )

    def _draw_sleeping_asset(self) -> bool:
        try:
            path = next(
                item
                for item in sorted(self.sleeping_face_directory.glob("*.png"))
                if item.is_file()
            )
            with Image.open(path) as source:
                face = source.convert("RGB").resize((330, 250), Image.Resampling.LANCZOS)
            self.face_image = ImageTk.PhotoImage(face)
            self.canvas.create_image(205, 267, image=self.face_image, anchor=tk.CENTER)
            return True
        except (StopIteration, OSError, ValueError, tk.TclError):
            return False

    def _draw_sleeping_fallback(self) -> None:
        self.canvas.create_rectangle(42, 119, 370, 414, fill=self.TEAL, outline=self.WHITE, width=4)
        self.canvas.create_arc(103, 205, 177, 247, start=200, extent=140, style=tk.ARC, outline=self.NAVY, width=6)
        self.canvas.create_arc(235, 205, 309, 247, start=200, extent=140, style=tk.ARC, outline=self.NAVY, width=6)
        self.canvas.create_arc(170, 264, 242, 315, start=25, extent=130, style=tk.ARC, outline=self.NAVY, width=5)
        self.canvas.create_text(319, 150, text="Z", fill=self.WHITE, font=self._font(22, bold=True))
        self.canvas.create_text(346, 123, text="z", fill=self.WHITE, font=self._font(15, bold=True))

    def _button(
        self,
        bounds: tuple[int, int, int, int],
        text: str,
        action: Callable[[], None],
        *,
        color: str | None = None,
        font_size: int = 14,
    ) -> None:
        color = color or self.DARK_BLUE
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(*bounds, fill=color, outline=self.WHITE, width=2)
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text=text,
            fill=self.WHITE,
            font=self._font(font_size, bold=True),
        )
        self.actions.append((bounds, action))

    def _digit(self, value: str) -> None:
        if len(self.entered) >= 4:
            return
        self.entered += value
        if len(self.entered) == 4:
            if self.unlock(self.entered):
                self.hide()
                return
            self.entered = ""
            self._draw(error=True)
            return
        self._draw()

    def _clear(self) -> None:
        self.entered = ""
        self._draw()

    def _backspace(self) -> None:
        self.entered = self.entered[:-1]
        self._draw()

    def _handle_tap(self, event: tk.Event) -> str:
        point = int(event.x), int(event.y)
        for bounds, action in reversed(self.actions):
            left, top, right, bottom = bounds
            if left <= point[0] <= right and top <= point[1] <= bottom:
                action()
                break
        return "break"

    def close(self) -> None:
        self.canvas.destroy()
