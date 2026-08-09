"""Configured Raspberry Pi camera routing and execution feature."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
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

    def __init__(self, rotation: object = 0) -> None:
        self.rotation = rotation

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

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        if normalize_direct_text(user_text) in cls.direct_phrases:
            return {"action": cls.action}
        return None


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register configured camera capture, matching, and execution."""
    registry.register(CaptureImageTool(settings.get("camera_rotation", 0)))
