"""UI-toolkit-neutral configuration for BMO face animation frames."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


WINDOW_WIDTH = 800
FACE_WIDTH = 108
FACE_HEIGHT = 65
FACE_ASPECT = (5, 3)
DEFAULT_RIGHT_MARGIN = 8
DEFAULT_TOP = 5
DEFAULT_REFRESH_MS = 150
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "compact_face.json"

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
    "alarm_clock_ringing": (Path("faces/alarm_clock"), 180),
}


@dataclass(frozen=True)
class CompactFaceState:
    """One configured runtime state and its contained animation directory."""

    directory: Path
    frame_duration_ms: int


@dataclass(frozen=True)
class CompactFaceConfig:
    """Validated layout and animation sources shared by display toolkits."""

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
            resolved = (
                directory
                if directory.is_absolute()
                else Path(project_root) / directory
            )
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


__all__ = [
    "CompactFaceConfig",
    "CompactFaceState",
    "DEFAULT_CONFIG_PATH",
    "FACE_HEIGHT",
    "FACE_WIDTH",
    "PROJECT_ROOT",
    "load_compact_face_config",
]
