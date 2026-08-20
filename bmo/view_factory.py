"""Toolkit-neutral discovery of presentation-host supplied views."""

from __future__ import annotations

from typing import Any


NOT_HOSTED = object()


def create_hosted_view(
    kind: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Ask the first factory argument to construct a named hosted view."""
    normalized = str(kind).strip().lower()
    if not normalized:
        raise ValueError("Hosted view kind cannot be empty.")
    if not args:
        return NOT_HOSTED
    creator = getattr(args[0], "create_bmo_view", None)
    if not callable(creator):
        return NOT_HOSTED
    return creator(normalized, *args[1:], **kwargs)


__all__ = ["NOT_HOSTED", "create_hosted_view"]
