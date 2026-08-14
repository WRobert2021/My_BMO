"""Calendar persistence, recurrence, voice, notification, and UI tests."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import Mock, patch

from bmo.app import BotGUI
from bmo.features.calendar import CalendarMidnightWorker, CalendarTool
from bmo.features.calendar_config import CalendarConfig, load_calendar_config
from bmo.features.calendar_store import (
    CalendarDataError,
    CalendarEvent,
    CalendarStore,
    RecurrenceRule,
    built_in_us_holidays,
    easter_sunday,
    expand_events,
    occurrence_dates,
)
from bmo.features.contracts import RuntimeAttention, RuntimeAttentionDismissal
from bmo.features.registry import ToolRegistry
from bmo.state import BotStates
from bmo.ui.calendar import CALENDAR_COLOR_PALETTE, CalendarApp, month_dot_positions
from bmo.ui.scrolling import VerticalScrollController


class CalendarStoreTests(unittest.TestCase):
    def test_calendar_value_objects_reject_runtime_type_confusion(self) -> None:
        with self.assertRaisesRegex(CalendarDataError, "end_date"):
            RecurrenceRule(end_date=datetime(2026, 8, 12))
        with self.assertRaisesRegex(CalendarDataError, "start_date"):
            CalendarEvent(
                "event",
                "Invalid",
                datetime(2026, 8, 12),
                all_day=True,
            )
        with self.assertRaisesRegex(CalendarDataError, "start_time"):
            CalendarEvent(
                "event",
                "Invalid",
                date(2026, 8, 12),
                start_time="10:00",  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(CalendarDataError, "recurrence"):
            CalendarEvent(
                "event",
                "Invalid",
                date(2026, 8, 12),
                all_day=True,
                recurrence={},  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(CalendarDataError, "frequency"):
            RecurrenceRule(frequency=None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(CalendarDataError, "event name"):
            CalendarEvent(
                "event",
                42,  # type: ignore[arg-type]
                date(2026, 8, 12),
                all_day=True,
            )
        with self.assertRaisesRegex(CalendarDataError, "notes"):
            CalendarEvent(
                "event",
                "Invalid",
                date(2026, 8, 12),
                all_day=True,
                notes=None,  # type: ignore[arg-type]
            )

    def test_calendar_json_rejects_values_that_would_be_string_coerced(self) -> None:
        base = {
            "id": "event",
            "name": "Event",
            "start_date": "2026-08-12",
            "all_day": True,
        }
        for field, value, message in (
            ("name", 42, "event name"),
            ("category", False, "event category"),
            ("notes", None, "event notes"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                CalendarDataError,
                message,
            ):
                CalendarEvent.from_json({**base, field: value})
        with self.assertRaisesRegex(CalendarDataError, "frequency"):
            CalendarEvent.from_json(
                {**base, "recurrence": {"frequency": None}}
            )

    def test_store_rejects_invalid_write_values_with_domain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CalendarStore(directory)

            with self.assertRaisesRegex(CalendarDataError, "CalendarEvent"):
                store.replace_events([object()])  # type: ignore[list-item]
            with self.assertRaisesRegex(CalendarDataError, "iterable"):
                store.replace_events(None)  # type: ignore[arg-type]
            with self.assertRaisesRegex(CalendarDataError, "acknowledgement id"):
                store.acknowledge(42)  # type: ignore[arg-type]

            store.acknowledge(" occurrence-id ")
            self.assertTrue(store.is_acknowledged("occurrence-id"))

    def test_calendar_operations_reject_datetime_as_a_calendar_date(self) -> None:
        event = CalendarEvent(
            "event",
            "Event",
            date(2026, 8, 12),
            all_day=True,
        )

        with self.assertRaisesRegex(CalendarDataError, "range start"):
            occurrence_dates(
                event,
                datetime(2026, 8, 12),
                date(2026, 8, 12),
            )
        with tempfile.TemporaryDirectory() as directory:
            store = CalendarStore(directory)
            store.add(event)
            with self.assertRaisesRegex(CalendarDataError, "occurrence date"):
                store.exclude_occurrence(
                    "event",
                    datetime(2026, 8, 12),
                )

    def test_round_trip_keeps_event_fields_and_acknowledges_one_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CalendarStore(directory)
            event = CalendarEvent(
                event_id="event-1",
                name="Game night",
                start_date=date(2026, 8, 12),
                start_time=time(18),
                end_time=time(20),
                color="#357A50",
                category="Family",
                notes="Bring a game.",
                recurrence=RecurrenceRule(
                    frequency="weekly",
                    weekdays=(0, 2),
                    end_date=date(2026, 9, 30),
                ),
            )
            store.add(event)
            store.acknowledge("event-1@2026-08-12")

            reloaded = CalendarStore(directory)

            self.assertEqual(reloaded.events(), (event,))
            self.assertTrue(reloaded.is_acknowledged("event-1@2026-08-12"))
            self.assertFalse(reloaded.is_acknowledged("event-1@2026-08-17"))

    def test_loaded_acknowledgement_ids_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "acknowledgements.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "acknowledged": [" event@2026-08-12 "],
                    }
                ),
                encoding="utf-8",
            )
            store = CalendarStore(directory)

            self.assertTrue(store.is_acknowledged("event@2026-08-12"))
            self.assertTrue(store.is_acknowledged(" event@2026-08-12 "))

    def test_malformed_data_is_not_overwritten_and_disables_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text("not json", encoding="utf-8")
            store = CalendarStore(directory)

            self.assertEqual(store.events(), ())
            self.assertIn("events", store.read_only_error or "")
            with self.assertRaisesRegex(CalendarDataError, "read-only"):
                store.add(
                    CalendarEvent(
                        "new",
                        "New event",
                        date(2026, 8, 12),
                        all_day=True,
                    )
                )
            self.assertEqual(path.read_text(encoding="utf-8"), "not json")

    def test_malformed_nested_calendar_fields_enter_read_only_mode(self) -> None:
        base_event = {
            "id": "event-1",
            "name": "Unsafe",
            "start_date": "2026-08-12",
            "all_day": True,
        }
        malformed_fields = (
            {"recurrence": {"frequency": "weekly", "weekdays": [[1]]}},
            {"excluded_dates": {"not": "a list"}},
        )
        for fields in malformed_fields:
            with (
                self.subTest(fields=fields),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "events.json"
                payload = {"version": 1, "events": [{**base_event, **fields}]}
                path.write_text(json.dumps(payload), encoding="utf-8")
                store = CalendarStore(directory)

                self.assertEqual(store.events(), ())
                self.assertIn("events", store.read_only_error or "")

    def test_occurrence_override_excludes_series_date_and_adds_single_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CalendarStore(directory)
            repeating = CalendarEvent(
                "weekly",
                "Practice",
                date(2026, 8, 3),
                start_time=time(15),
                recurrence=RecurrenceRule(frequency="weekly", weekdays=(0,)),
            )
            store.add(repeating)
            replacement = CalendarEvent(
                "ignored",
                "Practice moved",
                date(2026, 8, 10),
                start_time=time(16),
            )

            override = store.override_occurrence(
                "weekly",
                date(2026, 8, 10),
                replacement,
            )
            occurrences = expand_events(
                store.events(),
                date(2026, 8, 3),
                date(2026, 8, 17),
            )

            self.assertEqual(
                [(item.event.name, item.occurrence_date) for item in occurrences],
                [
                    ("Practice", date(2026, 8, 3)),
                    ("Practice moved", date(2026, 8, 10)),
                    ("Practice", date(2026, 8, 17)),
                ],
            )
            self.assertEqual(override.parent_event_id, "weekly")

    def test_weekly_count_stays_bounded_across_long_date_ranges(self) -> None:
        event = CalendarEvent(
            "old-weekly",
            "Old weekly event",
            date(1900, 1, 1),
            all_day=True,
            recurrence=RecurrenceRule(
                frequency="weekly",
                weekdays=(0,),
                count=2,
            ),
        )

        self.assertEqual(
            occurrence_dates(event, date(2026, 1, 1), date(2026, 12, 31)),
            (),
        )

    def test_sparse_recurrence_counts_stay_bounded_across_centuries(self) -> None:
        monthly = CalendarEvent(
            "old-monthly",
            "Old monthly event",
            date(1900, 1, 31),
            all_day=True,
            recurrence=RecurrenceRule(
                frequency="monthly",
                count=2,
                monthly_overflow="skip",
            ),
        )
        yearly = CalendarEvent(
            "old-yearly",
            "Old yearly event",
            date(1904, 2, 29),
            all_day=True,
            recurrence=RecurrenceRule(
                frequency="yearly",
                count=2,
                monthly_overflow="skip",
            ),
        )

        for event in (monthly, yearly):
            with self.subTest(frequency=event.recurrence.frequency):
                self.assertEqual(
                    occurrence_dates(
                        event,
                        date(2400, 1, 1),
                        date(2400, 12, 31),
                    ),
                    (),
                )

    def test_exhausted_recurrence_count_stops_after_first_candidate(self) -> None:
        event = CalendarEvent(
            "old-weekly",
            "Old weekly event",
            date(1900, 1, 1),
            all_day=True,
            recurrence=RecurrenceRule(frequency="weekly", count=2),
        )

        with patch(
            "bmo.features.calendar_store._occurrence_ordinal",
            return_value=3,
        ) as ordinal:
            self.assertEqual(
                occurrence_dates(
                    event,
                    date(2400, 1, 1),
                    date(9999, 12, 31),
                ),
                (),
            )

        ordinal.assert_called_once()

    def test_recurrence_generation_handles_maximum_calendar_date(self) -> None:
        for frequency in ("weekly", "monthly", "yearly"):
            event = CalendarEvent(
                f"max-{frequency}",
                "Maximum date",
                date.max,
                all_day=True,
                recurrence=RecurrenceRule(frequency=frequency),
            )
            with self.subTest(frequency=frequency):
                self.assertEqual(
                    occurrence_dates(event, date.max, date.max),
                    (date.max,),
                )


class CalendarConfigTests(unittest.TestCase):
    def test_private_config_owns_categories_paths_and_note_narration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.json"
            path.write_text(
                json.dumps(
                    {
                        "data_directory": "private/events",
                        "overlay_directory": "private/overlays",
                        "speak_notes": True,
                        "categories": ["Family", "School"],
                    }
                ),
                encoding="utf-8",
            )

            config = load_calendar_config({"config_path": str(path)})

            self.assertEqual(config.data_directory, Path("private/events"))
            self.assertEqual(config.overlay_directory, Path("private/overlays"))
            self.assertTrue(config.speak_notes)
            self.assertEqual(config.categories, ("Family", "School", "Holiday"))

    def test_malformed_private_config_falls_back_without_writing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.json"
            path.write_text("not json", encoding="utf-8")
            messages: list[str] = []

            config = load_calendar_config(
                {"config_path": str(path)},
                reporter=messages.append,
            )

            self.assertEqual(config, CalendarConfig())
            self.assertEqual(path.read_text(encoding="utf-8"), "not json")
            self.assertEqual(len(messages), 1)


class CalendarRecurrenceTests(unittest.TestCase):
    def test_weekly_rule_supports_multiple_selected_weekdays_and_count(self) -> None:
        event = CalendarEvent(
            "class",
            "Class",
            date(2026, 8, 3),
            start_time=time(9),
            recurrence=RecurrenceRule(
                frequency="weekly",
                weekdays=(0, 2),
                count=4,
            ),
        )

        self.assertEqual(
            occurrence_dates(event, date(2026, 8, 1), date(2026, 8, 31)),
            (
                date(2026, 8, 3),
                date(2026, 8, 5),
                date(2026, 8, 10),
                date(2026, 8, 12),
            ),
        )

    def test_monthly_missing_day_can_use_last_day_or_skip(self) -> None:
        base = CalendarEvent(
            "monthly",
            "Month end",
            date(2026, 1, 31),
            all_day=True,
            recurrence=RecurrenceRule(frequency="monthly"),
        )

        self.assertEqual(
            occurrence_dates(base, date(2026, 1, 1), date(2026, 3, 31)),
            (date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)),
        )
        skipping = CalendarEvent(
            "skip",
            "Month end",
            date(2026, 1, 31),
            all_day=True,
            recurrence=RecurrenceRule(
                frequency="monthly",
                monthly_overflow="skip",
            ),
        )
        self.assertEqual(
            occurrence_dates(skipping, date(2026, 1, 1), date(2026, 3, 31)),
            (date(2026, 1, 31), date(2026, 3, 31)),
        )

    def test_requested_holidays_include_fixed_relative_and_weekday_dates(self) -> None:
        holidays = {event.name: event.start_date for event in built_in_us_holidays(2026)}

        self.assertEqual(len(holidays), 18)
        self.assertEqual(holidays["Easter"], easter_sunday(2026))
        self.assertEqual(holidays["Good Friday"], date(2026, 4, 3))
        self.assertEqual(holidays["Thanksgiving"], date(2026, 11, 26))
        self.assertEqual(holidays["Memorial Day"], date(2026, 5, 25))
        self.assertEqual(holidays["Mother's Day"], date(2026, 5, 10))
        self.assertEqual(holidays["Father's Day"], date(2026, 6, 21))


class CalendarToolTests(unittest.TestCase):
    def make_tool(
        self,
        directory: str,
        *,
        speak_notes: bool = False,
    ) -> tuple[CalendarTool, list[RuntimeAttention], list[RuntimeAttentionDismissal]]:
        notices: list[RuntimeAttention] = []
        dismissals: list[RuntimeAttentionDismissal] = []
        tool = CalendarTool(
            CalendarConfig(
                data_directory=Path(directory),
                built_in_us_holidays=False,
                speak_notes=speak_notes,
            ),
            notify_attention=notices.append,
            dismiss_attention=dismissals.append,
            now=lambda: datetime(2026, 8, 12, 8),
            start_worker=False,
        )
        self.addCleanup(tool.close)
        return tool, notices, dismissals

    def test_voice_matching_reads_ranges_but_never_adds_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool, _notices, _dismissals = self.make_tool(directory)

            self.assertEqual(
                tool.match_direct_action("What's on my schedule tomorrow?"),
                {"action": "get_calendar", "period": "tomorrow"},
            )
            self.assertEqual(
                tool.match_direct_action("What is on the calendar next week?"),
                {"action": "get_calendar", "period": "next_week"},
            )
            self.assertIsNone(tool.match_direct_action("Schedule lunch tomorrow"))
            self.assertIsNone(
                tool.prepare_model_request(
                    {"action": "get_calendar", "operation": "add", "name": "Lunch"}
                )
            )

    def test_summary_orders_all_day_before_timed_and_excludes_notes_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool, _notices, _dismissals = self.make_tool(directory)
            tool.store.add(
                CalendarEvent(
                    "birthday",
                    "Birthday",
                    date(2026, 8, 12),
                    all_day=True,
                    notes="Secret present",
                )
            )
            tool.store.add(
                CalendarEvent(
                    "dentist",
                    "Dentist",
                    date(2026, 8, 12),
                    start_time=time(9, 30),
                )
            )

            summary = tool.execute(
                {"action": "get_calendar", "period": "today"}
            ).content

            self.assertEqual(
                summary,
                "For today, you have Birthday, all day; and Dentist at 9:30 am.",
            )
            self.assertNotIn("Secret", summary or "")

    def test_specific_date_speaks_ordinal_and_natural_start_end_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool, _notices, _dismissals = self.make_tool(directory)
            tool.store.add(
                CalendarEvent(
                    "school",
                    "school",
                    date(2026, 8, 13),
                    start_time=time(9),
                    end_time=time(14, 30),
                )
            )

            summary = tool.execute(
                {"action": "get_calendar", "date": "2026-08-13"}
            ).content

            self.assertEqual(
                summary,
                "On Thursday August 13th you have school at "
                "9 o'clock am to 2:30 pm.",
            )

    def test_notes_are_spoken_only_when_calendar_config_enables_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool, _notices, _dismissals = self.make_tool(
                directory,
                speak_notes=True,
            )
            tool.store.add(
                CalendarEvent(
                    "birthday",
                    "Birthday",
                    date(2026, 8, 12),
                    all_day=True,
                    notes="Bring the blue present",
                )
            )

            summary = tool.summary(date(2026, 8, 12), date(2026, 8, 12))

            self.assertIn("Note: Bring the blue present", summary)

    def test_attention_worker_refreshes_only_when_local_date_changes(self) -> None:
        moments = iter(
            (
                datetime(2026, 8, 12, 8),
                datetime(2026, 8, 12, 23, 59),
                datetime(2026, 8, 13, 0, 0),
            )
        )
        seen: list[date] = []
        worker = CalendarMidnightWorker(seen.append, now=lambda: next(moments))

        self.assertTrue(worker.check())
        self.assertFalse(worker.check())
        self.assertTrue(worker.check())
        self.assertEqual(seen, [date(2026, 8, 12), date(2026, 8, 13)])

    def test_startup_attention_acknowledges_persistently_and_dismisses_on_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool, notices, dismissals = self.make_tool(directory)
            tool.store.add(
                CalendarEvent(
                    "birthday",
                    "Birthday",
                    date(2026, 8, 12),
                    all_day=True,
                    overlay="birthday",
                )
            )

            self.assertTrue(tool.worker.check())
            self.assertEqual(len(notices), 1)
            attention = notices[0]
            self.assertEqual(attention.attention_id, "birthday@2026-08-12")
            self.assertEqual(attention.message, "Today: Birthday, all day.")
            self.assertTrue(attention.acknowledge())

            tool._publish_attentions(date(2026, 8, 12))

            self.assertEqual(
                dismissals,
                [RuntimeAttentionDismissal("get_calendar", "birthday@2026-08-12")],
            )
            reloaded = CalendarStore(directory)
            self.assertTrue(reloaded.is_acknowledged("birthday@2026-08-12"))

    def test_menu_callbacks_create_edit_and_delete_without_voice_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool, _notices, _dismissals = self.make_tool(directory)
            app_factory = Mock()
            tool._app_factory = app_factory
            context = Mock()
            context.master = "ROOT"
            context.current_face = Mock(return_value=None)
            context.announce = Mock(return_value=True)
            context.cancel_announcements = Mock()
            context.on_close = Mock()

            tool.open_menu(context)

            app_factory.assert_called_once()
            kwargs = app_factory.call_args.kwargs
            self.assertEqual(kwargs["categories"], tool.config.categories)
            self.assertIs(kwargs["face_provider"], context.current_face)
            kwargs["on_close"]()
            context.cancel_announcements.assert_called_once_with()
            context.on_close.assert_called_once_with()


class CalendarUiGeometryTests(unittest.TestCase):
    def test_touch_palette_offers_named_colors_without_rgb_entry(self) -> None:
        self.assertGreaterEqual(len(CALENDAR_COLOR_PALETTE), 12)
        self.assertEqual(len({color for _name, color in CALENDAR_COLOR_PALETTE}), len(CALENDAR_COLOR_PALETTE))
        self.assertTrue(all(color.startswith("#") and len(color) == 7 for _name, color in CALENDAR_COLOR_PALETTE))

    def test_month_dots_start_beside_number_and_never_cross_cell(self) -> None:
        positions = month_dot_positions(0, 0, 109, 52, 100)

        self.assertGreaterEqual(len(positions), 8)
        self.assertEqual(positions[0], (43, 12))
        self.assertEqual(positions[3], (82, 12))
        for x_value, y_value in positions:
            self.assertGreaterEqual(x_value - 4, 0)
            self.assertLessEqual(x_value + 4, 104)
            self.assertGreaterEqual(y_value - 4, 0)
            self.assertLessEqual(y_value + 4, 47)

    def test_more_than_four_day_rows_use_a_scrollable_viewport(self) -> None:
        scroller = VerticalScrollController(CalendarApp.DAY_LIST_HEIGHT)
        content_height = 6 * CalendarApp.DAY_ROW_STRIDE

        scroller.set_content_height(content_height)
        scroller.press(200)
        self.assertTrue(scroller.drag(20))

        self.assertGreater(scroller.max_offset, 0)
        self.assertGreater(scroller.offset, 0)


class RuntimeAttentionBoundaryTests(unittest.TestCase):
    def test_registry_forwards_typed_attention_and_dismissal(self) -> None:
        callback = Mock()
        registry = ToolRegistry(attention_callback=callback)
        attention = RuntimeAttention(
            "source",
            "notice-1",
            "Notice text",
            lambda: True,
        )
        dismissal = RuntimeAttentionDismissal("source", "notice-1")

        registry.notify_attention(attention)
        registry.dismiss_attention(dismissal)

        self.assertEqual(callback.call_args_list[0].args, (attention,))
        self.assertEqual(callback.call_args_list[1].args, (dismissal,))

    def make_gui(self) -> BotGUI:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.master = Mock()
        gui.runtime_attentions = {}
        gui.runtime_attentions_lock = threading.Lock()
        gui.current_state = BotStates.IDLE
        gui.menu_ui = None
        gui.kiosk_access = Mock()
        gui.kiosk_access.is_locked.return_value = False
        gui.attention_badge = Mock()
        gui.current_interaction = None
        gui.tts_queue = []
        gui.tts_queue_lock = threading.Lock()
        gui.set_state = Mock()
        gui.append_to_text = Mock()
        return gui

    def test_badge_is_root_owned_and_hidden_when_menu_pip_is_visible(self) -> None:
        gui = self.make_gui()
        attention = RuntimeAttention(
            "get_calendar",
            "event@2026-08-12",
            "Today: Event, all day.",
            lambda: True,
        )
        gui.runtime_attentions[(attention.source, attention.attention_id)] = attention

        gui._refresh_runtime_attention_ui()
        gui.attention_badge.place.assert_called_once()
        gui.attention_badge.reset_mock()
        gui.menu_ui = Mock()

        gui._refresh_runtime_attention_ui()

        gui.attention_badge.place.assert_not_called()
        gui.attention_badge.place_forget.assert_called_once_with()

    def test_tapping_badge_acknowledges_removes_and_queues_speech(self) -> None:
        gui = self.make_gui()
        acknowledge = Mock(return_value=True)
        attention = RuntimeAttention(
            "get_calendar",
            "event@2026-08-12",
            "Today: Event, all day.",
            acknowledge,
        )
        gui.runtime_attentions[(attention.source, attention.attention_id)] = attention

        gui._acknowledge_runtime_attention()

        acknowledge.assert_called_once_with()
        self.assertEqual(gui.runtime_attentions, {})
        self.assertEqual([item.text for item in gui.tts_queue], [attention.message])
        gui.set_state.assert_called_once_with(BotStates.SPEAKING, attention.message)

    def test_alarm_attention_overrides_face_until_silent_acknowledgment(self) -> None:
        gui = self.make_gui()
        attention = RuntimeAttention(
            "set_timer",
            "timer-1",
            "Timer 1 is done.",
            lambda: True,
            animation_state="ALARM",
            badge_label="timer",
            announce_on_acknowledge=False,
        )
        gui.runtime_attentions[(attention.source, attention.attention_id)] = attention

        self.assertIs(gui._runtime_animation_attention(), attention)
        self.assertIs(gui._first_runtime_attention(), attention)
        gui._refresh_runtime_attention_ui()
        gui.attention_badge.configure.assert_called_with(text="TIMER  1")

        gui._acknowledge_runtime_attention()

        self.assertEqual(gui.runtime_attentions, {})
        self.assertEqual(gui.tts_queue, [])
        gui.set_state.assert_called_once_with(BotStates.IDLE, "Ready")


if __name__ == "__main__":
    unittest.main()
