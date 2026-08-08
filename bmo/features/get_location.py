"""Configured-location tool and its deterministic direct phrases."""

from __future__ import annotations

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    normalize_direct_text,
)
from bmo.location import LocationError, LocationNotConfigured, LocationService


class GetLocationTool:
    """Report the configured home location."""

    action = "get_location"
    aliases = ("location", "where_am_i")
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

    def execute(self, request: ToolRequest) -> str:
        del request
        try:
            location = self.location_service.resolve()
            return f"Your configured location is {location.name}."
        except LocationNotConfigured:
            return (
                "I do not have a home location configured yet. "
                "Add one in config.json."
            )
        except (LocationError, OSError, TimeoutError) as exc:
            print(f"[LOCATION] Lookup failed: {exc}", flush=True)
            return "I cannot check the configured location right now."

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        if normalize_direct_text(user_text) in cls.direct_phrases:
            return {"action": cls.action}
        return None
