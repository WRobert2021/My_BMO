"""Qt host for feature and mode views supplied through app factories."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from bmo.qt.controller import QtFaceController


ViewFactory = Callable[..., Any]


class QtViewHost(QObject):
    """Create QML-backed adapters and keep one active hosted view."""

    _presentRequested = Signal(object)
    _updateRequested = Signal(object, object)
    _dismissRequested = Signal(object, bool)

    def __init__(
        self,
        controller: QtFaceController,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._current: Any | None = None
        self._factories: dict[str, ViewFactory] = {}
        self._presentRequested.connect(
            self._present_now,
            Qt.ConnectionType.QueuedConnection,
        )
        self._updateRequested.connect(
            self._update_now,
            Qt.ConnectionType.QueuedConnection,
        )
        self._dismissRequested.connect(
            self._dismiss_now,
            Qt.ConnectionType.QueuedConnection,
        )
        controller.viewActionRequested.connect(self._handle_action)
        controller.viewCloseRequested.connect(self.close_current)
        self._register_builtin_factories()

    def _register_builtin_factories(self) -> None:
        from bmo.qt.views import (
            QtAlbumView,
            QtCalendarView,
            QtGalaxyRVRView,
            QtLearningView,
            QtMatchingGameView,
            QtMusicView,
            QtTimerView,
            QtTwentyQuestionsView,
            QtWeatherView,
        )

        for kind, factory in (
            ("timer", QtTimerView),
            ("calendar", QtCalendarView),
            ("weather", QtWeatherView),
            ("album", QtAlbumView),
            ("galaxy_rvr", QtGalaxyRVRView),
            ("learning", QtLearningView),
            ("music", QtMusicView),
            ("matching_game", QtMatchingGameView),
            ("twenty_questions", QtTwentyQuestionsView),
        ):
            self.register(kind, factory)

    def register(self, kind: str, factory: ViewFactory) -> None:
        normalized = str(kind).strip().lower()
        if not normalized:
            raise ValueError("Qt view kind cannot be empty.")
        if not callable(factory):
            raise TypeError("Qt view factory must be callable.")
        self._factories[normalized] = factory

    def create_bmo_view(self, kind: str, *args: Any, **kwargs: Any) -> Any:
        """Factory surface discovered by toolkit-neutral extension adapters."""
        normalized = str(kind).strip().lower()
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            raise LookupError(f"No Qt view adapter for '{normalized}'.") from exc
        return factory(self, *args, **kwargs)

    @property
    def current(self) -> Any | None:
        return self._current

    def present(self, view: Any) -> None:
        if QThread.currentThread() is self.thread():
            self._present_now(view)
        else:
            self._presentRequested.emit(view)

    @Slot(object)
    def _present_now(self, view: Any) -> None:
        previous = self._current
        if previous is not None and previous is not view:
            previous.close()
        self._current = view
        self.controller.show_view(view.kind, view.title, view.payload())

    def update(self, view: Any) -> None:
        if QThread.currentThread() is self.thread():
            self._update_now(view, view.payload())
        else:
            self._updateRequested.emit(view, view.payload())

    @Slot(object, object)
    def _update_now(self, view: Any, payload: object) -> None:
        if self._current is view and isinstance(payload, dict):
            self.controller.update_view(payload)

    def dismiss(self, view: Any, *, return_to_menu: bool = True) -> None:
        if QThread.currentThread() is self.thread():
            self._dismiss_now(view, return_to_menu)
        else:
            self._dismissRequested.emit(view, return_to_menu)

    @Slot(object, bool)
    def _dismiss_now(self, view: Any, return_to_menu: bool) -> None:
        if self._current is not view:
            return
        self._current = None
        self.controller.hide_view(return_to_menu=return_to_menu)

    @Slot(str, str)
    def _handle_action(self, action: str, value: str) -> None:
        view = self._current
        if view is not None:
            view.handle_action(str(action), str(value))

    @Slot()
    def close_current(self) -> None:
        view = self._current
        if view is not None:
            view.close()

    def close(self) -> None:
        self.close_current()


__all__ = ["QtViewHost"]
