"""Configuration-only interaction-mode fixture for architecture tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bmo.modes.contracts import InputPolicy, ModeRuntimeContext


class ConfiguredTestMode:
    """Minimal multi-turn mode with observable lifecycle state."""

    name = "configured_test_mode"

    def __init__(
        self,
        context: ModeRuntimeContext,
        *,
        start_phrase: str,
        stop_phrase: str,
        response_text: str,
        silence_timeout: float,
    ) -> None:
        self.context = context
        self.start_phrase = start_phrase
        self.stop_phrase = stop_phrase
        self.response_text = response_text
        self.silence_timeout = silence_timeout
        self.active = False
        self.started_with: list[str] = []
        self.inputs: list[str] = []
        self.close_count = 0

    def matches_start_request(self, user_text: str) -> bool:
        return user_text.strip().lower() == self.start_phrase.lower()

    def start(self, user_text: str) -> None:
        self.started_with.append(user_text)
        self.active = True
        self.context.speak_response(self.response_text, None)
        self.context.remember_turn(user_text, self.response_text)

    def handle_input(self, user_text: str) -> None:
        self.inputs.append(user_text)
        if user_text.strip().lower() == self.stop_phrase.lower():
            self.active = False

    def is_active(self) -> bool:
        return self.active

    def input_policy(self) -> InputPolicy:
        return InputPolicy.continuous(
            initial_silence_timeout=self.silence_timeout,
            listening_status="Test mode listening",
            no_speech_status="Test mode waiting",
            empty_transcript_status="Test mode retry",
            trigger_source="TEST_MODE",
        )

    def close(self) -> None:
        self.active = False
        if self.close_count == 0:
            self.close_count = 1


def register(
    registry: Any,
    context: ModeRuntimeContext,
    settings: Mapping[str, Any],
) -> None:
    """Construct the fixture solely from context and its config settings."""
    registry.register(
        ConfiguredTestMode(
            context,
            start_phrase=str(settings.get("start_phrase", "start test mode")),
            stop_phrase=str(settings.get("stop_phrase", "stop test mode")),
            response_text=str(settings.get("response_text", "Test mode ready.")),
            silence_timeout=float(settings.get("silence_timeout", 5)),
        )
    )
