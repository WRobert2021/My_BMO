"""Configured Raspberry Pi camera routing and execution feature."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from bmo.features.contracts import (
    DirectAction,
    ToolAttachment,
    ToolAttachmentKind,
    ToolContext,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)


CAPTURE_TIMEOUT_SECONDS = 15
CAMERA_FAILURE_TEXT = "I could not use the camera right now."
DEFAULT_SAVE_DIRECTORY = Path.home() / "Pictures" / "bmo" / "what_do_you_see"


class CaptureImageTool:
    """Capture a configured still image and request vision processing."""

    action = "capture_image"
    aliases = ("look", "see")
    uses_context = True
    description = "Capture an image from the camera and describe what is visible."
    schemas = ('{"action":"capture_image"}',)
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples = (
        ("What do you see right now?", '{"action":"capture_image"}'),
    )
    direct_phrases = frozenset(
        {
            "take a photo",
            "take a picture",
            "capture a photo",
            "capture a picture",
            "what do you see",
            "what can you see",
            "look around",
        }
    )

    def __init__(
        self,
        rotation: object = 0,
        save_directory: object | None = None,
    ) -> None:
        self.rotation = rotation
        if save_directory is not None and not isinstance(
            save_directory,
            (str, Path),
        ):
            raise TypeError("save_directory must be a path string or null")
        if isinstance(save_directory, str) and not save_directory.strip():
            raise ValueError("save_directory must not be empty")
        self.save_directory = (
            Path(save_directory).expanduser() if save_directory else None
        )

    def execute(
        self,
        request: ToolRequest,
        context: ToolContext | None,
    ) -> ToolResult:
        del request
        if context is None:
            return ToolResult.error(CAMERA_FAILURE_TEXT)

        context.request_status("capturing", "Watching...")
        try:
            rotation = int(self.rotation)
            image_path = context.allocate_artifact(
                ToolAttachmentKind.IMAGE,
                ".jpg",
            )
            captured_path = self._capture(image_path, rotation=rotation)
            context.record_event(
                "image_captured",
                {"path": captured_path, "rotation": rotation},
            )
            self._save_persistent_copy(captured_path, context)
            return ToolResult.vision_follow_up(
                ToolAttachment.image(captured_path)
            )
        except Exception as exc:
            print(f"Camera Error: {exc}", flush=True)
            context.record_event("image_capture_failed", {"error": str(exc)})
            return ToolResult.error(CAMERA_FAILURE_TEXT)

    @staticmethod
    def _capture(output_path: str | Path, *, rotation: int = 0) -> str:
        """Capture one still and apply the configured image rotation."""
        image_path = Path(output_path)
        subprocess.run(
            [
                "rpicam-still",
                "-t",
                "500",
                "-n",
                "--width",
                "4608",
                "--height",
                "2592",
                "-o",
                str(image_path),
            ],
            check=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )
        if rotation:
            with Image.open(image_path) as image:
                image.rotate(rotation, expand=True).save(image_path)
        return str(image_path)

    def _save_persistent_copy(
        self,
        captured_path: str | Path,
        context: ToolContext,
    ) -> None:
        """Best-effort copy of a captured image to configured storage."""
        if self.save_directory is None:
            return

        try:
            saved_path = self._copy_capture(
                captured_path,
                self.save_directory,
            )
        except Exception as exc:
            print(f"Camera Save Error: {exc}", flush=True)
            context.record_event(
                "image_save_failed",
                {
                    "path": str(captured_path),
                    "save_directory": str(self.save_directory),
                    "error": str(exc),
                },
            )
            return

        context.record_event(
            "image_saved",
            {"path": saved_path, "source_path": str(captured_path)},
        )

    @staticmethod
    def _copy_capture(
        captured_path: str | Path,
        save_directory: str | Path,
    ) -> str:
        """Atomically copy one completed capture to persistent storage."""
        source = Path(captured_path)
        directory = Path(save_directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        suffix = source.suffix or ".jpg"
        destination = directory / (
            f"capture-{stamp}-{uuid.uuid4().hex[:8]}{suffix}"
        )
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return str(destination)

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        if normalize_direct_text(user_text) in cls.direct_phrases:
            return {"action": cls.action}
        return None


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register configured camera capture, matching, and execution."""
    registry.register(
        CaptureImageTool(
            settings.get("camera_rotation", 0),
            settings.get("save_directory", DEFAULT_SAVE_DIRECTORY),
        )
    )
