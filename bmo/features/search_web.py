"""Web-search tool and its deterministic direct phrases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    ToolArchive,
    ToolPresentation,
    ToolRequest,
    ToolResult,
    ToolResultKind,
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

SEARCH_EMPTY_TEXT = "I searched, but I couldn't find anything about that."
SEARCH_MODEL_ROUTED_EMPTY_TEXT = (
    "I searched, but I couldn't find any news about that."
)
SEARCH_ERROR_TEXT = "I cannot reach the internet right now."
SEARCH_SUMMARY_PRESENTATION = ToolPresentation.by_route(
    direct=ToolPresentation.summarize(
        system_prompt=(
            "You are reading current web-search results for the user. "
            "Briefly report the useful information contained in the results. "
            "The user's words may be a search command rather than a question. "
            "Do not claim the results are irrelevant when their titles or "
            "snippets clearly concern the requested subject. "
            "Use only the supplied results. Answer in one or two short sentences."
        ),
        user_prompt_template=(
            "Search request: {user_text}\n\n"
            "Web-search results:\n{content}\n\n"
            "Report what these results say."
        ),
        strip_response=True,
    ),
    model_routed=ToolPresentation.summarize(),
)


def _search_archive(details: dict[str, Any] | None = None) -> ToolArchive:
    return ToolArchive(
        category="web",
        filename="searches.jsonl",
        details=details,
    )


class SearchWebTool:
    """Search news first, then fall back to a general text result."""

    action = "search_web"
    aliases = ("google", "browser", "news", "search_news")
    description = "Search the web for current information."
    schemas = ('{"action":"search_web","query":"search terms"}',)
    prompt_guidance = (
        "Use search_web when the user explicitly asks for a web search or "
        "current online information.",
    )
    prompt_examples = (
        (
            "Search for news about robots.",
            '{"action":"search_web","query":"robots news"}',
        ),
    )
    direct_prefixes = SEARCH_PREFIXES

    def __init__(
        self,
        searcher: Callable[[str], ToolResult] | None = None,
    ) -> None:
        self._searcher = searcher or self.search

    def execute(self, request: ToolRequest) -> ToolResult:
        query = request.get("query") or request.get("value")
        normalized_query = str(query or "").strip()
        result = self._searcher(normalized_query)
        if result.archive.category == "web":
            return result
        if result.kind is ToolResultKind.CONTENT:
            return ToolResult.summarized(
                result.content or "",
                presentation=SEARCH_SUMMARY_PRESENTATION,
                archive=_search_archive(),
            )
        if result.kind is ToolResultKind.EMPTY:
            return ToolResult.empty(
                SEARCH_EMPTY_TEXT,
                model_routed_text=SEARCH_MODEL_ROUTED_EMPTY_TEXT,
                archive=_search_archive(),
            )
        if result.kind is ToolResultKind.ERROR:
            return ToolResult.error(
                SEARCH_ERROR_TEXT,
                archive=_search_archive(),
            )
        return result

    @staticmethod
    def prepare_model_request(
        request: ToolRequest,
    ) -> dict[str, Any] | None:
        """Require search terms before accepting a model-produced request."""
        normalized = dict(request)
        query = str(
            request.get("query") or request.get("value") or ""
        ).strip()
        if not query:
            return None
        normalized["query"] = query
        return normalized

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        normalized = normalize_direct_text(user_text)
        for prefix in cls.direct_prefixes:
            if normalized.startswith(prefix):
                query = normalized[len(prefix):].strip()
                if query:
                    return {"action": cls.action, "query": query}
        return None

    def search(self, query: str) -> ToolResult:
        """Run a web search with feature-owned presentation and archive data."""
        if not query:
            return ToolResult.empty(
                SEARCH_EMPTY_TEXT,
                model_routed_text=SEARCH_MODEL_ROUTED_EMPTY_TEXT,
                archive=_search_archive(),
            )

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
                    details = {"query": query, "results": []}
                    return ToolResult.empty(
                        SEARCH_EMPTY_TEXT,
                        model_routed_text=SEARCH_MODEL_ROUTED_EMPTY_TEXT,
                        archive=_search_archive(details),
                    )

                details = {
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

                return ToolResult.summarized(
                    f"SEARCH RESULTS for '{query}':\n\n"
                    + "\n\n".join(formatted_results),
                    presentation=SEARCH_SUMMARY_PRESENTATION,
                    archive=_search_archive(details),
                )
        except Exception as exc:
            print(f"[DEBUG] Connection/Library Error: {exc}", flush=True)
            details = {"query": query, "error": str(exc)}
            return ToolResult.error(
                SEARCH_ERROR_TEXT,
                archive=_search_archive(details),
            )


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register web search."""
    del settings
    registry.register(SearchWebTool())
