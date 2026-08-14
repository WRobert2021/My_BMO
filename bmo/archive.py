"""Durable, per-interaction archives for BMO activity."""

from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bmo.jsonio import atomic_write_json


ARCHIVE_CATEGORIES = ("input", "output", "web", "images")


def normalize_archive_category(value: object) -> str:
    """Return a known archive category without surrounding whitespace."""
    if not isinstance(value, str):
        raise TypeError("Archive category must be a string.")
    category = value.strip()
    if category not in ARCHIVE_CATEGORIES:
        raise ValueError(f"Unknown archive category: {category}")
    return category


def normalize_archive_filename(value: object) -> str:
    """Return one safe leaf filename for an archive category."""
    if not isinstance(value, str):
        raise TypeError("Archive filename must be a string.")
    filename = value.strip()
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        raise ValueError("Archive filename must be one non-empty leaf name.")
    return filename


def normalize_archive_suffix(value: object) -> str:
    """Return a short alphanumeric extension for an archive artifact."""
    if not isinstance(value, str):
        raise TypeError("Archive suffix must be a string.")
    suffix = value.strip()
    if (
        not suffix.startswith(".")
        or not suffix[1:].isalnum()
        or len(suffix) > 16
    ):
        raise ValueError(
            "Archive suffix must be a short alphanumeric file extension."
        )
    return suffix


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json_safe(value: Any) -> Any:
    """Convert SDK response objects and paths into JSON-safe values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump())
    return str(value)


class InteractionArchive:
    """One never-reused directory containing everything from a single turn."""

    CATEGORIES = ARCHIVE_CATEGORIES

    def __init__(self, root: Path, trigger: str) -> None:
        now = datetime.now(timezone.utc)
        interaction_id = (
            f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        self.path = (
            root
            / now.strftime("%Y")
            / now.strftime("%m")
            / now.strftime("%d")
            / interaction_id
        )
        self.id = interaction_id
        self._lock = threading.Lock()
        self._manifest = {
            "schema_version": 1,
            "interaction_id": interaction_id,
            "trigger": trigger,
            "started_at": _utc_now(),
            "status": "in_progress",
        }
        for category in self.CATEGORIES:
            (self.path / category).mkdir(parents=True, exist_ok=False)
        self._write_manifest()
        self.event("interaction_started", {"trigger": trigger})

    @property
    def audio_path(self) -> Path:
        return self.path / "input" / "voice.wav"

    def image_path(self, suffix: str = ".jpg") -> Path:
        """Return a collision-resistant destination for a captured image."""
        stamp = datetime.now(timezone.utc).strftime("%H%M%S.%f")
        return (
            self.path
            / "images"
            / f"capture-{stamp}{normalize_archive_suffix(suffix)}"
        )

    def speech_path(self) -> Path:
        """Return a unique destination for one synthesized speech segment."""
        stamp = datetime.now(timezone.utc).strftime("%H%M%S.%f")
        return self.path / "output" / f"speech-{stamp}.wav"

    def write_text(self, category: str, filename: str, text: str) -> Path:
        destination = self._category_file_path(category, filename)
        with self._lock:
            destination.write_text(text, encoding="utf-8")
        return destination

    def append_text(self, category: str, filename: str, text: str) -> Path:
        destination = self._category_file_path(category, filename)
        with self._lock, destination.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
        return destination

    def append_json(self, category: str, filename: str, data: dict[str, Any]) -> Path:
        destination = self._category_file_path(category, filename)
        record = {**_json_safe(data), "timestamp": _utc_now()}
        with self._lock, destination.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            )
        return destination

    def event(self, name: str, data: dict[str, Any] | None = None) -> None:
        record = {"timestamp": _utc_now(), "event": name, "data": data or {}}
        with self._lock, (self.path / "events.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(
                json.dumps(
                    _json_safe(record),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )

    def finish(self, status: str = "completed", error: str | None = None) -> None:
        self.event("interaction_finished", {"status": status, "error": error})
        with self._lock:
            self._manifest["status"] = status
            self._manifest["finished_at"] = _utc_now()
            if error:
                self._manifest["error"] = error
            self._write_manifest_unlocked()

    def _category_path(self, category: str) -> Path:
        return self.path / normalize_archive_category(category)

    def _category_file_path(self, category: str, filename: str) -> Path:
        return self._category_path(category) / normalize_archive_filename(
            filename
        )

    def _write_manifest(self) -> None:
        with self._lock:
            self._write_manifest_unlocked()

    def _write_manifest_unlocked(self) -> None:
        atomic_write_json(
            self.path / "manifest.json",
            self._manifest,
            indent=2,
            ensure_ascii=False,
        )


class InteractionArchiveManager:
    """Factory that can disable logging without changing call sites."""

    def __init__(self, root: str | Path, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled

    def begin(self, trigger: str) -> InteractionArchive | None:
        if not self.enabled:
            return None
        return InteractionArchive(self.root, trigger)
