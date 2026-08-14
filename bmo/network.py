"""Small configuration helpers for bounded online operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import math
from typing import Any


def online_timeout_seconds(
    settings: Mapping[str, Any],
    *,
    reporter: Callable[[str], None] | None = None,
) -> float:
    """Return the shared 1–30 second online timeout setting."""
    raw_timeout = settings.get("online_timeout_seconds", 6)
    try:
        if isinstance(raw_timeout, bool):
            raise TypeError
        timeout = float(raw_timeout)
        if not math.isfinite(timeout):
            raise ValueError
    except (OverflowError, TypeError, ValueError):
        message = "[CONFIG] online_timeout_seconds must be numeric; using 6."
        if reporter is None:
            print(message, flush=True)
        else:
            reporter(message)
        timeout = 6.0
    return min(max(timeout, 1.0), 30.0)
