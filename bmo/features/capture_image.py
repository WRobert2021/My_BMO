"""Camera-capture routing feature."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    normalize_direct_text,
)


class CaptureImageTool:
    """Signal the UI coordinator to capture and interpret an image."""

    action = "capture_image"
    aliases = ("look", "see")
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

    def execute(self, request: ToolRequest) -> str:
        del request
        return "IMAGE_CAPTURE_TRIGGERED"

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        if normalize_direct_text(user_text) in cls.direct_phrases:
            return {"action": cls.action}
        return None


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register camera-capture routing."""
    del settings
    registry.register(CaptureImageTool())
