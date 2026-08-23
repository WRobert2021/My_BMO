"""Legacy Tk fallback for the menu-launched Music feature."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
import tkinter as tk
from typing import Any

from PIL import Image, ImageTk

from bmo.features.music import MusicSession
from bmo.ui.compact_face import CompactFace


class MusicApp:
    """Offer touch-sized song selection and controls on the legacy surface."""

    REFRESH_MS = 250

    def __init__(
        self,
        root: tk.Misc,
        *,
        session: MusicSession,
        on_close: Callable[[], None],
        face_provider: Callable[[], Any | None] | None = None,
    ) -> None:
        self.root = root
        self.session = session
        self.on_close = on_close
        self.closed = False
        self._after_id: str | None = None
        self._art_image: ImageTk.PhotoImage | None = None
        self._last_signature: tuple[object, ...] | None = None

        self.canvas = tk.Canvas(
            root,
            width=800,
            height=480,
            bg="#eef8ff",
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, width=800, height=480)
        self.canvas.create_rectangle(0, 0, 800, 62, fill="#102a5e", outline="")
        self.canvas.create_text(
            22,
            31,
            anchor="w",
            text="MUSIC",
            fill="white",
            font=("Arial Rounded MT Bold", 23, "bold"),
        )
        self.compact_face = CompactFace(
            root,
            self.canvas,
            face_provider=face_provider,
            on_tap=self.close,
        )

        self.listbox = tk.Listbox(
            root,
            font=("Arial", 14, "bold"),
            bg="#fbfeff",
            fg="#102a5e",
            selectbackground="#d7f1ff",
            selectforeground="#102a5e",
            activestyle="none",
            borderwidth=2,
            relief="solid",
        )
        self.listbox.place(x=18, y=78, width=340, height=382)
        scrollbar = tk.Scrollbar(root, command=self.listbox.yview, width=20)
        scrollbar.place(x=338, y=80, width=18, height=378)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self._scrollbar = scrollbar
        for track in session.tracks:
            self.listbox.insert(tk.END, f"{track.title}  ·  {track.album}")
        if session.selected_index is not None:
            self.listbox.selection_set(session.selected_index)
        self.listbox.bind("<<ListboxSelect>>", self._select)

        self.art_label = tk.Label(root, bg="#dff6f5", text="MUSIC")
        self.art_label.place(x=383, y=84, width=190, height=190)
        self.title_label = tk.Label(
            root,
            bg="#eef8ff",
            fg="#102a5e",
            font=("Arial Rounded MT Bold", 17, "bold"),
            wraplength=195,
            justify="left",
        )
        self.title_label.place(x=590, y=88, width=190, height=85)
        self.album_label = tk.Label(
            root,
            bg="#eef8ff",
            fg="#1578d3",
            font=("Arial", 12, "bold"),
            wraplength=190,
            justify="left",
        )
        self.album_label.place(x=590, y=175, width=190, height=52)
        self.status_label = tk.Label(
            root,
            bg="#eef8ff",
            fg="#58708c",
            font=("Arial", 10, "bold"),
            wraplength=190,
            justify="left",
        )
        self.status_label.place(x=590, y=232, width=190, height=42)

        controls = (
            ("PLAY", "#3b8e63", self._play),
            ("PAUSE", "#1578d3", self._pause),
            ("STOP", "#c84b5b", self._stop),
            ("REPEAT", "#7656a7", self._repeat),
        )
        self._buttons: list[tk.Button] = []
        for index, (label, color, callback) in enumerate(controls):
            button = tk.Button(
                root,
                text=label,
                command=callback,
                bg=color,
                fg="white",
                activebackground=color,
                font=("Arial Rounded MT Bold", 11, "bold"),
                borderwidth=0,
            )
            button.place(x=382 + index * 100, y=300, width=91, height=56)
            self._buttons.append(button)
        self._refresh()

    def _select(self, _event: object) -> None:
        selection = self.listbox.curselection()
        if selection:
            self.session.select(int(selection[0]))
            self._last_signature = None

    def _play(self) -> None:
        self.session.play_selected()
        self._last_signature = None

    def _pause(self) -> None:
        self.session.pause_or_resume()
        self._last_signature = None

    def _stop(self) -> None:
        self.session.stop()
        self._last_signature = None

    def _repeat(self) -> None:
        self.session.toggle_repeat()
        self._last_signature = None

    def _refresh(self) -> None:
        if self.closed:
            return
        self.session.poll()
        signature = self.session.signature
        if signature != self._last_signature:
            self._last_signature = signature
            track = self.session.display_track
            self.title_label.configure(text=track.title if track else "Music Time!")
            self.album_label.configure(text=track.album if track else "")
            status = self.session.error or self.session.state.upper()
            self.status_label.configure(text=status)
            self._buttons[1].configure(
                text="RESUME" if self.session.state == "paused" else "PAUSE"
            )
            self._buttons[3].configure(
                bg="#d7a91f" if self.session.repeat else "#7656a7"
            )
            self._art_image = None
            if track and track.artwork:
                try:
                    source = Image.open(BytesIO(track.artwork)).convert("RGB")
                    source.thumbnail((190, 190), Image.Resampling.LANCZOS)
                    self._art_image = ImageTk.PhotoImage(source)
                except (OSError, ValueError):
                    self._art_image = None
            self.art_label.configure(
                image=self._art_image or "",
                text="" if self._art_image else "MUSIC",
            )
        self._after_id = self.root.after(self.REFRESH_MS, self._refresh)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except (tk.TclError, ValueError):
                pass
        self.session.close()
        self.compact_face.destroy()
        for widget in (
            self.listbox,
            self._scrollbar,
            self.art_label,
            self.title_label,
            self.album_label,
            self.status_label,
            *self._buttons,
            self.canvas,
        ):
            try:
                widget.destroy()
            except tk.TclError:
                pass
        self.on_close()


__all__ = ["MusicApp"]
