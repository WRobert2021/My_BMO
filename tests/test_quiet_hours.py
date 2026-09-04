"""Global quiet-hours configuration, policy, and kiosk integration tests."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest.mock import Mock

from bmo.app import BotGUI
from bmo.kiosk_access import (
    KioskAccessPolicy,
    QuietHoursConfig,
    load_quiet_hours_config,
)


class QuietHoursConfigTests(unittest.TestCase):
    def test_missing_or_malformed_config_safely_disables_quiet_hours(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            self.assertFalse(load_quiet_hours_config(missing).enabled)
            malformed = Path(directory) / "quiet.json"
            malformed.write_text("not json", encoding="utf-8")
            messages = []

            config = load_quiet_hours_config(malformed, reporter=messages.append)

            self.assertFalse(config.enabled)
            self.assertEqual(len(messages), 1)

    def test_private_config_accepts_plain_four_digit_passcode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quiet.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "start": "20:30",
                        "end": "06:45",
                        "weekdays": [0, 1, 2, 3, 4],
                        "passcode": "2468",
                        "sleeping_face_directory": "graphics/faces/sleeping",
                    }
                ),
                encoding="utf-8",
            )

            config = load_quiet_hours_config(path)

            self.assertTrue(config.enabled)
            self.assertEqual(config.start, time(20, 30))
            self.assertEqual(config.passcode, "2468")


class KioskAccessPolicyTests(unittest.TestCase):
    def make_policy(self) -> KioskAccessPolicy:
        return KioskAccessPolicy(
            QuietHoursConfig(
                enabled=True,
                start=time(21),
                end=time(7),
                weekdays=(0, 1, 2, 3, 4, 5, 6),
                passcode="2468",
            )
        )

    def test_overnight_period_uses_starting_date_and_unlocks_only_that_period(self) -> None:
        policy = self.make_policy()
        monday_night = datetime(2026, 8, 10, 22)
        tuesday_morning = datetime(2026, 8, 11, 6)
        next_night = datetime(2026, 8, 11, 22)

        self.assertTrue(policy.is_locked(monday_night))
        self.assertEqual(
            policy.scheduled_period(tuesday_morning),
            monday_night.date(),
        )
        self.assertFalse(policy.unlock("0000", monday_night))
        self.assertTrue(policy.unlock("2468", monday_night))
        self.assertFalse(policy.is_locked(tuesday_morning))
        self.assertTrue(policy.is_locked(next_night))

    def test_daytime_and_disabled_periods_remain_unlocked(self) -> None:
        policy = self.make_policy()
        self.assertFalse(policy.is_locked(datetime(2026, 8, 11, 12)))
        disabled = KioskAccessPolicy(QuietHoursConfig())
        self.assertFalse(disabled.is_locked(datetime(2026, 8, 11, 23)))


class QuietHoursAppBoundaryTests(unittest.TestCase):
    def make_gui(self, locked: bool) -> BotGUI:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.kiosk_access = Mock()
        gui.kiosk_access.is_locked.return_value = locked
        gui.menu_ui = None
        gui.current_state = "idle"
        gui.runtime_attentions = {}
        gui.runtime_attentions_lock = threading.Lock()
        return gui

    def test_menu_and_speech_are_suppressed_while_kiosk_is_locked(self) -> None:
        gui = self.make_gui(True)
        gui.tts_queue = []
        gui.current_interaction = None
        gui.tts_queue_lock = threading.Lock()
        gui.mode_registry = Mock()
        gui.tool_router = Mock()

        gui.open_menu()
        gui.enqueue_speech("should stay quiet")

        self.assertIsNone(gui.menu_ui)
        self.assertEqual(gui.tts_queue, [])

    def test_runtime_attention_is_hidden_during_quiet_hours(self) -> None:
        gui = self.make_gui(True)
        self.assertFalse(gui._runtime_attention_is_visible())


if __name__ == "__main__":
    unittest.main()
