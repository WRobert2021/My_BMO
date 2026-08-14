"""Registration and lifecycle dispatch for long-lived interaction modes."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
import threading

from bmo.extensions import RegistrationLedger
from bmo.modes.contracts import InputPolicy, InteractionMode, ModeMenuItem


class DuplicateModeError(ValueError):
    """Raised when two interaction modes use the same name."""


class ModeRegistry:
    """Select one long-lived mode and route input to it until it closes."""

    def __init__(self, modes: Iterable[InteractionMode] = ()) -> None:
        self._modes: dict[str, InteractionMode] = {}
        self._menu_items: dict[str, ModeMenuItem] = {}
        self._active_mode: InteractionMode | None = None
        self._quarantined_modes: dict[int, InteractionMode] = {}
        self._closed_modes: dict[int, InteractionMode] = {}
        self._registration_ledger = RegistrationLedger[InteractionMode]()
        self._closed = False
        self._lock = threading.RLock()
        for mode in modes:
            try:
                self.register(mode)
            except Exception:
                if not any(owned is mode for owned in self._modes.values()):
                    self._close_mode(
                        mode,
                        action="reject",
                        mode_name="<unregistered>",
                    )
                self.close()
                raise

    def register(self, mode: InteractionMode) -> None:
        """Register a mode under its unique normalized name."""
        attempt = self._registration_ledger.record(mode)
        raw_name = mode.name
        if not isinstance(raw_name, str):
            raise TypeError("Mode name must be a string.")
        name = raw_name.strip().lower()
        if attempt is not None:
            attempt.identifier = name
        if not name:
            raise ValueError("Mode name cannot be empty.")
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot register modes after closing the registry.")
            if self._quarantined_modes.get(id(mode)) is mode:
                raise RuntimeError(f"Mode '{name}' is quarantined.")
            if name in self._modes:
                raise DuplicateModeError(f"Duplicate mode name '{name}'.")
            menu_item = getattr(mode, "menu_item", None)
            if menu_item is not None:
                if not isinstance(menu_item, ModeMenuItem):
                    raise TypeError(
                        f"Mode '{name}' menu_item must be a ModeMenuItem."
                    )
                if menu_item.name != name:
                    raise ValueError(
                        f"Mode '{name}' menu item must use the same name."
                    )
            self._modes[name] = mode
            if menu_item is not None:
                self._menu_items[name] = menu_item

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered mode names in matching order."""
        with self._lock:
            return tuple(self._modes)

    def get(self, name: str) -> InteractionMode | None:
        """Return a registered mode by normalized name."""
        normalized = str(name).strip().lower()
        with self._lock:
            return self._modes.get(normalized)

    @property
    def menu_items(self) -> tuple[ModeMenuItem, ...]:
        """Return menu contributions in configured mode-registration order."""
        with self._lock:
            return tuple(
                self._menu_items[name]
                for name in self._modes
                if name in self._menu_items
            )

    @contextmanager
    def registration(self):
        """Roll back and close modes registered by a failing hook."""
        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "Cannot register modes after closing the registry."
                )
            modes_before = self._modes.copy()
            menu_items_before = self._menu_items.copy()
        with self._registration_ledger.transaction() as attempts:
            try:
                yield
            except Exception:
                with self._lock:
                    self._modes = modes_before
                    self._menu_items = menu_items_before
                existing_mode_ids = {
                    id(mode) for mode in modes_before.values()
                }
                closed_ids: set[int] = set()
                for attempt in reversed(attempts):
                    mode = attempt.candidate
                    mode_id = id(mode)
                    if mode_id in existing_mode_ids or mode_id in closed_ids:
                        continue
                    closed_ids.add(mode_id)
                    self._close_mode(
                        mode,
                        action="roll back",
                        mode_name=attempt.identifier,
                    )
                raise

    def match_start_request(self, user_text: str) -> InteractionMode | None:
        """Return the first mode matching a start request when none is active."""
        with self._lock:
            if self._closed or self._current_mode() is not None:
                return None
            modes = tuple(self._modes.values())
        for mode in modes:
            try:
                matches = mode.matches_start_request(user_text)
            except Exception as exc:
                self._handle_lifecycle_failure(
                    mode,
                    "matches_start_request",
                    exc,
                )
                raise
            if matches:
                return mode
        return None

    def start(self, mode: InteractionMode, user_text: str) -> None:
        """Start a registered mode and make it the input owner."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot start a mode after closing the registry.")
            if self._current_mode() is not None:
                raise RuntimeError("Another interaction mode is already active.")
            mode_name = next(
                (
                    name
                    for name, registered in self._modes.items()
                    if registered is mode
                ),
                None,
            )
            if mode_name is None:
                raise LookupError("The requested mode is not registered.")
            self._active_mode = mode
        try:
            mode.start(user_text)
        except Exception as exc:
            self._handle_lifecycle_failure(mode, "start", exc)
            raise
        self._clear_inactive(mode)

    def handle_input(self, user_text: str) -> bool:
        """Send subsequent input to the active mode, if one exists."""
        with self._lock:
            mode = self._current_mode()
        if mode is None:
            return False
        try:
            mode.handle_input(user_text)
        except Exception as exc:
            self._handle_lifecycle_failure(mode, "handle_input", exc)
            raise
        self._clear_inactive(mode)
        return True

    def route_input(self, user_text: str) -> bool:
        """Handle active-mode input or start a newly matched mode."""
        if self.handle_input(user_text):
            return True
        mode = self.match_start_request(user_text)
        if mode is None:
            return False
        self.start(mode, user_text)
        return True

    def start_menu_item(self, name: str) -> None:
        """Start the registered mode represented by one contributed menu item."""
        normalized = str(name).strip().lower()
        with self._lock:
            mode = self._modes.get(normalized)
            item = self._menu_items.get(normalized)
        if mode is None or item is None:
            raise LookupError(f"No registered mode menu item named '{normalized}'.")
        self.start(mode, item.start_request)

    def is_active(self) -> bool:
        """Return whether one registered mode currently owns input."""
        with self._lock:
            return self._current_mode() is not None

    def input_policy(self) -> InputPolicy:
        """Return the active mode's policy or normal wake-word behavior."""
        with self._lock:
            mode = self._current_mode()
        if mode is None:
            return InputPolicy.wake_word()
        try:
            return mode.input_policy()
        except Exception as exc:
            self._handle_lifecycle_failure(mode, "input_policy", exc)
            raise

    def close(self) -> None:
        """Close every registered mode once, in reverse registration order."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._active_mode = None
            modes = tuple(reversed(tuple(self._modes.items())))
        for mode_name, mode in modes:
            self._close_mode_once(mode, mode_name=mode_name)

    def _current_mode(self) -> InteractionMode | None:
        mode = self._active_mode
        if mode is not None:
            try:
                active = mode.is_active()
            except Exception as exc:
                self._handle_lifecycle_failure(mode, "is_active", exc)
                raise
            if not active:
                self._active_mode = None
                return None
        return mode

    def _clear_inactive(self, mode: InteractionMode) -> None:
        try:
            active = mode.is_active()
        except Exception as exc:
            self._handle_lifecycle_failure(mode, "is_active", exc)
            raise
        with self._lock:
            if self._active_mode is mode and not active:
                self._active_mode = None

    def _handle_lifecycle_failure(
        self,
        mode: InteractionMode,
        lifecycle: str,
        exc: Exception,
    ) -> None:
        """Release, quarantine, and close a mode after a failed callback."""
        with self._lock:
            mode_name = "<unknown>"
            if self._active_mode is mode:
                self._active_mode = None
            for name, registered in tuple(self._modes.items()):
                if registered is mode:
                    mode_name = name
                    del self._modes[name]
                    self._menu_items.pop(name, None)
            self._quarantined_modes[id(mode)] = mode
        print(
            f"[MODE] Unexpected failure in '{mode_name}.{lifecycle}': "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        self._close_mode_once(
            mode,
            action="clean up",
            mode_name=mode_name,
        )

    def _close_mode_once(
        self,
        mode: InteractionMode,
        *,
        action: str = "close",
        mode_name: str = "<unknown>",
    ) -> None:
        with self._lock:
            mode_id = id(mode)
            if self._closed_modes.get(mode_id) is mode:
                return
            self._closed_modes[mode_id] = mode
        self._close_mode(mode, action=action, mode_name=mode_name)

    @staticmethod
    def _close_mode(
        mode: InteractionMode,
        *,
        action: str = "close",
        mode_name: str = "<unknown>",
    ) -> None:
        try:
            mode.close()
        except Exception as exc:
            print(
                f"[MODE] Could not {action} '{mode_name}': {exc}",
                flush=True,
            )
