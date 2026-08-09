"""Typed lifecycle contract for long-lived interactions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from PIL import Image


SetState = Callable[[str, str], None]
SpeakResponse = Callable[[str, str | None], None]
RememberTurn = Callable[[str, str], None]
Chat = Callable[..., Any]


@dataclass(frozen=True)
class ModeRuntimeContext:
    """Narrow access to application services approved for interaction modes."""

    master: Any
    text_model: str
    chat: Chat
    speak_response: SpeakResponse
    remember_turn: RememberTurn
    wait_for_tts: Callable[[], None]
    set_state: SetState
    announce: Callable[[str], None]
    face_provider: Callable[[], Image.Image | None]

    def __post_init__(self) -> None:
        if not isinstance(self.text_model, str) or not self.text_model.strip():
            raise ValueError("Mode text model cannot be empty.")
        for name in (
            "chat",
            "speak_response",
            "remember_turn",
            "wait_for_tts",
            "set_state",
            "announce",
            "face_provider",
        ):
            if not callable(getattr(self, name)):
                raise TypeError(f"Mode runtime context {name} must be callable.")


class InputPolicyKind(str, Enum):
    """Ways the main input loop behaves while a mode owns the interaction."""

    WAKE_WORD = "wake_word"
    CONTINUOUS = "continuous"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class InputPolicy:
    """Input-loop behavior and user-visible retry messages for a mode."""

    kind: InputPolicyKind
    initial_silence_timeout: float = 1.5
    listening_status: str = "I'm listening!"
    no_speech_status: str = "Heard nothing."
    empty_transcript_status: str = "Transcription empty."
    trigger_source: str = "MODE"

    def __post_init__(self) -> None:
        if self.initial_silence_timeout <= 0:
            raise ValueError("Initial silence timeout must be positive.")
        if not self.trigger_source.strip():
            raise ValueError("Input policy trigger source cannot be empty.")

    @classmethod
    def wake_word(cls) -> InputPolicy:
        """Return the normal one-shot wake-word/PTT policy."""
        return cls(InputPolicyKind.WAKE_WORD, trigger_source="WAKE")

    @classmethod
    def continuous(
        cls,
        *,
        initial_silence_timeout: float,
        listening_status: str,
        no_speech_status: str,
        empty_transcript_status: str,
        trigger_source: str = "GAME",
    ) -> InputPolicy:
        """Return a policy that listens again without another wake word."""
        return cls(
            InputPolicyKind.CONTINUOUS,
            initial_silence_timeout=initial_silence_timeout,
            listening_status=listening_status,
            no_speech_status=no_speech_status,
            empty_transcript_status=empty_transcript_status,
            trigger_source=trigger_source,
        )

    @classmethod
    def suspended(cls) -> InputPolicy:
        """Return a policy that pauses speech input while another UI owns it."""
        return cls(InputPolicyKind.SUSPENDED, trigger_source="SUSPENDED")


class InteractionMode(Protocol):
    """Structural lifecycle implemented by every long-lived interaction."""

    name: str

    def matches_start_request(self, user_text: str) -> bool:
        """Return whether this mode owns the supplied start request."""

    def start(self, user_text: str) -> None:
        """Start the mode in response to a matched request."""

    def handle_input(self, user_text: str) -> None:
        """Handle input after the mode has started."""

    def is_active(self) -> bool:
        """Return whether the mode still owns subsequent input."""

    def input_policy(self) -> InputPolicy:
        """Select how input should be collected while the mode is active."""

    def close(self) -> None:
        """Release resources and end the mode."""
