"""Twenty Questions interaction mode and registration adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import math
from pathlib import Path
import threading
from typing import Any

from bmo.intent import infer_game_answer, infer_game_guess
from bmo.modes.contracts import (
    Chat,
    InputPolicy,
    ModeMenuItem,
    ModeRuntimeContext,
    SpeakResponse,
)
from bmo.state import BotStates
from bmo.twenty_questions import (
    BASE_DATA_PATH,
    HISTORY_PATH,
    LEARNED_DATA_PATH,
    TwentyQuestionsDataError,
    TwentyQuestionsDatasetLoader,
    TwentyQuestionsGame,
    TwentyQuestionsHistory,
    normalize_player_answer,
)
from bmo.twenty_questions_ui import TwentyQuestionsApp


GameAnswerInference = Callable[[str, str, Chat], str | None]
GameGuessInference = Callable[..., str | None]
TwentyQuestionsAppFactory = Callable[..., TwentyQuestionsApp]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TWENTY_QUESTIONS_MENU_ITEM = ModeMenuItem(
    name="twenty_questions",
    label="20 Questions",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "20_questions.png",
    start_request="Start Twenty Questions",
)


class TwentyQuestionsMode:
    """Adapt the indexed game to the exclusive interaction-mode lifecycle."""

    name = "twenty_questions"

    def __init__(
        self,
        game: TwentyQuestionsGame,
        *,
        master: Any | None = None,
        text_model: str,
        chat: Chat,
        speak_response: SpeakResponse,
        wait_for_tts: Callable[[], None],
        set_state: Callable[[str, str], None],
        answer_wait_seconds: object = 12,
        answer_inference: GameAnswerInference = infer_game_answer,
        guess_inference: GameGuessInference = infer_game_guess,
        menu_item: ModeMenuItem | None = TWENTY_QUESTIONS_MENU_ITEM,
        app_factory: TwentyQuestionsAppFactory = TwentyQuestionsApp,
        face_provider: Callable[[], Any] | None = None,
        thing_history: TwentyQuestionsHistory | None = None,
        dispatch_ui: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.game = game
        self.master = master
        self.text_model = text_model
        self.chat = chat
        self.speak_response = speak_response
        self.wait_for_tts = wait_for_tts
        self.set_state = set_state
        self.answer_wait_seconds = self._clamp_answer_wait(answer_wait_seconds)
        self.answer_inference = answer_inference
        self.guess_inference = guess_inference
        self.menu_item = menu_item
        self.app_factory = app_factory
        self.face_provider = face_provider
        self.thing_history = thing_history or TwentyQuestionsHistory(path=None)
        self.dispatch_ui = dispatch_ui or (
            (lambda callback: self.master.after(0, callback))
            if self.master is not None
            else None
        )
        self.ui: TwentyQuestionsApp | None = None
        self._active = threading.Event()
        self._menu_launched = False
        self._gui_input_lock = threading.Lock()
        self._gui_input_processing = False

    def matches_start_request(self, user_text: str) -> bool:
        return self.game.is_start_request(user_text)

    def start(self, user_text: str) -> None:
        self._menu_launched = self._is_menu_start(user_text)
        self._active.set()
        self.set_state(BotStates.THINKING, "Thinking...")
        try:
            response = self.game.start()
        except TwentyQuestionsDataError as exc:
            # Dataset failures belong to this mode only.  The mode registry
            # can immediately return ownership to normal BMO input.
            print(f"[20 QUESTIONS] Could not start: {exc}", flush=True)
            self.game.close()
            self._active.clear()
            self._speak_and_wait(
                "I can't load Twenty Questions right now."
            )
            self.set_state(BotStates.IDLE, "Ready")
            return
        if self._menu_launched and self.master is not None:
            if not self._open_ui_before_speech():
                return
            self._speak_and_wait(response)
            self.set_state(BotStates.IDLE, "Tap an answer.")
        else:
            self._speak_and_wait(response)
            self._listen_again()

    def handle_input(self, user_text: str) -> None:
        self.set_state(BotStates.THINKING, "Thinking...")
        if self.game.awaiting_reveal:
            response = self.game.reveal_and_learn(user_text)
            self._record_completed_thing()
            self._speak_and_wait(response)
            self._refresh_ui(response)
            if not self._menu_launched:
                self._active.clear()
            self.set_state(BotStates.IDLE, "Ready")
            return

        parsed_answer = normalize_player_answer(user_text)
        if parsed_answer is None:
            try:
                parsed_answer = self.answer_inference(
                    self.text_model,
                    user_text,
                    self.chat,
                )
                if parsed_answer:
                    print(
                        f"[20 QUESTIONS] Local model interpreted: {parsed_answer}",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f"[20 QUESTIONS] Answer interpretation failed: {exc}",
                    flush=True,
                )

        terminal = self.game.accept_answer(parsed_answer or user_text)
        if terminal is not None:
            self._record_completed_thing()
            self._speak_and_wait(terminal)
            self._refresh_ui(terminal)
            if self.game.active and not self._menu_launched:
                self._listen_again()
            elif not self.game.active and not self._menu_launched:
                self._active.clear()
                self.set_state(BotStates.IDLE, "Ready")
            elif self.game.active:
                self.set_state(BotStates.IDLE, "Tap an answer.")
            else:
                self.set_state(BotStates.IDLE, "Game complete. Tap EXIT GAME.")
            return

        response = self._next_move_with_llm()
        self._speak_and_wait(response)
        self._refresh_ui(response)
        if self.game.active and not self._menu_launched:
            self._listen_again()
        elif not self.game.active and not self._menu_launched:
            self._active.clear()
            self.set_state(BotStates.IDLE, "Ready")
        elif self.game.active:
            self.set_state(BotStates.IDLE, "Tap an answer.")
        else:
            self.set_state(BotStates.IDLE, "Game complete. Tap EXIT GAME.")

    def is_active(self) -> bool:
        return self._active.is_set()

    def input_policy(self) -> InputPolicy:
        if self._menu_launched and self._active.is_set():
            return InputPolicy.suspended()
        return InputPolicy.continuous(
            initial_silence_timeout=self.answer_wait_seconds,
            listening_status="Take your time. I'm listening...",
            no_speech_status="Still listening...",
            empty_transcript_status="I didn't catch that. Try again...",
            trigger_source="GAME",
        )

    def close(self) -> None:
        self._active.clear()
        self.game.close()
        ui = self.ui
        self.ui = None
        if ui is not None and self.master is not None:
            try:
                assert self.dispatch_ui is not None
                self.dispatch_ui(ui.close)
            except Exception as exc:
                print(f"[20 QUESTIONS] Could not close touch UI: {exc}", flush=True)

    def _open_ui(self) -> None:
        if not self._active.is_set() or not self._menu_launched or self.master is None:
            return
        try:
            self.ui = self.app_factory(
                self.master,
                game=self.game,
                on_answer=self._queue_gui_answer,
                on_reveal=self._queue_gui_reveal,
                on_play_again=self._queue_gui_restart,
                on_close=self._handle_ui_close,
                face_provider=self.face_provider,
                thing_history_provider=self.thing_history.snapshot,
            )
        except Exception as exc:
            print(f"[20 QUESTIONS] Could not open touch UI: {exc}", flush=True)
            self.ui = None
            self.game.close()
            self._active.clear()
            self.set_state(BotStates.ERROR, "Could not open Twenty Questions.")

    def _open_ui_before_speech(self) -> bool:
        """Create the embedded canvas before the intro reaches the speaker."""
        ready = threading.Event()

        def open_and_signal() -> None:
            try:
                self._open_ui()
            finally:
                ready.set()

        try:
            assert self.dispatch_ui is not None
            self.dispatch_ui(open_and_signal)
        except Exception as exc:
            print(f"[20 QUESTIONS] Could not open touch UI: {exc}", flush=True)
            self.game.close()
            self._active.clear()
            self.set_state(BotStates.ERROR, "Could not open Twenty Questions.")
            return False
        if not ready.wait(timeout=5):
            print("[20 QUESTIONS] Timed out opening touch UI.", flush=True)
            self.game.close()
            self._active.clear()
            self.set_state(BotStates.ERROR, "Could not open Twenty Questions.")
            return False
        return self.ui is not None and self._active.is_set()

    def _next_move_with_llm(self) -> str:
        response = self.game.next_move()
        if not self.game.needs_llm_guess:
            return response
        try:
            guess = self.guess_inference(
                self.text_model,
                self.game.structured_history(),
                self.chat,
                excluded_names=tuple(self.game.rejected_names),
            )
        except Exception as exc:
            print(f"[20 QUESTIONS] Fallback guess failed: {exc}", flush=True)
            guess = None
        if guess:
            offered = self.game.offer_llm_guess(guess)
            if offered:
                return offered
        self.game.llm_guess_failed()
        return self.game.next_move()

    def _handle_ui_close(self) -> None:
        self.ui = None
        self.game.close()
        self._active.clear()
        self.set_state(BotStates.IDLE, "Ready")

    def _queue_gui_answer(self, answer: str) -> None:
        self._queue_gui_input(answer)

    def _queue_gui_reveal(self, answer: str) -> None:
        self._queue_gui_input(answer)

    def _queue_gui_restart(self) -> None:
        if not self._active.is_set() or self.ui is None:
            return
        self._queue_gui_action(self._restart_game)

    def _record_completed_thing(self) -> None:
        completed_object = self.game.completed_object
        if completed_object is None:
            return
        self.thing_history.record(completed_object)

    def _queue_gui_input(self, text: str) -> None:
        self._queue_gui_action(lambda: self.handle_input(text))

    def _queue_gui_action(self, action: Callable[[], None]) -> None:
        if not self._active.is_set() or self.ui is None:
            return
        with self._gui_input_lock:
            if self._gui_input_processing:
                return
            self._gui_input_processing = True

        def process() -> None:
            try:
                action()
            finally:
                with self._gui_input_lock:
                    self._gui_input_processing = False

        threading.Thread(
            target=process,
            name="twenty-questions-touch-input",
            daemon=True,
        ).start()

    def _restart_game(self) -> None:
        self.set_state(BotStates.THINKING, "Thinking...")
        try:
            response = self.game.start()
        except TwentyQuestionsDataError as exc:
            print(f"[20 QUESTIONS] Could not restart: {exc}", flush=True)
            self.game.close()
            self._speak_and_wait("I can't load Twenty Questions right now.")
            self._refresh_ui("I couldn't start a new game.")
            self.set_state(BotStates.IDLE, "Tap PLAY AGAIN to retry.")
            return
        # Refresh the existing canvas before speaking the new introduction.
        self._refresh_ui()
        self._speak_and_wait(response)
        self._refresh_ui()
        self.set_state(BotStates.IDLE, "Tap an answer.")

    def _refresh_ui(self, status: str | None = None) -> None:
        ui = self.ui
        if ui is None or self.master is None:
            return
        try:
            assert self.dispatch_ui is not None
            self.dispatch_ui(lambda: ui.refresh(status))
        except Exception:
            pass

    def _is_menu_start(self, user_text: str) -> bool:
        item = self.menu_item
        return bool(
            item is not None
            and str(user_text).strip().casefold()
            == item.start_request.casefold()
        )

    def _speak_and_wait(self, response: str) -> None:
        self.speak_response(response, None)
        self.wait_for_tts()

    def _listen_again(self) -> None:
        self.set_state(BotStates.LISTENING, "Take your time. I'm listening...")

    @staticmethod
    def _clamp_answer_wait(value: object) -> float:
        try:
            if isinstance(value, bool):
                raise TypeError
            seconds = float(value)
            if not math.isfinite(seconds):
                raise ValueError
        except (OverflowError, TypeError, ValueError):
            seconds = 12.0
        return min(max(seconds, 3.0), 30.0)


def _path_setting(
    settings: Mapping[str, Any],
    key: str,
    default: Path,
) -> Path:
    value = settings.get(key, default)
    if not isinstance(value, (str, Path)):
        raise TypeError(f"Twenty Questions {key} must be a path string")
    path = Path(value)
    if not str(path):
        raise ValueError(f"Twenty Questions {key} cannot be empty")
    return path


def register(
    registry: Any,
    context: ModeRuntimeContext,
    settings: Mapping[str, Any],
) -> None:
    """Construct and register the dataset-backed mode."""
    show_in_menu = settings.get("show_in_menu", True)
    if not isinstance(show_in_menu, bool):
        raise TypeError("Twenty Questions show_in_menu must be true or false")
    debug = settings.get("debug", settings.get("twenty_questions_debug", False))
    data_path = _path_setting(settings, "data_path", BASE_DATA_PATH)
    learned_path = _path_setting(settings, "learned_path", LEARNED_DATA_PATH)
    history_path = _path_setting(settings, "history_path", HISTORY_PATH)
    resolved_history_path = history_path.resolve()
    if resolved_history_path in {
        data_path.resolve(),
        learned_path.resolve(),
    }:
        raise TwentyQuestionsDataError(
            "Twenty Questions history_path must be different from "
            "data_path and learned_path"
        )
    loader = TwentyQuestionsDatasetLoader(data_path, learned_path)
    game = TwentyQuestionsGame(
        loader=loader,
        debug=bool(debug),
        informative_question_limit=settings.get(
            "informative_question_limit",
            TwentyQuestionsGame.MAX_INFORMATIVE_DECISIONS,
        ),
        total_prompt_limit=settings.get(
            "total_prompt_limit",
            TwentyQuestionsGame.MAX_TOTAL_PROMPTS,
        ),
    )
    registry.register(
        TwentyQuestionsMode(
            game,
            master=context.master,
            text_model=context.text_model,
            chat=context.chat,
            speak_response=context.speak_response,
            wait_for_tts=context.wait_for_tts,
            set_state=context.set_state,
            face_provider=context.face_provider,
            thing_history=TwentyQuestionsHistory(history_path),
            dispatch_ui=context.call_soon,
            answer_wait_seconds=settings.get(
                "answer_wait_seconds",
                settings.get("game_answer_wait_seconds", 12),
            ),
            menu_item=TWENTY_QUESTIONS_MENU_ITEM if show_in_menu else None,
        )
    )


__all__ = [
    "TWENTY_QUESTIONS_MENU_ITEM",
    "TwentyQuestionsMode",
    "register",
]
