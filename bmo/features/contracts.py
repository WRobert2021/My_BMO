"""Typed contracts shared by executable BMO features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, TypeAlias


ToolRequest: TypeAlias = Mapping[str, Any]
ToolResponse: TypeAlias = str | None
ToolHandler: TypeAlias = Callable[[ToolRequest], ToolResponse]
DirectAction: TypeAlias = dict[str, str]
DirectMatcher: TypeAlias = Callable[[str], DirectAction | None]
PromptExample: TypeAlias = tuple[str, str]


def normalize_direct_text(user_text: str) -> str:
    """Normalize spoken text for deterministic direct-action matching."""
    return " ".join(user_text.lower().strip().rstrip("?.!").split())


class Tool(Protocol):
    """Structural contract accepted by :class:`ToolRegistry`."""

    action: str
    aliases: tuple[str, ...]
    description: str
    schemas: tuple[str, ...]
    prompt_guidance: tuple[str, ...]
    prompt_examples: tuple[PromptExample, ...]

    def execute(self, request: ToolRequest) -> ToolResponse:
        """Execute the tool for a normalized action request."""

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        """Return action JSON for an unambiguous direct phrase, if any."""


@dataclass(frozen=True)
class ToolContract:
    """Declarative tool metadata paired with its typed handler."""

    action: str
    handler: ToolHandler
    aliases: tuple[str, ...] = ()
    direct_matcher: DirectMatcher | None = None
    description: str = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[PromptExample, ...] = ()

    def execute(self, request: ToolRequest) -> ToolResponse:
        return self.handler(request)

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        if self.direct_matcher is None:
            return None
        return self.direct_matcher(user_text)
