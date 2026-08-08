"""Web-search tool and its deterministic direct phrases."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolRequest,
    normalize_direct_text,
)


SEARCH_PREFIXES = (
    "search the web for ",
    "do a web search for ",
    "run a web search for ",
    "perform a web search for ",
    "search online for ",
    "search for ",
    "look up ",
    "google ",
)


class SearchWebTool:
    """Search news first, then fall back to a general text result."""

    action = "search_web"
    aliases = ("google", "browser", "news", "search_news")
    direct_prefixes = SEARCH_PREFIXES

    def __init__(
        self,
        searcher: Callable[[str], str] | None = None,
    ) -> None:
        self._searcher = searcher or self.search
        self.last_details: dict[str, Any] | None = None

    def execute(self, request: ToolRequest) -> str:
        value = request.get("value") or request.get("query")
        return self._searcher(str(value or "").strip())

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        normalized = normalize_direct_text(user_text)
        for prefix in cls.direct_prefixes:
            if normalized.startswith(prefix):
                query = normalized[len(prefix):].strip()
                if query:
                    return {"action": cls.action, "query": query}
        return None

    def search(self, query: str) -> str:
        """Run a web search and retain full details for interaction archives."""
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
                    self.last_details = {"query": query, "results": []}
                    return "SEARCH_EMPTY"

                self.last_details = {
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
            self.last_details = {"query": query, "error": str(exc)}
            return "SEARCH_ERROR"
