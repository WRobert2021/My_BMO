"""Typed contracts shared by executable BMO features."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
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
    ATTACHMENT = "attachment"
    FOLLOW_UP = "follow_up"


class ToolAttachmentKind(str, Enum):
    """Attachment types understood by the core application."""

    IMAGE = "image"


class ToolFollowUpKind(str, Enum):
    """Generic application follow-ups requested by a feature result."""

    VISION = "vision"


@dataclass(frozen=True)
class ToolAttachment:
    """A typed local artifact returned by an executable feature."""

    kind: ToolAttachmentKind
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ToolAttachmentKind):
            raise TypeError("Attachment kind must be a ToolAttachmentKind.")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("Attachment path cannot be empty.")

    @classmethod
    def image(cls, path: str | Path) -> ToolAttachment:
        """Return a typed image attachment for a local path."""
        return cls(ToolAttachmentKind.IMAGE, str(path))

    def archive_value(self) -> dict[str, str]:
        """Return a stable JSON-friendly attachment representation."""
        return {"kind": self.kind.value, "path": self.path}


@dataclass(frozen=True)
class ToolFollowUp:
    """A feature-neutral request for core processing of an attachment."""

    kind: ToolFollowUpKind
    attachment: ToolAttachment

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ToolFollowUpKind):
            raise TypeError("Follow-up kind must be a ToolFollowUpKind.")
        if not isinstance(self.attachment, ToolAttachment):
            raise TypeError("Follow-up attachment must be a ToolAttachment.")
        if (
            self.kind is ToolFollowUpKind.VISION
            and self.attachment.kind is not ToolAttachmentKind.IMAGE
        ):
            raise ValueError("Vision follow-ups require an image attachment.")

    @classmethod
    def vision(cls, attachment: ToolAttachment) -> ToolFollowUp:
        """Ask the application to run a vision turn for an image."""
        return cls(ToolFollowUpKind.VISION, attachment)

    def archive_value(self) -> dict[str, Any]:
        """Return a stable JSON-friendly follow-up representation."""
        return {
            "kind": self.kind.value,
            "attachment": self.attachment.archive_value(),
        }


@dataclass(frozen=True)
class ToolEvent:
    """A structured interaction event emitted during tool execution."""

    name: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool event name cannot be empty.")
        if not isinstance(self.data, Mapping):
            raise TypeError("Tool event data must be a mapping.")


@dataclass(frozen=True)
class ToolStatusUpdate:
    """A generic UI status requested during tool execution."""

    state: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, str) or not self.state.strip():
            raise ValueError("Tool status state cannot be empty.")
        if not isinstance(self.message, str):
            raise TypeError("Tool status message must be a string.")


ArtifactAllocator: TypeAlias = Callable[
    [ToolAttachmentKind, str], Path
]
ToolEventRecorder: TypeAlias = Callable[[ToolEvent], None]
ToolStatusRequester: TypeAlias = Callable[[ToolStatusUpdate], None]


@dataclass(frozen=True)
class ToolContext:
    """Narrow, per-execution access to approved runtime services."""

    artifact_allocator: ArtifactAllocator
    event_recorder: ToolEventRecorder
    status_requester: ToolStatusRequester

    def __post_init__(self) -> None:
        for name in (
            "artifact_allocator",
            "event_recorder",
            "status_requester",
        ):
            if not callable(getattr(self, name)):
                raise TypeError(f"Tool context {name} must be callable.")

    def allocate_artifact(
        self,
        kind: ToolAttachmentKind,
        suffix: str,
    ) -> Path:
        """Allocate a runtime-approved path for one local artifact."""
        if not isinstance(kind, ToolAttachmentKind):
            raise TypeError("Artifact kind must be a ToolAttachmentKind.")
        if not isinstance(suffix, str) or not suffix.startswith("."):
            raise ValueError("Artifact suffix must start with '.'.")
        path = self.artifact_allocator(kind, suffix)
        if not isinstance(path, Path):
            raise TypeError("Artifact allocator must return pathlib.Path.")
        return path

    def record_event(
        self,
        name: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a structured event in the active interaction, if any."""
        self.event_recorder(ToolEvent(name, data or {}))

    def request_status(self, state: str, message: str = "") -> None:
        """Request a runtime-owned UI status update."""
        self.status_requester(ToolStatusUpdate(state, message))


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
    attachments: tuple[ToolAttachment, ...] = ()
    follow_up: ToolFollowUp | None = None

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
        if not isinstance(self.attachments, tuple) or any(
            not isinstance(attachment, ToolAttachment)
            for attachment in self.attachments
        ):
            raise TypeError("ToolResult attachments must be ToolAttachments.")
        if self.follow_up is not None and not isinstance(
            self.follow_up,
            ToolFollowUp,
        ):
            raise TypeError("ToolResult follow-up must be a ToolFollowUp.")
        if self.kind is ToolResultKind.ATTACHMENT:
            if not self.attachments:
                raise ValueError("Attachment results require an attachment.")
            if self.follow_up is not None:
                raise ValueError(
                    "Attachment results cannot include a follow-up."
                )
        elif self.kind is ToolResultKind.FOLLOW_UP:
            if self.follow_up is None:
                raise ValueError("Follow-up results require a follow-up.")
            if self.follow_up.attachment not in self.attachments:
                raise ValueError(
                    "Follow-up attachment must be included in attachments."
                )
        elif self.attachments or self.follow_up is not None:
            raise ValueError(
                "Only attachment and follow-up results can carry artifacts."
            )
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
    def image_attachment(
        cls,
        attachment: ToolAttachment,
        user_text: str | None = None,
        *,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        """Return an image for generic UI presentation."""
        if not isinstance(attachment, ToolAttachment):
            raise TypeError("Image results require a ToolAttachment.")
        if attachment.kind is not ToolAttachmentKind.IMAGE:
            raise ValueError("Image results require an image attachment.")
        return cls(
            ToolResultKind.ATTACHMENT,
            presentation=ToolPresentation.direct(user_text),
            archive=archive or ToolArchive(),
            attachments=(attachment,),
        )

    @classmethod
    def vision_follow_up(
        cls,
        attachment: ToolAttachment,
        *,
        archive: ToolArchive | None = None,
    ) -> ToolResult:
        """Ask the core application to run vision on an image attachment."""
        follow_up = ToolFollowUp.vision(attachment)
        return cls(
            ToolResultKind.FOLLOW_UP,
            archive=archive or ToolArchive(),
            attachments=(attachment,),
            follow_up=follow_up,
        )

    def archive_value(self) -> dict[str, Any]:
        """Return a stable JSON-friendly representation for interaction logs."""
        value: dict[str, Any] = {
            "kind": self.kind.value,
            "content": self.content,
        }
        if self.attachments:
            value["attachments"] = [
                attachment.archive_value()
                for attachment in self.attachments
            ]
        if self.follow_up is not None:
            value["follow_up"] = self.follow_up.archive_value()
        return value


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
