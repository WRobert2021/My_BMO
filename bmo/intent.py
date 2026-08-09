"""Semantic tool-intent routing with the local language model."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from bmo.config import OLLAMA_OPTIONS
from bmo.prompts import build_routing_prompt
from bmo.speech import extract_json_from_text
from bmo.tools import ToolRouter


ChatRequest = Callable[..., dict[str, Any]]


ROUTER_PROMPT = """Routing prompts are generated from the enabled tool registry.
Use build_routing_prompt(registry) to obtain the effective prompt."""


def infer_tool_action(
    model: str,
    user_text: str,
    chat_request: ChatRequest,
    tool_router: ToolRouter | None = None,
) -> dict[str, str] | None:
    """Ask the local model to classify an utterance without conversation bias."""
    effective_router = tool_router or ToolRouter(
        {"online_timeout_seconds": 6}
    )
    routing_prompt = build_routing_prompt(effective_router.registry)
    response = chat_request(
        model=model,
        messages=[
            {"role": "system", "content": routing_prompt},
            {"role": "user", "content": user_text},
        ],
        stream=False,
        format="json",
        options={**OLLAMA_OPTIONS, "temperature": 0},
    )
    message = response.get("message")
    if not isinstance(message, dict):
        return None
    action_data = extract_json_from_text(str(message.get("content") or ""))
    if not action_data:
        return None

    normalized_data = effective_router.normalize_request(action_data)
    action = str(normalized_data["action"])
    valid_tools = effective_router.VALID_TOOLS
    if action not in valid_tools:
        return None

    result = {"action": action}
    if action == "get_weather":
        location = str(normalized_data.get("location") or "")
        if location:
            result["location"] = location
    elif action == "search_web":
        query = str(
            normalized_data.get("query")
            or normalized_data.get("value")
            or ""
        ).strip()
        if not query:
            return None
        result["query"] = query
    elif action == "set_timer":
        for key in (
            "operation",
            "duration",
            "duration_seconds",
            "timer_id",
            "label",
        ):
            value = normalized_data.get(key)
            if value not in (None, ""):
                result[key] = str(value)
    return result


def infer_game_answer(
    model: str,
    user_text: str,
    chat_request: ChatRequest,
) -> str | None:
    """Interpret a conversational game answer using a constrained local model."""
    response = chat_request(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify a response to a yes-or-no question. Return JSON "
                    'only: {"answer":"yes"}, {"answer":"no"}, '
                    '{"answer":"maybe"}, or {"answer":"unknown"}.'
                ),
            },
            {"role": "user", "content": user_text},
        ],
        stream=False,
        format="json",
        options={**OLLAMA_OPTIONS, "temperature": 0},
    )
    message = response.get("message")
    if not isinstance(message, dict):
        return None
    data = extract_json_from_text(str(message.get("content") or ""))
    answer = str((data or {}).get("answer") or "").lower().strip()
    return answer if answer in {"yes", "no", "maybe", "unknown"} else None


def infer_game_candidates(
    model: str,
    history: list[dict[str, Any]],
    semantic_keys: list[str],
    chat_request: ChatRequest,
    *,
    excluded_names: list[str] | None = None,
    request_count: int = 30,
    debug: bool = False,
) -> list[dict[str, Any]]:
    """Let the local model propose entities, never game-state decisions."""
    asked_keys = [
        str(turn.get("question_key") or "")
        for turn in history
        if not turn.get("was_guess")
    ]
    response = chat_request(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    f"Suggest {request_count} diverse, distinct entities that "
                    "fit this Twenty Questions history. Include plausible real "
                    "objects, infrastructure, tools, media, concepts, fictional "
                    "entities, people, places, events, and substances whenever "
                    "the answers allow them. Do not choose a question or winner. "
                    "Every candidate MUST include a trait value for every asked "
                    "semantic key. Trait values may be yes, no, variable, or "
                    "unknown. Use unknown only when genuinely uncertain. Return "
                    "JSON as "
                    '{"candidates":[{"name":"...", "entity_type":"...", '
                    '"traits":{"physical":"yes"}}]}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Semantic keys: {', '.join(semantic_keys)}\n"
                    f"Asked keys requiring values: {', '.join(asked_keys)}\n"
                    f"Existing or rejected names to avoid: "
                    f"{', '.join((excluded_names or [])[:120])}\n"
                    f"Structured history:\n"
                    f"{json.dumps(history, ensure_ascii=True)}"
                ),
            },
        ],
        stream=False,
        format="json",
        options={**OLLAMA_OPTIONS, "temperature": 0.2},
    )
    message = response.get("message")
    if not isinstance(message, dict):
        return []
    data = extract_json_from_text(str(message.get("content") or ""))
    raw_candidates = (data or {}).get("candidates")
    if not isinstance(raw_candidates, list):
        if debug:
            print(
                "[20 QUESTIONS DEBUG] Expansion response had no candidates list.",
                flush=True,
            )
        return []
    allowed = set(semantic_keys)
    excluded = {
        re.sub(r"^(?:a|an|the)\s+", "", name.casefold().strip())
        for name in (excluded_names or [])
    }
    candidates = []
    rejection_reasons: list[str] = []
    for item in raw_candidates[:50]:
        if not isinstance(item, dict):
            rejection_reasons.append("item was not an object")
            continue
        name = str(item.get("name") or "").strip()
        if not name or len(name) > 80:
            rejection_reasons.append("missing or overlong name")
            continue
        canonical = re.sub(
            r"^(?:a|an|the)\s+",
            "",
            name.casefold(),
        )
        if canonical in excluded:
            rejection_reasons.append(f"{name}: excluded duplicate")
            continue
        raw_traits = item.get("traits")
        if not isinstance(raw_traits, dict):
            rejection_reasons.append(f"{name}: traits were not an object")
            continue
        traits = {}
        for key, value in raw_traits.items():
            if key not in allowed:
                continue
            if isinstance(value, str):
                state = value.lower().strip()
                if state in {"yes", "no", "variable", "maybe", "unknown"}:
                    traits[key] = state
            elif isinstance(value, (int, float)):
                traits[key] = min(max(float(value), 0.02), 0.98)
        missing = set(asked_keys) - traits.keys()
        if missing:
            rejection_reasons.append(
                f"{name}: missing asked traits {sorted(missing)}"
            )
            continue
        candidates.append(
            {
                "name": name,
                "entity_type": str(
                    item.get("entity_type") or "provisional"
                )[:40],
                "traits": traits,
            }
        )
    if debug:
        print(
            f"[20 QUESTIONS DEBUG] Expansion returned={len(raw_candidates)}, "
            f"validated={len(candidates)}, rejected={len(rejection_reasons)}",
            flush=True,
        )
        for reason in rejection_reasons:
            print(
                f"[20 QUESTIONS DEBUG] Expansion parser rejection: {reason}",
                flush=True,
            )
    return candidates
