"""Deterministic coverage for the configurable timer feature."""

from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import Mock

from bmo.app import BotGUI
from bmo.features import RuntimeNotification, ToolRegistry, ToolResult
from bmo.features.loader import load_feature_registry
from bmo.features.set_timer import SetTimerTool, parse_duration
from bmo.state import BotStates


class FakeClock:
    def __init__(self, initial: float = 1000.0) -> None:
        self._value = initial
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._value += seconds


class DurationParsingTests(unittest.TestCase):
    def test_natural_and_compound_durations_are_supported(self) -> None:
        cases = {
            "five minutes": 300.0,
            "two minutes and thirty seconds": 150.0,
            "one hour and thirty minutes": 5400.0,
            "one and a half hours": 5400.0,
            "an hour and a half": 5400.0,
            "half an hour": 1800.0,
            "1.5 hours": 5400.0,
            "a day": 86400.0,
            "30-second": 30.0,
        }

        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(parse_duration(request), expected)

    def test_missing_non_positive_and_negative_durations_are_rejected(
        self,
    ) -> None:
        for request in (
            "soon",
            "0 seconds",
            "minus five minutes",
            "-5 minutes",
            None,
        ):
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    parse_duration(request)


class DirectTimerRoutingTests(unittest.TestCase):
    def test_natural_set_requests_route_without_the_conversation_model(
        self,
    ) -> None:
        cases = {
            "Set a timer for five minutes.": {
                "action": "set_timer",
                "duration": "five minutes",
            },
            "Set another timer for one hour and thirty minutes": {
                "action": "set_timer",
                "duration": "one hour and thirty minutes",
            },
            "Set a tea timer for ten minutes": {
                "action": "set_timer",
                "duration": "ten minutes",
                "label": "tea",
            },
            "Set a 5-minute timer called pasta": {
                "action": "set_timer",
                "duration": "5-minute",
                "label": "pasta",
            },
        }

        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(
                    SetTimerTool.match_direct_action(request),
                    expected,
                )

    def test_cancel_and_list_requests_route_to_timer_operations(self) -> None:
        cases = {
            "Cancel timer number two": {
                "action": "set_timer",
                "operation": "cancel",
                "timer_id": "2",
            },
            "Cancel my five minute timer": {
                "action": "set_timer",
                "operation": "cancel",
                "duration": "five minute",
            },
            "Cancel all timers": {
                "action": "set_timer",
                "operation": "cancel_all",
            },
            "What timers are running?": {
                "action": "set_timer",
                "operation": "list",
            },
        }

        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(
                    SetTimerTool.match_direct_action(request),
                    expected,
                )


