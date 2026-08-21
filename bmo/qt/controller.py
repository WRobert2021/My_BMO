"""Qt property and signal controller for BMO's animated face shell."""

from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from bmo.face_config import (
    PROJECT_ROOT,
    CompactFaceConfig,
    load_compact_face_config,
)
from bmo.gestures import GestureKind, HorizontalSwipeRecognizer
from bmo.menu_catalog import MenuCatalog
from bmo.menu_model import (
    IconMenuPage,
    MenuBounds,
    MenuNavigation,
    MenuNavigator,
)
from bmo.state import BotStates


MENU_BOUNDS = MenuBounds(18, 76, 782, 448)


class QtFaceController(QObject):
    """Expose toolkit-neutral face state to the QML presentation thread."""

    frameSourceChanged = Signal()
    overlaySourceChanged = Signal()
    stateChanged = Signal()
    statusChanged = Signal()
    responseTextChanged = Signal()
    hudVisibleChanged = Signal()
    menuVisibleChanged = Signal()
    menuItemsChanged = Signal()
    menuPageLabelChanged = Signal()
    viewVisibleChanged = Signal()
    viewKindChanged = Signal()
    viewTitleChanged = Signal()
    viewDataChanged = Signal()
    attentionCountChanged = Signal()
    attentionLabelChanged = Signal()
    quietHoursVisibleChanged = Signal()
    quietPinChanged = Signal()
    quietPinErrorChanged = Signal()
    typedInputVisibleChanged = Signal()

    menuRequested = Signal()
    menuItemSelected = Signal(str)
    menuSelectionRequested = Signal(object)
    viewActionRequested = Signal(str, str)
    viewCloseRequested = Signal()
    attentionRequested = Signal()
    quietPinSubmitted = Signal(str)
    typedInputRequested = Signal(str)
    pushToTalkRequested = Signal()
    interruptRequested = Signal()
    exitRequested = Signal()

    def __init__(
        self,
        *,
        config: CompactFaceConfig | None = None,
        project_root: Path = PROJECT_ROOT,
        initial_state: str = BotStates.WARMUP,
        initial_status: str = "Initializing...",
        parent: QObject | None = None,
        rng: random.Random | None = None,
        start_timer: bool = True,
        menu_catalog: MenuCatalog | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config or load_compact_face_config()
        self._project_root = Path(project_root)
        self._rng = rng or random.Random()
        self._gesture = HorizontalSwipeRecognizer()
        self._menu_gesture = HorizontalSwipeRecognizer()
        self._frames = self._discover_frames()
        self._state = str(initial_state).strip().lower() or BotStates.IDLE
        self._status = str(initial_status)
        self._response_text = ""
        self._hud_visible = False
        self._menu_visible = False
        self._menu_items_payload: list[dict[str, object]] = []
        self._menu_page_label = ""
        self._view_visible = False
        self._view_kind = ""
        self._view_title = ""
        self._view_data: dict[str, object] = {}
        self._attention_count = 0
        self._attention_label = ""
        self._quiet_hours_visible = False
        self._quiet_pin = ""
        self._quiet_pin_error = False
        self._typed_input_visible = False
        self._menu_catalog = MenuCatalog()
        self._menu_pages: tuple[IconMenuPage, ...] = ()
        self._menu_navigator = MenuNavigator(1)
        self._frame_index = 0
        self._frame_source = QUrl()
        self._overlay_source = QUrl()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.advanceFrame)
        self.set_menu_catalog(menu_catalog or MenuCatalog())
        self._show_current_frame()
        if start_timer:
            self._restart_timer()

    def _discover_frames(self) -> dict[str, tuple[Path, ...]]:
        frames = {
            state: self._config.frame_paths(
                state,
                project_root=self._project_root,
            )
            for state in self._config.states or ()
        }
        blank = self._project_root / "faces" / "blank.png"
        fallback = (blank,) if blank.is_file() else ()
        idle = frames.get(BotStates.IDLE) or fallback
        return {
            state: discovered or idle
            for state, discovered in frames.items()
        }

    def _state_frames(self) -> tuple[Path, ...]:
        return self._frames.get(self._state) or self._frames.get(BotStates.IDLE, ())

    def _show_current_frame(self) -> None:
        frames = self._state_frames()
        source = (
            QUrl.fromLocalFile(str(frames[self._frame_index % len(frames)].resolve()))
            if frames
            else QUrl()
        )
        if source != self._frame_source:
            self._frame_source = source
            self.frameSourceChanged.emit()

    def _restart_timer(self) -> None:
        self._timer.start(self._config.state_duration(self._state))

    @Property(QUrl, notify=frameSourceChanged)
    def frameSource(self) -> QUrl:  # noqa: N802 - QML naming convention
        return self._frame_source

    @Property(QUrl, notify=overlaySourceChanged)
    def overlaySource(self) -> QUrl:  # noqa: N802 - QML naming convention
        return self._overlay_source

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=responseTextChanged)
    def responseText(self) -> str:  # noqa: N802 - QML naming convention
        return self._response_text

    @Property(bool, notify=hudVisibleChanged)
    def hudVisible(self) -> bool:  # noqa: N802 - QML naming convention
        return self._hud_visible

    @Property(bool, notify=menuVisibleChanged)
    def menuVisible(self) -> bool:  # noqa: N802 - QML naming convention
        return self._menu_visible

    @Property("QVariantList", notify=menuItemsChanged)
    def menuItems(self) -> list[dict[str, object]]:  # noqa: N802
        return self._menu_items_payload

    @Property(str, notify=menuPageLabelChanged)
    def menuPageLabel(self) -> str:  # noqa: N802
        return self._menu_page_label

    @Property(bool, notify=viewVisibleChanged)
    def viewVisible(self) -> bool:  # noqa: N802
        return self._view_visible

    @Property(str, notify=viewKindChanged)
    def viewKind(self) -> str:  # noqa: N802
        return self._view_kind

    @Property(str, notify=viewTitleChanged)
    def viewTitle(self) -> str:  # noqa: N802
        return self._view_title

    @Property("QVariantMap", notify=viewDataChanged)
    def viewData(self) -> dict[str, object]:  # noqa: N802
        return self._view_data

    @Property(int, notify=attentionCountChanged)
    def attentionCount(self) -> int:  # noqa: N802
        return self._attention_count

    @Property(str, notify=attentionLabelChanged)
    def attentionLabel(self) -> str:  # noqa: N802
        return self._attention_label

    @Property(bool, notify=quietHoursVisibleChanged)
    def quietHoursVisible(self) -> bool:  # noqa: N802
        return self._quiet_hours_visible

    @Property(str, notify=quietPinChanged)
    def quietPinDisplay(self) -> str:  # noqa: N802
        return "● " * len(self._quiet_pin) + "○ " * (4 - len(self._quiet_pin))

    @Property(bool, notify=quietPinErrorChanged)
    def quietPinError(self) -> bool:  # noqa: N802
        return self._quiet_pin_error

    @Property(bool, notify=typedInputVisibleChanged)
    def typedInputVisible(self) -> bool:  # noqa: N802
        return self._typed_input_visible

    @Slot()
    def advanceFrame(self) -> None:  # noqa: N802 - QML naming convention
        frames = self._state_frames()
        if not frames:
            return
        if self._state == BotStates.SPEAKING and len(frames) > 1:
            self._frame_index = self._rng.randint(1, len(frames) - 1)
        else:
            self._frame_index = (self._frame_index + 1) % len(frames)
        self._show_current_frame()

    def set_state(
        self,
        state: str,
        status: str = "",
        overlay_path: str | None = None,
    ) -> None:
        """Update presentation state from a future runtime adapter."""
        normalized = str(state).strip().lower() or BotStates.IDLE
        if normalized != self._state:
            self._state = normalized
            self._frame_index = 0
            self.stateChanged.emit()
            self._show_current_frame()
            self._restart_timer()
        if status and status != self._status:
            self._status = str(status)
            self.statusChanged.emit()

        overlay = Path(overlay_path) if overlay_path else None
        source = (
            QUrl.fromLocalFile(str(overlay.resolve()))
            if overlay is not None and overlay.is_file()
            else QUrl()
        )
        if source != self._overlay_source:
            self._overlay_source = source
            self.overlaySourceChanged.emit()

    @Slot(str, str, str)
    def setState(self, state: str, status: str, overlay_path: str) -> None:  # noqa: N802
        self.set_state(state, status, overlay_path or None)

    def append_response(self, text: str, *, newline: bool = True) -> None:
        """Append response text while retaining the production HUD behavior."""
        self._response_text += str(text) + ("\n" if newline else "")
        self.responseTextChanged.emit()

    @Slot(str, bool)
    def appendResponse(self, text: str, newline: bool = True) -> None:  # noqa: N802
        self.append_response(text, newline=newline)

    @Slot()
    def toggleHud(self) -> None:  # noqa: N802
        self._hud_visible = not self._hud_visible
        self.hudVisibleChanged.emit()

    @Slot(float, float)
    def facePressed(self, x: float, y: float) -> None:  # noqa: N802
        self._gesture.press(int(x), int(y))

    @Slot(float, float)
    def faceReleased(self, x: float, y: float) -> None:  # noqa: N802
        gesture = self._gesture.release(int(x), int(y))
        if gesture == GestureKind.SWIPE_LEFT:
            self.show_menu()
            self.menuRequested.emit()
        elif gesture == GestureKind.TAP:
            self.toggleHud()

    def set_menu_catalog(self, catalog: MenuCatalog) -> None:
        """Replace typed menu metadata and reset navigation to page one."""
        if not isinstance(catalog, MenuCatalog):
            raise TypeError("Qt menu catalog must be a MenuCatalog.")
        self._menu_catalog = catalog
        self._menu_pages = IconMenuPage.paginate(catalog.items)
        self._menu_navigator = MenuNavigator(max(1, len(self._menu_pages)))
        self._refresh_menu_page()

    def _refresh_menu_page(self) -> None:
        page_count = len(self._menu_pages)
        if not page_count:
            payload: list[dict[str, object]] = []
            label = ""
        else:
            page = self._menu_pages[self._menu_navigator.page_index]
            payload = []
            for index, item in enumerate(page.items):
                left, top, right, bottom = page.tile_bounds(index, MENU_BOUNDS)
                payload.append(
                    {
                        "name": item.name,
                        "label": item.label,
                        "iconSource": QUrl.fromLocalFile(
                            str(item.icon_path.resolve())
                        ),
                        "x": left,
                        "y": top,
                        "width": right - left,
                        "height": bottom - top,
                        "iconSize": IconMenuPage.ICON_SIZE,
                    }
                )
            label = (
                f"{self._menu_navigator.page_index + 1} / {page_count}"
                if page_count > 1
                else ""
            )
        self._menu_items_payload = payload
        self._menu_page_label = label
        self.menuItemsChanged.emit()
        self.menuPageLabelChanged.emit()

    def show_menu(self) -> None:
        """Show page one of the QML menu."""
        self._menu_navigator = MenuNavigator(max(1, len(self._menu_pages)))
        self._refresh_menu_page()
        if not self._menu_visible:
            self._menu_visible = True
            self._hud_visible = False
            self.menuVisibleChanged.emit()
            self.hudVisibleChanged.emit()

    def hide_menu(self) -> None:
        """Return from the menu to the fullscreen face."""
        if self._menu_visible:
            self._menu_visible = False
            self.menuVisibleChanged.emit()

    def show_view(
        self,
        kind: str,
        title: str,
        data: dict[str, object] | None = None,
    ) -> None:
        """Present one hosted feature or mode above the retained menu."""
        normalized = str(kind).strip().lower()
        if not normalized:
            raise ValueError("Qt hosted view kind cannot be empty.")
        self._view_kind = normalized
        self._view_title = str(title).strip() or normalized.replace("_", " ").title()
        self._view_data = dict(data or {})
        self._view_visible = True
        if self._menu_visible:
            self._menu_visible = False
            self.menuVisibleChanged.emit()
        self._hud_visible = False
        self.viewKindChanged.emit()
        self.viewTitleChanged.emit()
        self.viewDataChanged.emit()
        self.viewVisibleChanged.emit()
        self.hudVisibleChanged.emit()

    def update_view(self, data: dict[str, object]) -> None:
        """Replace the active hosted view payload."""
        if not isinstance(data, dict):
            raise TypeError("Qt hosted view data must be a dictionary.")
        self._view_data = dict(data)
        self.viewDataChanged.emit()

    def hide_view(self, *, return_to_menu: bool = True) -> None:
        """Close the hosted surface and optionally reveal its menu."""
        if not self._view_visible:
            return
        self._view_visible = False
        self._view_kind = ""
        self._view_title = ""
        self._view_data = {}
        self.viewVisibleChanged.emit()
        self.viewKindChanged.emit()
        self.viewTitleChanged.emit()
        self.viewDataChanged.emit()
        if return_to_menu:
            self._menu_visible = True
            self.menuVisibleChanged.emit()

    @Slot(int, str)
    def set_attentions(self, count: int, label: str = "") -> None:
        normalized = max(0, int(count))
        cleaned = str(label).strip()
        if normalized != self._attention_count:
            self._attention_count = normalized
            self.attentionCountChanged.emit()
        if cleaned != self._attention_label:
            self._attention_label = cleaned
            self.attentionLabelChanged.emit()

    @Slot(bool)
    def setQuietHours(self, visible: bool) -> None:  # noqa: N802
        shown = bool(visible)
        if shown != self._quiet_hours_visible:
            self._quiet_hours_visible = shown
            self._quiet_pin = ""
            self._quiet_pin_error = False
            self.quietHoursVisibleChanged.emit()
            self.quietPinChanged.emit()
            self.quietPinErrorChanged.emit()

    @Slot(str)
    def quietPinDigit(self, digit: str) -> None:  # noqa: N802
        value = str(digit)
        if not self._quiet_hours_visible or len(self._quiet_pin) >= 4 or not value.isdigit():
            return
        self._quiet_pin += value[0]
        self._quiet_pin_error = False
        self.quietPinChanged.emit()
        self.quietPinErrorChanged.emit()
        if len(self._quiet_pin) == 4:
            self.quietPinSubmitted.emit(self._quiet_pin)

    @Slot()
    def quietPinClear(self) -> None:  # noqa: N802
        self._quiet_pin = ""
        self._quiet_pin_error = False
        self.quietPinChanged.emit()
        self.quietPinErrorChanged.emit()

    @Slot()
    def quietPinBackspace(self) -> None:  # noqa: N802
        self._quiet_pin = self._quiet_pin[:-1]
        self._quiet_pin_error = False
        self.quietPinChanged.emit()
        self.quietPinErrorChanged.emit()

    @Slot(bool)
    def quietPinResult(self, accepted: bool) -> None:  # noqa: N802
        if accepted:
            self.setQuietHours(False)
            return
        self._quiet_pin = ""
        self._quiet_pin_error = True
        self.quietPinChanged.emit()
        self.quietPinErrorChanged.emit()

    def set_typed_input_visible(self, visible: bool) -> None:
        shown = bool(visible)
        if shown != self._typed_input_visible:
            self._typed_input_visible = shown
            self.typedInputVisibleChanged.emit()

    @Slot(float, float)
    def menuPressed(self, x: float, y: float) -> None:  # noqa: N802
        self._menu_gesture.press(int(x), int(y))

    @Slot(float, float)
    def menuReleased(self, x: float, y: float) -> None:  # noqa: N802
        point = (int(x), int(y))
        gesture = self._menu_gesture.release(*point)
        if gesture == GestureKind.SWIPE_LEFT:
            if self._menu_navigator.swipe_left() == MenuNavigation.PAGE:
                self._refresh_menu_page()
            return
        if gesture == GestureKind.SWIPE_RIGHT:
            navigation = self._menu_navigator.swipe_right()
            if navigation == MenuNavigation.FACE:
                self.hide_menu()
            elif navigation == MenuNavigation.PAGE:
                self._refresh_menu_page()
            return
        if gesture != GestureKind.TAP:
            return
        left, top, right, bottom = self._config.bounds
        if left <= point[0] <= right and top <= point[1] <= bottom:
            self.hide_menu()
            return
        if not self._menu_pages:
            return
        page = self._menu_pages[self._menu_navigator.page_index]
        action = page.action_at(point, MENU_BOUNDS)
        if action is None:
            return
        request = self._menu_catalog.request_for(action)
        self.menuItemSelected.emit(action)
        self.menuSelectionRequested.emit(request)

    @Slot()
    def requestPushToTalk(self) -> None:  # noqa: N802
        self.pushToTalkRequested.emit()

    @Slot()
    def requestInterrupt(self) -> None:  # noqa: N802
        self.interruptRequested.emit()

    @Slot(str, str)
    def requestViewAction(self, action: str, value: str = "") -> None:  # noqa: N802
        self.viewActionRequested.emit(str(action), str(value))

    @Slot()
    def requestViewClose(self) -> None:  # noqa: N802
        self.viewCloseRequested.emit()

    @Slot()
    def requestAttention(self) -> None:  # noqa: N802
        self.attentionRequested.emit()

    @Slot(str)
    def submitTypedInput(self, text: str) -> None:  # noqa: N802
        value = str(text).strip()
        if value:
            self.typedInputRequested.emit(value)

    @Slot()
    def requestExit(self) -> None:  # noqa: N802
        self.exitRequested.emit()

    def stop(self) -> None:
        """Stop controller-owned animation callbacks during shutdown."""
        self._timer.stop()

    def frame_paths(self, state: str) -> tuple[Path, ...]:
        """Return discovered paths for diagnostics and tests."""
        return self._frames.get(state, ())


__all__ = ["QtFaceController"]
