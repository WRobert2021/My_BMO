"""Dependency-light spoken request matching for Pup Pairs."""

from __future__ import annotations

import re


def is_matching_game_start_request(text: str) -> bool:
    """Return whether spoken text clearly asks to start this game."""
    normalized = " ".join(text.lower().strip().rstrip("?.!").split())
    direct_names = {
        "matching game",
        "memory game",
        "pup pairs",
        "paw patrol game",
    }
    if normalized in direct_names:
        return True
    start_words = r"(?:play|start|open|launch|let'?s play)"
    game_names = (
        r"(?:(?:a|the) )?(?:matching|memory|paw patrol(?: matching)?) game|"
        r"(?:a )?game of (?:matching|memory)|pup pairs"
    )
    return bool(
        re.search(
            rf"\b{start_words}\b.*\b(?:{game_names})\b",
            normalized,
        )
    )


__all__ = ["is_matching_game_start_request"]
