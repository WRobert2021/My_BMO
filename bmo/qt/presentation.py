"""Thread-safe Qt implementation of the runtime presentation port."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot

from bmo.qt.controller import QtFaceController


class QtRuntimePresentation(QObject):
    """Marshal runtime worker updates onto the Qt application thread."""

    _callSoon = Signal(object)
    _state = Signal(str, str, str)
    _append = Signal(str, bool)
    _attentions = Signal(int, str)
    _quietHours = Signal(bool)

    def __init__(self, controller: QtFaceController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        queued = Qt.ConnectionType.QueuedConnection
        self._callSoon.connect(self._run_callback, queued)
        self._state.connect(controller.setState, queued)
        self._append.connect(controller.appendResponse, queued)
        self._attentions.connect(controller.set_attentions, queued)
        self._quietHours.connect(controller.setQuietHours, queued)

    def call_soon(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            raise TypeError("Qt presentation callback must be callable.")
        self._callSoon.emit(callback)

    @Slot(object)
    def _run_callback(self, callback: Any) -> None:
        if callable(callback):
            callback()

    def set_state(
        self,
        state: str,
        status: str = "",
        overlay_path: str | None = None,
    ) -> None:
        self._state.emit(str(state), str(status), str(overlay_path or ""))

    def append_response(self, text: str, *, newline: bool = True) -> None:
        self._append.emit(str(text), bool(newline))

    def attention_changed(self, attentions: tuple[Any, ...]) -> None:
        first = attentions[0] if attentions else None
        label = str(getattr(first, "badge_label", "") or "ITEMS") if first else ""
        self._attentions.emit(len(attentions), label)

    def quiet_hours_changed(self, locked: bool) -> None:
        self._quietHours.emit(bool(locked))


__all__ = ["QtRuntimePresentation"]
