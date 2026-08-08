"""Typed feature contracts and registry infrastructure."""

from bmo.features.contracts import (
    DirectAction,
    DirectMatcher,
    Tool,
    ToolContract,
    ToolHandler,
    ToolRequest,
    ToolResponse,
    normalize_direct_text,
)
from bmo.features.get_location import GetLocationTool
from bmo.features.get_time import GetTimeTool
from bmo.features.get_weather import GetWeatherTool, clean_weather_location
from bmo.features.registry import (
    DuplicateToolError,
    ToolRegistry,
    UnknownToolError,
)
from bmo.features.search_web import SearchWebTool

__all__ = [
    "DuplicateToolError",
    "DirectAction",
    "DirectMatcher",
    "GetLocationTool",
    "GetTimeTool",
    "GetWeatherTool",
    "SearchWebTool",
    "Tool",
    "ToolContract",
    "ToolHandler",
    "ToolRegistry",
    "ToolRequest",
    "ToolResponse",
    "UnknownToolError",
    "clean_weather_location",
    "normalize_direct_text",
]
