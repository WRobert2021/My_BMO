"""Compatibility mapping for repository roots moved during layout refactors."""

from __future__ import annotations

from pathlib import Path


_MOVED_RELATIVE_ROOTS = {
    "data": Path("bmo/data"),
    "faces": Path("graphics/faces"),
    "sounds": Path("audio/sounds"),
}


def relocated_repository_path(value: str | Path) -> Path:
    """Map a legacy project-relative root to its current repository location."""
    path = Path(value).expanduser()
    if path.is_absolute() or not path.parts:
        return path
    replacement = _MOVED_RELATIVE_ROOTS.get(path.parts[0])
    if replacement is None:
        return path
    return replacement.joinpath(*path.parts[1:])


__all__ = ["relocated_repository_path"]
