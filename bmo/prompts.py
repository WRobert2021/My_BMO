"""Registry-driven system and routing prompt construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bmo.features.registry import ToolRegistry


BASE_SYSTEM_PROMPT = """You are a helpful robot assistant running on a Raspberry Pi.
Personality: Cute, helpful, robot.
Style: Short sentences. Enthusiastic."""

ROUTER_PROMPT_HEADER = """Classify the user's intent for a robot assistant.
Return exactly one JSON object and no explanation."""


def _capability_lines(registry: ToolRegistry) -> list[str]:
    lines = []
    for capability in registry.capabilities:
        description = (
            f" - {capability.description}" if capability.description else ""
        )
        lines.append(f"- {capability.action}{description}")
    return lines


def build_capability_prompt(registry: ToolRegistry) -> str:
    """Describe only executable assistant capabilities in the registry."""
    capabilities = registry.capabilities
    if not capabilities:
        return (
            "CAPABILITIES:\n"
            "- No external actions are currently enabled.\n\n"
            "INSTRUCTIONS:\n"
            "- Reply with normal text."
        )

    lines = ["CAPABILITIES:", *_capability_lines(registry), "", "INSTRUCTIONS:"]
    lines.append(
        "- If the user asks for an enabled physical or live-information "
        "action, output its JSON object."
    )
    for capability in capabilities:
        lines.extend(f"- {guidance}" for guidance in capability.guidance)
    lines.append("- If the user just wants to chat, reply with normal text.")

    examples = [
        example
        for capability in capabilities
        for example in capability.examples
    ]
    if examples:
        lines.extend(("", "EXAMPLES:"))
        for user_text, response in examples:
            lines.extend((f"User: {user_text}", f"You: {response}", ""))
        if not lines[-1]:
            lines.pop()
    return "\n".join(lines)


def build_routing_prompt(registry: ToolRegistry) -> str:
    """Build the classifier prompt from the currently enabled registry."""
    lines = [ROUTER_PROMPT_HEADER, "", "Available actions:"]
    for capability in registry.capabilities:
        for schema in capability.schemas:
            description = (
                f" - {capability.description}"
                if capability.description
                else ""
            )
            lines.append(f"- {schema}{description}")
    lines.append('- {"action":"chat"} - Reply without using an action.')

    guidance = [
        item
        for capability in registry.capabilities
        for item in capability.guidance
    ]
    if guidance:
        lines.extend(("", *guidance))
    lines.extend(
        (
            "Infer the likely intended request when speech-to-text produces "
            "similar-sounding words.",
            "Use chat only when no enabled action is appropriate.",
        )
    )
    return "\n".join(lines)


def build_system_prompt(
    config: Mapping[str, Any],
    registry: ToolRegistry | None = None,
) -> str:
    """Build the effective prompt and always append enabled capabilities."""
    if registry is None:
        from bmo.features.loader import load_feature_registry

        registry = load_feature_registry(config).registry

    prompt = str(config.get("system_prompt") or BASE_SYSTEM_PROMPT).strip()
    prompt = f"{prompt}\n\n{build_capability_prompt(registry)}"
    extras = str(config.get("system_prompt_extras") or "").strip()
    if extras:
        prompt = f"{prompt}\n\n{extras}"
    return prompt
