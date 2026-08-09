"""Compatibility facade for configuration-driven BMO features."""

from __future__ import annotations

import datetime
from typing import Any

from bmo.config import load_config
from bmo.features.contracts import RuntimeCallback, ToolResult
from bmo.features.loader import FeatureLoadFailure, load_feature_registry
from bmo.features.registry import ToolRegistry


_DEFAULT_ACTIONS = {
    "get_time",
    "set_timer",
    "get_location",
    "get_weather",
    "search_web",
    "capture_image",
}
_DEFAULT_ALIASES = {
    "check_time": "get_time",
    "timer": "set_timer",
    "location": "get_location",
    "where_am_i": "get_location",
    "weather": "get_weather",
    "forecast": "get_weather",
    "check_weather": "get_weather",
    "google": "search_web",
    "browser": "search_web",
    "news": "search_web",
    "search_news": "search_web",
    "look": "capture_image",
    "see": "capture_image",
}
_default_router: ToolRouter | None = None


class ToolRouter:
    """Preserve the routing API while loading tools from configuration."""

    # Class-level defaults preserve the historical introspection API. Each
    # instance shadows these with the actions it actually loaded.
    VALID_TOOLS = set(_DEFAULT_ACTIONS)
    ALIASES = dict(_DEFAULT_ALIASES)

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        runtime_callback: RuntimeCallback | None = None,
    ) -> None:
        effective_config = load_config() if config is None else config
        result = load_feature_registry(
            effective_config,
            shared_settings={
                key: value
                for key, value in effective_config.items()
                if key != "features"
            },
            runtime_callback=runtime_callback,
        )
        self.registry = result.registry
        self.feature_failures: tuple[FeatureLoadFailure, ...] = result.failures
        self.feature_modules = result.modules
        self.VALID_TOOLS = self.registry.actions
        self.ALIASES = self.registry.aliases

        time_tool = self.registry.get("get_time")
        if time_tool is not None and hasattr(time_tool, "_now"):
            time_tool._now = lambda: datetime.datetime.now()

        # Retain the patchable compatibility boundary used by archive and test
        # callers while the feature continues to own the real search work.
        search_tool = self.registry.get("search_web")
        if search_tool is not None and hasattr(search_tool, "_searcher"):
            search_tool._searcher = lambda query: self._search_web(query)

    def _require_tool(self, action: str) -> Any:
        tool = self.registry.get(action)
        if tool is None:
            raise AttributeError(f"Feature '{action}' is not enabled.")
        return tool

    @property
    def location_service(self) -> Any:
        """Expose the location dependency retained by the legacy router API."""
        return self._require_tool("get_location").location_service

    @location_service.setter
    def location_service(self, service: Any) -> None:
        self._require_tool("get_location").location_service = service

    @property
    def weather_service(self) -> Any:
        """Expose the weather dependency retained by the legacy router API."""
        return self._require_tool("get_weather").weather_service

    @weather_service.setter
    def weather_service(self, service: Any) -> None:
        self._require_tool("get_weather").weather_service = service

    def normalize_action(
        self,
        action_data: dict[str, Any] | None = None,
    ) -> str:
        """Normalize using instance actions, or defaults for a class call."""
        if isinstance(self, ToolRouter):
            request = action_data or {}
            return ToolRegistry.resolve_action(request, self.ALIASES)

        # Compatibility for ToolRouter.normalize_action(action_data).
        request = self
        return ToolRegistry.resolve_action(request, _DEFAULT_ALIASES)

    def normalize_request(self, action_data: dict[str, Any]) -> dict[str, Any]:
        """Apply action aliases and feature-specific request normalization."""
        return self.registry.normalize_request(action_data)

    @staticmethod
    def clean_weather_location(place_name: str) -> str:
        """Retain the old helper without importing weather during startup."""
        from bmo.features.get_weather import clean_weather_location

        return clean_weather_location(place_name)

    def match_direct_action(
        self,
        user_text: str | None = None,
    ) -> dict[str, str] | None:
        """Match direct phrases using only enabled feature modules."""
        if isinstance(self, ToolRouter):
            return self.registry.match_direct_action(str(user_text or ""))

        # Compatibility for ToolRouter.match_direct_action(user_text).
        return _get_default_router().registry.match_direct_action(str(self))

    def execute(self, action_data: dict[str, Any]) -> ToolResult:
        raw_action = str(action_data.get("action", "")).lower().strip()
        value = action_data.get("value") or action_data.get("query")
        action = self.normalize_action(action_data)
        print(f"ACTION: {raw_action} -> {action}", flush=True)

        if action not in self.VALID_TOOLS:
            if value and isinstance(value, str) and len(value.split()) > 1:
                return ToolResult.chat_fallback(value)
            return ToolResult.invalid_action()
        return self.registry.execute(action_data)

    def close(self) -> None:
        """Close feature-owned workers and other runtime resources."""
        self.registry.close()

    def _execute_get_time(self, action_data: dict[str, Any]) -> ToolResult:
        """Compatibility wrapper for the time feature."""
        return self.registry.execute(action_data)

    def _execute_get_location(self, action_data: dict[str, Any]) -> ToolResult:
        """Compatibility wrapper for the location feature."""
        return self.registry.execute(action_data)

    def _execute_get_weather(self, action_data: dict[str, Any]) -> ToolResult:
        """Compatibility wrapper for the weather feature."""
        return self.registry.execute(action_data)

    def _execute_search_web(self, action_data: dict[str, Any]) -> ToolResult:
        """Compatibility wrapper retaining search results for archives."""
        value = action_data.get("value") or action_data.get("query")
        return self._search_web(str(value or "").strip())

    def _search_web(self, query: str) -> ToolResult:
        """Compatibility wrapper retaining search results for archives."""
        search_tool = self._require_tool("search_web")
        return search_tool.search(query)


def _get_default_router() -> ToolRouter:
    """Lazily create a default router for legacy class-method-style calls."""
    global _default_router
    if _default_router is None:
        _default_router = ToolRouter({"online_timeout_seconds": 6})
    return _default_router
