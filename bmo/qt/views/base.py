"""Common lifecycle for QML-backed hosted views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class QtHostedView:
    """Plain-Python view adapter rendered by the shared QML host."""

    kind = "generic"
    title = "BMO"

    def __init__(
        self,
        host: Any,
        *,
        on_close: Callable[[], None],
    ) -> None:
        if not callable(on_close):
            raise TypeError("Qt hosted view on_close must be callable.")
        self.host = host
        self.on_close = on_close
        self.closed = False
        self.host.present(self)

    def payload(self) -> dict[str, object]:
        return {}

    def refresh(self, *_args: Any, **_kwargs: Any) -> None:
        if not self.closed:
            self.host.update(self)

    def handle_action(self, action: str, value: str) -> None:
        del value
        if action == "close":
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.host.dismiss(self)
        self.on_close()


__all__ = ["QtHostedView"]
