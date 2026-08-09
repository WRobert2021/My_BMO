"""Matching game interaction mode and registration adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import threading
from typing import Any

from PIL import Image

from bmo.matching_game import MatchingGameApp, is_matching_game_start_request
from bmo.modes.contracts import (
    InputPolicy,
    ModeRuntimeContext,
    RememberTurn,
    SetState,
    SpeakResponse,
)
from bmo.state import BotStates


MatchingAppFactory = Callable[..., MatchingGameApp]


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
        app_factory: MatchingAppFactory = MatchingGameApp,
    ) -> None:
        self.master = master
        self.speak_response = speak_response
        self.remember_turn = remember_turn
        self.wait_for_tts = wait_for_tts
        self.set_state = set_state
        self.announce = announce
        self.face_provider = face_provider
        self.app_factory = app_factory
        self._active = threading.Event()
        self.ui: MatchingGameApp | None = None

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
        self.master.after(0, self._open_game)

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
            self.master.after(0, ui.close)
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
        if player == "bmo":
            self.set_state(BotStates.THINKING, "BMO's turn.")
        else:
            self.set_state(BotStates.IDLE, "Your turn.")


def register(
    registry: Any,
    context: ModeRuntimeContext,
    settings: Mapping[str, Any],
) -> None:
    """Construct and register the existing embedded matching-game UI."""
    del settings
    registry.register(
        MatchingGameMode(
            context.master,
            speak_response=context.speak_response,
            remember_turn=context.remember_turn,
            wait_for_tts=context.wait_for_tts,
            set_state=context.set_state,
            announce=context.announce,
            face_provider=context.face_provider,
        )
    )