class TimerSchedulerTests(unittest.TestCase):
    def make_tool(
        self,
        *,
        max_timers: int = 20,
        max_duration_seconds: float = 7 * 24 * 60 * 60,
    ):
        clock = FakeClock()
        notifications: queue.Queue[RuntimeNotification] = queue.Queue()
        registry = ToolRegistry(runtime_callback=notifications.put)
        tool = SetTimerTool(
            registry.notify_runtime,
            clock=clock,
            max_timers=max_timers,
            max_duration_seconds=max_duration_seconds,
        )
        registry.register(tool)
        self.addCleanup(registry.close)
        return tool, clock, notifications, registry

    def test_multiple_timers_share_one_thread_and_expire_by_deadline(self) -> None:
        tool, clock, notifications, registry = self.make_tool()

        self.assertEqual(
            registry.execute(
                {"action": "set_timer", "duration": "ten seconds"}
            ),
            ToolResult.success("Timer 1 is set for 10 seconds."),
        )
        scheduler_thread = tool.scheduler.thread
        self.assertIsNotNone(scheduler_thread)
        self.assertTrue(scheduler_thread.is_alive())

        self.assertEqual(
            registry.execute(
                {"action": "set_timer", "duration": "five seconds"}
            ),
            ToolResult.success("Timer 2 is set for 5 seconds."),
        )
        self.assertIs(tool.scheduler.thread, scheduler_thread)

        clock.advance(5)
        tool.scheduler.notify_clock_changed()
        self.assertEqual(
            notifications.get(timeout=1),
            RuntimeNotification("set_timer", "Timer 2 is done."),
        )

        clock.advance(5)
        tool.scheduler.notify_clock_changed()
        self.assertEqual(
            notifications.get(timeout=1),
            RuntimeNotification("set_timer", "Timer 1 is done."),
        )
        self.assertTrue(notifications.empty())

    def test_cancellation_by_id_and_duration_preserves_other_timers(self) -> None:
        tool, clock, notifications, registry = self.make_tool()
        registry.execute({"action": "set_timer", "duration": "5 seconds"})
        registry.execute({"action": "set_timer", "duration": "10 seconds"})

        self.assertEqual(
            registry.execute(
                {
                    "action": "set_timer",
                    "operation": "cancel",
                    "duration": "5 seconds",
                }
            ),
            ToolResult.success("I canceled timer 1."),
        )
        self.assertEqual(
            registry.execute(
                {
                    "action": "set_timer",
                    "operation": "cancel",
                    "timer_id": "99",
                }
            ),
            ToolResult.success("Timer 99 is not active."),
        )

        clock.advance(10)
        tool.scheduler.notify_clock_changed()
        self.assertEqual(
            notifications.get(timeout=1).message,
            "Timer 2 is done.",
        )
        self.assertTrue(notifications.empty())

    def test_generic_cancellation_is_safe_with_multiple_timers(self) -> None:
        _tool, _clock, _notifications, registry = self.make_tool()
        registry.execute({"action": "set_timer", "duration": "1 minute"})
        registry.execute({"action": "set_timer", "duration": "2 minutes"})

        result = registry.execute(
            {"action": "set_timer", "operation": "cancel"}
        )

        self.assertEqual(
            result,
            ToolResult.success(
                "You have 2 active timers. Tell me a timer number, or ask me "
                "to cancel all timers."
            ),
        )

    def test_cancel_all_prevents_every_pending_expiration(self) -> None:
        tool, clock, notifications, registry = self.make_tool()
        registry.execute({"action": "set_timer", "duration": "1 minute"})
        registry.execute({"action": "set_timer", "duration": "2 minutes"})

        self.assertEqual(
            registry.execute(
                {"action": "set_timer", "operation": "cancel_all"}
            ),
            ToolResult.success("I canceled 2 timers."),
        )
        clock.advance(120)
        tool.scheduler.notify_clock_changed()
        registry.close()
        self.assertTrue(notifications.empty())

    def test_registry_shutdown_wakes_and_joins_the_scheduler(self) -> None:
        tool, _clock, notifications, registry = self.make_tool()
        registry.execute({"action": "set_timer", "duration": "1 day"})
        scheduler_thread = tool.scheduler.thread
        self.assertTrue(scheduler_thread.is_alive())

        registry.close()

        self.assertFalse(scheduler_thread.is_alive())
        self.assertEqual(tool.scheduler.active_timers(), ())
        self.assertTrue(notifications.empty())
        self.assertEqual(
            tool.execute({"action": "set_timer", "duration": "1 minute"}),
            ToolResult.success("The timer service is shutting down."),
        )

    def test_configured_capacity_is_enforced_without_extra_threads(self) -> None:
        tool, _clock, _notifications, registry = self.make_tool(max_timers=1)
        registry.execute({"action": "set_timer", "duration": "1 minute"})
        scheduler_thread = tool.scheduler.thread

        self.assertEqual(
            registry.execute({"action": "set_timer", "duration": "2 minutes"}),
            ToolResult.success(
                "You already have the maximum number of active timers."
            ),
        )
        self.assertIs(tool.scheduler.thread, scheduler_thread)

    def test_numeric_duration_seconds_from_model_routing_are_supported(self) -> None:
        _tool, _clock, _notifications, registry = self.make_tool()

        self.assertEqual(
            registry.execute(
                {"action": "set_timer", "duration_seconds": "90"}
            ),
            ToolResult.success("Timer 1 is set for 1 minute 30 seconds."),
        )

    def test_configured_maximum_duration_is_enforced_before_scheduling(
        self,
    ) -> None:
        tool, _clock, _notifications, registry = self.make_tool(
            max_duration_seconds=60
        )

        self.assertEqual(
            registry.execute({"action": "set_timer", "duration": "2 minutes"}),
            ToolResult.success("Timers can be at most 1 minute."),
        )
        self.assertIsNone(tool.scheduler.thread)


class TimerIntegrationTests(unittest.TestCase):
    def test_disabled_timer_feature_is_absent_and_starts_no_scheduler(self) -> None:
        result = load_feature_registry(
            {
                "features": [
                    {
                        "module": "bmo.features.set_timer",
                        "enabled": False,
                        "settings": {"max_timers": 1},
                    }
                ]
            }
        )

        self.assertEqual(result.registry.actions, set())
        self.assertEqual(result.modules, ())
        self.assertEqual(result.failures, ())

    def test_runtime_notification_uses_ui_and_tts_entry_points(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.set_state = Mock()
        gui.append_to_text = Mock()
        gui.enqueue_speech = Mock()
        notification = RuntimeNotification("set_timer", "Timer 3 is done.")

        BotGUI._handle_runtime_notification(gui, notification)

        gui.set_state.assert_called_once_with(
            BotStates.SPEAKING,
            "Timer 3 is done.",
        )
        gui.append_to_text.assert_called_once_with("BOT: Timer 3 is done.")
        gui.enqueue_speech.assert_called_once_with("Timer 3 is done.")


if __name__ == "__main__":
    unittest.main()
