"""Text and answer normalization for Twenty Questions."""

from __future__ import annotations

import re

from bmo.twenty_questions_contracts import TwentyQuestionsDataError


PLAYER_ANSWERS = ("yes", "no", "sometimes", "unknown")
DATASET_ANSWERS = frozenset({"yes", "no", "sometimes", "often"})
LEARNED_ANSWERS = frozenset((*DATASET_ANSWERS, "unknown"))
DISPLAY_ANSWERS = {
    "yes": "Yes",
    "no": "No",
    "sometimes": "Sometimes",
    "often": "Often",
    "unknown": "Unknown",
}


def canonical_object_name(name: str) -> str:
    """Normalize an object name for case-insensitive overlay matching."""
    return " ".join(str(name).strip().split()).casefold()


def clean_display_name(name: str) -> str:
    """Collapse whitespace while retaining the speaker's display spelling."""
    return " ".join(str(name).strip().split())


def normalize_dataset_answer(value: object, *, learned: bool = False) -> str:
    """Normalize one dataset value and reject labels outside its contract."""
    if not isinstance(value, str):
        raise TwentyQuestionsDataError("answer values must be strings")
    normalized = " ".join(value.strip().casefold().split())
    allowed = LEARNED_ANSWERS if learned else DATASET_ANSWERS
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise TwentyQuestionsDataError(
            f"answer label must be one of {allowed_text}"
        )
    return normalized


def normalize_player_answer(text: object) -> str | None:
    """Normalize natural speech to a player answer or quit command."""
    if not isinstance(text, str):
        return None
    normalized = text.casefold().replace("’", "'")
    normalized = re.sub(r"^[\s\-\u2013\u2014*•]+", "", normalized)
    normalized = re.sub(r"^(?:oh|well|um|uh|okay|ok)[,.\s]+", "", normalized)
    normalized = re.sub(r"^[^\w']+|[^\w']+$", "", normalized)
    normalized = " ".join(normalized.split())
    aliases = {
        "yes": {"yes", "yep", "yeah", "correct", "it is", "sure"},
        "no": {
            "no", "nope", "nah", "incorrect", "it isn't", "it is not",
            "it isnt",
        },
        "sometimes": {
            "sometimes", "maybe", "probably", "possibly", "often", "usually",
            "sort of", "kind of", "it depends",
        },
        "unknown": {
            "i don't know", "i dont know", "don't know", "dont know",
            "not sure", "unsure", "unknown",
        },
        "quit": {"stop", "quit", "cancel", "end game"},
    }
    for answer, words in aliases.items():
        if normalized in words:
            return answer
    return None


normalize_answer = normalize_player_answer


__all__ = [
    "DATASET_ANSWERS",
    "DISPLAY_ANSWERS",
    "LEARNED_ANSWERS",
    "PLAYER_ANSWERS",
    "canonical_object_name",
    "clean_display_name",
    "normalize_answer",
    "normalize_dataset_answer",
    "normalize_player_answer",
]
