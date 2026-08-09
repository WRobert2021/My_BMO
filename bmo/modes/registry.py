"""Registration and lifecycle dispatch for long-lived interaction modes."""

from __future__ import annotations

from collections.abc import Iterable
import threading

from bmo.modes.contracts import InputPolicy, InteractionMode


class DuplicateModeError(ValueError):
    """Raised when two interaction modes use the same name."""


class ModeRegistry:
    """Select one long-lived mode and route input to it until it closes."""

    def __init__(self, modes: Iterable[InteractionMode] = ()) -> None:
        self._modes: dict[str, InteractionMode] = {}
        self._active_mode: InteractionMode | None = None
        self._closed = False
        self._lock = threading.RLock()
        for mode in modes:
            self.register(mode)

    def register(self, mode: InteractionMode) -> None:
        """Register a mode under its unique normalized name."""
        name = str(mode.name).strip().lower()
        if not name:
            raise ValueError("Mode name cannot be empty.")
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot register modes after closing the registry.")
            if name in self._modes:
                raise DuplicateModeError(f"Duplicate mode name '{name}'.")
            self._modes[name] = mode

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered mode names in matching order."""
        with self._lock:
            return tuple(self._modes)

    def match_start_request(self, user_text: str) -> InteractionMode | None:
        """Return the first mode matching a start request when none is active."""
        with self._lock:
            if self._closed or self._current_mode() is not None:
                return None
            modes = tuple(self._modes.values())
        return next(
            (mode for mode in modes if mode.matches_start_request(user_text)),
            None,
        )

    def start(self, mode: InteractionMode, user_text: str) -> None:
        """Start a registered mode and make it the input owner."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot start a mode after closing the registry.")
            if self._current_mode() is not None:
                raise RuntimeError("Another interaction mode is already active.")
            registered = self._modes.get(str(mode.name).strip().lower())
            if registered is not mode:
                raise LookupError(f"Mode '{mode.name}' is not registered.")
            self._active_mode = mode
        try:
            mode.start(user_text)
        except Exception:
            with self._lock:
                if self._active_mode is mode:
                    self._active_mode = None
            raise
        self._clear_inactive(mode)

    def handle_input(self, user_text: str) -> bool:
        """Send subsequent input to the active mode, if one exists."""
        with self._lock:
            mode = self._current_mode()
        if mode is None:
            return False
        mode.handle_input(user_text)
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

    def is_active(self) -> bool:
        """Return whether one registered mode currently owns input."""
        with self._lock:
            return self._current_mode() is not None

    def input_policy(self) -> InputPolicy:
        """Return the active mode's policy or normal wake-word behavior."""
        with self._lock:
            mode = self._current_mode()
        return mode.input_policy() if mode is not None else InputPolicy.wake_word()

    def close(self) -> None:
        """Close every registered mode once, in reverse registration order."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._active_mode = None
            modes = tuple(reversed(tuple(self._modes.values())))
        for mode in modes:
            try:
                mode.close()
            except Exception as exc:
                print(
                    f"[MODE] Could not close '{mode.name}': {exc}",
                    flush=True,
                )

    def _current_mode(self) -> InteractionMode | None:
        mode = self._active_mode
        if mode is not None and not mode.is_active():
            self._active_mode = None
            return None
        return mode

    def _clear_inactive(self, mode: InteractionMode) -> None:
        with self._lock:
            if self._active_mode is mode and not mode.is_active():
                self._active_mode = None
