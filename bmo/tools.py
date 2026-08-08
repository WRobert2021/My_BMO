"""Compatibility facade for registered BMO features and camera routing."""

from __future__ import annotations

import datetime
from typing import Any

from bmo.config import load_config
from bmo.features import (
    GetLocationTool,
    GetTimeTool,
    GetWeatherTool,
    SearchWebTool,
    ToolRegistry,
    ToolRequest,
    clean_weather_location,
    normalize_direct_text,
)
from bmo.location import LocationService
from bmo.weather import WeatherService


_FEATURE_TOOL_TYPES = (
    GetTimeTool,
    GetLocationTool,
    GetWeatherTool,
    SearchWebTool,
)
_FEATURE_ACTIONS = {tool_type.action for tool_type in _FEATURE_TOOL_TYPES}
_FEATURE_ALIASES = {
    alias: tool_type.action
    for tool_type in _FEATURE_TOOL_TYPES
    for alias in tool_type.aliases
}


class ToolRouter:
    """Preserve the legacy routing API while features own tool behavior."""

    VALID_TOOLS = {*_FEATURE_ACTIONS, "capture_image"}
    ALIASES = {
        **_FEATURE_ALIASES,
        "look": "capture_image",
        "see": "capture_image",
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        effective_config = config or load_config()
        try:
            timeout = float(effective_config.get("online_timeout_seconds", 6))
        except (TypeError, ValueError):
            print(
                "[CONFIG] online_timeout_seconds must be numeric; using 6.",
                flush=True,
            )
            timeout = 6.0
        timeout = min(max(timeout, 1.0), 30.0)

        location_service = LocationService(
            effective_config.get("location"),
            timeout=timeout,
        )
        weather_service = WeatherService(
            location_service,
            timeout=timeout,
            units=str(effective_config.get("weather_units", "imperial")),
        )
        self._get_time_tool = GetTimeTool(
            now=lambda: datetime.datetime.now()
        )
        self._get_location_tool = GetLocationTool(location_service)
        self._get_weather_tool = GetWeatherTool(weather_service)
        self._search_web_tool = SearchWebTool(
            searcher=lambda query: self._search_web(query)
        )
        self.registry = ToolRegistry(
            (
                self._get_time_tool,
                self._get_location_tool,
                self._get_weather_tool,
                self._search_web_tool,
            )
        )

    @property
    def location_service(self) -> LocationService:
        """Expose the location dependency retained by the legacy router API."""
        return self._get_location_tool.location_service

    @location_service.setter
    def location_service(self, service: LocationService) -> None:
        self._get_location_tool.location_service = service

    @property
    def weather_service(self) -> WeatherService:
        """Expose the weather dependency retained by the legacy router API."""
        return self._get_weather_tool.weather_service

    @weather_service.setter
    def weather_service(self, service: WeatherService) -> None:
        self._get_weather_tool.weather_service = service

    @property
    def last_tool_details(self) -> dict[str, Any] | None:
        """Expose web-search details for the existing archive workflow."""
        return self._search_web_tool.last_details

    @last_tool_details.setter
    def last_tool_details(self, details: dict[str, Any] | None) -> None:
        self._search_web_tool.last_details = details

    @classmethod
    def normalize_action(cls, action_data: dict[str, Any]) -> str:
        return ToolRegistry.resolve_action(action_data, cls.ALIASES)

    @staticmethod
    def clean_weather_location(place_name: str) -> str:
        return clean_weather_location(place_name)

    @staticmethod
    def match_direct_action(user_text: str) -> dict[str, str] | None:
        """Route unambiguous built-in requests without probabilistic output."""
        for tool_type in _FEATURE_TOOL_TYPES:
            action_data = tool_type.match_direct_action(user_text)
            if action_data is not None:
                return action_data

        normalized = normalize_direct_text(user_text)
        camera_requests = {
            "take a photo",
            "take a picture",
            "capture a photo",
            "capture a picture",
            "what do you see",
            "what can you see",
            "look around",
        }
        if normalized in camera_requests:
            return {"action": "capture_image"}
        return None

    def execute(self, action_data: dict[str, Any]) -> str | None:
        self.last_tool_details = None
        raw_action = str(action_data.get("action", "")).lower().strip()
        value = action_data.get("value") or action_data.get("query")
        action = self.normalize_action(action_data)
        print(f"ACTION: {raw_action} -> {action}", flush=True)

        if action not in self.VALID_TOOLS:
            if value and isinstance(value, str) and len(value.split()) > 1:
                return f"CHAT_FALLBACK::{value}"
            return "INVALID_ACTION"

        # Camera capture remains owned by BotGUI; this symbolic response keeps
        # its existing ToolRouter boundary until that feature is migrated.
        if action == "capture_image":
            return "IMAGE_CAPTURE_TRIGGERED"

        return self.registry.execute(action_data)

    def _execute_get_time(self, action_data: ToolRequest) -> str:
        """Compatibility wrapper for the migrated time feature."""
        return self._get_time_tool.execute(action_data)

    def _execute_get_location(self, action_data: ToolRequest) -> str:
        """Compatibility wrapper for the migrated location feature."""
        return self._get_location_tool.execute(action_data)

    def _execute_get_weather(self, action_data: ToolRequest) -> str:
        """Compatibility wrapper for the migrated weather feature."""
        return self._get_weather_tool.execute(action_data)

    def _execute_search_web(self, action_data: ToolRequest) -> str:
        """Compatibility wrapper for the migrated web-search feature."""
        value = action_data.get("value") or action_data.get("query")
        return self._search_web(str(value or "").strip())

    def _search_web(self, query: str) -> str:
        """Compatibility wrapper retaining search results for archives."""
        return self._search_web_tool.search(query)
