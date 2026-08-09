"""Regression tests for per-interaction application failure boundaries."""

from __future__ import annotations

import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, call, patch

from bmo.app import BotGUI
from bmo.features import ToolResult
from bmo.modes import InputPolicy
from bmo.state import BotStates
from typed_agent import TypedBotGUI


class InteractionFailureRecoveryTests(unittest.TestCase):
    def _configure_gui(self, gui: BotGUI) -> list[Mock]:
        gui.exiting = False
        gui.shutdown_event = threading.Event()
        gui.interrupted = threading.Event()
        gui.thinking_sound_active = threading.Event()
        gui.recording_active = threading.Event()
        gui.current_interaction = None
        gui.current_state = BotStates.IDLE
        gui.text_model = "test-model"
        gui.vision_model = "vision-model"
        gui.master = Mock()
        gui.tts_thread = None
        gui.warm_up_logic = Mock()
        gui._tts_worker = Mock()
        gui.set_state = Mock()
        gui.append_to_text = Mock()
        gui.enqueue_speech = Mock()
        gui.wait_for_tts = Mock()
        gui._remember_turn = Mock()

        gui.mode_registry = Mock()
        gui.mode_registry.input_policy.return_value = InputPolicy.wake_word()
        gui.mode_registry.route_input.return_value = False
        gui.mode_registry.is_active.return_value = False

        gui.tool_router = Mock()
        gui.tool_router.normalize_action.return_value = "buggy_tool"
        gui.tool_router.match_direct_action.return_value = {
            "action": "buggy_tool"
        }
        gui.tool_router.execute.side_effect = [
            RuntimeError("tool exploded"),
            ToolResult.success("The next request worked."),
        ]

        archives: list[Mock] = []

        def start_interaction(trigger: str) -> None:
            archive = Mock()
            archive.path = Path(f"/tmp/test-archive-{len(archives)}")
            archive.audio_path = archive.path / "input" / "voice.wav"
            archive.speech_path.return_value = (
                archive.path / "output" / "speech.wav"
            )
            archive.trigger = trigger
            archives.append(archive)
            gui.current_interaction = archive

        gui._start_interaction = start_interaction
        return archives

    def _assert_failed_tool_then_success(
        self,
        gui: BotGUI,
        archives: list[Mock],
        output: str,
    ) -> None:
        self.assertEqual(gui.tool_router.execute.call_count, 2)
        self.assertEqual(len(archives), 2)
        archives[0].finish.assert_called_once_with("error", "tool exploded")
        archives[1].finish.assert_called_once_with("completed", None)
        self.assertEqual(gui.current_interaction, None)
        self.assertFalse(gui.thinking_sound_active.is_set())
        self.assertIn("buggy_tool", output)
        self.assertIn("tool exploded", output)
        self.assertIn(
            call(BotStates.IDLE, "Ready"),
            gui.set_state.call_args_list,
        )
        gui.enqueue_speech.assert_any_call(gui.INTERACTION_FAILURE_MESSAGE)

        failed_tool_records = [
            archive_call.args[2]
            for archive_call in archives[0].append_json.call_args_list
            if len(archive_call.args) >= 3
            and archive_call.args[:2] == ("output", "tools.jsonl")
        ]
        self.assertEqual(len(failed_tool_records), 1)
        self.assertEqual(failed_tool_records[0]["action"], "buggy_tool")
        self.assertEqual(failed_tool_records[0]["error"], "tool exploded")

    def test_voice_tool_exception_does_not_end_following_request(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        archives = self._configure_gui(gui)
        gui.detect_wake_word_or_ptt = Mock(
            side_effect=["WAKE", "WAKE", "STOP"]
        )
        gui.recorder = Mock()
        gui.recorder.record_adaptive.side_effect = [
            "first.wav",
            "second.wav",
        ]
        gui.transcriber = Mock()
        gui.transcriber.transcribe.side_effect = [
            "run the broken tool",
            "run it again",
        ]
        gui.random_sound = Mock(return_value=None)
        gui.play_sound = Mock()

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            gui.safe_main_execution()

        self._assert_failed_tool_then_success(gui, archives, stdout.getvalue())

    def test_typed_tool_exception_does_not_end_following_request(self) -> None:
        gui = TypedBotGUI.__new__(TypedBotGUI)
        archives = self._configure_gui(gui)
        gui._wait_for_typed_input = Mock(
            side_effect=[
                "run the broken tool",
                "run it again",
                None,
            ]
        )

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            gui.safe_main_execution()

        self._assert_failed_tool_then_success(gui, archives, stdout.getvalue())

    def test_expected_tool_result_is_not_logged_as_unexpected(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.current_interaction = None
        gui.tool_router = Mock()
        gui.tool_router.normalize_action.return_value = "expected_failure"
        gui.tool_router.execute.return_value = ToolResult.error()

        output = StringIO()
        with redirect_stdout(output):
            result = gui._execute_tool({"action": "expected_failure"})

        self.assertEqual(result, ToolResult.error())
        self.assertNotIn("Unexpected failure", output.getvalue())

    def test_startup_failure_remains_outside_interaction_recovery(self) -> None:
        gui = TypedBotGUI.__new__(TypedBotGUI)
        self._configure_gui(gui)
        gui.warm_up_logic = Mock(side_effect=RuntimeError("startup exploded"))
        gui._wait_for_typed_input = Mock()
        gui._recover_interaction_failure = Mock()

        with redirect_stderr(StringIO()):
            gui.safe_main_execution()

        gui._recover_interaction_failure.assert_not_called()
        gui._wait_for_typed_input.assert_not_called()
        gui.set_state.assert_called_once_with(
            BotStates.ERROR,
            "Fatal Error: startup exploded",
        )

    @patch("bmo.app.ollama.generate")
    @patch("bmo.app.save_chat_history")
    def test_shutdown_still_closes_features_and_modes(
        self,
        save_chat_history: Mock,
        generate: Mock,
    ) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.shutdown_event = threading.Event()
        gui.tool_router = Mock()
        gui.mode_registry = Mock()
        gui.interrupted = threading.Event()
        gui.ptt_event = threading.Event()
        gui.recording_active = threading.Event()
        gui.thinking_sound_active = threading.Event()
        gui.tts_queue_lock = threading.Lock()
        gui.tts_queue = []
        gui.speaker = Mock()
        gui.main_thread = None
        gui.tts_thread = None
        gui.permanent_memory = []
        gui.session_memory = []
        gui.text_model = "test-model"
        gui.master = Mock()

        gui.safe_exit()
        gui.safe_exit()

        gui.tool_router.close.assert_called_once_with()
        gui.mode_registry.close.assert_called_once_with()
        gui.speaker.stop.assert_called_once_with()
        self.assertTrue(gui.shutdown_event.is_set())
        self.assertTrue(gui.interrupted.is_set())
        self.assertTrue(gui.ptt_event.is_set())
        save_chat_history.assert_called_once()
        generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
