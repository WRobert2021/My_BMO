"""Private, validated configuration owned by the Music feature."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bmo.jsonio import load_json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MUSIC_CONFIG_PATH = Path("config/music.json")
DEFAULT_MUSIC_ROOT = PROJECT_ROOT / "completed"
MAX_CONFIG_BYTES = 64 * 1024
_OWNED_KEYS = frozenset(
    {
        "music_root",
        "allowed_genres",
        "show_in_menu",
        "player_command",
    }
)


@dataclass(frozen=True, slots=True)
class MusicConfig:
    """Settings that belong only to local music discovery and playback."""

    music_root: Path = DEFAULT_MUSIC_ROOT
    allowed_genres: tuple[str, ...] = ("song",)
    show_in_menu: bool = True
    player_command: str = "ffplay"


def _path(value: object) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("music music_root must be a non-empty path")
    return Path(value).expanduser()


def _genres(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError("music allowed_genres must be a list of 1 to 16 names")
    genres: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 64:
            raise ValueError("music genres must be non-empty strings")
        normalized = item.strip().casefold()
        if normalized in genres:
            raise ValueError("music genres must be unique")
        genres.append(normalized)
    return tuple(genres)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"music {label} must be true or false")
    return value


def _command(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("music player_command must be a non-empty string")
    command = value.strip()
    if len(command) > 1024 or "\x00" in command:
        raise ValueError("music player_command is invalid")
    return command


def _parse(values: Mapping[str, Any]) -> MusicConfig:
    unknown = set(values).difference(_OWNED_KEYS)
    if unknown:
        raise ValueError(
            "unknown music setting(s): " + ", ".join(sorted(unknown))
        )
    return MusicConfig(
        music_root=_path(values.get("music_root", DEFAULT_MUSIC_ROOT)),
        allowed_genres=_genres(values.get("allowed_genres", ["song"])),
        show_in_menu=_boolean(values.get("show_in_menu", True), "show_in_menu"),
        player_command=_command(values.get("player_command", "ffplay")),
    )


def load_music_config(
    settings: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] | None = None,
) -> MusicConfig:
    """Load the optional private file, then apply feature-entry overrides."""
    emit = reporter or (lambda message: print(message, flush=True))
    raw_path = settings.get("config_path", DEFAULT_MUSIC_CONFIG_PATH)
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        emit("[MUSIC] Invalid config_path. Using defaults.")
        return MusicConfig()
    path = Path(raw_path).expanduser()
    file_values: Mapping[str, Any] = {}
    if path.exists():
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("configuration is too large")
            with path.open("r", encoding="utf-8") as handle:
                loaded = load_json(handle)
            if not isinstance(loaded, Mapping):
                raise ValueError("configuration root must be an object")
            file_values = loaded
        except (OSError, ValueError) as exc:
            emit(
                f"[MUSIC] Could not load configuration: "
                f"{type(exc).__name__}. Using defaults."
            )
            return MusicConfig()

    overrides = {
        key: value for key, value in settings.items() if key in _OWNED_KEYS
    }
    try:
        return _parse({**file_values, **overrides})
    except (TypeError, ValueError) as exc:
        emit(f"[MUSIC] Invalid settings: {exc}. Using defaults.")
        return MusicConfig()


__all__ = [
    "DEFAULT_MUSIC_CONFIG_PATH",
    "DEFAULT_MUSIC_ROOT",
    "MusicConfig",
    "load_music_config",
]
