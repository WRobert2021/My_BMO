"""Configuration loading and shared application paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_FILE = Path("config.json")
MEMORY_FILE = Path("memory.json")
BMO_IMAGE_FILE = Path("current_image.jpg")
WAKE_WORD_MODEL = Path("wakeword.onnx")
WAKE_WORD_THRESHOLD = 0.5

DEFAULT_CONFIG: dict[str, Any] = {
    "text_model": "gemma:2b",
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
    "location": {
        "name": "",
        "latitude": None,
        "longitude": None,
        "timezone": "auto",
    },
    "weather_units": "imperial",
    "online_timeout_seconds": 6,
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


def load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    """Load JSON configuration over known defaults."""
    config = DEFAULT_CONFIG.copy()
    if not path.exists():
        return config

    try:
        with path.open("r", encoding="utf-8") as handle:
            user_config = json.load(handle)
        if not isinstance(user_config, dict):
            raise ValueError("configuration root must be a JSON object")
        config.update(user_config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Config Error: {exc}. Using defaults.", flush=True)
    return config
