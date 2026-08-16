"""UI-neutral capture, transcription, and completion for one voice turn."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
from typing import Any, Protocol

from bmo.modes.contracts import InputPolicyKind
from bmo.runtime_loop import RuntimeTurn, RuntimeTurnKind
from bmo.state import BotStates


class VoiceRecorderPort(Protocol):
    """Audio-capture operations required by the voice-turn runtime."""

    def record_ptt(
        self,
        recording_active: threading.Event,
        filename: str = "input.wav",
        shutdown_event: threading.Event | None = None,
    ) -> str | None:
        """Capture until push-to-talk is released."""

    def record_adaptive(
        self,
        filename: str = "input.wav",
        shutdown_event: threading.Event | None = None,
        initial_silence_timeout: float = 1.5,
    ) -> str | None:
        """Capture one silence-bounded utterance."""


class VoiceTranscriberPort(Protocol):
    """Speech-to-text operation required by the voice-turn runtime."""

    def transcribe(
        self,
        filename: str | Path,
        archive_directory: str | Path | None = None,
    ) -> str:
        """Return the captured utterance as text."""


class VoiceArchivePort(Protocol):
    """Narrow active-interaction archive used by voice execution."""

    audio_path: Path
    path: Path

    def write_text(self, category: str, filename: str, text: str) -> Any:
        """Persist one text artifact."""

    def event(self, event_type: str, details: dict[str, Any]) -> None:
        """Append one interaction event."""


ArchiveProvider = Callable[[], VoiceArchivePort | None]
StartInteraction = Callable[[str], None]
FinishInteraction = Callable[[str], None]
SetState = Callable[[str, str], None]
PresentTranscript = Callable[[str], None]


class RuntimeVoiceTurnExecutor:
    """Execute one prepared voice turn through narrow runtime ports."""

    def __init__(
        self,
        *,
        recorder: VoiceRecorderPort,
        transcriber: VoiceTranscriberPort,
        recording_active_event: threading.Event,
        shutdown_event: threading.Event,
        interrupted_event: threading.Event,
        start_interaction: StartInteraction,
        current_archive: ArchiveProvider,
        finish_interaction: FinishInteraction,
        play_acknowledgement: Callable[[], None],
        mode_is_active: Callable[[], bool],
        set_state: SetState,
        present_transcript: PresentTranscript,
        chat: Callable[[str], None],
    ) -> None:
        if not callable(getattr(recorder, "record_ptt", None)) or not callable(
            getattr(recorder, "record_adaptive", None)
        ):
            raise TypeError(
                "Runtime voice recorder must expose record_ptt() and "
                "record_adaptive()."
            )
        if not callable(getattr(transcriber, "transcribe", None)):
            raise TypeError("Runtime voice transcriber must expose transcribe().")
        callbacks = {
            "start_interaction": start_interaction,
            "current_archive": current_archive,
            "finish_interaction": finish_interaction,
            "play_acknowledgement": play_acknowledgement,
            "mode_is_active": mode_is_active,
            "set_state": set_state,
            "present_transcript": present_transcript,
            "chat": chat,
        }
        for name, callback in callbacks.items():
            if not callable(callback):
                raise TypeError(f"Runtime voice {name} must be callable.")
        for name, event in (
            ("recording_active_event", recording_active_event),
            ("shutdown_event", shutdown_event),
            ("interrupted_event", interrupted_event),
        ):
            if not isinstance(event, threading.Event):
                raise TypeError(f"Runtime voice {name} must be an Event.")

        self._recorder = recorder
        self._transcriber = transcriber
        self._recording_active_event = recording_active_event
        self._shutdown_event = shutdown_event
        self._interrupted_event = interrupted_event
        self._start_interaction = start_interaction
        self._current_archive = current_archive
        self._finish_interaction = finish_interaction
        self._play_acknowledgement = play_acknowledgement
        self._mode_is_active = mode_is_active
        self._set_state = set_state
        self._present_transcript = present_transcript
        self._chat = chat

    def execute(self, turn: RuntimeTurn) -> bool:
        """Capture and process one ready turn; return true to keep looping."""
        if not isinstance(turn, RuntimeTurn):
            raise TypeError("Runtime voice execution requires a RuntimeTurn.")
        if turn.kind is not RuntimeTurnKind.READY:
            raise ValueError("Runtime voice execution requires a ready turn.")
        input_policy = turn.input_policy
        trigger_source = turn.trigger_source
        if input_policy is None or trigger_source is None:
            raise RuntimeError("Ready runtime turn omitted its input details.")

        self._start_interaction(trigger_source)
        archive = self._current_archive()
        audio_path = (
            str(archive.audio_path) if archive is not None else "input.wav"
        )
        if trigger_source == "PTT":
            audio_file = self._recorder.record_ptt(
                self._recording_active_event,
                filename=audio_path,
                shutdown_event=self._shutdown_event,
            )
        else:
            audio_file = self._recorder.record_adaptive(
                filename=audio_path,
                shutdown_event=self._shutdown_event,
                initial_silence_timeout=input_policy.initial_silence_timeout,
            )

        if not audio_file:
            self._present_empty_capture(
                input_policy.kind,
                input_policy.no_speech_status,
            )
            self._finish_interaction("no_speech")
            return True

        self._play_acknowledgement()
        user_text = str(
            self._transcriber.transcribe(
                audio_file,
                archive_directory=(
                    archive.path / "input" if archive is not None else None
                ),
            )
            or ""
        ).strip()
        if not user_text:
            self._present_empty_capture(
                input_policy.kind,
                input_policy.empty_transcript_status,
                transcript_empty=True,
            )
            self._finish_interaction("transcription_empty")
            return True

        if archive is not None:
            archive.write_text("input", "transcript.txt", user_text + "\n")
            archive.event(
                "transcription_completed",
                {"text": user_text, "audio_file": str(audio_file)},
            )
        self._present_transcript(user_text)
        self._interrupted_event.clear()
        self._chat(user_text)
        self._finish_interaction("completed")
        return True

    def _present_empty_capture(
        self,
        policy_kind: InputPolicyKind,
        mode_status: str,
        *,
        transcript_empty: bool = False,
    ) -> None:
        if policy_kind is InputPolicyKind.CONTINUOUS and self._mode_is_active():
            self._set_state(BotStates.LISTENING, mode_status)
            return
        message = "Transcription empty." if transcript_empty else "Heard nothing."
        self._set_state(BotStates.IDLE, message)


__all__ = [
    "RuntimeVoiceTurnExecutor",
    "VoiceArchivePort",
    "VoiceRecorderPort",
    "VoiceTranscriberPort",
]
