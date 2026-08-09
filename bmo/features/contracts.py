"""Typed contracts shared by executable BMO features."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, TypeAlias


ToolRequest: TypeAlias = Mapping[str, Any]
DirectAction: TypeAlias = dict[str, str]
DirectMatcher: TypeAlias = Callable[[str], DirectAction | None]
PromptExample: TypeAlias = tuple[str, str]
RequestNormalizer: TypeAlias = Callable[[ToolRequest], Mapping[str, Any]]
ModelRequestPreparer: TypeAlias = Callable[
    [ToolRequest], Mapping[str, Any] | None
]


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
    """Semantic outcomes returned by executable tools."""

    CONTENT = "content"
    EMPTY = "empty"
    ERROR = "error"
    INVALID_ACTION = "invalid_action"
    CHAT_FALLBACK = "chat_fallback"
    CAPTURE_IMAGE = "capture_image"


class ToolPresentationKind(str, Enum):
    """Declarative strategies for presenting a tool result."""

    DIRECT = "direct"
    SUMMARIZE = "summarize"


DEFAULT_SUMMARY_SYSTEM_PROMPT = "Summarize this result in one short sentence."
DEFAULT_SUMMARY_USER_PROMPT = "RESULT: {content}\nUser Question: {user_text}"


@dataclass(frozen=True)
class ToolPresentation:
    """User-facing text or local-model instructions for one result."""

    kind: ToolPresentationKind
    user_text: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    strip_response: bool = False
    model_routed: ToolPresentation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ToolPresentationKind):
            raise TypeError(
                "Tool presentation kind must be a ToolPresentationKind."
            )
        if self.model_routed is not None and not isinstance(
            self.model_routed,
            ToolPresentation,
        ):
            raise TypeError(
                "Model-routed presentation must be a ToolPresentation."
            )
        if self.kind is ToolPresentationKind.DIRECT:
            if (
                self.system_prompt is not None
                or self.user_prompt_template is not None
            ):
                raise ValueError(
                    "Direct presentation cannot include summary prompts."
                )
            if self.strip_response:
                raise ValueError(
                    "Direct presentation cannot strip a model response."
                )
        else:
            if self.user_text is not None:
                raise ValueError(
                    "Summary presentation cannot include direct user text."
                )
            if not isinstance(self.system_prompt, str) or not self.system_prompt:
                raise TypeError(
                    "Summary presentation requires a system prompt."
                )
            if (
                not isinstance(self.user_prompt_template, str)
                or not self.user_prompt_template
            ):
                raise TypeError(
                    "Summary presentation requires a user prompt template."
                )

    @classmethod
    def direct(cls, user_text: str | None = None) -> ToolPresentation:
        """Present supplied text without another model call."""
        if user_text is not None and not isinstance(user_text, str):
            raise TypeError("Direct presentation text must be a string.")
        return cls(ToolPresentationKind.DIRECT, user_text=user_text)

    @classmethod
    def summarize(
        cls,
        *,
        system_prompt: str = DEFAULT_SUMMARY_SYSTEM_PROMPT,
        user_prompt_template: str = DEFAULT_SUMMARY_USER_PROMPT,
        strip_response: bool = False,
    ) -> ToolPresentation:
        """Ask the local model to summarize content with feature-owned prompts."""
        return cls(
            ToolPresentationKind.SUMMARIZE,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            strip_response=strip_response,
        )

    @classmethod
    def by_route(
        cls,
        *,
        direct: ToolPresentation,
        model_routed: ToolPresentation,
    ) -> ToolPresentation:
        """Select declarative presentation without inspecting an action name."""
        if not isinstance(direct, cls) or not isinstance(model_routed, cls):
            raise TypeError("Route presentations must be ToolPresentation values.")
        return replace(direct, model_routed=model_routed)

    def for_route(self, *, direct: bool) -> ToolPresentation:
        """Resolve the feature-owned presentation for one routing source."""
        if not direct and self.model_routed is not None:
            return self.model_routed
        return self

    def summary_messages(
        self,
        *,
        content: str,
        user_text: str,
    ) -> list[dict[str, str]]:
        """Render local-model messages for a summarized result."""
        if self.kind is not ToolPresentationKind.SUMMARIZE:
            raise ValueError("Direct presentation has no summary messages.")
        assert self.system_prompt is not None
        assert self.user_prompt_template is not None
        return [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": self.user_prompt_template.format(
                    content=content,
                    user_text=user_text,
                ),
            },
        ]


@dataclass(frozen=True)
class ToolArchive:
    """Declarative archive destination and feature-owned structured details."""

    category: str = "output"
    filename: str = "tools.jsonl"
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("Tool archive category cannot be empty.")
        if not isinstance(self.filename, str) or not self.filename.strip():
            raise ValueError("Tool archive filename cannot be empty.")
        if self.details is not None and not isinstance(self.details, dict):
            raise TypeError("Tool archive details must be a dictionary.")


@dataclass(frozen=True)
class ToolResult:
    """Typed result returned by every registered tool."""

    kind: ToolResultKind
    content: str | None = None
    presentation: ToolPresentation = field(
        default_factory=ToolPresentation.direct
    )
    archive: ToolArchive = field(default_factory=ToolArchive)

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
        if not isinstance(self.presentation, ToolPresentation):
            raise TypeError(
                "ToolResult presentation must be a ToolPresentation."
            )
        if not isinstance(self.archive, ToolArchive):
            raise TypeError("ToolResult archive must be a ToolArchive.")
        presentations = [self.presentation]
        if self.presentation.model_routed is not None:
            presentations.append(self.presentation.model_routed)
        if self.kind is not ToolResultKind.CONTENT and any(
            presentation.kind is ToolPresentationKind.SUMMARIZE
            for presentation in presentations
        ):
            raise ValueError("Only content results can be summarized.")
        if self.kind in {ToolResultKind.EMPTY, ToolResultKind.ERROR}:
            if any(
                not presentation.user_text
                for presentation in presentations
            ):
                raise ValueError(
                    f"{self.kind.value} results require user-facing text."
                )

    @classmethod
    def success(
        cls,
        content: str,
        *,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        """Return user-ready content without another model call."""
        return cls(
            ToolResultKind.CONTENT,
            content,
            ToolPresentation.direct(),
            archive or ToolArchive(),
        )

    direct = success

    @classmethod
    def summarized(
        cls,
        content: str,
        *,
        presentation: ToolPresentation | None = None,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        """Return content that the local model should summarize."""
        summary = presentation or ToolPresentation.summarize()
        if summary.kind is not ToolPresentationKind.SUMMARIZE:
            raise ValueError(
                "Summarized results require summary presentation metadata."
            )
        return cls(
            ToolResultKind.CONTENT,
            content,
            summary,
            archive or ToolArchive(),
        )

    @classmethod
    def model_summarized(
        cls,
        content: str,
        *,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        """Present direct matches verbatim and summarize model-routed matches."""
        return cls(
            ToolResultKind.CONTENT,
            content,
            ToolPresentation.by_route(
                direct=ToolPresentation.direct(),
                model_routed=ToolPresentation.summarize(),
            ),
            archive or ToolArchive(),
        )

    @classmethod
    def empty(
        cls,
        user_text: str = "I could not find anything for that request.",
        *,
        model_routed_text: str | None = None,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        presentation = ToolPresentation.direct(user_text)
        if model_routed_text is not None:
            presentation = ToolPresentation.by_route(
                direct=presentation,
                model_routed=ToolPresentation.direct(model_routed_text),
            )
        return cls(
            ToolResultKind.EMPTY,
            presentation=presentation,
            archive=archive or ToolArchive(),
        )

    @classmethod
    def error(
        cls,
        user_text: str = "I could not complete that request.",
        *,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        return cls(
            ToolResultKind.ERROR,
            presentation=ToolPresentation.direct(user_text),
            archive=archive or ToolArchive(),
        )

    @classmethod
    def invalid_action(cls) -> ToolResult:
        return cls(
            ToolResultKind.INVALID_ACTION,
            presentation=ToolPresentation.direct(
                "I am not sure how to do that."
            ),
        )

    @classmethod
    def chat_fallback(cls, content: str) -> ToolResult:
        return cls(ToolResultKind.CHAT_FALLBACK, content)

    @classmethod
    def capture_image(cls) -> ToolResult:
        return cls(
            ToolResultKind.CAPTURE_IMAGE,
            presentation=ToolPresentation.direct(
                "I could not use the camera right now."
            ),
        )

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
    request_normalizer: RequestNormalizer | None = None
    model_request_preparer: ModelRequestPreparer | None = None

    def execute(self, request: ToolRequest) -> ToolResponse:
        return self.handler(request)

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        if self.direct_matcher is None:
            return None
        return self.direct_matcher(user_text)

    def normalize_request(self, request: ToolRequest) -> dict[str, Any]:
        if self.request_normalizer is None:
            return dict(request)
        return dict(self.request_normalizer(request))

    def prepare_model_request(
        self,
        request: ToolRequest,
    ) -> dict[str, Any] | None:
        if self.model_request_preparer is None:
            return dict(request)
        prepared = self.model_request_preparer(request)
        return None if prepared is None else dict(prepared)
