"""Deterministic coverage for the configurable timer feature."""

from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import Mock

from bmo.app import BotGUI
from bmo.features import (
    FeatureMenuContext,
    RuntimeAttention,
    RuntimeAttentionDismissal,
    RuntimeNotification,
    ToolRegistry,
    ToolResult,
)
from bmo.features.loader import load_feature_registry
from bmo.features.set_timer import TIMER_MENU_ITEM, SetTimerTool, parse_duration
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
        app_factory=None,
    ):
        clock = FakeClock()
        notifications: queue.Queue[RuntimeNotification] = queue.Queue()
        registry = ToolRegistry(runtime_callback=notifications.put)
        kwargs = {}
        if app_factory is not None:
            kwargs["app_factory"] = app_factory
        tool = SetTimerTool(
            registry.notify_runtime,
            clock=clock,
            max_timers=max_timers,
            max_duration_seconds=max_duration_seconds,
            **kwargs,
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

    def test_cancellation_removes_all_scheduler_references_immediately(self) -> None:
        tool, _clock, _notifications, registry = self.make_tool()
        registry.execute({"action": "set_timer", "duration": "1 minute"})
        registry.execute({"action": "set_timer", "duration": "2 minutes"})

        tool.scheduler.cancel(2)

        self.assertEqual(
            tuple(timer.timer_id for timer in tool.scheduler.active_timers()),
            (1,),
        )
        self.assertEqual(
            tuple(entry[2].timer_id for entry in tool.scheduler._heap),
            (1,),
        )

        tool.scheduler.cancel_all()

        self.assertEqual(tool.scheduler.active_timers(), ())
        self.assertEqual(tool.scheduler._heap, [])

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

    def test_menu_launch_shows_voice_timers_and_deletes_same_timer(self) -> None:
        opened_ui = Mock()
        app_factory = Mock(return_value=opened_ui)
        tool, clock, _notifications, registry = self.make_tool(
            app_factory=app_factory
        )
        registry.execute(
            {
                "action": "set_timer",
                "duration": "10 seconds",
                "label": "tea",
            }
        )
        app_factory.assert_not_called()
        on_close = Mock()

        registry.open_menu_item(
            "set_timer",
            FeatureMenuContext(master="ROOT", on_close=on_close),
        )

        app_factory.assert_called_once()
        self.assertEqual(registry.menu_items, (TIMER_MENU_ITEM,))
        kwargs = app_factory.call_args.kwargs
        self.assertIsNone(kwargs["face_provider"]())
        items = kwargs["timer_provider"]()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(
            (item.timer_id, item.label, item.remaining_seconds),
            (1, "tea", 10.0),
        )

        clock.advance(3)
        self.assertEqual(kwargs["timer_provider"]()[0].remaining_seconds, 7.0)
        self.assertTrue(kwargs["cancel_timer"](1))
        self.assertEqual(kwargs["timer_provider"](), ())
        self.assertEqual(tool.scheduler._heap, [])

        self.assertTrue(kwargs["create_timer"](90))
        self.assertEqual(kwargs["timer_provider"]()[0].remaining_seconds, 90.0)

        kwargs["on_close"]()
        on_close.assert_called_once_with()

    def test_expiration_publishes_alarm_attention_until_acknowledged(self) -> None:
        clock = FakeClock()
        notifications: list[RuntimeNotification] = []
        attention_events: list[RuntimeAttention | RuntimeAttentionDismissal] = []
        registry = ToolRegistry(
            runtime_callback=notifications.append,
            attention_callback=attention_events.append,
        )
        tool = SetTimerTool(
            registry.notify_runtime,
            notify_attention=registry.notify_attention,
            dismiss_attention=registry.dismiss_attention,
            clock=clock,
        )
        registry.register(tool)
        self.addCleanup(registry.close)
        tool.execute({"duration": "5 seconds"})

        clock.advance(5)
        tool.scheduler.notify_clock_changed()
        for _attempt in range(100):
            if attention_events:
                break
            threading.Event().wait(0.005)

        attention = attention_events[0]
        self.assertIsInstance(attention, RuntimeAttention)
        assert isinstance(attention, RuntimeAttention)
        self.assertEqual(attention.animation_state, BotStates.ALARM)
        self.assertEqual(attention.badge_label, "TIMER")
        self.assertFalse(attention.announce_on_acknowledge)
        self.assertIn(1, tool._expired)
        self.assertTrue(attention.acknowledge())
        self.assertNotIn(1, tool._expired)
        self.assertEqual(
            attention_events[-1],
            RuntimeAttentionDismissal("set_timer", "timer-1"),
        )


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

    def test_timer_menu_can_be_hidden_without_disabling_voice_actions(self) -> None:
        result = load_feature_registry(
            {
                "features": [
                    {
                        "module": "bmo.features.set_timer",
                        "enabled": True,
                        "settings": {"show_in_menu": False},
                    }
                ]
            }
        )
        self.addCleanup(result.registry.close)

        self.assertEqual(result.registry.menu_items, ())
        self.assertEqual(result.registry.actions, {"set_timer"})
        self.assertEqual(
            result.registry.execute(
                {"action": "set_timer", "duration": "1 minute"}
            ),
            ToolResult.success("Timer 1 is set for 1 minute."),
        )

    def test_runtime_notification_uses_ui_and_tts_entry_points(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.set_state = Mock()
        gui.append_to_text = Mock()
        gui.current_interaction = None
        gui.tts_queue = []
        gui.tts_queue_lock = threading.Lock()
        notification = RuntimeNotification("set_timer", "Timer 3 is done.")

        BotGUI._handle_runtime_notification(gui, notification)

        gui.set_state.assert_called_once_with(
            BotStates.SPEAKING,
            "Timer 3 is done.",
        )
        gui.append_to_text.assert_called_once_with("BOT: Timer 3 is done.")
        self.assertEqual([item.text for item in gui.tts_queue], ["Timer 3 is done."])
        gui.tts_queue[0].on_complete()
        gui.set_state.assert_called_with(BotStates.IDLE, "Ready")


if __name__ == "__main__":
    unittest.main()
