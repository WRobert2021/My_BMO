"""Tests for GUI-neutral voice capture and transcription execution."""

from __future__ import annotations

import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from bmo.modes import InputPolicy
from bmo.runtime_loop import RuntimeTurn
from bmo.runtime_voice import RuntimeVoiceTurnExecutor
from bmo.state import BotStates


class RuntimeVoiceTurnExecutorTests(unittest.TestCase):
    def make_executor(
        self,
        *,
        archive: Mock | None = None,
        mode_active: bool = False,
    ):
        recorder = Mock()
        recorder.record_adaptive.return_value = "captured.wav"
        recorder.record_ptt.return_value = "captured.wav"
        transcriber = Mock()
        transcriber.transcribe.return_value = "hello BMO"
        recording_active = threading.Event()
        shutdown = threading.Event()
        interrupted = threading.Event()
        callbacks = {
            "start_interaction": Mock(),
            "current_archive": Mock(return_value=archive),
            "finish_interaction": Mock(),
            "play_acknowledgement": Mock(),
            "mode_is_active": Mock(return_value=mode_active),
            "set_state": Mock(),
            "present_transcript": Mock(),
            "chat": Mock(),
        }
        executor = RuntimeVoiceTurnExecutor(
            recorder=recorder,
            transcriber=transcriber,
            recording_active_event=recording_active,
            shutdown_event=shutdown,
            interrupted_event=interrupted,
            **callbacks,
        )
        return (
            executor,
            recorder,
            transcriber,
            recording_active,
            shutdown,
            interrupted,
            callbacks,
        )

    @staticmethod
    def make_archive() -> Mock:
        archive = Mock()
        archive.audio_path = Path("archive/input/voice.wav")
        archive.path = Path("archive")
        return archive

    def test_adaptive_turn_transcribes_archives_and_chats(self) -> None:
        archive = self.make_archive()
        (
            executor,
            recorder,
            transcriber,
            _recording,
            shutdown,
            interrupted,
            callbacks,
        ) = self.make_executor(archive=archive)
        interrupted.set()
        transcriber.transcribe.return_value = "  hello BMO  "
        policy = InputPolicy.wake_word()

        self.assertTrue(executor.execute(RuntimeTurn.ready(policy, "WAKE")))

        callbacks["start_interaction"].assert_called_once_with("WAKE")
        recorder.record_adaptive.assert_called_once_with(
            filename="archive/input/voice.wav",
            shutdown_event=shutdown,
            initial_silence_timeout=policy.initial_silence_timeout,
        )
        recorder.record_ptt.assert_not_called()
        callbacks["play_acknowledgement"].assert_called_once_with()
        transcriber.transcribe.assert_called_once_with(
            "captured.wav",
            archive_directory=Path("archive/input"),
        )
        archive.write_text.assert_called_once_with(
            "input",
            "transcript.txt",
            "hello BMO\n",
        )
        archive.event.assert_called_once_with(
            "transcription_completed",
            {"text": "hello BMO", "audio_file": "captured.wav"},
        )
        callbacks["present_transcript"].assert_called_once_with("hello BMO")
        callbacks["chat"].assert_called_once_with("hello BMO")
        callbacks["finish_interaction"].assert_called_once_with("completed")
        self.assertFalse(interrupted.is_set())

    def test_push_to_talk_uses_recording_event_and_fallback_path(self) -> None:
        (
            executor,
            recorder,
            _transcriber,
            recording,
            shutdown,
            _interrupted,
            callbacks,
        ) = self.make_executor()

        self.assertTrue(
            executor.execute(RuntimeTurn.ready(InputPolicy.wake_word(), "PTT"))
        )

        recorder.record_ptt.assert_called_once_with(
            recording,
            filename="input.wav",
            shutdown_event=shutdown,
        )
        recorder.record_adaptive.assert_not_called()
        callbacks["current_archive"].assert_called_once_with()
        callbacks["finish_interaction"].assert_called_once_with("completed")

    def test_no_speech_uses_mode_retry_or_normal_idle_state(self) -> None:
        policy = InputPolicy.continuous(
            initial_silence_timeout=2.0,
            listening_status="Listening",
            no_speech_status="Tap and try again.",
            empty_transcript_status="No answer.",
        )
        executor, recorder, transcriber, *_rest, callbacks = self.make_executor(
            mode_active=True
        )
        recorder.record_adaptive.return_value = None

        self.assertTrue(executor.execute(RuntimeTurn.ready(policy, "GAME")))

        callbacks["set_state"].assert_called_once_with(
            BotStates.LISTENING,
            "Tap and try again.",
        )
        callbacks["finish_interaction"].assert_called_once_with("no_speech")
        callbacks["play_acknowledgement"].assert_not_called()
        transcriber.transcribe.assert_not_called()

        normal, normal_recorder, *_unused, normal_callbacks = self.make_executor()
        normal_recorder.record_adaptive.return_value = None

        normal.execute(RuntimeTurn.ready(InputPolicy.wake_word(), "WAKE"))

        normal_callbacks["set_state"].assert_called_once_with(
            BotStates.IDLE,
            "Heard nothing.",
        )

    def test_empty_transcript_uses_current_mode_state(self) -> None:
        policy = InputPolicy.continuous(
            initial_silence_timeout=2.0,
            listening_status="Listening",
            no_speech_status="No speech.",
            empty_transcript_status="Please answer again.",
        )
        executor, _recorder, transcriber, *_rest, callbacks = self.make_executor(
            mode_active=True
        )
        transcriber.transcribe.return_value = "   "

        self.assertTrue(executor.execute(RuntimeTurn.ready(policy, "GAME")))

        callbacks["set_state"].assert_called_once_with(
            BotStates.LISTENING,
            "Please answer again.",
        )
        callbacks["finish_interaction"].assert_called_once_with(
            "transcription_empty"
        )
        callbacks["present_transcript"].assert_not_called()
        callbacks["chat"].assert_not_called()

    def test_capture_failure_propagates_to_worker_recovery(self) -> None:
        executor, recorder, *_unused, callbacks = self.make_executor()
        recorder.record_adaptive.side_effect = RuntimeError("microphone failed")

        with self.assertRaisesRegex(RuntimeError, "microphone failed"):
            executor.execute(RuntimeTurn.ready(InputPolicy.wake_word(), "WAKE"))

        callbacks["start_interaction"].assert_called_once_with("WAKE")
        callbacks["finish_interaction"].assert_not_called()

    def test_rejects_non_ready_turns_and_missing_ports(self) -> None:
        executor, *_rest = self.make_executor()

        with self.assertRaisesRegex(ValueError, "requires a ready turn"):
            executor.execute(RuntimeTurn.handled())
        with self.assertRaisesRegex(TypeError, "recorder must expose"):
            RuntimeVoiceTurnExecutor(
                recorder=object(),  # type: ignore[arg-type]
                transcriber=Mock(),
                recording_active_event=threading.Event(),
                shutdown_event=threading.Event(),
                interrupted_event=threading.Event(),
                start_interaction=Mock(),
                current_archive=Mock(return_value=None),
                finish_interaction=Mock(),
                play_acknowledgement=Mock(),
                mode_is_active=Mock(),
                set_state=Mock(),
                present_transcript=Mock(),
                chat=Mock(),
            )


class RuntimeVoiceImportTests(unittest.TestCase):
    def test_import_initializes_no_gui_or_audio_backend(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bmo.runtime_voice; "
                    "assert 'tkinter' not in sys.modules; "
                    "assert 'PySide6' not in sys.modules; "
                    "assert 'sounddevice' not in sys.modules; "
                    "assert 'openwakeword' not in sys.modules; "
                    "assert 'onnxruntime' not in sys.modules"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
