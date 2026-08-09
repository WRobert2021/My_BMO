"""Integration tests for long-lived interaction modes and adapters."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from bmo.modes import InputPolicy, InputPolicyKind, ModeRegistry
from bmo.modes.games import MatchingGameMode, TwentyQuestionsMode
from bmo.state import BotStates
from bmo.twenty_questions import TwentyQuestionsGame


class StubMode:
    def __init__(self, name: str, start_phrase: str) -> None:
        self.name = name
        self.start_phrase = start_phrase
        self.active = False
        self.started_with: list[str] = []
        self.inputs: list[str] = []
        self.closed = False

    def matches_start_request(self, user_text: str) -> bool:
        return user_text == self.start_phrase

    def start(self, user_text: str) -> None:
        self.started_with.append(user_text)
        self.active = True

    def handle_input(self, user_text: str) -> None:
        self.inputs.append(user_text)
        if user_text == "done":
            self.active = False

    def is_active(self) -> bool:
        return self.active

    def input_policy(self) -> InputPolicy:
        return InputPolicy.continuous(
            initial_silence_timeout=8,
            listening_status="Listening",
            no_speech_status="Again",
            empty_transcript_status="Repeat",
        )

    def close(self) -> None:
        self.closed = True
        self.active = False


class ModeRegistryTests(unittest.TestCase):
    def test_routes_start_and_subsequent_input_through_one_mode(self) -> None:
        first = StubMode("first", "start first")
        second = StubMode("second", "start second")
        registry = ModeRegistry((first, second))

        self.assertFalse(registry.route_input("ordinary chat"))
        self.assertTrue(registry.route_input("start second"))
        self.assertEqual(second.started_with, ["start second"])
        self.assertTrue(registry.is_active())
        self.assertEqual(
            registry.input_policy().kind,
            InputPolicyKind.CONTINUOUS,
        )

        self.assertTrue(registry.route_input("start first"))
        self.assertEqual(second.inputs, ["start first"])
        self.assertEqual(first.started_with, [])

        self.assertTrue(registry.route_input("done"))
        self.assertFalse(registry.is_active())
        self.assertEqual(
            registry.input_policy().kind,
            InputPolicyKind.WAKE_WORD,
        )

    def test_close_releases_every_registered_mode_once(self) -> None:
        first = StubMode("first", "first")
        second = StubMode("second", "second")
        registry = ModeRegistry((first, second))
        registry.route_input("first")

        registry.close()
        registry.close()

        self.assertTrue(first.closed)
        self.assertTrue(second.closed)
        self.assertFalse(registry.is_active())


class TwentyQuestionsModeTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.game = TwentyQuestionsGame(Path(temp_dir.name) / "learned.json")
        self.spoken: list[str] = []
        self.states: list[tuple[str, str]] = []
        self.wait_count = 0

        def wait_for_tts() -> None:
            self.wait_count += 1

        self.mode = TwentyQuestionsMode(
            self.game,
            text_model="test-model",
            chat=Mock(),
            speak_response=lambda text, _image: self.spoken.append(text),
            wait_for_tts=wait_for_tts,
            set_state=lambda state, status: self.states.append((state, status)),
            answer_wait_seconds=17.5,
        )

    def test_adapter_starts_real_engine_and_preserves_listening_policy(self) -> None:
        self.assertTrue(self.mode.matches_start_request("Let's play 20 questions"))

        self.mode.start("Let's play 20 questions")

        self.assertTrue(self.game.active)
        self.assertTrue(self.mode.is_active())
        self.assertIn("Think of anything", self.spoken[-1])
        self.assertEqual(self.wait_count, 1)
        self.assertEqual(self.states[0], (BotStates.THINKING, "Thinking..."))
        self.assertEqual(
            self.states[-1],
            (BotStates.LISTENING, "Take your time. I'm listening..."),
        )
        policy = self.mode.input_policy()
        self.assertEqual(policy.kind, InputPolicyKind.CONTINUOUS)
        self.assertEqual(policy.initial_silence_timeout, 17.5)
        self.assertEqual(policy.trigger_source, "GAME")
        self.assertEqual(policy.no_speech_status, "Still listening...")
        self.assertEqual(
            policy.empty_transcript_status,
            "I didn't catch that. Try again...",
        )

    def test_adapter_handles_followup_and_reports_when_engine_finishes(self) -> None:
        self.mode.start("Twenty questions")

        self.mode.handle_input("stop")

        self.assertFalse(self.mode.is_active())
        self.assertEqual(self.spoken[-1], "Okay, game over!")
        self.assertEqual(self.states[-1], (BotStates.IDLE, "Ready"))
        self.assertEqual(self.wait_count, 2)

    def test_answer_timeout_keeps_existing_bounds_and_fallback(self) -> None:
        common: dict[str, Any] = {
            "game": self.game,
            "text_model": "test-model",
            "chat": Mock(),
            "speak_response": Mock(),
            "wait_for_tts": Mock(),
            "set_state": Mock(),
        }
        too_short = TwentyQuestionsMode(
            **common,
            answer_wait_seconds=1,
        )
        too_long = TwentyQuestionsMode(
            **common,
            answer_wait_seconds=90,
        )
        invalid = TwentyQuestionsMode(
            **common,
            answer_wait_seconds="eventually",
        )

        self.assertEqual(too_short.input_policy().initial_silence_timeout, 3)
        self.assertEqual(too_long.input_policy().initial_silence_timeout, 30)
        self.assertEqual(invalid.input_policy().initial_silence_timeout, 12)


class MatchingGameModeTests(unittest.TestCase):
    def test_adapter_opens_existing_embedded_ui_with_same_callbacks(self) -> None:
        created: dict[str, Any] = {}
        states: list[tuple[str, str]] = []
        spoken: list[str] = []
        remembered: list[tuple[str, str]] = []
        announced: list[str] = []
        announce = announced.append
        face = Mock(return_value=None)

        class ImmediateMaster:
            @staticmethod
            def after(_delay: int, callback) -> str:
                callback()
                return "after-id"

        class FakeMatchingApp:
            def __init__(self, root, **kwargs) -> None:
                created["root"] = root
                created.update(kwargs)

            def close(self) -> None:
                created["on_close"]()

        master = ImmediateMaster()
        mode = MatchingGameMode(
            master,
            speak_response=lambda text, _image: spoken.append(text),
            remember_turn=lambda user, response: remembered.append(
                (user, response)
            ),
            wait_for_tts=Mock(),
            set_state=lambda state, status: states.append((state, status)),
            announce=announce,
            face_provider=face,
            app_factory=FakeMatchingApp,
        )

        self.assertTrue(mode.matches_start_request("Start a memory game"))
        mode.start("Start a memory game")

        self.assertTrue(mode.is_active())
        self.assertEqual(mode.input_policy().kind, InputPolicyKind.SUSPENDED)
        self.assertIs(created["root"], master)
        self.assertTrue(created["embedded"])
        self.assertIs(created["announce"], announce)
        self.assertIs(created["face_provider"], face)
        self.assertIn("Tap two cards", spoken[0])
        self.assertEqual(remembered, [("Start a memory game", spoken[0])])
        self.assertEqual(states[-1], (BotStates.IDLE, "Your turn."))

        created["on_player_change"]("bmo")
        self.assertEqual(states[-1], (BotStates.THINKING, "BMO's turn."))
        created["on_player_change"]("human")
        self.assertEqual(states[-1], (BotStates.IDLE, "Your turn."))

        mode.ui.close()
        self.assertFalse(mode.is_active())
        self.assertIsNone(mode.ui)
        self.assertEqual(states[-1], (BotStates.IDLE, "Ready"))


if __name__ == "__main__":
    unittest.main()
