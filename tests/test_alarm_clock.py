"""Alarm-clock scheduling, persistence, routing, and view-boundary tests."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from bmo.features.alarm_clock import (
    ALARM_MENU_ITEM,
    AlarmClockTool,
    format_alarm_time,
    parse_alarm_time,
    parse_weekdays,
)
from bmo.features.alarm_config import AlarmClockConfig, load_alarm_clock_config
from bmo.features.alarm_store import (
    AlarmPersistenceError,
    AlarmRecord,
    AlarmState,
    AlarmStore,
    decode_alarm_state,
)
from bmo.features.contracts import RuntimeAttention, RuntimeAttentionDismissal
from bmo.face_config import CompactFaceConfig
from bmo.features.loader import load_feature_registry
from bmo.menu_loader import load_menu_catalog


class MutableNow:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def make_tool(
    now: MutableNow,
    *,
    store: AlarmStore | None = None,
    snooze_minutes: int = 9,
) -> tuple[AlarmClockTool, Mock, Mock, Mock]:
    runtime = Mock()
    attention = Mock()
    dismissal = Mock()
    config = AlarmClockConfig(snooze_minutes=snooze_minutes)
    tool = AlarmClockTool(
        config,
        runtime,
        notify_attention=attention,
        dismiss_attention=dismissal,
        now=now,
        start_worker=False,
        store=store or AlarmStore(None),
    )
    return tool, runtime, attention, dismissal


class AlarmParsingTests(unittest.TestCase):
    def test_time_and_repeat_shortcuts_are_normalized(self) -> None:
        self.assertEqual(parse_alarm_time({"time": "7:05 AM"}), (7, 5))
        self.assertEqual(parse_alarm_time({"time": "12 PM"}), (12, 0))
        self.assertEqual(parse_alarm_time({"hour": 23, "minute": 45}), (23, 45))
        self.assertEqual(parse_weekdays("weekdays"), (0, 1, 2, 3, 4))
        self.assertEqual(parse_weekdays("Saturday and Sunday"), (5, 6))
        self.assertEqual(parse_weekdays("daily"), tuple(range(7)))
        self.assertEqual(format_alarm_time(0, 5, False), "12:05 AM")
        self.assertEqual(format_alarm_time(17, 5, True), "17:05")

    def test_invalid_time_and_weekdays_are_rejected(self) -> None:
        for request in ({"time": "25:00"}, {"time": "13 pm"}, {"hour": True}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                parse_alarm_time(request)
        with self.assertRaises(ValueError):
            parse_weekdays("Funday")

    def test_direct_voice_routes_common_alarm_requests(self) -> None:
        self.assertEqual(
            AlarmClockTool.match_direct_action(
                "Set an alarm for 7:15 am every weekday called School"
            ),
            {
                "action": "alarm_clock",
                "operation": "set",
                "time": "7:15 am",
                "weekdays": "weekdays",
                "label": "school",
            },
        )
        self.assertEqual(
            AlarmClockTool.match_direct_action("Delete alarm number 3"),
            {"action": "alarm_clock", "operation": "delete", "alarm_id": "3"},
        )
        self.assertEqual(
            AlarmClockTool.match_direct_action("Snooze my alarm"),
            {"action": "alarm_clock", "operation": "snooze"},
        )


class AlarmStoreTests(unittest.TestCase):
    def test_state_round_trips_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alarms.json"
            store = AlarmStore(path)
            state = AlarmState(
                alarms=(
                    AlarmRecord(
                        1,
                        7,
                        30,
                        "School",
                        weekdays=(0, 1, 2, 3, 4),
                    ),
                ),
                next_id=2,
                use_24_hour=True,
            )

            store.save(state)
            loaded = AlarmStore(path)

        self.assertEqual(loaded.state, state)
        self.assertFalse(loaded.read_only)

    def test_malformed_state_is_visible_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alarms.json"
            path.write_text('{"version":1,"version":1}', encoding="utf-8")

            store = AlarmStore(path)

        self.assertTrue(store.read_only)
        self.assertIn("could not be loaded", store.error)
        with self.assertRaises(AlarmPersistenceError):
            store.save(AlarmState())

    def test_strict_schema_rejects_duplicate_ids_and_unknown_fields(self) -> None:
        alarm = {
            "id": 1,
            "hour": 7,
            "minute": 0,
            "label": "Alarm",
            "enabled": True,
            "weekdays": [],
            "one_time_date": "2026-08-24",
            "snoozed_until": None,
        }
        with self.assertRaises(AlarmPersistenceError):
            decode_alarm_state(
                {"version": 1, "next_id": 2, "use_24_hour": False, "alarms": [alarm, alarm]}
            )
        with self.assertRaises(AlarmPersistenceError):
            decode_alarm_state(
                {"version": 1, "next_id": 1, "use_24_hour": False, "alarms": [], "extra": True}
            )


class AlarmClockToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = MutableNow(datetime(2026, 8, 23, 18, 0, 20))
        self.tool, self.runtime, self.attention, self.dismissal = make_tool(self.now)
        self.addCleanup(self.tool.close)

    def test_create_list_toggle_and_delete(self) -> None:
        result = self.tool.execute(
            {
                "operation": "set",
                "time": "7:15 am",
                "label": "School",
                "weekdays": "weekdays",
            }
        )
        self.assertIn("Alarm 1 is set", result.content)
        self.assertIn("School", self.tool.execute({"operation": "list"}).content)
        self.assertIn(
            "now off",
            self.tool.execute({"operation": "disable", "alarm_id": 1}).content,
        )
        self.assertFalse(self.tool.state.alarms[0].enabled)
        self.assertIn(
            "deleted alarm 1",
            self.tool.execute({"operation": "delete", "alarm_id": 1}).content,
        )
        self.assertEqual(self.tool.state.alarms, ())

    def test_one_time_alarm_uses_next_occurrence_and_rings_once(self) -> None:
        self.tool.execute({"operation": "set", "time": "6:01 pm", "label": "Dinner"})
        alarm = self.tool.state.alarms[0]
        self.assertEqual(alarm.one_time_date.isoformat(), "2026-08-23")

        self.now.value = datetime(2026, 8, 23, 18, 1, 0)
        self.tool.worker.check()
        self.tool.worker.check()

        self.assertFalse(self.tool.state.alarms[0].enabled)
        self.attention.assert_called_once()
        notice = self.attention.call_args.args[0]
        self.assertIsInstance(notice, RuntimeAttention)
        self.assertEqual(notice.animation_state, "alarm_clock_ringing")
        self.assertEqual(notice.badge_label, "ALARM")
        self.runtime.assert_called_once()

    def test_snooze_dismisses_attention_and_rings_again(self) -> None:
        self.tool.execute({"operation": "set", "time": "6:01 pm"})
        self.now.value = datetime(2026, 8, 23, 18, 1)
        self.tool.worker.check()

        result = self.tool.execute({"operation": "snooze", "alarm_id": 1})

        self.assertIn("9 minutes", result.content)
        self.assertEqual(
            self.tool.state.alarms[0].snoozed_until,
            datetime(2026, 8, 23, 18, 10),
        )
        self.assertIsInstance(self.dismissal.call_args.args[0], RuntimeAttentionDismissal)

        self.now.value = datetime(2026, 8, 23, 18, 10)
        self.tool.worker.check()
        self.assertEqual(self.attention.call_count, 2)
        self.assertIsNone(self.tool.state.alarms[0].snoozed_until)

    def test_repeating_alarm_remains_enabled_after_ringing(self) -> None:
        self.tool.execute({"operation": "set", "time": "6:01 pm", "weekdays": [6]})
        self.now.value = datetime(2026, 8, 23, 18, 1)

        self.tool.worker.check()

        self.assertTrue(self.tool.state.alarms[0].enabled)

    def test_short_worker_delay_does_not_miss_or_repeat_alarm(self) -> None:
        self.tool.execute({"operation": "set", "time": "6:01 pm", "weekdays": [6]})
        self.now.value = datetime(2026, 8, 23, 18, 3)

        self.tool.worker.check()
        self.tool.worker.check()

        self.attention.assert_called_once()

    def test_menu_callbacks_edit_format_and_face_hook_payload(self) -> None:
        self.tool.execute({"operation": "set", "time": "7 am"})
        self.assertTrue(self.tool._set_24_hour(True))
        self.assertEqual(self.tool._view_items()[0].time_text, "07:00")
        self.assertTrue(self.tool._update_from_menu(1, 8, 30, "Bus", (0, 2, 4)))
        self.assertEqual(self.tool._editor_alarm(1).label, "Bus")


class AlarmRegistrationTests(unittest.TestCase):
    def test_default_feature_and_menu_metadata_use_alarm_graphic(self) -> None:
        result = load_feature_registry({}, metadata_only=True)
        self.addCleanup(result.registry.close)
        menu = load_menu_catalog({})

        self.assertIn("alarm_clock", result.registry.actions)
        self.assertIn("alarm", result.registry.aliases)
        alarm_item = next(item for item in menu.catalog.items if item.name == "feature:alarm_clock")
        self.assertEqual(alarm_item.label, "Alarm Clock")
        self.assertEqual(alarm_item.icon_path, ALARM_MENU_ITEM.icon_path)
        self.assertTrue(str(alarm_item.icon_path).endswith("graphics/icons/alarm.png"))

    def test_private_config_defaults_and_validation(self) -> None:
        messages: list[str] = []
        config = load_alarm_clock_config(
            {"snooze_minutes": 0, "show_in_menu": "yes"},
            reporter=messages.append,
        )
        self.assertEqual(config, AlarmClockConfig())
        self.assertTrue(messages)

    def test_face_animation_hook_is_ready_for_future_frames(self) -> None:
        face = CompactFaceConfig()

        self.assertIn("alarm_clock_ringing", face.states)
        self.assertEqual(
            face.states["alarm_clock_ringing"].directory,
            Path("graphics/faces/alarm_clock"),
        )


class AlarmQmlContractTests(unittest.TestCase):
    def test_qml_keeps_face_shared_and_exposes_child_friendly_controls(self) -> None:
        root = Path(__file__).resolve().parents[1] / "bmo" / "qt" / "qml"
        source = (root / "AlarmClockView.qml").read_text(encoding="utf-8")
        host = (root / "HostedView.qml").read_text(encoding="utf-8")
        main = (root / "Main.qml").read_text(encoding="utf-8")

        self.assertIn('objectName: "alarmDigitalClockCard"', source)
        self.assertIn('objectName: "alarmClockList"', source)
        self.assertIn('objectName: "alarmClockEditor"', source)
        self.assertIn('text: "+ NEW ALARM"', source)
        self.assertIn('"SNOOZE "', source)
        self.assertIn('case "alarm_clock": return alarmClockView', host)
        self.assertIn('objectName: "hostedCompactFace"', host)
        self.assertIn("x: 684", host)
        self.assertIn("y: 5", host)
        self.assertNotIn("frameSource", source)
        self.assertIn('objectName: "menuItemLabel"', main)

    def test_alarm_qml_instantiates_inside_kiosk_without_moving_face(self) -> None:
        script = r'''
import json
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from bmo.qt.app import QML_PATH
from bmo.qt.controller import QtFaceController

app = QGuiApplication(["alarm-qml-geometry"])
controller = QtFaceController(start_timer=False)
controller.show_view("alarm_clock", "Alarm Clock", {
    "clock": "7:30 AM", "seconds": "05", "date": "Sunday, August 23",
    "use24Hour": False, "items": [{"id": 1, "time": "7:30 AM", "label": "School", "repeat": "Weekdays", "enabled": True, "ringing": False, "snoozed": False}],
    "ringing": False, "faceAnimationHook": "alarm_clock_idle",
    "editing": False, "editingId": 0, "draftHour": 7, "draftMinute": 30,
    "draftTime": "7:30 AM", "draftLabel": "Alarm", "draftWeekdays": [],
    "snoozeMinutes": 9, "readOnly": False, "error": "",
})
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bmoUi", controller)
engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
window = engine.rootObjects()[0]
window.showNormal()
window.resize(800, 480)
app.processEvents()
face = window.findChild(QQuickItem, "hostedCompactFace")
clock = window.findChild(QQuickItem, "alarmDigitalClockCard")
alarm_list = window.findChild(QQuickItem, "alarmClockList")
print(json.dumps({
    "face": [face.x(), face.y(), face.width(), face.height()],
    "clock": [clock.x(), clock.y(), clock.width(), clock.height()],
    "list": [alarm_list.x(), alarm_list.y(), alarm_list.width(), alarm_list.height()],
}))
window.close()
controller.stop()
engine.deleteLater()
app.processEvents()
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        geometry = json.loads(result.stdout.strip())
        self.assertEqual(geometry["face"], [684.0, 5.0, 108.0, 65.0])
        for key in ("clock", "list"):
            x, y, width, height = geometry[key]
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + width, 800)
            self.assertLessEqual(y + height, 418)


if __name__ == "__main__":
    unittest.main()
