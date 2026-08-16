"""Tests for UI-neutral worker ownership and voice-turn arbitration."""

from __future__ import annotations

import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from bmo.modes import InputPolicy
from bmo.runtime_loop import (
    RuntimeTurn,
    RuntimeTurnCoordinator,
    RuntimeTurnKind,
    RuntimeWorkerLoop,
)
from bmo.state import BotStates


class RuntimeWorkerLoopTests(unittest.TestCase):
    def make_loop(self, **overrides):
        shutdown_event = overrides.pop("shutdown_event", threading.Event())
        callbacks = {
            "initialize": Mock(),
            "run_iteration": Mock(return_value=False),
            "recover_failure": Mock(),
            "handle_startup_failure": Mock(),
            "handle_shutdown_failure": Mock(),
            "is_exiting": Mock(return_value=False),
        }
        callbacks.update(overrides)
        loop = RuntimeWorkerLoop(
            shutdown_event=shutdown_event,
            **callbacks,
        )
        return loop, shutdown_event, callbacks

    def test_initializes_once_and_runs_until_iteration_stops(self) -> None:
        iteration = Mock(side_effect=[True, True, False])
        loop, _shutdown, callbacks = self.make_loop(
            run_iteration=iteration,
        )

        loop.run()

        callbacks["initialize"].assert_called_once_with()
        self.assertEqual(iteration.call_count, 3)
        callbacks["recover_failure"].assert_not_called()

    def test_recovers_one_turn_failure_and_continues(self) -> None:
        iteration = Mock(side_effect=[RuntimeError("turn failed"), False])
        loop, _shutdown, callbacks = self.make_loop(
            run_iteration=iteration,
        )

        loop.run()

        callbacks["recover_failure"].assert_called_once()
        self.assertEqual(
            str(callbacks["recover_failure"].call_args.args[0]),
            "turn failed",
        )
        self.assertEqual(iteration.call_count, 2)

    def test_startup_failure_does_not_enter_turn_recovery(self) -> None:
        loop, _shutdown, callbacks = self.make_loop(
            initialize=Mock(side_effect=RuntimeError("startup failed")),
        )

        loop.run()

        callbacks["handle_startup_failure"].assert_called_once()
        callbacks["run_iteration"].assert_not_called()
        callbacks["recover_failure"].assert_not_called()

    def test_failure_during_shutdown_uses_shutdown_handler(self) -> None:
        shutdown_event = threading.Event()

        def fail_during_shutdown() -> bool:
            shutdown_event.set()
            raise RuntimeError("cancelled work")

        loop, _shutdown, callbacks = self.make_loop(
            shutdown_event=shutdown_event,
            run_iteration=Mock(side_effect=fail_during_shutdown),
        )

        loop.run()

        callbacks["handle_shutdown_failure"].assert_called_once()
        callbacks["recover_failure"].assert_not_called()


