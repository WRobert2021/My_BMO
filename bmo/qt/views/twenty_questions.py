"""QML adapter for the Twenty Questions mode."""

from __future__ import annotations

from typing import Any

from bmo.qt.views.base import QtHostedView


class QtTwentyQuestionsView(QtHostedView):
    kind = "twenty_questions"
    title = "20 Questions"

    def __init__(
        self,
        host: Any,
        *,
        game: Any,
        on_answer: Any,
        on_reveal: Any,
        on_play_again: Any,
        on_close: Any,
        thing_history_provider: Any,
        face_provider: Any = None,
    ) -> None:
        del face_provider
        self.game = game
        self.on_answer = on_answer
        self.on_reveal = on_reveal
        self.on_play_again = on_play_again
        self.thing_history_provider = thing_history_provider
        self.status = ""
        super().__init__(host, on_close=on_close)

    def payload(self) -> dict[str, object]:
        if self.game.guess_name is not None:
            question = f"My guess is {self.game.guess_name}. Am I right?"
            answers = ["yes", "no", "unknown"]
        elif self.game.current_question is not None:
            question = self.game.current_question
            answers = ["yes", "no", "sometimes", "unknown"]
        elif self.game.awaiting_reveal:
            question = "What were you thinking of?"
            answers = []
        else:
            question = "Game complete"
            answers = []
        status = self.status
        if not status:
            if self.game.awaiting_reveal:
                status = "Tell me the object and I’ll learn it."
            elif self.game.active:
                status = "Tap an answer."
            else:
                status = "Tap play again to start another game."
        return {
            "question": question,
            "status": status,
            "answers": answers,
            "active": self.game.active,
            "awaitingReveal": self.game.awaiting_reveal,
            "candidateCount": self.game.candidate_count,
            "decisionCount": self.game.informative_decisions,
            "promptCount": self.game.total_prompt_count,
            "recentThings": list(self.thing_history_provider()[:5]),
        }

    def refresh(self, status: str | None = None) -> None:
        if status is not None:
            self.status = status
        super().refresh()

    def handle_action(self, action: str, value: str) -> None:
        if action == "twenty_answer" and self.game.active:
            self.status = "Thinking..."
            self.on_answer(value)
        elif action == "twenty_reveal" and value.strip():
            self.status = "Learning..."
            self.on_reveal(value.strip())
        elif action == "twenty_play_again":
            self.status = "Starting..."
            self.on_play_again()
        else:
            super().handle_action(action, value)
            return
        self.refresh()


__all__ = ["QtTwentyQuestionsView"]
