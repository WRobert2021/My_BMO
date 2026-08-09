"""Registration, normalization, and dispatch for BMO tools."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import json
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    RuntimeCallback,
    RuntimeNotification,
    Tool,
    ToolContext,
    ToolRequest,
    ToolResult,
    ToolResponse,
)


class DuplicateToolError(ValueError):
    """Raised when tool identifiers overlap in a registry."""


class UnknownToolError(LookupError):
    """Raised when execution is requested for an unregistered action."""


@dataclass(frozen=True)
class ToolCapability:
    """Prompt metadata for one registered tool."""

    action: str
    description: str
    schemas: tuple[str, ...]
    guidance: tuple[str, ...]
    examples: tuple[tuple[str, str], ...]


class ToolRegistry:
    """Own an allowlist of tools and dispatch requests by action or alias."""

    def __init__(
        self,
        tools: Iterable[Tool] = (),
        *,
        runtime_callback: RuntimeCallback | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}
        self._runtime_callback = runtime_callback
        self._closed = False
        for tool in tools:
            self.register(tool)

    def notify_runtime(self, notification: RuntimeNotification) -> None:
        """Present an asynchronous feature notification through the runtime."""
        if not isinstance(notification, RuntimeNotification):
            raise TypeError("Runtime notifications must use RuntimeNotification.")
        if self._closed or self._runtime_callback is None:
            return
        self._runtime_callback(notification)

    def close(self) -> None:
        """Close registered feature resources once, in reverse load order."""
        if self._closed:
            return
        self._closed = True
        for tool in reversed(tuple(self._tools.values())):
            close = getattr(tool, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:
                print(
                    f"[FEATURE] Could not close '{tool.action}': {exc}",
                    flush=True,
                )

    @property
    def actions(self) -> set[str]:
        """Return a snapshot of canonical registered action names."""
        return set(self._tools)

    @property
    def aliases(self) -> dict[str, str]:
        """Return a snapshot mapping registered aliases to their actions."""
        return dict(self._aliases)

    @property
    def capabilities(self) -> tuple[ToolCapability, ...]:
        """Return prompt metadata in registration order."""
        capabilities = []
        for action, tool in self._tools.items():
            schemas = tuple(getattr(tool, "schemas", ())) or (
                json.dumps({"action": action}, separators=(",", ":")),
            )
            capabilities.append(
                ToolCapability(
                    action=action,
                    description=str(getattr(tool, "description", "")).strip(),
                    schemas=schemas,
                    guidance=tuple(getattr(tool, "prompt_guidance", ())),
                    examples=tuple(getattr(tool, "prompt_examples", ())),
                )
            )
        return tuple(capabilities)

    def get(self, action: str) -> Tool | None:
        """Return a registered tool by canonical action name or alias."""
        normalized = str(action).lower().strip()
        normalized = self._aliases.get(normalized, normalized)
        return self._tools.get(normalized)

    @contextmanager
    def registration(self):
        """Roll back all registrations performed in a failing block."""
        tools_before = self._tools.copy()
        aliases_before = self._aliases.copy()
        try:
            yield
        except Exception:
            self._tools = tools_before
            self._aliases = aliases_before
            raise

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

    def normalize_request(self, request: ToolRequest) -> dict[str, Any]:
        """Normalize an action and apply optional feature-owned cleanup."""
        normalized_request = dict(request)
        action = self.normalize_action(request)
        normalized_request["action"] = action
        tool = self._tools.get(action)
        normalizer = getattr(tool, "normalize_request", None)
        if callable(normalizer):
            normalized_request = dict(normalizer(normalized_request))
            normalized_request["action"] = action
        return normalized_request

    def prepare_model_request(
        self,
        request: ToolRequest,
    ) -> dict[str, Any] | None:
        """Prepare model action data for an enabled feature, or reject it."""
        normalized_request = self.normalize_request(request)
        action = str(normalized_request["action"])
        tool = self._tools.get(action)
        if tool is None:
            return None

        preparer = getattr(tool, "prepare_model_request", None)
        if callable(preparer):
            prepared_request = preparer(normalized_request)
            if prepared_request is None:
                return None
            normalized_request = dict(prepared_request)
            normalized_request["action"] = action
        return normalized_request

    def execute(
        self,
        request: ToolRequest,
        *,
        context: ToolContext | None = None,
    ) -> ToolResponse:
        """Dispatch a request or raise if its action is not registered."""
        if context is not None and not isinstance(context, ToolContext):
            raise TypeError("Tool execution context must be a ToolContext.")
        normalized_request = self.normalize_request(request)
        action = str(normalized_request["action"])
        try:
            tool = self._tools[action]
        except KeyError as exc:
            raise UnknownToolError(
                f"No tool is registered for action '{action}'."
            ) from exc
        if getattr(tool, "uses_context", False):
            result = tool.execute(normalized_request, context)
        else:
            result = tool.execute(normalized_request)
        if not isinstance(result, ToolResult):
            raise TypeError(
                f"Tool '{action}' returned {type(result).__name__}; "
                "expected ToolResult."
            )
        return result

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
