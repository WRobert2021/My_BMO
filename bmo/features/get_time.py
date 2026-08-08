"""Current-time tool and its deterministic direct phrases."""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)


class GetTimeTool:
    """Report the current local time."""

    action = "get_time"
    aliases = ("check_time",)
    description = "Report the current local time."
    schemas = ('{"action":"get_time"}',)
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples = (("What time is it?", '{"action":"get_time"}'),)
    direct_phrases = frozenset(
        {
            "what time is it",
            "what's the time",
            "whats the time",
            "tell me the time",
            "what is the current time",
            "current time",
        }
    )

    def __init__(
        self,
        now: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._now = now or datetime.datetime.now

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        now = self._now().strftime("%I:%M %p")
        return ToolResult.success(f"The current time is {now}.")

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        if normalize_direct_text(user_text) in cls.direct_phrases:
            return {"action": cls.action}
        return None


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register the current-time feature."""
    del settings
    registry.register(GetTimeTool())
