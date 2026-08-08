"""Allowlisted local and online tool execution."""

from __future__ import annotations

import datetime
import re
from typing import Any

from bmo.config import load_config
from bmo.location import LocationError, LocationNotConfigured, LocationService
from bmo.weather import WeatherError, WeatherService


class ToolRouter:
    VALID_TOOLS = {
        "get_time",
        "get_location",
        "get_weather",
        "search_web",
        "capture_image",
    }
    ALIASES = {
        "google": "search_web",
        "browser": "search_web",
        "news": "search_web",
        "search_news": "search_web",
        "look": "capture_image",
        "see": "capture_image",
        "check_time": "get_time",
        "location": "get_location",
        "where_am_i": "get_location",
        "weather": "get_weather",
        "forecast": "get_weather",
        "check_weather": "get_weather",
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
        self.location_service = LocationService(
            effective_config.get("location"),
            timeout=timeout,
        )
        self.weather_service = WeatherService(
            self.location_service,
            timeout=timeout,
            units=str(effective_config.get("weather_units", "imperial")),
        )
        self.last_tool_details: dict[str, Any] | None = None

    @classmethod
    def normalize_action(cls, action_data: dict[str, Any]) -> str:
        raw_action = str(action_data.get("action", "")).lower().strip()
        return cls.ALIASES.get(raw_action, raw_action)

    @staticmethod
    def clean_weather_location(place_name: str) -> str:
        """Remove time qualifiers that are not part of a place name."""
        cleaned = place_name.strip().rstrip("?.!")
        temporal_suffix = re.compile(
            r"(?:\s*,?\s+)"
            r"(?:today|right now|currently|now|at the moment|"
            r"this (?:morning|afternoon|evening|weekend))$",
            re.IGNORECASE,
        )
        while True:
            updated = temporal_suffix.sub("", cleaned).strip()
            if updated == cleaned:
                return cleaned
            cleaned = updated

    @staticmethod
    def match_direct_action(user_text: str) -> dict[str, str] | None:
        """Route unambiguous built-in requests without probabilistic LLM output."""
        normalized = " ".join(user_text.lower().strip().rstrip("?.!").split())
        time_requests = {
            "what time is it",
            "what's the time",
            "whats the time",
            "tell me the time",
            "what is the current time",
            "current time",
        }
        if normalized in time_requests:
            return {"action": "get_time"}

        location_requests = {
            "where am i",
            "what is my location",
            "what's my location",
            "whats my location",
            "what city am i in",
            "where are we",
        }
        if normalized in location_requests:
            return {"action": "get_location"}

        weather_at_home = {
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
        if normalized in weather_at_home:
            return {"action": "get_weather"}

        weather_prefixes = (
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
        for prefix in weather_prefixes:
            if normalized.startswith(prefix):
                place_name = normalized[len(prefix):].strip()
                if place_name:
                    return {
                        "action": "get_weather",
                        "location": ToolRouter.clean_weather_location(
                            place_name
                        ),
                    }

        search_prefixes = (
            "search the web for ",
            "do a web search for ",
            "run a web search for ",
            "perform a web search for ",
            "search online for ",
            "search for ",
            "look up ",
            "google ",
        )
        for prefix in search_prefixes:
            if normalized.startswith(prefix):
                query = normalized[len(prefix):].strip()
                if query:
                    return {"action": "search_web", "query": query}

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

        if action == "get_time":
            now = datetime.datetime.now().strftime("%I:%M %p")
            return f"The current time is {now}."

        if action == "get_location":
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

        if action == "get_weather":
            place_name = self.clean_weather_location(
                str(action_data.get("location") or value or "")
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

        if action == "search_web":
            return self._search_web(str(value or "").strip())

        if action == "capture_image":
            return "IMAGE_CAPTURE_TRIGGERED"

        return None

    def _search_web(self, query: str) -> str:
        if not query:
            return "SEARCH_EMPTY"

        print(f"Searching web for: {query}...", flush=True)
        try:
            from ddgs import DDGS

            with DDGS() as ddgs:
                results = []
                try:
                    results = list(
                        ddgs.news(query, region="us-en", max_results=3)
                    )
                    if results:
                        print(
                            f"[DEBUG] Found News: {results[0].get('title')}",
                            flush=True,
                        )
                except Exception as exc:
                    print(f"[DEBUG] News Search Error: {exc}", flush=True)

                if not results:
                    print(
                        "[DEBUG] No news found, trying text search...",
                        flush=True,
                    )
                    try:
                        results = list(
                            ddgs.text(query, region="us-en", max_results=1)
                        )
                        if results:
                            print(
                                f"[DEBUG] Found Text: {results[0].get('title')}",
                                flush=True,
                            )
                    except Exception as exc:
                        print(f"[DEBUG] Text Search Error: {exc}", flush=True)

                if not results:
                    print("[DEBUG] Search returned 0 results.", flush=True)
                    self.last_tool_details = {"query": query, "results": []}
                    return "SEARCH_EMPTY"

                self.last_tool_details = {
                    "query": query,
                    "results": results[:3],
                }

                formatted_results = []
                for index, result in enumerate(results[:3], start=1):
                    title = result.get("title", "No title")
                    body = result.get("body", result.get("snippet", ""))
                    source = result.get("source", "")
                    url = result.get("url", result.get("href", ""))
                    formatted_results.append(
                        f"Result {index}:\n"
                        f"Title: {title}\n"
                        f"Source: {source}\n"
                        f"Snippet: {body[:500]}\n"
                        f"URL: {url}"
                    )

                return (
                    f"SEARCH RESULTS for '{query}':\n\n"
                    + "\n\n".join(formatted_results)
                )
        except Exception as exc:
            print(f"[DEBUG] Connection/Library Error: {exc}", flush=True)
            self.last_tool_details = {"query": query, "error": str(exc)}
            return "SEARCH_ERROR"
