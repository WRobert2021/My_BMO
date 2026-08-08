"""Current-weather tool and its deterministic direct phrases."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    normalize_direct_text,
)
from bmo.location import LocationError, LocationNotConfigured, LocationService
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
    description = "Report current weather for a named or configured place."
    schemas = (
        '{"action":"get_weather"}',
        '{"action":"get_weather","location":"city, state or country"}',
    )
    prompt_guidance = (
        "Use get_weather for current weather or today's forecast.",
        "Include location only when the user names a place, excluding time "
        "words such as today and right now.",
    )
    prompt_examples = (
        ("What's the weather?", '{"action":"get_weather"}'),
        (
            "What's the weather in Austin?",
            '{"action":"get_weather","location":"Austin, Texas"}',
        ),
    )
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

    @staticmethod
    def normalize_request(request: ToolRequest) -> dict[str, Any]:
        """Normalize a model-supplied place without changing other fields."""
        normalized = dict(request)
        location = clean_weather_location(
            str(request.get("location") or "")
        )
        if location:
            normalized["location"] = location
        else:
            normalized.pop("location", None)
        return normalized

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
    """Register current-weather lookup with configured dependencies."""
    timeout = _online_timeout(settings)
    location_service = LocationService(
        settings.get("location"),
        timeout=timeout,
    )
    weather_service = WeatherService(
        location_service,
        timeout=timeout,
        units=str(settings.get("weather_units", "imperial")),
    )
    registry.register(GetWeatherTool(weather_service))
