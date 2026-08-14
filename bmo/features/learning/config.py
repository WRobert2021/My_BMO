"""Private, strictly validated configuration for the Learning feature.

Learning configuration is deliberately kept out of the application's shared
settings mapping.  Loading this module has no filesystem side effects.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import hmac
from pathlib import Path
from typing import Any

from bmo.jsonio import load_json


DEFAULT_LEARNING_CONFIG_PATH = Path("config/learning.json")
DEFAULT_DATA_DIRECTORY = Path("data/learning")
DEFAULT_GRAPHICS_DIRECTORY = Path("graphics/learning")
DEFAULT_FONT_FAMILIES = (
    "DejaVu Sans",
    "Liberation Sans",
    "Arial",
    "sans-serif",
)

MIN_SESSION_QUESTIONS = 3
MAX_SESSION_QUESTIONS = 20
MIN_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 10_000
MIN_MASTERY_HISTORY_LIMIT = 3
MAX_MASTERY_HISTORY_LIMIT = 100
MAX_CONFIG_BYTES = 64 * 1024

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OWNED_KEYS = frozenset(
    {
        "data_directory",
        "graphics_directory",
        "show_in_menu",
        "teacher_pin",
        "default_session_questions",
        "mastery_threshold",
        "mastery_min_evidence",
        "history_limit",
        "mastery_history_limit",
        "font_families",
        "speech_enabled",
        "debug_seed",
    }
)


@dataclass(frozen=True)
class LearningConfig:
    """Validated settings owned only by Learning.

    ``teacher_pin`` is excluded from the generated representation so routine
    diagnostics cannot accidentally disclose it.  Call
    :meth:`verify_teacher_pin` instead of comparing or logging it elsewhere.
    """

    data_directory: Path = DEFAULT_DATA_DIRECTORY
    graphics_directory: Path = DEFAULT_GRAPHICS_DIRECTORY
    show_in_menu: bool = True
    teacher_pin: str = field(default="0000", repr=False)
    default_session_questions: int = 8
    mastery_threshold: float = 0.8
    mastery_min_evidence: int = 5
    history_limit: int = 2_000
    mastery_history_limit: int = 20
    font_families: tuple[str, ...] = DEFAULT_FONT_FAMILIES
    speech_enabled: bool = True
    debug_seed: int | None = None

    def verify_teacher_pin(self, candidate: object) -> bool:
        """Return whether *candidate* matches without exposing the stored PIN."""
        if not isinstance(candidate, str):
            return False
        return hmac.compare_digest(self.teacher_pin, candidate)


def _path(value: object, label: str, default: Path) -> Path:
    if value is None:
        return default
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"learning {label} must be a non-empty path")
    return Path(value).expanduser()


def _owned_directory(
    value: object,
    *,
    label: str,
    default: Path,
    root_name: str,
    project_root: Path,
) -> Path:
    supplied = _path(value, label, default)
    project = project_root.expanduser().absolute()
    owned_root = (project / root_name).absolute()
    candidate = supplied.absolute() if supplied.is_absolute() else (project / supplied).absolute()

    if owned_root.is_symlink():
        raise ValueError(
            f"learning {label} cannot use a symlinked {root_name}/ root"
        )

    try:
        relative = candidate.relative_to(owned_root)
    except ValueError as exc:
        raise ValueError(
            f"learning {label} must stay inside the project's {root_name}/ folder"
        ) from exc
    if not relative.parts:
        raise ValueError(f"learning {label} must use its own folder in {root_name}/")

    # ``resolve(strict=False)`` follows only components that already exist. It
    # catches a configured symlink that escapes the owned tree without creating
    # either tree during configuration loading.
    resolved_root = owned_root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"learning {label} cannot follow a symlink outside {root_name}/"
        ) from exc

    # Preserve conventional project-relative paths in the public config while
    # retaining absolute paths explicitly supplied by tests or deployments.
    return candidate if supplied.is_absolute() else Path(root_name) / relative


def _boolean(value: object, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"learning {label} must be true or false")
    return value


def _bounded_integer(
    value: object,
    label: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"learning {label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"learning {label} must be between {minimum} and {maximum}"
        )
    return value


def _threshold(value: object) -> float:
    if value is None:
        return 0.8
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("learning mastery_threshold must be a number")
    parsed = float(value)
    if not 0.5 <= parsed <= 1.0:
        raise ValueError("learning mastery_threshold must be between 0.5 and 1.0")
    return parsed


def _teacher_pin(value: object) -> str:
    if value is None:
        return "0000"
    if not isinstance(value, str) or len(value) != 4 or not value.isascii() or not value.isdigit():
        raise ValueError("learning teacher_pin must contain exactly four ASCII digits")
    return value


def _font_families(value: object) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_FONT_FAMILIES
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("learning font_families must be a list of 1 to 8 names")
    fonts: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 64:
            raise ValueError("learning font family names must be non-empty strings")
        fonts.append(item.strip())
    if len({font.casefold() for font in fonts}) != len(fonts):
        raise ValueError("learning font family names must be unique")
    return tuple(fonts)


def _debug_seed(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("learning debug_seed must be an integer or null")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("learning debug_seed must be between 0 and 4294967295")
    return value


def _parse(values: Mapping[str, Any], *, project_root: Path) -> LearningConfig:
    unknown = set(values).difference(_OWNED_KEYS)
    if unknown:
        raise ValueError("unknown learning setting(s): " + ", ".join(sorted(unknown)))
    mastery_min_evidence = _bounded_integer(
        values.get("mastery_min_evidence"),
        "mastery_min_evidence",
        5,
        2,
        20,
    )
    mastery_history_limit = _bounded_integer(
        values.get("mastery_history_limit"),
        "mastery_history_limit",
        20,
        MIN_MASTERY_HISTORY_LIMIT,
        MAX_MASTERY_HISTORY_LIMIT,
    )
    if mastery_history_limit < mastery_min_evidence:
        raise ValueError(
            "learning mastery_history_limit must be at least "
            "mastery_min_evidence"
        )
    return LearningConfig(
        data_directory=_owned_directory(
            values.get("data_directory"),
            label="data_directory",
            default=DEFAULT_DATA_DIRECTORY,
            root_name="data",
            project_root=project_root,
        ),
        graphics_directory=_owned_directory(
            values.get("graphics_directory"),
            label="graphics_directory",
            default=DEFAULT_GRAPHICS_DIRECTORY,
            root_name="graphics",
            project_root=project_root,
        ),
        show_in_menu=_boolean(values.get("show_in_menu"), "show_in_menu", True),
        teacher_pin=_teacher_pin(values.get("teacher_pin")),
        default_session_questions=_bounded_integer(
            values.get("default_session_questions"),
            "default_session_questions",
            8,
            MIN_SESSION_QUESTIONS,
            MAX_SESSION_QUESTIONS,
        ),
        mastery_threshold=_threshold(values.get("mastery_threshold")),
        mastery_min_evidence=mastery_min_evidence,
        history_limit=_bounded_integer(
            values.get("history_limit"),
            "history_limit",
            2_000,
            MIN_HISTORY_LIMIT,
            MAX_HISTORY_LIMIT,
        ),
        mastery_history_limit=mastery_history_limit,
        font_families=_font_families(values.get("font_families")),
        speech_enabled=_boolean(
            values.get("speech_enabled"), "speech_enabled", True
        ),
        debug_seed=_debug_seed(values.get("debug_seed")),
    )


def _safe_defaults(project_root: Path) -> LearningConfig:
    """Return defaults, disabling the menu if even default roots are unsafe."""
    try:
        return _parse({}, project_root=project_root)
    except (OSError, TypeError, ValueError):
        return LearningConfig(show_in_menu=False)


def load_learning_config(
    settings: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] = print,
    project_root: str | Path | None = None,
) -> LearningConfig:
    """Load private Learning JSON and apply only Learning-owned overrides.

    Shared application settings supplied by the extension loader are ignored.
    A malformed private file or override produces one non-sensitive report and
    returns safe in-memory defaults; the private file is never created.
    """
    root = (
        Path(project_root).expanduser().absolute()
        if project_root is not None
        else _PROJECT_ROOT
    )
    try:
        path = _path(
            settings.get("config_path", DEFAULT_LEARNING_CONFIG_PATH),
            "config_path",
            DEFAULT_LEARNING_CONFIG_PATH,
        )
        if not path.is_absolute():
            path = root / path
    except (TypeError, ValueError) as exc:
        reporter(f"[LEARNING] Invalid config path: {exc}. Using defaults.")
        return _safe_defaults(root)

    file_values: Mapping[str, Any] = {}
    if path.exists():
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("learning configuration file is too large")
            with path.open("r", encoding="utf-8") as handle:
                loaded = load_json(handle)
            if not isinstance(loaded, Mapping):
                raise ValueError("learning configuration root must be an object")
            file_values = loaded
        except (OSError, ValueError) as exc:
            # JSON exceptions do not include document contents. In particular,
            # never report the PIN or any other config values.
            reporter(f"[LEARNING] Could not load private configuration: {exc}. Using defaults.")
            file_values = {}

    overrides = {key: value for key, value in settings.items() if key in _OWNED_KEYS}
    try:
        return _parse({**file_values, **overrides}, project_root=root)
    except (TypeError, ValueError) as exc:
        reporter(f"[LEARNING] Invalid settings: {exc}. Using defaults.")
        return _safe_defaults(root)