class RuntimeTurnCoordinatorTests(unittest.TestCase):
    def make_coordinator(self, **overrides):
        shutdown_event = overrides.pop("shutdown_event", threading.Event())
        interrupted_event = overrides.pop(
            "interrupted_event",
            threading.Event(),
        )
        callbacks = {
            "is_exiting": Mock(return_value=False),
            "quiet_hours_locked": Mock(return_value=False),
            "start_pending_action": Mock(return_value=False),
            "input_policy": Mock(return_value=InputPolicy.wake_word()),
            "wait_for_wake_trigger": Mock(return_value="WAKE"),
            "set_state": Mock(),
        }
        callbacks.update(overrides)
        coordinator = RuntimeTurnCoordinator(
            shutdown_event=shutdown_event,
            interrupted_event=interrupted_event,
            **callbacks,
        )
        return coordinator, shutdown_event, interrupted_event, callbacks

    def test_pending_menu_action_has_priority_over_voice_input(self) -> None:
        coordinator, _shutdown, _interrupted, callbacks = self.make_coordinator(
            start_pending_action=Mock(return_value=True),
        )

        turn = coordinator.next_turn()

        self.assertEqual(turn, RuntimeTurn.handled())
        callbacks["input_policy"].assert_not_called()
        callbacks["wait_for_wake_trigger"].assert_not_called()

    def test_waits_through_quiet_hours_and_suspended_mode(self) -> None:
        coordinator, shutdown, _interrupted, callbacks = self.make_coordinator(
            quiet_hours_locked=Mock(side_effect=[True, False]),
            input_policy=Mock(
                side_effect=[InputPolicy.suspended(), InputPolicy.wake_word()]
            ),
        )
        shutdown.wait = Mock()  # type: ignore[method-assign]

        turn = coordinator.next_turn()

        self.assertEqual(turn.kind, RuntimeTurnKind.READY)
        self.assertEqual(turn.trigger_source, "WAKE")
        self.assertEqual(shutdown.wait.call_count, 2)
        self.assertEqual(
            callbacks["set_state"].call_args_list,
            [
                call(BotStates.IDLE, "Waiting..."),
                call(BotStates.LISTENING, "I'm listening!"),
            ],
        )

    def test_continuous_mode_skips_wake_word_wait(self) -> None:
        policy = InputPolicy.continuous(
            initial_silence_timeout=2.0,
            listening_status="Tap an answer.",
            no_speech_status="Try again.",
            empty_transcript_status="No answer.",
            trigger_source="GAME",
        )
        coordinator, _shutdown, _interrupted, callbacks = self.make_coordinator(
            input_policy=Mock(return_value=policy),
        )

        turn = coordinator.next_turn()

        self.assertEqual(turn, RuntimeTurn.ready(policy, "GAME"))
        callbacks["wait_for_wake_trigger"].assert_not_called()
        callbacks["set_state"].assert_called_once_with(
            BotStates.LISTENING,
            "Tap an answer.",
        )

    def test_menu_wake_runs_pending_action_without_voice_capture(self) -> None:
        pending = Mock(side_effect=[False, True])
        coordinator, _shutdown, _interrupted, _callbacks = self.make_coordinator(
            start_pending_action=pending,
            wait_for_wake_trigger=Mock(return_value="MENU"),
        )

        turn = coordinator.next_turn()

        self.assertEqual(turn, RuntimeTurn.handled())
        self.assertEqual(pending.call_count, 2)

    def test_interrupt_resets_before_voice_capture(self) -> None:
        interrupted = threading.Event()
        interrupted.set()
        coordinator, _shutdown, _interrupted, callbacks = self.make_coordinator(
            interrupted_event=interrupted,
        )

        turn = coordinator.next_turn()

        self.assertEqual(turn, RuntimeTurn.handled())
        self.assertFalse(interrupted.is_set())
        self.assertEqual(
            callbacks["set_state"].call_args_list[-1],
            call(BotStates.IDLE, "Resetting..."),
        )

    def test_shutdown_stops_quiet_or_suspended_waits(self) -> None:
        shutdown = threading.Event()
        shutdown.set()
        coordinator, _shutdown, _interrupted, callbacks = self.make_coordinator(
            shutdown_event=shutdown,
            quiet_hours_locked=Mock(return_value=True),
        )

        turn = coordinator.next_turn()

        self.assertEqual(turn, RuntimeTurn.stopped())
        callbacks["start_pending_action"].assert_not_called()
        callbacks["input_policy"].assert_not_called()

        shutdown.clear()
        shutdown.wait = Mock(  # type: ignore[method-assign]
            side_effect=lambda _timeout: shutdown.set()
        )
        suspended, _shutdown, _interrupted, callbacks = self.make_coordinator(
            shutdown_event=shutdown,
            input_policy=Mock(return_value=InputPolicy.suspended()),
        )

        self.assertEqual(suspended.next_turn(), RuntimeTurn.stopped())
        shutdown.wait.assert_called_once_with(0.1)
        callbacks["wait_for_wake_trigger"].assert_not_called()

    def test_ready_turn_requires_typed_policy_and_source(self) -> None:
        with self.assertRaisesRegex(TypeError, "requires an InputPolicy"):
            RuntimeTurn(RuntimeTurnKind.READY, None, "WAKE")
        with self.assertRaisesRegex(ValueError, "requires a trigger source"):
            RuntimeTurn(RuntimeTurnKind.READY, InputPolicy.wake_word(), "")
        with self.assertRaisesRegex(ValueError, "cannot carry input details"):
            RuntimeTurn(
                RuntimeTurnKind.HANDLED,
                InputPolicy.wake_word(),
                "WAKE",
            )


class RuntimeLoopImportTests(unittest.TestCase):
    def test_runtime_loop_imports_neither_gui_toolkit(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bmo.runtime_loop; "
                    "assert 'tkinter' not in sys.modules; "
                    "assert 'PySide6' not in sys.modules; "
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
