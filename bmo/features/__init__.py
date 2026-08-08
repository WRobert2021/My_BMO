"""Typed feature infrastructure with lazy compatibility exports."""

from __future__ import annotations

from importlib import import_module

from bmo.features.contracts import (
    DirectAction,
    DirectMatcher,
    PromptExample,
    Tool,
    ToolContract,
    ToolHandler,
    ToolRequest,
    ToolResult,
    ToolResultKind,
    ToolResponse,
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
    "GetLocationTool",
    "GetTimeTool",
    "GetWeatherTool",
    "PromptExample",
    "SearchWebTool",
    "Tool",
    "ToolCapability",
    "ToolContract",
    "ToolHandler",
    "ToolRegistry",
    "ToolRequest",
    "ToolResult",
    "ToolResultKind",
    "ToolResponse",
    "UnknownToolError",
    "clean_weather_location",
    "normalize_direct_text",
    "load_feature_registry",
]
