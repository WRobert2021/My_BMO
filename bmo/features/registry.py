"""Registration, normalization, and dispatch for BMO tools."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    Tool,
    ToolRequest,
    ToolResponse,
)


class DuplicateToolError(ValueError):
    """Raised when tool identifiers overlap in a registry."""


class UnknownToolError(LookupError):
    """Raised when execution is requested for an unregistered action."""


class ToolRegistry:
    """Own an allowlist of tools and dispatch requests by action or alias."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}
        for tool in tools:
            self.register(tool)

    @property
    def actions(self) -> set[str]:
        """Return a snapshot of canonical registered action names."""
        return set(self._tools)

    @property
    def aliases(self) -> dict[str, str]:
        """Return a snapshot mapping registered aliases to their actions."""
        return dict(self._aliases)

    def register(self, tool: Tool) -> None:
        """Register one tool, rejecting all ambiguous identifiers."""
        action = self._normalize_identifier(tool.action, "action name")
        aliases = [
            self._normalize_identifier(alias, "alias")
            for alias in tool.aliases
        ]

        if action in self._tools:
            raise DuplicateToolError(
                f"Duplicate tool action name '{action}'."
            )
        if action in self._aliases:
            owner = self._aliases[action]
            raise DuplicateToolError(
                f"Tool action name '{action}' conflicts with an alias "
                f"registered for '{owner}'."
            )

        aliases_seen: set[str] = set()
        for alias in aliases:
            if alias == action:
                raise DuplicateToolError(
                    f"Tool alias '{alias}' duplicates its action name."
                )
            if alias in aliases_seen:
                raise DuplicateToolError(
                    f"Duplicate tool alias '{alias}' for action '{action}'."
                )
            aliases_seen.add(alias)

            if alias in self._tools:
                raise DuplicateToolError(
                    f"Tool alias '{alias}' conflicts with the registered "
                    "action name."
                )
            if alias in self._aliases:
                owner = self._aliases[alias]
                raise DuplicateToolError(
                    f"Duplicate tool alias '{alias}'; it is already "
                    f"registered for '{owner}'."
                )

        self._tools[action] = tool
        self._aliases.update({alias: action for alias in aliases})

    def normalize_action(self, request: ToolRequest) -> str:
        """Return the canonical action for a request."""
        return self.resolve_action(request, self._aliases)

    def execute(self, request: ToolRequest) -> ToolResponse:
        """Dispatch a request or raise if its action is not registered."""
        action = self.normalize_action(request)
        try:
            tool = self._tools[action]
        except KeyError as exc:
            raise UnknownToolError(
                f"No tool is registered for action '{action}'."
            ) from exc
        normalized_request = dict(request)
        normalized_request["action"] = action
        return tool.execute(normalized_request)

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        """Return the first direct phrase match from registered tools."""
        for tool in self._tools.values():
            matcher = getattr(tool, "match_direct_action", None)
            if not callable(matcher):
                continue
            action_data = matcher(user_text)
            if action_data is not None:
                return action_data
        return None

    @staticmethod
    def resolve_action(
        request: Mapping[str, Any],
        aliases: Mapping[str, str],
    ) -> str:
        """Normalize a request action using the supplied alias vocabulary."""
        raw_action = str(request.get("action", "")).lower().strip()
        return aliases.get(raw_action, raw_action)

    @staticmethod
    def _normalize_identifier(identifier: object, label: str) -> str:
        normalized = str(identifier).lower().strip()
        if not normalized:
            raise ValueError(f"Tool {label} cannot be empty.")
        return normalized
