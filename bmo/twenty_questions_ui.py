"""Embedded touch UI for the menu-launched Twenty Questions mode."""

from __future__ import annotations

from collections.abc import Callable
import tkinter as tk

from PIL import Image

from bmo.twenty_questions import TwentyQuestionsGame
from bmo.ui.compact_face import CompactFace


WINDOW_SIZE = (800, 480)
PLAYER_BUTTONS = (("Yes", "yes"), ("No", "no"), ("Sometimes", "sometimes"), ("I DON'T KNOW", "unknown"))
GUESS_BUTTONS = (("Yes", "yes"), ("No", "no"), ("I DON'T KNOW", "unknown"))


class TwentyQuestionsApp:
    """Draw the current game state and send touch answers to the mode."""

    BACKGROUND = "#eef8ff"
    NAVY = "#102a5e"
    BLUE = "#1578d3"
    CYAN = "#bde7ff"
    WHITE = "#ffffff"
    MUTED = "#58708c"
    GREEN = "#198754"

    def __init__(
        self,
        root: tk.Misc,
        *,
        game: TwentyQuestionsGame,
        on_answer: Callable[[str], None],
        on_reveal: Callable[[str], None],
        on_play_again: Callable[[], None],
        on_close: Callable[[], None],
        thing_history_provider: Callable[[], tuple[str, ...]],
        face_provider: Callable[[], Image.Image | None] | None = None,
    ) -> None:
        self.root = root
        self.game = game
        self.on_answer = on_answer
        self.on_reveal = on_reveal
        self.on_play_again = on_play_again
        self.on_close = on_close
        self.thing_history_provider = thing_history_provider
        self.closed = False
        self.canvas = tk.Canvas(
            root,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            bg=self.BACKGROUND,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1])
        self.button_items: list[int] = []
        self.button_tags: list[str] = []
        self.reveal_entry: tk.Entry | None = None
        self._draw_static_ui()
        self.compact_face = CompactFace(
            root,
            self.canvas,
            face_provider=face_provider,
        )
        self.refresh()

    def _draw_static_ui(self) -> None:
        self.canvas.create_rectangle(0, 0, 800, 62, fill=self.NAVY, outline="")
        self.canvas.create_text(
            24,
            30,
            anchor=tk.W,
            text="20 QUESTIONS",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self._draw_button(552, 10, 668, 51, "EXIT GAME", self.close, color=self.BLUE)
        # The EXIT control is static; dynamic answer controls are tracked
        # separately and rebuilt whenever the game state changes.
        self.button_items.clear()
        self.button_tags.clear()

        self.canvas.create_rectangle(
            626,
            76,
            792,
            450,
            fill=self.NAVY,
            outline=self.WHITE,
            width=3,
        )
        self.candidate_item = self.canvas.create_text(
            709,
            220,
            text="",
            fill=self.WHITE,
            font=("Arial", 11, "bold"),
        )
        self.prompt_count_item = self.canvas.create_text(
            709,
            246,
            text="",
            fill=self.CYAN,
            font=("Arial", 10),
        )
        self.canvas.create_text(
            640,
            278,
            anchor=tk.W,
            text="LAST 5 THINGS",
            fill=self.CYAN,
            font=("Arial", 9, "bold"),
        )
        self.last_thing_items = [
            self.canvas.create_text(
                640,
                306 + index * 27,
                anchor=tk.W,
                text="—",
                fill=self.WHITE,
                width=145,
                font=("Arial", 8),
            )
            for index in range(5)
        ]

        self.canvas.create_rectangle(
            24,
            86,
            602,
            270,
            fill=self.WHITE,
            outline=self.NAVY,
            width=3,
        )
        self.canvas.create_text(
            52,
            112,
            anchor=tk.W,
            text="BMO ASKS",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self.question_item = self.canvas.create_text(
            313,
            176,
            text="",
            fill=self.NAVY,
            width=510,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self.status_item = self.canvas.create_text(
            313,
            244,
            text="",
            fill=self.MUTED,
            width=510,
            font=("Arial", 12, "bold"),
        )
        self.canvas.create_text(
            24,
            300,
            anchor=tk.W,
            text="TAP AN ANSWER",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self.answer_top = 320

    def _draw_button(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        label: str,
        command: Callable[[], None],
        *,
        color: str,
    ) -> None:
        tag = f"twenty-questions-button-{label.casefold().replace(' ', '-')}"
        self.button_tags.append(tag)
        self.button_items.append(
            self.canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                fill=color,
                outline="",
                tags=(tag,),
            )
        )
        self.button_items.append(
            self.canvas.create_text(
                (left + right) // 2,
                (top + bottom) // 2,
                text=label,
                fill=self.WHITE,
                font=("Arial", 11, "bold"),
                tags=(tag,),
            )
        )
        self.canvas.tag_bind(tag, "<Button-1>", lambda _event: command())

    def _clear_buttons(self) -> None:
        for item in self.button_items:
            self.canvas.delete(item)
        self.button_items.clear()
        self.button_tags.clear()

    def _draw_answer_buttons(self) -> None:
        self._clear_buttons()
        if not self.game.active:
            self._draw_button(
                24,
                320,
                240,
                372,
                "PLAY AGAIN",
                self.on_play_again,
                color=self.GREEN,
            )
            return
        if self.game.awaiting_reveal:
            self._draw_button(
                438,
                382,
                602,
                424,
                "SUBMIT OBJECT",
                self._submit_reveal,
                color=self.GREEN,
            )
            return
        choices = (
            GUESS_BUTTONS
            if self.game.current_guess is not None or self.game.current_llm_guess is not None
            else PLAYER_BUTTONS
        )
        left = 24
        gap = 12
        width = (578 - gap * (len(choices) - 1)) // len(choices)
        for label, answer in choices:
            right = left + width
            self._draw_button(
                left,
                self.answer_top,
                right,
                372,
                label,
                lambda answer=answer: self.on_answer(answer),
                color=self.BLUE,
            )
            left = right + gap

    def _show_reveal_entry(self) -> None:
        if not self.game.awaiting_reveal or not self.game.active:
            if self.reveal_entry is not None:
                self.reveal_entry.destroy()
                self.reveal_entry = None
            return
        if self.reveal_entry is None:
            self.reveal_entry = tk.Entry(
                self.root,
                font=("Arial", 16),
                justify=tk.CENTER,
                relief=tk.FLAT,
            )
            self.reveal_entry.place(x=24, y=382, width=400, height=42)
            self.reveal_entry.focus_set()

    def _submit_reveal(self) -> None:
        if self.reveal_entry is None:
            return
        value = self.reveal_entry.get().strip()
        if value:
            self.on_reveal(value)

    def refresh(self, status: str | None = None) -> None:
        """Refresh the question, counters, status, and touch controls."""
        if self.closed:
            return
        if self.game.guess_name is not None:
            question = f"My guess is {self.game.guess_name}. Am I right?"
        elif self.game.current_question is not None:
            question = self.game.current_question
        elif self.game.awaiting_reveal:
            question = "What were you thinking of?"
        else:
            question = "Game complete"
        self.canvas.itemconfigure(self.question_item, text=question)
        self.canvas.itemconfigure(
            self.candidate_item,
            text=f"{self.game.candidate_count} candidates",
        )
        self.canvas.itemconfigure(
            self.prompt_count_item,
            text=(
                f"{self.game.informative_decisions} decisions  •  "
                f"{self.game.total_prompt_count} questions"
            ),
        )
        recent_things = self.thing_history_provider()[:5]
        for index, item in enumerate(self.last_thing_items):
            self.canvas.itemconfigure(
                item,
                text=recent_things[index] if index < len(recent_things) else "—",
            )
        if status is not None:
            self.canvas.itemconfigure(self.status_item, text=status)
        elif self.game.awaiting_reveal:
            self.canvas.itemconfigure(
                self.status_item,
                text="Tell me the object and I’ll learn it.",
            )
        elif self.game.active:
            self.canvas.itemconfigure(
                self.status_item,
                text="Tap an answer, or tap EXIT GAME to stop.",
            )
        else:
            self.canvas.itemconfigure(
                self.status_item,
                text="Tap PLAY AGAIN to start another game.",
            )
        self._draw_answer_buttons()
        self._show_reveal_entry()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.compact_face.destroy()
        if self.reveal_entry is not None:
            self.reveal_entry.destroy()
            self.reveal_entry = None
        try:
            self.canvas.destroy()
        except tk.TclError:
            pass
        self.on_close()


__all__ = ["GUESS_BUTTONS", "PLAYER_BUTTONS", "TwentyQuestionsApp"]
