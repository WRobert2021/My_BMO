"""Configured-location tool and its deterministic direct phrases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)
from bmo.location import LocationError, LocationNotConfigured, LocationService


class GetLocationTool:
    """Report the configured home location."""

    action = "get_location"
    aliases = ("location", "where_am_i")
    description = "Report the configured home location."
    schemas = ('{"action":"get_location"}',)
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples = (("Where am I?", '{"action":"get_location"}'),)
    direct_phrases = frozenset(
        {
            "where am i",
            "what is my location",
            "what's my location",
            "whats my location",
            "what city am i in",
            "where are we",
        }
    )

    def __init__(self, location_service: LocationService) -> None:
        self.location_service = location_service

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        try:
            location = self.location_service.resolve()
            return ToolResult.model_summarized(
                f"Your configured location is {location.name}."
            )
        except LocationNotConfigured:
            return ToolResult.model_summarized(
                "I do not have a home location configured yet. "
                "Add one in config.json."
            )
        except (LocationError, OSError, TimeoutError) as exc:
            print(f"[LOCATION] Lookup failed: {exc}", flush=True)
            return ToolResult.model_summarized(
                "I cannot check the configured location right now."
            )

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        if normalize_direct_text(user_text) in cls.direct_phrases:
            return {"action": cls.action}
        return None


def _online_timeout(settings: Mapping[str, Any]) -> float:
    try:
        timeout = float(settings.get("online_timeout_seconds", 6))
    except (TypeError, ValueError):
        print(
            "[CONFIG] online_timeout_seconds must be numeric; using 6.",
            flush=True,
        )
        timeout = 6.0
    return min(max(timeout, 1.0), 30.0)


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register configured-location lookup."""
    service = LocationService(
        settings.get("location"),
        timeout=_online_timeout(settings),
    )
    registry.register(GetLocationTool(service))
