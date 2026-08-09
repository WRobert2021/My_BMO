"""Twenty Questions interaction mode and registration adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bmo.intent import infer_game_answer, infer_game_candidates
from bmo.modes.contracts import (
    Chat,
    InputPolicy,
    ModeRuntimeContext,
    SetState,
    SpeakResponse,
)
from bmo.state import BotStates
from bmo.twenty_questions import QUESTIONS, TwentyQuestionsGame


GameAnswerInference = Callable[[str, str, Chat], str | None]
CandidateInference = Callable[..., list[dict[str, Any]]]


class TwentyQuestionsMode:
    """Adapt :class:`TwentyQuestionsGame` to the interaction-mode lifecycle."""

    name = "twenty_questions"

    def __init__(
        self,
        game: TwentyQuestionsGame,
        *,
        text_model: str,
        chat: Chat,
        speak_response: SpeakResponse,
        wait_for_tts: Callable[[], None],
        set_state: SetState,
        answer_wait_seconds: object = 12,
        answer_inference: GameAnswerInference = infer_game_answer,
        candidate_inference: CandidateInference = infer_game_candidates,
    ) -> None:
        self.game = game
        self.text_model = text_model
        self.chat = chat
        self.speak_response = speak_response
        self.wait_for_tts = wait_for_tts
        self.set_state = set_state
        self.answer_wait_seconds = self._clamp_answer_wait(answer_wait_seconds)
        self.answer_inference = answer_inference
        self.candidate_inference = candidate_inference

    def matches_start_request(self, user_text: str) -> bool:
        return self.game.is_start_request(user_text)

    def start(self, user_text: str) -> None:
        del user_text
        self.set_state(BotStates.THINKING, "Thinking...")
        response = self.game.start()
        self._speak_and_wait(response)
        self._listen_again()

    def handle_input(self, user_text: str) -> None:
        """Advance the game while retaining its tested Bayesian engine."""
        self.set_state(BotStates.THINKING, "Thinking...")
        if self.game.awaiting_reveal:
            response = self.game.reveal_and_learn(user_text)
            self._speak_and_wait(response)
            self.set_state(BotStates.IDLE, "Ready")
            return

        parsed_answer = self.game.parse_answer(user_text)
        if parsed_answer is None:
            try:
                parsed_answer = self.answer_inference(
                    self.text_model,
                    user_text,
                    self.chat,
                )
                if parsed_answer:
                    print(
                        "[20 QUESTIONS] Local model interpreted: "
                        f"{parsed_answer}",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f"[20 QUESTIONS] Answer interpretation failed: {exc}",
                    flush=True,
                )

        terminal = self.game.accept_answer(parsed_answer or user_text)
        if terminal is not None:
            self._speak_and_wait(terminal)
            if self.game.active:
                self._listen_again()
            else:
                self.set_state(BotStates.IDLE, "Ready")
            return

        if self.game.question_count in {5, 10, 15}:
            self._expand_candidates()

        response = self.game.next_move()
        self._speak_and_wait(response)
        self._listen_again()

    def is_active(self) -> bool:
        return self.game.active

    def input_policy(self) -> InputPolicy:
        return InputPolicy.continuous(
            initial_silence_timeout=self.answer_wait_seconds,
            listening_status="Take your time. I'm listening...",
            no_speech_status="Still listening...",
            empty_transcript_status="I didn't catch that. Try again...",
            trigger_source="GAME",
        )

    def close(self) -> None:
        self.game.active = False
        self.game.awaiting_reveal = False

    def _expand_candidates(self) -> None:
        try:
            total_returned = 0
            total_added = 0
            for attempt in range(2):
                candidates = self.candidate_inference(
                    self.text_model,
                    self.game.structured_history(),
                    [question.key for question in QUESTIONS],
                    self.chat,
                    excluded_names=self.game.expansion_exclusions(),
                    request_count=30 if attempt == 0 else 50,
                    debug=self.game.debug,
                )
                total_returned += len(candidates)
                total_added += self.game.add_provisional_candidates(candidates)
                if total_added >= 20:
                    break
                if attempt == 0 and self.game.debug:
                    print(
                        "[20 QUESTIONS DEBUG] Expansion produced fewer "
                        "than 20 usable candidates; retrying once.",
                        flush=True,
                    )
            print(
                "[20 QUESTIONS] Candidate expansion: "
                f"returned {total_returned}, accepted {total_added}.",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[20 QUESTIONS] Candidate expansion failed: {exc}",
                flush=True,
            )

    def _speak_and_wait(self, response: str) -> None:
        self.speak_response(response, None)
        self.wait_for_tts()

    def _listen_again(self) -> None:
        self.set_state(
            BotStates.LISTENING,
            "Take your time. I'm listening...",
        )

    @staticmethod
    def _clamp_answer_wait(value: object) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = 12.0
        return min(max(seconds, 3.0), 30.0)


def register(
    registry: Any,
    context: ModeRuntimeContext,
    settings: Mapping[str, Any],
) -> None:
    """Construct and register the Twenty Questions lifecycle adapter."""
    debug = settings.get(
        "debug",
        settings.get("twenty_questions_debug", False),
    )
    answer_wait_seconds = settings.get(
        "answer_wait_seconds",
        settings.get("game_answer_wait_seconds", 12),
    )
    registry.register(
        TwentyQuestionsMode(
            TwentyQuestionsGame(debug=bool(debug)),
            text_model=context.text_model,
            chat=context.chat,
            speak_response=context.speak_response,
            wait_for_tts=context.wait_for_tts,
            set_state=context.set_state,
            answer_wait_seconds=answer_wait_seconds,
        )
    )
