"""Shared configuration and rendering for BMO's compact kiosk face."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tkinter as tk
from typing import Any
import weakref

from PIL import Image, ImageOps, ImageTk


WINDOW_WIDTH = 800
FACE_WIDTH = 108
FACE_HEIGHT = 65
FACE_ASPECT = (5, 3)
DEFAULT_RIGHT_MARGIN = 8
DEFAULT_TOP = 5
DEFAULT_REFRESH_MS = 150
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "compact_face.json"
FACE_BACKGROUND = "#68c8bb"
FACE_OUTLINE = "#ffffff"
FACE_FALLBACK = "#102a5e"
FACE_TAG = "compact-bmo-face"

_STATE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DEFAULT_STATE_VALUES = {
    "idle": (Path("faces/idle"), 500),
    "listening": (Path("faces/listening"), 500),
    "thinking": (Path("faces/thinking"), 500),
    "speaking": (Path("faces/speaking"), 50),
    "error": (Path("faces/error"), 500),
    "capturing": (Path("faces/capturing"), 500),
    "warmup": (Path("faces/warmup"), 500),
    "alarm": (Path("faces/alarm"), 180),
}


@dataclass(frozen=True)
class CompactFaceState:
    """One configured runtime state and its contained animation directory."""

    directory: Path
    frame_duration_ms: int


@dataclass(frozen=True)
class CompactFaceConfig:
    """Validated layout and animation sources shared by every compact face."""

    width: int = FACE_WIDTH
    height: int = FACE_HEIGHT
    right_margin: int = DEFAULT_RIGHT_MARGIN
    top: int = DEFAULT_TOP
    refresh_ms: int = DEFAULT_REFRESH_MS
    states: Mapping[str, CompactFaceState] | None = None

    def __post_init__(self) -> None:
        if (self.width, self.height) != (FACE_WIDTH, FACE_HEIGHT):
            raise ValueError("compact face size must be exactly 108x65")
        if self.right_margin < 0 or self.top < 0:
            raise ValueError("compact face margins cannot be negative")
        if self.right_margin + self.width > WINDOW_WIDTH:
            raise ValueError("compact face must remain inside the kiosk width")
        if self.refresh_ms < 20 or self.refresh_ms > 10_000:
            raise ValueError("compact face refresh_ms must be from 20 to 10000")
        states = self.states
        if states is None:
            states = {
                name: CompactFaceState(directory, duration)
                for name, (directory, duration) in _DEFAULT_STATE_VALUES.items()
            }
        object.__setattr__(self, "states", dict(states))

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        right = WINDOW_WIDTH - self.right_margin
        return right - self.width, self.top, right, self.top + self.height

    @property
    def center(self) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2

    @property
    def artwork_size(self) -> tuple[int, int]:
        """Largest exact 5:3 integer canvas contained by 108x65."""
        scale = min(self.width // FACE_ASPECT[0], self.height // FACE_ASPECT[1])
        return FACE_ASPECT[0] * scale, FACE_ASPECT[1] * scale

    def state_duration(self, state: str) -> int:
        configured = (self.states or {}).get(state)
        if configured is None:
            configured = (self.states or {}).get("idle")
        return configured.frame_duration_ms if configured else self.refresh_ms

    def frame_paths(
        self,
        state: str,
        *,
        project_root: Path = PROJECT_ROOT,
        faces_root: Path | None = None,
    ) -> tuple[Path, ...]:
        configured = (self.states or {}).get(state)
        if configured is None:
            return ()
        directory = configured.directory
        if faces_root is not None and not directory.is_absolute():
            parts = directory.parts
            relative = Path(*parts[1:]) if parts and parts[0] == "faces" else directory
            resolved = Path(faces_root) / relative
        else:
            resolved = directory if directory.is_absolute() else Path(project_root) / directory
        try:
            return tuple(
                sorted(
                    (
                        path
                        for path in resolved.iterdir()
                        if path.is_file() and path.suffix.casefold() == ".png"
                    ),
                    key=lambda path: (path.name.casefold(), path.name),
                )
            )
        except OSError:
            return ()

    def web_layout(self) -> dict[str, int]:
        left, top, _right, _bottom = self.bounds
        art_width, art_height = self.artwork_size
        return {
            "left": left,
            "top": top,
            "width": self.width,
            "height": self.height,
            "art_width": art_width,
            "art_height": art_height,
            "refresh_ms": self.refresh_ms,
        }


def _positive_int(value: object, label: str, default: int) -> int:
    if value is None:
        return default
    if type(value) is not int or value <= 0:
        raise ValueError(f"compact face {label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str, default: int) -> int:
    if value is None:
        return default
    if type(value) is not int or value < 0:
        raise ValueError(f"compact face {label} must be a non-negative integer")
    return value


def _contained_directory(value: object, *, project_root: Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("compact face state directory must be a non-empty path")
    raw = Path(value)
    resolved = (raw if raw.is_absolute() else project_root / raw).resolve()
    faces_root = (project_root / "faces").resolve()
    if not resolved.is_relative_to(faces_root):
        raise ValueError("compact face state directories must stay inside faces/")
    try:
        return resolved.relative_to(project_root.resolve())
    except ValueError:
        return resolved


def _parse_config(values: Mapping[str, Any], *, project_root: Path) -> CompactFaceConfig:
    allowed = {"width", "height", "right_margin", "top", "refresh_ms", "states"}
    unknown = set(values).difference(allowed)
    if unknown:
        raise ValueError("unknown compact face setting(s): " + ", ".join(sorted(unknown)))
    states = {
        name: CompactFaceState(directory, duration)
        for name, (directory, duration) in _DEFAULT_STATE_VALUES.items()
    }
    raw_states = values.get("states", {})
    if not isinstance(raw_states, Mapping):
        raise ValueError("compact face states must be an object")
    for raw_name, raw_state in raw_states.items():
        name = str(raw_name).strip().lower()
        if not _STATE_NAME.fullmatch(name):
            raise ValueError(f"invalid compact face state name {raw_name!r}")
        if not isinstance(raw_state, Mapping):
            raise ValueError(f"compact face state {name!r} must be an object")
        unknown_state = set(raw_state).difference({"directory", "frame_duration_ms"})
        if unknown_state:
            raise ValueError(
                f"unknown compact face {name} setting(s): "
                + ", ".join(sorted(unknown_state))
            )
        previous = states.get(name)
        default_directory = previous.directory if previous else Path("faces") / name
        default_duration = previous.frame_duration_ms if previous else DEFAULT_REFRESH_MS
        states[name] = CompactFaceState(
            _contained_directory(
                raw_state.get("directory", default_directory),
                project_root=project_root,
            ),
            _positive_int(
                raw_state.get("frame_duration_ms"),
                f"{name} frame_duration_ms",
                default_duration,
            ),
        )
    return CompactFaceConfig(
        width=_positive_int(values.get("width"), "width", FACE_WIDTH),
        height=_positive_int(values.get("height"), "height", FACE_HEIGHT),
        right_margin=_nonnegative_int(
            values.get("right_margin"), "right_margin", DEFAULT_RIGHT_MARGIN
        ),
        top=_nonnegative_int(values.get("top"), "top", DEFAULT_TOP),
        refresh_ms=_positive_int(
            values.get("refresh_ms"), "refresh_ms", DEFAULT_REFRESH_MS
        ),
        states=states,
    )


def load_compact_face_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
    reporter: Callable[[str], None] = print,
) -> CompactFaceConfig:
    """Load optional private compact-face settings with startup-safe defaults."""
    config_path = Path(path)
    if not config_path.exists():
        return CompactFaceConfig()
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            values = json.load(handle)
        if not isinstance(values, Mapping):
            raise ValueError("compact face configuration root must be an object")
        return _parse_config(values, project_root=Path(project_root))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        reporter(f"[COMPACT FACE] Could not load {config_path}: {exc}. Using defaults.")
        return CompactFaceConfig()


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
