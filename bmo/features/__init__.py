"""Typed feature infrastructure with lazy compatibility exports."""

from __future__ import annotations

from importlib import import_module

from bmo.features.contracts import (
    DirectAction,
    DirectMatcher,
    FeatureAnnouncer,
    FeatureAnnouncementCompletion,
    FeatureFaceProvider,
    FeatureMenuContext,
    FeatureMenuItem,
    FeatureVisionCompletion,
    FeatureVisionRequester,
    ModelRequestPreparer,
    PromptExample,
    RequestNormalizer,
    RuntimeCallback,
    RuntimeAttention,
    RuntimeAttentionCallback,
    RuntimeAttentionDismissal,
    RuntimeAttentionEvent,
    RuntimeNotification,
    Tool,
    ToolArchive,
    ToolAttachment,
    ToolAttachmentKind,
    ToolContract,
    ToolContext,
    ToolEvent,
    ToolFollowUp,
    ToolFollowUpKind,
    ToolHandler,
    ToolRequest,
    ToolPresentation,
    ToolPresentationKind,
    ToolResult,
    ToolResultKind,
    ToolResponse,
    ToolStatusUpdate,
    match_exact_direct_action,
    normalize_direct_text,
)
from bmo.features.loader import (
    DEFAULT_FEATURE_MODULES,
    FeatureLoadFailure,
    FeatureLoadResult,
    load_feature_registry,
)
from bmo.features.registry import (
    DuplicateToolError,
    ToolCapability,
    ToolRegistry,
    UnknownToolError,
)


_LAZY_EXPORTS = {
    "GetLocationTool": ("bmo.features.get_location", "GetLocationTool"),
    "GetTimeTool": ("bmo.features.get_time", "GetTimeTool"),
    "GetWeatherTool": ("bmo.features.get_weather", "GetWeatherTool"),
    "SearchWebTool": ("bmo.features.search_web", "SearchWebTool"),
    "ScheduledTimer": ("bmo.features.set_timer", "ScheduledTimer"),
    "SetTimerTool": ("bmo.features.set_timer", "SetTimerTool"),
    "TimerScheduler": ("bmo.features.set_timer", "TimerScheduler"),
    "format_duration": ("bmo.features.set_timer", "format_duration"),
    "parse_duration": ("bmo.features.set_timer", "parse_duration"),
    "clean_weather_location": (
        "bmo.features.get_weather",
        "clean_weather_location",
    ),
}


def __getattr__(name: str):
    """Import legacy feature exports only when callers explicitly use them."""
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = [
    "DuplicateToolError",
    "DirectAction",
    "DirectMatcher",
    "DEFAULT_FEATURE_MODULES",
    "FeatureLoadFailure",
    "FeatureLoadResult",
    "FeatureAnnouncer",
    "FeatureAnnouncementCompletion",
    "FeatureFaceProvider",
    "FeatureMenuContext",
    "FeatureMenuItem",
    "FeatureVisionCompletion",
    "FeatureVisionRequester",
    "GetLocationTool",
    "GetTimeTool",
    "GetWeatherTool",
    "ModelRequestPreparer",
    "PromptExample",
    "RequestNormalizer",
    "RuntimeCallback",
    "RuntimeAttention",
    "RuntimeAttentionCallback",
    "RuntimeAttentionDismissal",
    "RuntimeAttentionEvent",
    "RuntimeNotification",
    "ScheduledTimer",
    "SearchWebTool",
    "SetTimerTool",
    "Tool",
    "ToolArchive",
    "ToolAttachment",
    "ToolAttachmentKind",
    "ToolCapability",
    "ToolContract",
    "ToolContext",
    "ToolEvent",
    "ToolFollowUp",
    "ToolFollowUpKind",
    "ToolHandler",
    "ToolRegistry",
    "ToolRequest",
    "ToolPresentation",
    "ToolPresentationKind",
    "ToolResult",
    "ToolResultKind",
    "ToolResponse",
    "ToolStatusUpdate",
    "TimerScheduler",
    "UnknownToolError",
    "clean_weather_location",
    "format_duration",
    "match_exact_direct_action",
    "normalize_direct_text",
    "load_feature_registry",
    "parse_duration",
]
