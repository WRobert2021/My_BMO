"""Conversation-memory persistence."""

from __future__ import annotations

from pathlib import Path

from bmo.jsonio import atomic_write_json, load_json


_MEMORY_ROLES = frozenset({"system", "user", "assistant"})


def _valid_message(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("role") in _MEMORY_ROLES
        and isinstance(value.get("content"), str)
        and set(value).issubset({"role", "content"})
    )


def load_chat_history(path: Path, system_prompt: str) -> list[dict[str, str]]:
    """Load saved messages, falling back to a fresh system prompt."""
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = load_json(handle)
            if (
                isinstance(data, list)
                and data
                and all(_valid_message(message) for message in data)
            ):
                # Tool availability comes from the current application prompt,
                # not a stale system message persisted by an earlier run.
                if (
                    isinstance(data[0], dict)
                    and data[0].get("role") == "system"
                ):
                    data[0] = {"role": "system", "content": system_prompt}
                else:
                    data.insert(
                        0,
                        {"role": "system", "content": system_prompt},
                    )
                return data
        except (OSError, ValueError):
            pass
    return [{"role": "system", "content": system_prompt}]


def save_chat_history(
    path: Path,
    permanent_memory: list[dict[str, str]],
    session_memory: list[dict[str, str]],
    max_conversation_messages: int = 10,
) -> None:
    """Persist recent messages atomically to reduce corruption risk."""
    if (
        isinstance(max_conversation_messages, bool)
        or not isinstance(max_conversation_messages, int)
        or max_conversation_messages < 0
    ):
        raise ValueError("max_conversation_messages must be a non-negative integer")
    full = permanent_memory + session_memory
    if not full:
        return
    if not all(_valid_message(message) for message in full):
        raise ValueError("chat history contains an invalid message")

    conversation = full[1:]
    if max_conversation_messages == 0:
        conversation = []
    elif len(conversation) > max_conversation_messages:
        conversation = conversation[-max_conversation_messages:]

    payload = [full[0]] + conversation
    atomic_write_json(path, payload, indent=4, ensure_ascii=True)
