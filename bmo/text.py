"""Neutral text normalization shared by voice-facing modules."""


def normalize_spoken_command(value: object) -> str:
    """Normalize spacing, case, and terminal speech punctuation."""
    return " ".join(str(value).casefold().strip().rstrip("?.!").split())
