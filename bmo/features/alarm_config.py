"""Private configuration owned by the alarm-clock feature."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bmo.jsonio import load_json
from bmo.repository_paths import relocated_repository_path


DEFAULT_ALARM_CONFIG_PATH = Path("config/alarm_clock.json")
DEFAULT_ALARM_STATE_PATH = Path("bmo/data/alarms/alarms.json")
MAX_CONFIG_BYTES = 64 * 1024
_OWNED_KEYS = frozenset(
    {"show_in_menu", "state_path", "snooze_minutes", "use_24_hour"}
)


@dataclass(frozen=True, slots=True)
class AlarmClockConfig:
    """Validated feature-owned alarm settings."""

    show_in_menu: bool = True
    state_path: Path = DEFAULT_ALARM_STATE_PATH
    snooze_minutes: int = 9
    use_24_hour: bool = False


def _parse(values: Mapping[str, Any]) -> AlarmClockConfig:
    unknown = set(values).difference(_OWNED_KEYS)
    if unknown:
        raise ValueError(
            "unknown alarm-clock setting(s): " + ", ".join(sorted(unknown))
        )
    show_in_menu = values.get("show_in_menu", True)
    use_24_hour = values.get("use_24_hour", False)
    if not isinstance(show_in_menu, bool):
        raise TypeError("alarm-clock show_in_menu must be true or false")
    if not isinstance(use_24_hour, bool):
        raise TypeError("alarm-clock use_24_hour must be true or false")
    raw_path = values.get("state_path", DEFAULT_ALARM_STATE_PATH)
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        raise ValueError("alarm-clock state_path must be a non-empty path")
    raw_snooze = values.get("snooze_minutes", 9)
    if isinstance(raw_snooze, bool) or not isinstance(raw_snooze, int):
        raise TypeError("alarm-clock snooze_minutes must be an integer")
    if not 1 <= raw_snooze <= 60:
        raise ValueError("alarm-clock snooze_minutes must be from 1 to 60")
    return AlarmClockConfig(
        show_in_menu=show_in_menu,
        state_path=relocated_repository_path(raw_path),
        snooze_minutes=raw_snooze,
        use_24_hour=use_24_hour,
    )


def load_alarm_clock_config(
    settings: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] | None = None,
) -> AlarmClockConfig:
    """Load the optional private file, then apply feature-entry overrides."""
    emit = reporter or (lambda message: print(message, flush=True))
    raw_path = settings.get("config_path", DEFAULT_ALARM_CONFIG_PATH)
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        emit("[ALARM] Invalid config_path. Using defaults.")
        return AlarmClockConfig()
    config_path = Path(raw_path).expanduser()
    file_values: Mapping[str, Any] = {}
    if config_path.exists():
        try:
            if config_path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("configuration is too large")
            with config_path.open("r", encoding="utf-8") as handle:
                loaded = load_json(handle)
            if not isinstance(loaded, Mapping):
                raise ValueError("configuration root must be an object")
            file_values = loaded
        except (OSError, ValueError) as exc:
            emit(
                "[ALARM] Could not load configuration: "
                f"{type(exc).__name__}. Using defaults."
            )
            return AlarmClockConfig()
    overrides = {key: value for key, value in settings.items() if key in _OWNED_KEYS}
    try:
        return _parse({**file_values, **overrides})
    except (TypeError, ValueError) as exc:
        emit(f"[ALARM] Invalid settings: {exc}. Using defaults.")
        return AlarmClockConfig()


__all__ = [
    "AlarmClockConfig",
    "DEFAULT_ALARM_CONFIG_PATH",
    "DEFAULT_ALARM_STATE_PATH",
    "load_alarm_clock_config",
]
