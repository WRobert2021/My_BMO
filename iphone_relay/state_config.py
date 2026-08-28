"""Strict, resource-free configuration for Stage 3 relay-owned state."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .errors import StateConfigError
from .state import MAX_SQLITE_INTEGER, RetryPolicy


STATE_CONFIG_SCHEMA_VERSION = 1
DEFAULT_RELATIVE_STATE_PATH = Path("data/imessage_relay/relay_state.db")
MAX_CONFIG_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class RelayStateConfig:
    state_path: Path
    retry_policy: RetryPolicy


def load_state_config(
    config_path: Path | str,
    *,
    base_directory: Path | str | None = None,
) -> RelayStateConfig:
    """Load private relay-state settings or return in-memory defaults if absent."""

    path = Path(config_path).expanduser()
    base = (
        Path(base_directory).expanduser().resolve(strict=False)
        if base_directory is not None
        else Path.cwd().resolve()
    )
    if path.is_symlink():
        raise StateConfigError("relay state configuration cannot be a symbolic link")
    if not path.exists():
        return RelayStateConfig(
            state_path=(base / DEFAULT_RELATIVE_STATE_PATH).resolve(strict=False),
            retry_policy=RetryPolicy(),
        )
    if not path.is_file():
        raise StateConfigError("relay state configuration must be a regular file")
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise StateConfigError("relay state configuration exceeds the size limit")
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StateConfigError("relay state configuration could not be read") from exc
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise StateConfigError("relay state configuration is not valid JSON") from exc
    if not isinstance(value, dict):
        raise StateConfigError("relay state configuration must be an object")
    _exact_keys(value, {"schema_version", "state_path", "retry_policy"})
    if _positive_int(value["schema_version"], "schema version") != 1:
        raise StateConfigError("relay state configuration version is unsupported")

    state_path_raw = value["state_path"]
    if not isinstance(state_path_raw, str) or not state_path_raw or "\x00" in state_path_raw:
        raise StateConfigError("relay state path must be a non-empty string")
    configured_path = Path(state_path_raw).expanduser()
    state_path = (
        configured_path.resolve(strict=False)
        if configured_path.is_absolute()
        else (base / configured_path).resolve(strict=False)
    )

    retry = value["retry_policy"]
    if not isinstance(retry, dict):
        raise StateConfigError("retry policy must be an object")
    _exact_keys(
        retry,
        {
            "initial_delay_seconds",
            "multiplier",
            "max_delay_seconds",
            "max_attempts",
            "lease_duration_seconds",
        },
    )
    initial_delay_seconds = _positive_int(
        retry["initial_delay_seconds"],
        "initial delay",
    )
    max_delay_seconds = _positive_int(retry["max_delay_seconds"], "maximum delay")
    lease_duration_seconds = _positive_int(
        retry["lease_duration_seconds"],
        "lease duration",
    )
    for seconds, label in (
        (initial_delay_seconds, "initial delay"),
        (max_delay_seconds, "maximum delay"),
        (lease_duration_seconds, "lease duration"),
    ):
        if seconds > MAX_SQLITE_INTEGER // 1_000:
            raise StateConfigError(f"{label} exceeds the supported range")
    try:
        retry_policy = RetryPolicy(
            initial_delay_ms=initial_delay_seconds * 1_000,
            multiplier=_positive_int(retry["multiplier"], "retry multiplier"),
            max_delay_ms=max_delay_seconds * 1_000,
            max_attempts=_positive_int(retry["max_attempts"], "maximum attempts"),
            lease_duration_ms=lease_duration_seconds * 1_000,
        )
    except ValueError as exc:
        raise StateConfigError("retry policy values are inconsistent") from exc
    return RelayStateConfig(state_path=state_path, retry_policy=retry_policy)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StateConfigError("relay state configuration has duplicate fields")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    del value
    raise StateConfigError("relay state configuration contains a non-finite number")


def _exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise StateConfigError("relay state configuration fields are invalid")


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StateConfigError(f"{label} must be a positive integer")
    return value
