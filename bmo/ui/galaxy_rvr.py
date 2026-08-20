"""Legacy Tk fallback view for the GalaxyRVR controller remote."""

from __future__ import annotations

import tkinter as tk
from queue import Empty, SimpleQueue
from collections.abc import Callable
from typing import Any

from bmo.features.galaxy_rvr import GalaxyRVRStatus
from bmo.features.galaxy_rvr_config import GalaxyRVRConfig
from bmo.ui.compact_face import CompactFace


class GalaxyRVRApp:
    """Show remote status while the background session owns controller I/O."""

    def __init__(
        self,
        root: tk.Misc,
        *,
        config: GalaxyRVRConfig,
        session_factory: Callable[[Callable[[GalaxyRVRStatus], None]], Any],
        on_close: Callable[[], None],
        face_provider: Callable[[], Any | None] | None = None,
    ) -> None:
        self.root = root
        self.config = config
        self.on_close = on_close
        self.closed = False
        self.status = GalaxyRVRStatus(servo_angle=config.servo_start_angle)
        self._status_queue: SimpleQueue[GalaxyRVRStatus] = SimpleQueue()
        self._poll_after_id: str | None = None
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
            text="GALAXYRVR REMOTE",
            fill="white",
            font=("Arial Rounded MT Bold", 23, "bold"),
        )
        self.canvas.create_rectangle(
            630, 9, 772, 53, fill="#1578d3", outline="white", width=2
        )
        self.canvas.create_text(
            701,
            31,
            text="BACK",
            fill="white",
            font=("Arial Rounded MT Bold", 12, "bold"),
        )
        self.canvas.bind("<ButtonRelease-1>", self._tap)
        self.status_item = self.canvas.create_text(
            30,
            105,
            anchor="nw",
            width=730,
            text="Starting remote...",
            fill="#102a5e",
            font=("Arial", 18, "bold"),
        )
        self.detail_item = self.canvas.create_text(
            30,
            160,
            anchor="nw",
            width=730,
            text="",
            fill="#58708c",
            font=("Arial", 15),
        )
        self.canvas.create_text(
            30,
            270,
            anchor="nw",
            width=730,
            text=(
                "LEFT STICK  Forward / backward\n"
                "RIGHT STICK  Turn left / right\n"
                "LT / RT  Camera up / down\n"
                "A BUTTON  Save photo"
            ),
            fill="#1578d3",
            font=("Arial Rounded MT Bold", 16, "bold"),
        )
        self.compact_face = CompactFace(
            root,
            self.canvas,
            face_provider=face_provider,
        )
        self.session = session_factory(self._status_changed)
        self.session.start()
        self._poll_status()

    def _status_changed(self, status: GalaxyRVRStatus) -> None:
        self._status_queue.put(status)

    def _poll_status(self) -> None:
        if self.closed:
            return
        changed = False
        while True:
            try:
                self.status = self._status_queue.get_nowait()
                changed = True
            except Empty:
                break
        if changed:
            self._render()
        self._poll_after_id = self.root.after(50, self._poll_status)

    def _render(self) -> None:
        if self.closed:
            return
        status = self.status
        self.canvas.itemconfigure(self.status_item, text=status.state)
        detail = (
            f"Rover: {'connected' if status.rover_connected else 'waiting'}    "
            f"Controller: {'connected' if status.controller_connected else 'waiting'}\n"
            f"Motors: {status.left_power:+d} / {status.right_power:+d}    "
            f"Camera: {status.servo_angle}°\n"
            f"Axes: {status.axis_summary}"
        )
        if status.error:
            detail += f"\n{status.error}"
        self.canvas.itemconfigure(self.detail_item, text=detail)

    def _tap(self, event: tk.Event[Any]) -> None:
        if 630 <= event.x <= 772 and 9 <= event.y <= 53:
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.session.close()
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        self.compact_face.destroy()
        self.canvas.destroy()
        self.on_close()


__all__ = ["GalaxyRVRApp"]
