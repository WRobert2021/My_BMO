"""Matching game interaction mode and registration adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import threading
from typing import Any

from PIL import Image

from bmo.matching_game_text import is_matching_game_start_request
from bmo.modes.contracts import (
    InputPolicy,
    ModeMenuItem,
    ModeRuntimeContext,
    RememberTurn,
    SetState,
    SpeakResponse,
)
from bmo.state import BotStates


MatchingAppFactory = Callable[..., Any]


def _create_matching_app(*args: Any, **kwargs: Any) -> Any:
    """Construct the Tk game view only when the mode starts from the menu."""
    from bmo.matching_game import MatchingGameApp

    return MatchingGameApp(*args, **kwargs)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATCHING_GAME_MENU_ITEM = ModeMenuItem(
    name="matching_game",
    label="Matching Game",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "matching_game.png",
    start_request="Start the matching game",
)


class MatchingGameMode:
    """Adapt :class:`MatchingGameApp` without changing its touch UI."""

    name = "matching_game"

    def __init__(
        self,
        master: Any,
        *,
        speak_response: SpeakResponse,
        remember_turn: RememberTurn,
        wait_for_tts: Callable[[], None],
        set_state: SetState,
        announce: Callable[[str], None],
        face_provider: Callable[[], Image.Image | None],
        dispatch_ui: Callable[[Callable[[], None]], None] | None = None,
        app_factory: MatchingAppFactory = _create_matching_app,
        menu_item: ModeMenuItem | None = MATCHING_GAME_MENU_ITEM,
    ) -> None:
        self.master = master
        self.speak_response = speak_response
        self.remember_turn = remember_turn
        self.wait_for_tts = wait_for_tts
        self.set_state = set_state
        self.announce = announce
        self.face_provider = face_provider
        self.dispatch_ui = dispatch_ui or (
            lambda callback: self.master.after(0, callback)
        )
        self.app_factory = app_factory
        self.menu_item = menu_item
        self._active = threading.Event()
        self.ui: Any | None = None

    def matches_start_request(self, user_text: str) -> bool:
        return is_matching_game_start_request(user_text)

    def start(self, user_text: str) -> None:
        if self._active.is_set():
            return
        self._active.set()
        response = "Pup Pairs! You go first. Tap two cards, then I'll take my turn."
        self.speak_response(response, None)
        self.remember_turn(user_text, response)
        self.wait_for_tts()
        self.set_state(BotStates.IDLE, "Your turn.")
        self.dispatch_ui(self._open_game)

    def handle_input(self, user_text: str) -> None:
        del user_text

    def is_active(self) -> bool:
        return self._active.is_set()

    def input_policy(self) -> InputPolicy:
        return InputPolicy.suspended()

    def close(self) -> None:
        self._active.clear()
        ui = self.ui
        if ui is None:
            return
        try:
            self.dispatch_ui(ui.close)
        except Exception as exc:
            print(f"[MATCHING GAME] Could not close: {exc}", flush=True)

    def _open_game(self) -> None:
        if not self._active.is_set():
            return
        try:
            self.ui = self.app_factory(
                self.master,
                embedded=True,
                on_close=self._handle_ui_close,
                announce=self.announce,
                face_provider=self.face_provider,
                on_player_change=self._handle_player_change,
            )
        except Exception as exc:
            print(f"[MATCHING GAME] Could not start: {exc}", flush=True)
            self._active.clear()
            self.ui = None
            self.set_state(BotStates.ERROR, "Could not start Pup Pairs.")

    def _handle_ui_close(self) -> None:
        self.ui = None
        self._active.clear()
        self.set_state(BotStates.IDLE, "Ready")

    def _handle_player_change(self, player: str) -> None:
        if player == "speaking":
            self.set_state(BotStates.SPEAKING, "BMO is announcing the winner.")
        elif player == "bmo":
            self.set_state(BotStates.THINKING, "BMO's turn.")
        else:
            self.set_state(BotStates.IDLE, "Your turn.")


def register(
    registry: Any,
    context: ModeRuntimeContext,
    settings: Mapping[str, Any],
) -> None:
    """Construct and register the existing embedded matching-game UI."""
    show_in_menu = settings.get("show_in_menu", True)
    if not isinstance(show_in_menu, bool):
        raise TypeError("matching-game show_in_menu must be true or false")
    registry.register(
        MatchingGameMode(
            context.master,
            speak_response=context.speak_response,
            remember_turn=context.remember_turn,
            wait_for_tts=context.wait_for_tts,
            set_state=context.set_state,
            announce=context.announce,
            face_provider=context.face_provider,
            dispatch_ui=context.call_soon,
            menu_item=MATCHING_GAME_MENU_ITEM if show_in_menu else None,
        )
    )


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Contribute Pup Pairs metadata without constructing its mode or UI."""
    show_in_menu = settings.get("show_in_menu", True)
    if not isinstance(show_in_menu, bool):
        raise TypeError("matching-game show_in_menu must be true or false")
    if show_in_menu:
        registry.register(MATCHING_GAME_MENU_ITEM)
