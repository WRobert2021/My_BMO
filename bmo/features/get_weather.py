"""Current-weather tool and its deterministic direct phrases."""

from __future__ import annotations

import re

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    normalize_direct_text,
)
from bmo.location import LocationError, LocationNotConfigured
from bmo.weather import WeatherError, WeatherService


WEATHER_AT_HOME = frozenset(
    {
        "weather",
        "weather today",
        "today's weather",
        "todays weather",
        "what is the weather",
        "what's the weather",
        "whats the weather",
        "what is the weather like today",
        "what's the weather like today",
        "whats the weather like today",
        "how is the weather",
        "how's the weather",
        "hows the weather",
        "what is it like outside",
        "what's it like outside",
        "whats it like outside",
    }
)

WEATHER_PREFIXES = (
    "what is the weather in ",
    "what's the weather in ",
    "whats the weather in ",
    "what is the weather like in ",
    "what's the weather like in ",
    "whats the weather like in ",
    "how is the weather in ",
    "how's the weather in ",
    "hows the weather in ",
    "weather in ",
    "weather for ",
    "forecast for ",
    "forecast in ",
)

_TEMPORAL_SUFFIX = re.compile(
    r"(?:\s*,?\s+)"
    r"(?:today|right now|currently|now|at the moment|"
    r"this (?:morning|afternoon|evening|weekend))$",
    re.IGNORECASE,
)


def clean_weather_location(place_name: str) -> str:
    """Remove time qualifiers that are not part of a place name."""
    cleaned = place_name.strip().rstrip("?.!")
    while True:
        updated = _TEMPORAL_SUFFIX.sub("", cleaned).strip()
        if updated == cleaned:
            return cleaned
        cleaned = updated


class GetWeatherTool:
    """Report current weather for a named or configured place."""

    action = "get_weather"
    aliases = ("weather", "forecast", "check_weather")
    direct_phrases = WEATHER_AT_HOME
    direct_prefixes = WEATHER_PREFIXES

    def __init__(self, weather_service: WeatherService) -> None:
        self.weather_service = weather_service

    def execute(self, request: ToolRequest) -> str:
        value = request.get("value") or request.get("query")
        place_name = clean_weather_location(
            str(request.get("location") or value or "")
        )
        try:
            return self.weather_service.current_report(place_name or None)
        except LocationNotConfigured:
            return (
                "I need a home location in config.json, or you can ask "
                "for the weather in a named city."
            )
        except LocationError as exc:
            print(f"[LOCATION] Weather place lookup failed: {exc}", flush=True)
            return str(exc)
        except (WeatherError, OSError, TimeoutError) as exc:
            print(f"[WEATHER] Lookup failed: {exc}", flush=True)
            return "I cannot reach the weather service right now."
        except Exception as exc:
            print(f"[WEATHER] Unexpected lookup error: {exc}", flush=True)
            return "I cannot reach the weather service right now."

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        normalized = normalize_direct_text(user_text)
        if normalized in cls.direct_phrases:
            return {"action": cls.action}

        for prefix in cls.direct_prefixes:
            if normalized.startswith(prefix):
                place_name = normalized[len(prefix):].strip()
                if place_name:
                    return {
                        "action": cls.action,
                        "location": clean_weather_location(place_name),
                    }
        return None
