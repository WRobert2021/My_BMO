"""Typed contracts shared by executable BMO features."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, TypeAlias


ToolRequest: TypeAlias = Mapping[str, Any]
DirectAction: TypeAlias = dict[str, str]
DirectMatcher: TypeAlias = Callable[[str], DirectAction | None]
PromptExample: TypeAlias = tuple[str, str]


@dataclass(frozen=True)
class RuntimeNotification:
    """A feature-originated message approved for runtime presentation."""

    source: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("Runtime notification source cannot be empty.")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("Runtime notification message cannot be empty.")


RuntimeCallback: TypeAlias = Callable[[RuntimeNotification], None]


class ToolResultKind(str, Enum):
    """Ways a tool result can be presented by the application."""

    CONTENT = "content"
    EMPTY = "empty"
    ERROR = "error"
    INVALID_ACTION = "invalid_action"
    CHAT_FALLBACK = "chat_fallback"
    CAPTURE_IMAGE = "capture_image"


@dataclass(frozen=True)
class ToolResult:
    """Typed result returned by every registered tool."""

    kind: ToolResultKind
    content: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ToolResultKind):
            raise TypeError("ToolResult kind must be a ToolResultKind.")
        content_kinds = {
            ToolResultKind.CONTENT,
            ToolResultKind.CHAT_FALLBACK,
        }
        if self.kind in content_kinds and not isinstance(self.content, str):
            raise TypeError(f"{self.kind.value} results require string content.")
        if self.kind not in content_kinds and self.content is not None:
            raise ValueError(
                f"{self.kind.value} results cannot include content."
            )

    @classmethod
    def success(cls, content: str) -> ToolResult:
        return cls(ToolResultKind.CONTENT, content)

    @classmethod
    def empty(cls) -> ToolResult:
        return cls(ToolResultKind.EMPTY)

    @classmethod
    def error(cls) -> ToolResult:
        return cls(ToolResultKind.ERROR)

    @classmethod
    def invalid_action(cls) -> ToolResult:
        return cls(ToolResultKind.INVALID_ACTION)

    @classmethod
    def chat_fallback(cls, content: str) -> ToolResult:
        return cls(ToolResultKind.CHAT_FALLBACK, content)

    @classmethod
    def capture_image(cls) -> ToolResult:
        return cls(ToolResultKind.CAPTURE_IMAGE)

    def archive_value(self) -> dict[str, str | None]:
        """Return a stable JSON-friendly representation for interaction logs."""
        return {"kind": self.kind.value, "content": self.content}


ToolResponse: TypeAlias = ToolResult
ToolHandler: TypeAlias = Callable[[ToolRequest], ToolResponse]


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
