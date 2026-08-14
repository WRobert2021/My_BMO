"""Semantic tool-intent routing with the local language model."""

from __future__ import annotations

import json
from typing import Any, Callable

from bmo.config import OLLAMA_OPTIONS
from bmo.prompts import build_routing_prompt
from bmo.speech import extract_json_from_text
from bmo.tools import ToolRouter, default_metadata_router


ChatRequest = Callable[..., dict[str, Any]]


ROUTER_PROMPT = """Routing prompts are generated from the enabled tool registry.
Use build_routing_prompt(registry) to obtain the effective prompt."""


def infer_tool_action(
    model: str,
    user_text: str,
    chat_request: ChatRequest,
    tool_router: ToolRouter | None = None,
) -> dict[str, Any] | None:
    """Ask the local model to classify an utterance without conversation bias."""
    effective_router = tool_router or default_metadata_router()
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

    return effective_router.registry.prepare_model_request(action_data)


def infer_game_answer(
    model: str,
    user_text: str,
    chat_request: ChatRequest,
) -> str | None:
    """Interpret a game response using only the four canonical answers."""
    response = chat_request(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify a response to a yes-or-no question. Return JSON "
                    'only: {"answer":"yes"}, {"answer":"no"}, '
                    '{"answer":"sometimes"}, or {"answer":"unknown"}. '
                    "Use sometimes for qualified or conditional answers."
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
    answer = str((data or {}).get("answer") or "").casefold().strip()
    # A stale local model may still emit the former aliases.  Normalize them
    # here, while keeping the public classifier result canonical.
    if answer in {"maybe", "often"}:
        answer = "sometimes"
    return answer if answer in {"yes", "no", "sometimes", "unknown"} else None


def infer_game_guess(
    model: str,
    history: list[dict[str, object]],
    chat_request: ChatRequest,
    *,
    excluded_names: tuple[str, ...] = (),
) -> str | None:
    """Ask the local model for one best guess when the indexed pool is empty."""
    history_json = json.dumps(history, ensure_ascii=False)
    excluded_json = json.dumps(tuple(excluded_names), ensure_ascii=False)
    response = chat_request(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are making a fallback guess in a Twenty Questions game. "
                    "Use the question-and-answer history to choose the single "
                    "most likely object. Return JSON only in this exact shape: "
                    '{"guess":"object name"}. Do not return an explanation, a '
                    "list, or a question. Never repeat an excluded guess."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"History: {history_json}\n"
                    f"Excluded guesses: {excluded_json}"
                ),
            },
        ],
        stream=False,
        format="json",
        options={**OLLAMA_OPTIONS, "temperature": 0},
    )
    message = response.get("message")
    if not isinstance(message, dict):
        return None
    data = extract_json_from_text(str(message.get("content") or ""))
    guess = str((data or {}).get("guess") or "").strip()
    if not guess or guess.casefold() in {"unknown", "none", "null"}:
        return None
    excluded = {str(name).strip().casefold() for name in excluded_names}
    if guess.casefold() in excluded:
        return None
    return " ".join(guess.split())
