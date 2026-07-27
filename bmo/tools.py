"""Allowlisted local and online tool execution."""

from __future__ import annotations

import datetime
from typing import Any

class ToolRouter:
    VALID_TOOLS = {"get_time", "search_web", "capture_image"}
    ALIASES = {
        "google": "search_web",
        "browser": "search_web",
        "news": "search_web",
        "search_news": "search_web",
        "look": "capture_image",
        "see": "capture_image",
        "check_time": "get_time",
    }

    @classmethod
    def normalize_action(cls, action_data: dict[str, Any]) -> str:
        raw_action = str(action_data.get("action", "")).lower().strip()
        return cls.ALIASES.get(raw_action, raw_action)

    @staticmethod
    def match_direct_action(user_text: str) -> dict[str, str] | None:
        """Route unambiguous built-in requests without probabilistic LLM output.

        Only explicit command-shaped phrases are matched here. Ambiguous requests
        still go through the language model so ordinary conversation is not
        accidentally treated as a tool invocation.
        """
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

        if action == "search_web":
            return self._search_web(str(value or "").strip())

        if action == "capture_image":
            return "IMAGE_CAPTURE_TRIGGERED"

        return None

    @staticmethod
    def _search_web(query: str) -> str:
        if not query:
            return "SEARCH_EMPTY"

        print(f"Searching web for: {query}...", flush=True)
        try:
            from ddgs import DDGS

            with DDGS() as ddgs:
                results = []
                try:
                    results = list(ddgs.news(query, region="us-en", max_results=3))
                    if results:
                        print(f"[DEBUG] Found News: {results[0].get('title')}", flush=True)
                except Exception as exc:
                    print(f"[DEBUG] News Search Error: {exc}", flush=True)

                if not results:
                    print("[DEBUG] No news found, trying text search...", flush=True)
                    try:
                        results = list(ddgs.text(query, region="us-en", max_results=1))
                        if results:
                            print(f"[DEBUG] Found Text: {results[0].get('title')}", flush=True)
                    except Exception as exc:
                        print(f"[DEBUG] Text Search Error: {exc}", flush=True)

                if not results:
                    print("[DEBUG] Search returned 0 results.", flush=True)
                    return "SEARCH_EMPTY"

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
            return "SEARCH_ERROR"
