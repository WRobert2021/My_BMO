"""Conversation-memory persistence."""

from __future__ import annotations

import json
from pathlib import Path


def load_chat_history(path: Path, system_prompt: str) -> list[dict[str, str]]:
    """Load saved messages, falling back to a fresh system prompt."""
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list) and data:
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return [{"role": "system", "content": system_prompt}]


def save_chat_history(
    path: Path,
    permanent_memory: list[dict[str, str]],
    session_memory: list[dict[str, str]],
    max_conversation_messages: int = 10,
) -> None:
    """Persist recent messages atomically to reduce corruption risk."""
    full = permanent_memory + session_memory
    if not full:
        return

    conversation = full[1:]
    if len(conversation) > max_conversation_messages:
        conversation = conversation[-max_conversation_messages:]

    payload = [full[0]] + conversation
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
    temp_path.replace(path)
