"""Configuration loading and shared application paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIRECTORY = Path("config")
SETTINGS_CONFIG_FILE = CONFIG_DIRECTORY / "settings.json"
FEATURES_CONFIG_FILE = CONFIG_DIRECTORY / "features.json"
WEATHER_CONFIG_FILE = CONFIG_DIRECTORY / "weather.json"
FEATURE_CONFIG_KEYS = frozenset({"features", "modes"})
# Retain the old public constant name for callers that import it. It now points
# at the user-settings file in the split configuration layout.
CONFIG_FILE = SETTINGS_CONFIG_FILE
MEMORY_FILE = Path("memory.json")
BMO_IMAGE_FILE = Path("current_image.jpg")
WAKE_WORD_MODEL = Path("wakeword.onnx")
WAKE_WORD_THRESHOLD = 0.5

DEFAULT_CONFIG: dict[str, Any] = {
    "text_model": "gemma3:1b",
    "vision_model": "moondream",
    "voice_model": "piper/en_GB-semaine-medium.onnx",
    "chat_memory": True,
    "camera_rotation": 0,
    "system_prompt": None,
    "system_prompt_extras": "",
    "input_device": None,
    "input_sample_rate": None,
    "whisper_binary": "whisper.cpp/build/bin/whisper-cli",
    "whisper_model": "whisper.cpp/models/ggml-base.en.bin",
    "weather_units": "imperial",
    "weather_config_path": None,
    "online_timeout_seconds": 6,
    "game_answer_wait_seconds": 12,
    "twenty_questions_debug": False,
    "interaction_logging": True,
    "interaction_log_directory": "interaction_logs",
}

OLLAMA_OPTIONS: dict[str, Any] = {
    "keep_alive": "-1",
    "num_thread": 4,
    "temperature": 0.7,
    "top_k": 40,
    "top_p": 0.9,
}

SOUND_DIRECTORIES = {
    "greeting": Path("sounds/greeting_sounds"),
    "ack": Path("sounds/ack_sounds"),
    "thinking": Path("sounds/thinking_sounds"),
    "error": Path("sounds/error_sounds"),
}


def _load_config_file(path: Path) -> dict[str, Any]:
    """Load one optional JSON configuration object."""
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)
    if not isinstance(values, dict):
        raise ValueError("configuration root must be a JSON object")
    return values


def _validate_settings_config(
    values: dict[str, Any],
    features_path: Path,
) -> None:
    misplaced_keys = FEATURE_CONFIG_KEYS.intersection(values)
    if misplaced_keys:
        names = ", ".join(sorted(misplaced_keys))
        raise ValueError(f"{names} must be configured in {features_path}")


def _validate_features_config(
    values: dict[str, Any],
    settings_path: Path,
) -> None:
    unexpected_keys = set(values).difference(FEATURE_CONFIG_KEYS)
    if unexpected_keys:
        names = ", ".join(sorted(unexpected_keys))
        raise ValueError(f"{names} must be configured in {settings_path}")


def load_config(
    settings_path: Path = SETTINGS_CONFIG_FILE,
    features_path: Path | None = None,
) -> dict[str, Any]:
    """Load user settings and extension configuration over known defaults.

    When a custom settings path is supplied without a feature path, the
    feature file is resolved beside it. This keeps isolated tests and alternate
    deployments from unexpectedly reading the repository's local config.
    """
    settings_path = Path(settings_path)
    if features_path is None:
        features_path = (
            FEATURES_CONFIG_FILE
            if settings_path == SETTINGS_CONFIG_FILE
            else settings_path.with_name(FEATURES_CONFIG_FILE.name)
        )
    else:
        features_path = Path(features_path)

    config = DEFAULT_CONFIG.copy()
    sources = (
        (
            settings_path,
            lambda values: _validate_settings_config(values, features_path),
        ),
        (
            features_path,
            lambda values: _validate_features_config(values, settings_path),
        ),
    )
    for path, validate in sources:
        try:
            values = _load_config_file(path)
            validate(values)
            config.update(values)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(
                f"Config Error in {path}: {exc}. Using defaults for that file.",
                flush=True,
            )
    if config.get("weather_config_path") is None:
        config["weather_config_path"] = (
            WEATHER_CONFIG_FILE
            if settings_path == SETTINGS_CONFIG_FILE
            else settings_path.with_name(WEATHER_CONFIG_FILE.name)
        )
    return config
