"""Typed contracts shared by executable BMO features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, TypeAlias


ToolRequest: TypeAlias = Mapping[str, Any]
ToolResponse: TypeAlias = str | None
ToolHandler: TypeAlias = Callable[[ToolRequest], ToolResponse]


class Tool(Protocol):
    """Structural contract accepted by :class:`ToolRegistry`."""

    action: str
    aliases: tuple[str, ...]

    def execute(self, request: ToolRequest) -> ToolResponse:
        """Execute the tool for a normalized action request."""


@dataclass(frozen=True)
class ToolContract:
    """Declarative tool metadata paired with its typed handler."""

    action: str
    handler: ToolHandler
    aliases: tuple[str, ...] = ()

    def execute(self, request: ToolRequest) -> ToolResponse:
        return self.handler(request)
