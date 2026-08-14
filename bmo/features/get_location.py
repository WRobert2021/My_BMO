"""Configured-location tool and its deterministic direct phrases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    ToolResult,
    match_exact_direct_action,
)
from bmo.location import LocationError, LocationNotConfigured, LocationService
from bmo.network import online_timeout_seconds


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
                "Add one in config/settings.json."
            )
        except (LocationError, OSError, TimeoutError) as exc:
            print(f"[LOCATION] Lookup failed: {exc}", flush=True)
            return ToolResult.model_summarized(
                "I cannot check the configured location right now."
            )

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        return match_exact_direct_action(
            user_text,
            action=cls.action,
            phrases=cls.direct_phrases,
        )


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register configured-location lookup."""
    service = LocationService(
        settings.get("location"),
        timeout=online_timeout_seconds(settings),
    )
    registry.register(GetLocationTool(service))
