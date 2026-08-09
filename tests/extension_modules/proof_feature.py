"""Configuration-only feature fixture exercising the complete tool contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)


class ConfiguredEchoTool:
    """Small stateful tool used to prove third-party feature integration."""

    action = "configured_echo"
    aliases = ("echo_extension",)
    description = "Repeat configured text a requested number of times."
    schemas = (
        '{"action":"configured_echo","message":"text","repeat":2}',
    )
    prompt_guidance = (
        "Preserve configured_echo message strings and numeric repeat values.",
    )
    prompt_examples = (
        (
            "Echo hello twice.",
            '{"action":"configured_echo","message":"hello","repeat":2}',
        ),
    )

    def __init__(
        self,
        *,
        direct_phrase: str,
        response_prefix: str,
        error_text: str,
        failure_token: str,
        max_repeat: int,
    ) -> None:
        self.direct_phrase = normalize_direct_text(direct_phrase)
        self.response_prefix = response_prefix
        self.error_text = error_text
        self.failure_token = failure_token
        self.max_repeat = max_repeat
        self.close_count = 0

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        normalized = normalize_direct_text(user_text)
        prefix = f"{self.direct_phrase} "
        if not normalized.startswith(prefix):
            return None
        message = normalized[len(prefix):].strip()
        if not message:
            return None
        return {"action": self.action, "message": message, "repeat": "1"}

    @staticmethod
    def normalize_request(request: ToolRequest) -> dict[str, Any]:
        normalized = dict(request)
        message = request.get("message")
        if isinstance(message, str):
            normalized["message"] = " ".join(message.strip().split())
        repeat = request.get("repeat", 1)
        if isinstance(repeat, str) and repeat.strip().isdigit():
            repeat = int(repeat.strip())
        elif isinstance(repeat, float) and repeat.is_integer():
            repeat = int(repeat)
        normalized["repeat"] = repeat
        return normalized

    def prepare_model_request(
        self,
        request: ToolRequest,
    ) -> dict[str, Any] | None:
        message = request.get("message")
        repeat = request.get("repeat")
        if not isinstance(message, str) or not message:
            return None
        if isinstance(repeat, bool) or not isinstance(repeat, int):
            return None
        if not 1 <= repeat <= self.max_repeat:
            return None
        return dict(request)

    def execute(self, request: ToolRequest) -> ToolResult:
        message = request.get("message")
        repeat = request.get("repeat")
        if message == self.failure_token:
            return ToolResult.error(self.error_text)
        if not isinstance(message, str) or not message:
            return ToolResult.error(self.error_text)
        if isinstance(repeat, bool) or not isinstance(repeat, int):
            return ToolResult.error(self.error_text)
        if not 1 <= repeat <= self.max_repeat:
            return ToolResult.error(self.error_text)
        repeated = " | ".join(message for _ in range(repeat))
        return ToolResult.direct(f"{self.response_prefix}: {repeated}")

    def close(self) -> None:
        """Record one idempotent cleanup for the integration assertion."""
        if self.close_count == 0:
            self.close_count = 1


def register(
    registry: Any,
    settings: Mapping[str, Any],
) -> None:
    """Build the fixture entirely from its feature configuration entry."""
    registry.register(
        ConfiguredEchoTool(
            direct_phrase=str(settings.get("direct_phrase", "extension echo")),
            response_prefix=str(settings.get("response_prefix", "Echo")),
            error_text=str(settings.get("error_text", "Extension failed.")),
            failure_token=str(settings.get("failure_token", "fail")),
            max_repeat=int(settings.get("max_repeat", 3)),
        )
    )
