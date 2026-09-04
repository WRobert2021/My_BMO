"""Private calendar configuration loading without global-settings merging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from bmo.features.calendar_store import DEFAULT_CATEGORIES
from bmo.jsonio import load_json
from bmo.repository_paths import relocated_repository_path


DEFAULT_CALENDAR_CONFIG_PATH = Path("config/calendar.json")
DEFAULT_DATA_DIRECTORY = Path("bmo/data/calendar")
DEFAULT_OVERLAY_DIRECTORY = Path("graphics/faces/calendar")


@dataclass(frozen=True)
class CalendarConfig:
    """Validated settings owned only by the calendar feature."""

    data_directory: Path = DEFAULT_DATA_DIRECTORY
    overlay_directory: Path = DEFAULT_OVERLAY_DIRECTORY
    show_in_menu: bool = True
    built_in_us_holidays: bool = True
    speak_notes: bool = False
    categories: tuple[str, ...] = DEFAULT_CATEGORIES


def _path(value: object, label: str, default: Path) -> Path:
    if value is None:
        return default
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"calendar {label} must be a non-empty path")
    return relocated_repository_path(value)


def _boolean(value: object, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"calendar {label} must be true or false")
    return value


def _categories(value: object) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_CATEGORIES
    if not isinstance(value, list) or not value:
        raise ValueError("calendar categories must be a non-empty list")
    categories = tuple(str(item).strip() for item in value)
    if any(not item for item in categories):
        raise ValueError("calendar category names cannot be empty")
    if len({item.casefold() for item in categories}) != len(categories):
        raise ValueError("calendar category names must be unique")
    if "holiday" not in {item.casefold() for item in categories}:
        categories = (*categories, "Holiday")
    return categories


def _parse(values: Mapping[str, Any]) -> CalendarConfig:
    allowed = {
        "data_directory",
        "overlay_directory",
        "show_in_menu",
        "built_in_us_holidays",
        "speak_notes",
        "categories",
    }
    unknown = set(values).difference(allowed)
    if unknown:
        raise ValueError(
            "unknown calendar setting(s): " + ", ".join(sorted(unknown))
        )
    return CalendarConfig(
        data_directory=_path(
            values.get("data_directory"),
            "data_directory",
            DEFAULT_DATA_DIRECTORY,
        ),
        overlay_directory=_path(
            values.get("overlay_directory"),
            "overlay_directory",
            DEFAULT_OVERLAY_DIRECTORY,
        ),
        show_in_menu=_boolean(values.get("show_in_menu"), "show_in_menu", True),
        built_in_us_holidays=_boolean(
            values.get("built_in_us_holidays"),
            "built_in_us_holidays",
            True,
        ),
        speak_notes=_boolean(values.get("speak_notes"), "speak_notes", False),
        categories=_categories(values.get("categories")),
    )


def load_calendar_config(
    settings: Mapping[str, Any],
    *,
    reporter=print,
) -> CalendarConfig:
    """Load a private JSON file, then apply feature-entry overrides."""
    raw_path = settings.get("config_path", DEFAULT_CALENDAR_CONFIG_PATH)
    path = _path(raw_path, "config_path", DEFAULT_CALENDAR_CONFIG_PATH)
    file_values: Mapping[str, Any] = {}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                loaded = load_json(handle)
            if not isinstance(loaded, Mapping):
                raise ValueError("calendar configuration root must be an object")
            file_values = loaded
        except (OSError, ValueError) as exc:
            reporter(f"[CALENDAR] Could not load {path}: {exc}. Using defaults.")
    owned_keys = {
        "data_directory",
        "overlay_directory",
        "show_in_menu",
        "built_in_us_holidays",
        "speak_notes",
        "categories",
    }
    # Feature loading supplies shared application settings as fallbacks. Keep
    # this private file independent by considering only calendar-owned keys.
    overrides = {key: value for key, value in settings.items() if key in owned_keys}
    try:
        return _parse({**file_values, **overrides})
    except (TypeError, ValueError) as exc:
        reporter(f"[CALENDAR] Invalid settings: {exc}. Using defaults.")
        return CalendarConfig()
