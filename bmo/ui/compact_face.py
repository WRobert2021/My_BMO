"""Shared configuration and rendering for BMO's compact kiosk face."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
import weakref

from PIL import Image, ImageOps, ImageTk

from bmo.face_config import (
    FACE_HEIGHT,
    FACE_WIDTH,
    CompactFaceConfig,
    CompactFaceState,
    load_compact_face_config,
)


FACE_BACKGROUND = "#68c8bb"
FACE_OUTLINE = "#ffffff"
FACE_FALLBACK = "#102a5e"
FACE_TAG = "compact-bmo-face"


DEFAULT_COMPACT_FACE_CONFIG = CompactFaceConfig()
COMPACT_FACE_BOUNDS = DEFAULT_COMPACT_FACE_CONFIG.bounds
COMPACT_FACE_CENTER = DEFAULT_COMPACT_FACE_CONFIG.center


def normalize_face_image(
    source: Image.Image,
    config: CompactFaceConfig = DEFAULT_COMPACT_FACE_CONFIG,
) -> Image.Image:
    """Letterbox one face without distortion inside the fixed 108x65 viewport."""
    artwork_size = config.artwork_size
    contained = ImageOps.contain(
        source.convert("RGB"),
        artwork_size,
        method=Image.Resampling.LANCZOS,
    )
    artwork = Image.new("RGB", artwork_size, FACE_BACKGROUND)
    artwork.paste(
        contained,
        (
            (artwork_size[0] - contained.width) // 2,
            (artwork_size[1] - contained.height) // 2,
        ),
    )
    viewport = Image.new("RGB", (config.width, config.height), FACE_BACKGROUND)
    viewport.paste(
        artwork,
        (
            (config.width - artwork.width) // 2,
            (config.height - artwork.height) // 2,
        ),
    )
    return viewport


FaceProvider = Callable[[], Image.Image | None]


class CompactFace:
    """Render the one canonical compact face and own its callback lifecycle."""

    _stacks: dict[int, list[weakref.ReferenceType["CompactFace"]]] = {}

    @classmethod
    def _store_stack(cls, key: int, live: list["CompactFace"]) -> None:
        if not live:
            cls._stacks.pop(key, None)
            return

        def collected(_reference: weakref.ReferenceType["CompactFace"]) -> None:
            remaining = [
                item
                for reference in cls._stacks.get(key, [])
                if (item := reference()) is not None and not item.destroyed
            ]
            cls._store_stack(key, remaining)
            if remaining:
                remaining[-1].resume()

        cls._stacks[key] = [weakref.ref(item, collected) for item in live]

    @classmethod
    def _top_for_root(cls, root: tk.Misc) -> "CompactFace | None":
        live = [
            item
            for reference in cls._stacks.get(id(root), [])
            if (item := reference()) is not None and not item.destroyed
        ]
        cls._store_stack(id(root), live)
        return live[-1] if live else None

    @classmethod
    def suspend_for_external_surface(cls, root: tk.Misc) -> None:
        """Pause the visible Tk face while a non-Tk kiosk covers the root."""
        top = cls._top_for_root(root)
        if top is not None:
            top.suspend()

    @classmethod
    def resume_after_external_surface(cls, root: tk.Misc) -> None:
        """Resume the visible Tk face after a covering non-Tk kiosk closes."""
        top = cls._top_for_root(root)
        if top is not None:
            top.resume()

    def __init__(
        self,
        root: tk.Misc,
        canvas: tk.Canvas,
        *,
        face_provider: FaceProvider | None,
        on_tap: Callable[[], None] | None = None,
        config: CompactFaceConfig | None = None,
        auto_mount: bool = True,
    ) -> None:
        self.root = root
        self.canvas = canvas
        self.face_provider = face_provider
        self.on_tap = on_tap
        self.config = config or load_compact_face_config()
        self.after_id: str | None = None
        self.image: ImageTk.PhotoImage | None = None
        self.image_item: int | None = None
        self.fallback_item: int | None = None
        self.outline_item: int | None = None
        self.mounted = False
        self.active = False
        self.destroyed = False
        if auto_mount:
            self.mount()

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        return self.config.bounds

    def contains(self, point: tuple[int, int]) -> bool:
        left, top, right, bottom = self.bounds
        return left <= point[0] <= right and top <= point[1] <= bottom

    def mount(self, canvas: tk.Canvas | None = None) -> None:
        if self.destroyed:
            return
        if canvas is not None:
            self.canvas = canvas
        try:
            self.canvas.delete(FACE_TAG)
            center_x, center_y = self.config.center
            self.image_item = self.canvas.create_image(
                center_x,
                center_y,
                anchor=tk.CENTER,
                tags=(FACE_TAG,),
            )
            self.outline_item = self.canvas.create_rectangle(
                *self.bounds,
                fill="",
                outline=FACE_OUTLINE,
                width=2,
                tags=(FACE_TAG,),
            )
            self.fallback_item = self.canvas.create_text(
                center_x,
                center_y,
                text="BMO",
                fill=FACE_FALLBACK,
                font=("Arial Rounded MT Bold", 14, "bold"),
                tags=(FACE_TAG,),
            )
            if self.on_tap is not None:
                self.canvas.tag_bind(
                    FACE_TAG,
                    "<ButtonRelease-1>",
                    lambda _event: self.on_tap(),
                )
            self.mounted = True
        except tk.TclError:
            self.mounted = False
            return
        self.start()

    def unmount(self) -> None:
        """Hide this face while retaining ownership over covered underlays."""
        self.suspend()
        try:
            self.canvas.delete(FACE_TAG)
        except tk.TclError:
            pass
        self.mounted = False
        self.image_item = None
        self.fallback_item = None
        self.outline_item = None
        self.image = None

    def _live_stack(self) -> list["CompactFace"]:
        key = id(self.root)
        live = [
            item
            for reference in self._stacks.get(key, [])
            if (item := reference()) is not None and not item.destroyed
        ]
        self._store_stack(key, live)
        return live

    def _acquire(self) -> None:
        live = self._live_stack()
        if self in live:
            live.remove(self)
        if live:
            live[-1]._pause_schedule()
        live.append(self)
        self._store_stack(id(self.root), live)

    def start(self) -> None:
        if self.destroyed or not self.mounted:
            return
        self._acquire()
        if self.active:
            return
        self.active = True
        self._refresh()

    def resume(self) -> None:
        if self.destroyed or not self.mounted:
            return
        live = self._live_stack()
        if live and live[-1] is not self:
            return
        self.start()

    def _pause_schedule(self) -> None:
        self.active = False
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except (tk.TclError, ValueError):
                pass
            self.after_id = None

    def suspend(self) -> None:
        self._pause_schedule()

    stop = suspend

    def _show_fallback(self) -> None:
        """Clear any stale frame and restore the built-in visible fallback."""
        self.image = None
        try:
            if self.image_item is not None:
                self.canvas.itemconfigure(self.image_item, image="")
            if self.fallback_item is not None:
                self.canvas.itemconfigure(self.fallback_item, state=tk.NORMAL)
        except (tk.TclError, ValueError):
            pass

    def _refresh(self) -> None:
        if self.destroyed or not self.active or not self.mounted:
            return
        try:
            face = self.face_provider() if self.face_provider is not None else None
        except Exception:
            face = None
        if face is None or self.image_item is None:
            self._show_fallback()
        else:
            try:
                self.image = ImageTk.PhotoImage(normalize_face_image(face, self.config))
                self.canvas.itemconfigure(self.image_item, image=self.image)
                if self.fallback_item is not None:
                    self.canvas.itemconfigure(self.fallback_item, state=tk.HIDDEN)
            except Exception:
                self._show_fallback()
        try:
            # Canvas.lift() is an alias for tag_raise() and requires an item.
            # Raise only this shared face group so refreshes work on real Tk.
            self.canvas.tag_raise(FACE_TAG)
        except (tk.TclError, ValueError):
            pass
        if self.active and not self.destroyed:
            try:
                self.after_id = self.root.after(self.config.refresh_ms, self._refresh)
            except (tk.TclError, ValueError):
                self.after_id = None

    def destroy(self) -> None:
        if self.destroyed:
            return
        live = self._live_stack()
        was_top = bool(live and live[-1] is self)
        self._pause_schedule()
        self.unmount()
        self.destroyed = True
        live = [item for item in live if item is not self]
        self._store_stack(id(self.root), live)
        if was_top and live:
            live[-1].resume()


__all__ = [
    "COMPACT_FACE_BOUNDS",
    "COMPACT_FACE_CENTER",
    "CompactFace",
    "CompactFaceConfig",
    "CompactFaceState",
    "DEFAULT_COMPACT_FACE_CONFIG",
    "FACE_HEIGHT",
    "FACE_WIDTH",
    "load_compact_face_config",
    "normalize_face_image",
]
