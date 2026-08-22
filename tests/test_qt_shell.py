"""Qt/QML face-shell tests for the incremental GUI migration."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from bmo.face_config import CompactFaceConfig, CompactFaceState  # noqa: E402
from bmo.features.calendar_view import CalendarViewEvent  # noqa: E402
from bmo.features.weather_config import WeatherLocationConfig  # noqa: E402
from bmo.features.weather_view import WeatherPageData  # noqa: E402
from bmo.location import Location  # noqa: E402
from bmo.matching_game_core import MatchingGameHistory  # noqa: E402
from bmo.menu_catalog import MenuCatalog, MenuOwner  # noqa: E402
from bmo.menu_model import IconMenuItem  # noqa: E402
from bmo.qt.app import (  # noqa: E402
    QML_PATH,
    configured_menu_catalog,
    preview_menu_catalog,
)
from bmo.qt.controller import QtFaceController  # noqa: E402
from bmo.qt.view_host import QtViewHost  # noqa: E402
from bmo.qt.views.calendar import QtCalendarView  # noqa: E402
from bmo.qt.views.matching_game import QtMatchingGameView  # noqa: E402
from bmo.qt.views.weather import QtWeatherView  # noqa: E402
from bmo.state import BotStates  # noqa: E402
from bmo.weather import HourlyWeather, WeatherSnapshot  # noqa: E402


def weather_snapshot(**changes: object) -> WeatherSnapshot:
    values: dict[str, object] = {
        "location": Location("Tomball, Texas", 30.0972, -95.6161),
        "imperial": True,
        "observed_at": "2026-08-10T11:15",
        "temperature": 87,
        "apparent_temperature": 96,
        "weather_code": 2,
        "high": 93,
        "low": 75,
        "precipitation_probability_max": 45,
        "humidity": 72,
        "wind_speed": 9,
        "wind_gusts": 18,
        "is_day": True,
        "sunrise": "2026-08-10T06:30",
        "sunset": "2026-08-10T20:00",
        "hourly": tuple(
            HourlyWeather(
                f"2026-08-10T{hour:02}:00",
                88 + index,
                91 + index,
                (0, 2, 61, 0)[index],
                (5, 10, 30, 0)[index],
                True,
            )
            for index, hour in enumerate((12, 14, 16, 20))
        ),
    }
    values.update(changes)
    return WeatherSnapshot(**values)  # type: ignore[arg-type]


class QtFaceControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication(["pytest-qt-shell"])

    def make_controller(self, root: Path) -> QtFaceController:
        for state, count in (("idle", 2), ("speaking", 3)):
            directory = root / "faces" / state
            directory.mkdir(parents=True)
            for index in range(count):
                (directory / f"{index:02}.png").write_bytes(b"frame")
        return QtFaceController(
            config=CompactFaceConfig(
                states={
                    "idle": CompactFaceState(Path("faces/idle"), 500),
                    "speaking": CompactFaceState(Path("faces/speaking"), 50),
                }
            ),
            project_root=root,
            initial_state=BotStates.IDLE,
            rng=random.Random(1),
            start_timer=False,
        )

    def test_controller_discovers_frames_and_updates_qml_properties(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            overlay = root / "overlay.png"
            overlay.write_bytes(b"overlay")

            first = controller.frameSource.toLocalFile()
            controller.advanceFrame()
            second = controller.frameSource.toLocalFile()
            controller.set_state(BotStates.SPEAKING, "Speaking...", str(overlay))
            controller.append_response("BOT: hello")

        self.assertTrue(first.endswith("00.png"))
        self.assertTrue(second.endswith("01.png"))
        self.assertEqual(controller.state, BotStates.SPEAKING)
        self.assertEqual(controller.status, "Speaking...")
        self.assertEqual(controller.responseText, "BOT: hello\n")
        self.assertTrue(controller.overlaySource.toLocalFile().endswith("overlay.png"))

    def test_tap_toggles_hud_and_left_swipe_requests_menu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            menu_requests: list[bool] = []
            controller.menuRequested.connect(lambda: menu_requests.append(True))

            controller.facePressed(100, 100)
            controller.faceReleased(102, 101)
            controller.facePressed(700, 200)
            controller.faceReleased(100, 200)

        self.assertFalse(controller.hudVisible)
        self.assertTrue(controller.menuVisible)
        self.assertEqual(menu_requests, [True])

    def test_menu_pages_select_items_and_swipe_back_to_face(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.make_controller(root)
            items = tuple(
                IconMenuItem(
                    f"feature:item-{index}",
                    f"Item {index}",
                    root / f"{index}.png",
                )
                for index in range(17)
            )
            selected: list[str] = []
            requests: list[object] = []
            controller.menuItemSelected.connect(selected.append)
            controller.menuSelectionRequested.connect(requests.append)
            controller.set_menu_catalog(MenuCatalog(items))
            controller.show_menu()

            self.assertEqual(len(controller.menuItems), 15)
            self.assertEqual(controller.menuPageLabel, "1 / 2")
            self.assertEqual(controller.menuItems[0]["iconSize"], 108)
            controller.menuPressed(50, 100)
            controller.menuReleased(50, 100)
            controller.menuPressed(700, 300)
            controller.menuReleased(100, 300)

            self.assertEqual(selected, ["feature:item-0"])
            self.assertEqual(requests[0].owner, MenuOwner.FEATURE)
            self.assertEqual(requests[0].name, "item-0")
            self.assertEqual(len(controller.menuItems), 2)
            self.assertEqual(controller.menuPageLabel, "2 / 2")

            controller.menuPressed(100, 300)
            controller.menuReleased(700, 300)
            controller.menuPressed(100, 300)
            controller.menuReleased(700, 300)

        self.assertFalse(controller.menuVisible)

    def test_unknown_state_uses_idle_frames_without_losing_state_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))

            controller.set_state("not-configured", "Fallback")

        self.assertEqual(controller.state, "not-configured")
        self.assertTrue(controller.frameSource.toLocalFile().endswith("00.png"))

    def test_hosted_view_and_global_overlay_properties_are_qml_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            controller.show_menu()
            controller.show_view("timer", "Timers", {"items": []})
            controller.set_attentions(2, "TIMERS")
            controller.setQuietHours(True)
            controller.quietPinDigit("1")

            self.assertTrue(controller.viewVisible)
            self.assertEqual(controller.viewKind, "timer")
            self.assertEqual(controller.viewTitle, "Timers")
            self.assertEqual(controller.viewData, {"items": []})
            self.assertFalse(controller.menuVisible)
            self.assertEqual(controller.attentionCount, 2)
            self.assertEqual(controller.attentionLabel, "TIMERS")
            self.assertTrue(controller.quietHoursVisible)
            self.assertTrue(controller.quietPinDisplay.startswith("●"))

            controller.hide_view()
            controller.quietPinResult(True)

        self.assertFalse(controller.viewVisible)
        self.assertTrue(controller.menuVisible)
        self.assertFalse(controller.quietHoursVisible)

    def test_qt_controller_import_does_not_import_tkinter(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bmo.menu_catalog, bmo.menu_model, "
                    "bmo.qt.controller; "
                    "raise SystemExit('tkinter' in sys.modules)"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_menu_extension_modules_import_without_tkinter(self) -> None:
        modules = (
            "bmo.features.get_weather",
            "bmo.features.calendar",
            "bmo.features.set_timer",
            "bmo.features.album",
            "bmo.features.learning",
            "bmo.features.galaxy_rvr",
            "bmo.modes.twenty_questions",
            "bmo.modes.matching_game",
        )
        script = (
            "import importlib, sys; "
            "module = sys.argv[1]; "
            "importlib.import_module(module); "
            "raise SystemExit('tkinter' in sys.modules)"
        )

        for module in modules:
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c", script, module],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )

    def test_production_qt_runtime_modules_import_without_tkinter(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import agent, bmo.runtime, bmo.qt.view_host; "
                    "raise SystemExit('tkinter' in sys.modules)"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_view_host_dispatches_registered_adapter_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            host = QtViewHost(controller)
            actions: list[tuple[str, str]] = []

            class View:
                kind = "proof"
                title = "Proof"

                def __init__(self, owner: QtViewHost) -> None:
                    self.owner = owner

                def payload(self) -> dict[str, object]:
                    return {"ready": True}

                def handle_action(self, action: str, value: str) -> None:
                    actions.append((action, value))

                def close(self) -> None:
                    self.owner.dismiss(self)

            host.register("proof", View)
            view = host.create_bmo_view("proof")
            host.present(view)
            controller.requestViewAction("go", "now")

        self.assertTrue(controller.viewVisible)
        self.assertEqual(controller.viewData, {"ready": True})
        self.assertEqual(actions, [("go", "now")])


class QtWeatherViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication(
            ["pytest-qt-weather"]
        )

    @staticmethod
    def make_controller(root: Path) -> QtFaceController:
        return QtFaceController(
            config=CompactFaceConfig(
                states={
                    "idle": CompactFaceState(Path("missing/idle"), 500),
                    "speaking": CompactFaceState(Path("missing/speaking"), 50),
                }
            ),
            project_root=root,
            start_timer=False,
        )

    def test_adapter_restores_complete_animated_scene_contract(self) -> None:
        location = WeatherLocationConfig("home", "Tomball", "Tomball, Texas")
        page = WeatherPageData(weather_snapshot())
        announce = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            host = QtViewHost(controller)
            with patch("bmo.qt.views.weather.threading.Thread") as thread:
                view = QtWeatherView(
                    host,
                    locations=(location,),
                    default_index=0,
                    page_provider=Mock(return_value=page),
                    announce=announce,
                    cancel_announcements=Mock(),
                    announcements_available=True,
                    season_style="auto",
                    animations=True,
                    debug=True,
                    announce_warnings=False,
                    on_close=Mock(),
                )
                thread.call_args.kwargs["target"]()
                state = view.payload()

                self.assertEqual(state["status"], "ready")
                self.assertEqual(state["condition"], "partly")
                self.assertEqual(state["season"], "summer")
                self.assertEqual(state["time"], "midday")
                self.assertEqual(len(state["hours"]), 4)
                self.assertTrue(state["animations"])
                self.assertTrue(state["debug"])

                view.handle_action("weather_speak", "feels")
                spoken, completed = announce.call_args.args
                self.assertIn("your body may feel", spoken)
                self.assertEqual(view.payload()["speaking_key"], "feels")
                completed()
                self.assertIsNone(view.payload()["speaking_key"])

                announce.reset_mock()
                view.handle_action(
                    "weather_debug_speak",
                    json.dumps(
                        {
                            "key": "condition",
                            "condition": "snow",
                            "temperature": 28,
                            "feels": 20,
                            "high": 31,
                            "low": 19,
                            "rain": 85,
                            "hour": None,
                        }
                    ),
                )
                debug_spoken, debug_completed = announce.call_args.args
                self.assertIn("Coat, hat, gloves", debug_spoken)
                self.assertEqual(view.payload()["speaking_key"], "condition")
                debug_completed()

                announce.reset_mock()
                view.handle_action("weather_debug_speak", "not json")
                view.handle_action(
                    "weather_debug_speak",
                    json.dumps({"key": "condition", "condition": []}),
                )
                announce.assert_not_called()
                view.close()

    def test_navigation_keeps_location_results_isolated(self) -> None:
        home = WeatherLocationConfig("home", "Home", "Tomball, Texas")
        school = WeatherLocationConfig("school", "School", "Austin, Texas")
        pages = {
            "home": WeatherPageData(weather_snapshot(temperature=87)),
            "school": WeatherPageData(
                weather_snapshot(
                    location=Location("Austin, Texas", 30.2672, -97.7431),
                    temperature=70,
                )
            ),
        }
        provider = Mock(side_effect=lambda location: pages[location.id])
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            host = QtViewHost(controller)
            with patch("bmo.qt.views.weather.threading.Thread") as thread:
                view = QtWeatherView(
                    host,
                    locations=(home, school),
                    default_index=0,
                    page_provider=provider,
                    announce=Mock(return_value=False),
                    cancel_announcements=Mock(),
                    announcements_available=False,
                    on_close=Mock(),
                )
                first_target = thread.call_args.kwargs["target"]
                view.handle_action("weather_next", "")
                second_target = thread.call_args.kwargs["target"]
                second_target()
                first_target()

                state = view.payload()
                self.assertEqual(state["location"], "Austin, Texas")
                self.assertEqual(state["temperature"], 70)
                self.assertFalse(state["speech_available"])
                view.close()

    def test_provider_failure_keeps_retryable_weather_surface(self) -> None:
        location = WeatherLocationConfig("home", "Home", "Tomball, Texas")
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))
            host = QtViewHost(controller)
            with patch("bmo.qt.views.weather.threading.Thread") as thread:
                view = QtWeatherView(
                    host,
                    locations=(location,),
                    default_index=0,
                    page_provider=Mock(side_effect=RuntimeError("private detail")),
                    announce=Mock(return_value=False),
                    cancel_announcements=Mock(),
                    announcements_available=False,
                    on_close=Mock(),
                )
                thread.call_args.kwargs["target"]()
                state = view.payload()

                self.assertEqual(state["status"], "error")
                self.assertIn("tap to retry", state["message"])
                self.assertNotIn("private detail", state["message"])
                view.close()


class QtCalendarViewTests(unittest.TestCase):
    def make_view(
        self,
        events: tuple[CalendarViewEvent, ...],
    ) -> tuple[QtCalendarView, Mock, Mock]:
        save = Mock()
        delete = Mock()

        def event_provider(start: date, end: date) -> tuple[CalendarViewEvent, ...]:
            return tuple(
                event
                for event in events
                if start <= event.occurrence_date <= end
            )

        view = QtCalendarView(
            Mock(),
            event_provider=event_provider,
            save_event=save,
            delete_event=delete,
            summary_provider=lambda start, end: f"Plans from {start} to {end}",
            categories=("Family", "School", "Holiday"),
            announce=Mock(return_value=True),
            on_close=Mock(),
            today_provider=lambda: date(2026, 8, 12),
        )
        return view, save, delete

    @staticmethod
    def event(
        index: int,
        occurrence_date: date,
        *,
        frequency: str = "none",
    ) -> CalendarViewEvent:
        return CalendarViewEvent(
            event_id=f"event-{index}",
            occurrence_id=f"event-{index}@{occurrence_date.isoformat()}",
            name=f"Event {index}",
            occurrence_date=occurrence_date,
            all_day=False,
            start_time=time(8 + index % 10),
            end_time=time(9 + index % 10),
            color=("#1578D3", "#D9545D", "#3B8E63")[index % 3],
            category="Family",
            frequency=frequency,
            weekdays=(0, 2) if frequency == "weekly" else (),
            recurrence_count=6 if frequency == "weekly" else None,
        )

    def test_day_month_and_year_payloads_restore_dots_and_counts(self) -> None:
        today = date(2026, 8, 12)
        events = tuple(self.event(index, today) for index in range(12)) + (
            self.event(20, date(2026, 9, 2)),
        )
        view, _save, _delete = self.make_view(events)

        self.assertEqual(len(view.payload()["events"]), 12)
        view.handle_action("calendar_show_month", "")
        month = view.payload()
        today_cell = next(
            item for item in month["monthDays"] if item["date"] == "2026-08-12"
        )

        self.assertEqual(month["mode"], "month")
        self.assertEqual(len(month["monthDays"]), 42)
        self.assertEqual(len(today_cell["dots"]), 9)
        self.assertEqual(today_cell["overflow"], 3)

        view.handle_action("calendar_show_year", "")
        year = view.payload()

        self.assertEqual(year["mode"], "year")
        self.assertEqual(len(year["yearMonths"]), 12)
        self.assertEqual(year["yearMonths"][7]["eventCount"], 12)
        self.assertEqual(year["yearMonths"][8]["eventCount"], 1)

    def test_editor_restores_color_recurrence_and_series_scope(self) -> None:
        recurring = self.event(1, date(2026, 8, 12), frequency="weekly")
        view, save, delete = self.make_view((recurring,))
        view.handle_action("calendar_select", recurring.occurrence_id)
        view.handle_action("calendar_edit", "")

        editor = view.payload()["editor"]
        self.assertEqual(editor["weekdays"], [0, 2])
        self.assertEqual(editor["repeatEndKind"], "count")
        self.assertGreaterEqual(len(view.payload()["colorPalette"]), 12)

        view.handle_action(
            "calendar_request_save",
            json.dumps(
                {
                    "name": "Team practice",
                    "date": "2026-08-12",
                    "allDay": False,
                    "startTime": "15:00",
                    "endTime": "16:30",
                    "category": "Family",
                    "color": "#7051B8",
                    "notes": "Bring water",
                    "frequency": "weekly",
                    "weekdays": [0, 2, 5],
                    "repeatEndKind": "count",
                    "repeatEndValue": "8",
                    "monthlyOverflow": "last_day",
                }
            ),
        )

        self.assertEqual(view.mode, "scope")
        save.assert_not_called()
        self.assertIn("whole series", view.payload()["scopePrompt"])

        view.handle_action("calendar_scope", "occurrence")

        saved_edit, selected, scope = save.call_args.args
        self.assertIs(selected, recurring)
        self.assertEqual(scope, "occurrence")
        self.assertEqual(saved_edit.weekdays, (0, 2, 5))
        self.assertEqual(saved_edit.recurrence_count, 8)
        self.assertEqual(saved_edit.color, "#7051B8")
        self.assertEqual(view.mode, "day")

        view.handle_action("calendar_select", recurring.occurrence_id)
        view.handle_action("calendar_request_delete", "")
        self.assertEqual(view.mode, "scope")
        delete.assert_not_called()
        view.handle_action("calendar_scope", "series")
        delete.assert_called_once_with(recurring, "series")

    def test_calendar_qml_keeps_shared_face_geometry_and_uses_dedicated_views(self) -> None:
        hosted = (QML_PATH.parent / "HostedView.qml").read_text(encoding="utf-8")
        calendar_qml = (QML_PATH.parent / "CalendarView.qml").read_text(
            encoding="utf-8"
        )

        self.assertIn('objectName: "hostedCompactFace"', hosted)
        self.assertIn("x: 684", hosted)
        self.assertIn("y: 5", hosted)
        self.assertIn("width: 108", hosted)
        self.assertIn("height: 65", hosted)
        self.assertIn("CalendarView {", hosted)
        for object_name in (
            "calendarDayView",
            "calendarDayEvents",
            "calendarMonthView",
            "calendarYearView",
            "calendarEditorFlick",
            "calendarColorPicker",
            "calendarHuePicker",
            "calendarScopeDialog",
        ):
            self.assertIn(f'objectName: "{object_name}"', calendar_qml)
        self.assertIn('root.send("calendar_request_delete")', calendar_qml)
        self.assertIn('root.send("calendar_request_save"', calendar_qml)
        self.assertIn("Qt.hsla", calendar_qml)
        self.assertNotIn('model: ["none","daily"', calendar_qml)


class QtQmlShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication(["pytest-qml-shell"])

    def test_main_qml_loads_with_controller_context(self) -> None:
        script = r'''
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from bmo.qt.app import QML_PATH, preview_menu_catalog
from bmo.qt.controller import QtFaceController

app = QGuiApplication(["main-qml-load"])
controller = QtFaceController(start_timer=False, menu_catalog=preview_menu_catalog())
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bmoUi", controller)
engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
raise SystemExit(0 if engine.rootObjects() else 1)
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

    def test_calendar_qml_instantiates_inside_bounds_without_moving_face(self) -> None:
        script = r'''
import json
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from bmo.qt.app import QML_PATH
from bmo.qt.controller import QtFaceController

app = QGuiApplication(["calendar-qml-geometry"])
controller = QtFaceController(start_timer=False)
controller.show_view("calendar", "Calendar", {
    "mode": "day",
    "date": "2026-08-12",
    "dateLabel": "Wednesday, August 12, 2026",
    "navigationLabel": "Wednesday, August 12, 2026",
    "accentColor": "#668C25",
    "events": [],
    "monthDays": [],
    "yearMonths": [],
    "weekdayLabels": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
    "selectedId": "",
    "selectedReadOnly": False,
    "selectedRecurring": False,
    "categories": ["Family"],
    "colorPalette": [{"name": "Ocean", "color": "#1578D3"}],
    "error": "",
    "editor": {},
    "scopeKind": "",
    "scopePrompt": "",
})
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bmoUi", controller)
engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
window = engine.rootObjects()[0]
window.showNormal()
window.resize(800, 480)
app.processEvents()
face = window.findChild(QQuickItem, "hostedCompactFace")
calendar_root = window.findChild(QQuickItem, "calendarRoot")
day_view = window.findChild(QQuickItem, "calendarDayView")
print(json.dumps({
    "face": [face.x(), face.y(), face.width(), face.height()],
    "calendar": [calendar_root.width(), calendar_root.height()],
    "day": [day_view.x(), day_view.y(), day_view.width(), day_view.height()],
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
        self.assertEqual(geometry["calendar"], [800.0, 418.0])
        self.assertLessEqual(
            geometry["day"][0] + geometry["day"][2],
            geometry["calendar"][0],
        )
        self.assertLessEqual(
            geometry["day"][1] + geometry["day"][3],
            geometry["calendar"][1],
        )

    def test_loaded_menu_icons_do_not_overlap_and_face_geometry_is_fixed(
        self,
    ) -> None:
        script = r'''
import json
from PySide6.QtCore import QPointF, QRectF, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from bmo.qt.app import QML_PATH, preview_menu_catalog
from bmo.qt.controller import QtFaceController

app = QGuiApplication(["menu-qml-geometry"])
controller = QtFaceController(start_timer=False, menu_catalog=preview_menu_catalog())
controller.show_menu()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bmoUi", controller)
engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
root = engine.rootObjects()[0]
root.showNormal()
root.resize(800, 480)
app.processEvents()
scene = root.contentItem()
face = root.findChild(QQuickItem, "menuCompactFace")
page_pill = root.findChild(QQuickItem, "menuPagePill")

def descendants(item):
    found = []
    for child in item.childItems():
        found.append(child)
        found.extend(descendants(child))
    return found

icons = [item for item in descendants(scene) if item.objectName() == "menuIcon"]
rects = []
for icon in icons:
    origin = icon.mapToItem(scene, QPointF(0, 0))
    rects.append(QRectF(origin.x(), origin.y(), icon.width(), icon.height()))
overlaps = any(
    rect.intersects(other)
    for index, rect in enumerate(rects)
    for other in rects[index + 1:]
)
print(json.dumps({
    "face": [face.x(), face.y(), face.width(), face.height()],
    "pill": [page_pill.x(), page_pill.y(), page_pill.width(), page_pill.height()],
    "window": [root.width(), root.height()],
    "iconCount": len(icons),
    "iconSizes": [[icon.width(), icon.height()] for icon in icons],
    "overlaps": overlaps,
}))
window = root
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
        self.assertEqual(geometry["pill"], [361.0, 448.0, 78.0, 24.0])
        self.assertEqual(geometry["window"], [800, 480])
        self.assertEqual(geometry["iconCount"], 7)
        self.assertTrue(
            all(size == [108.0, 108.0] for size in geometry["iconSizes"])
        )
        self.assertFalse(geometry["overlaps"])

    def test_main_menu_uses_clean_compact_kid_friendly_layout(self) -> None:
        source = QML_PATH.read_text(encoding="utf-8")

        self.assertIn('text: "BMO MENU"', source)
        self.assertIn('text: "Pick an adventure!"', source)
        self.assertIn('width: modelData.iconSize', source)
        self.assertIn('height: modelData.iconSize', source)
        self.assertNotIn('text: "Selected:', source)
        self.assertNotIn("bmoUi.menuSelection", source)
        self.assertIn('objectName: "menuCompactFace"', source)
        self.assertIn('objectName: "menuIconHalo"', source)
        self.assertIn("anchors.horizontalCenter: parent.horizontalCenter", source)
        self.assertIn('color: "#fff3d3"', source)

    def test_matching_view_uses_project_card_back_and_balanced_grid(self) -> None:
        host = Mock()
        view = QtMatchingGameView(
            host,
            history=MatchingGameHistory(path=None),
        )

        payload = view.payload()
        qml = (QML_PATH.parent / "HostedView.qml").read_text(encoding="utf-8")

        self.assertTrue(
            payload["cardBackSource"].toLocalFile().endswith(
                "graphics/card_backs/card_back.png"
            )
        )
        self.assertIn(
            "source: modelData.revealed ? modelData.source "
            ": root.viewModel.cardBackSource",
            qml,
        )
        self.assertIn("property int cardColumns: cardCount <= 16 ? 4", qml)
        self.assertIn("Math.max(64", qml)
        self.assertIn('root.send("matching_pair_delta", -1)', qml)
        self.assertIn('root.send("matching_pair_delta", 1)', qml)
        self.assertNotIn("model: [4, 6, 8]", qml)
        self.assertIn('objectName: "hostedCompactFace"', qml)
        self.assertIn("x: 684", qml)
        self.assertIn("y: 5", qml)
        self.assertIn("width: 108", qml)
        self.assertIn("height: 65", qml)

    def test_matching_pair_controls_step_and_clamp_to_available_art(self) -> None:
        host = Mock()
        view = QtMatchingGameView(
            host,
            history=MatchingGameHistory(path=None),
        )

        view.handle_action("matching_pair_delta", "-1")
        self.assertEqual(view.pair_count, 5)
        for _index in range(20):
            view.handle_action("matching_pair_delta", "-1")
        self.assertEqual(view.pair_count, 4)
        self.assertEqual(len(view.model.cards), 8)

        for _index in range(20):
            view.handle_action("matching_pair_delta", "1")
        self.assertEqual(view.pair_count, 14)
        self.assertEqual(len(view.model.cards), 28)

    def test_matching_winner_announcement_restores_face_when_speech_finishes(
        self,
    ) -> None:
        completions: list[object] = []
        players: list[str] = []
        spoken: list[str] = []

        def announce(text: str, on_complete: object) -> None:
            spoken.append(text)
            completions.append(on_complete)

        view = QtMatchingGameView(
            Mock(),
            history=MatchingGameHistory(path=None),
            announce=announce,
            on_player_change=players.append,
        )
        view.model.matched = {card.card_id for card in view.model.cards}
        view.model.scores["human"] = view.pair_count

        self.assertTrue(view._finish_if_complete())
        self.assertEqual(players, ["speaking"])
        self.assertIn("You win", spoken[0])

        completion = completions[0]
        self.assertTrue(callable(completion))
        completion()
        self.assertEqual(players[-1], "complete")

    def test_new_matching_round_ignores_old_announcement_completion(self) -> None:
        completions: list[object] = []
        players: list[str] = []
        view = QtMatchingGameView(
            Mock(),
            history=MatchingGameHistory(path=None),
            announce=lambda _text, done: completions.append(done),
            on_player_change=players.append,
        )
        view.model.matched = {card.card_id for card in view.model.cards}

        self.assertTrue(view._finish_if_complete())
        view.handle_action("matching_restart", "")
        completion = completions[0]
        self.assertTrue(callable(completion))
        completion()

        self.assertEqual(players[-1], "human")

    def test_runtime_speech_queue_retains_mode_completion_callback(self) -> None:
        import threading

        from bmo.runtime import AssistantRuntime

        runtime = AssistantRuntime.__new__(AssistantRuntime)
        runtime.kiosk_access = Mock()
        runtime.kiosk_access.is_locked.return_value = False
        runtime.current_interaction = None
        runtime.tts_queue = []
        runtime.tts_queue_lock = threading.Lock()
        completion = Mock()

        runtime.enqueue_speech("Winner announcement", completion)

        self.assertEqual(runtime.tts_queue[0].text, "Winner announcement")
        self.assertIs(runtime.tts_queue[0].on_complete, completion)

    def test_weather_qml_contains_full_scene_and_debug_catalog(self) -> None:
        qml_root = QML_PATH.parent
        view = (qml_root / "WeatherView.qml").read_text(encoding="utf-8")
        scene = (qml_root / "WeatherScene.qml").read_text(encoding="utf-8")
        icon = (qml_root / "WeatherIcon.qml").read_text(encoding="utf-8")

        for condition in (
            "sunny",
            "mostly-clear",
            "partly",
            "overcast",
            "fog",
            "drizzle",
            "heavy-rain",
            "freezing-rain",
            "storm",
            "heavy-snow",
            "sleet",
            "hail",
            "wind",
            "hot",
            "cold",
            "mixed",
            "severe",
        ):
            self.assertIn(f'"{condition}"', view)
        for season in ("spring", "summer", "fall", "winter"):
            self.assertIn(f'"{season}"', scene)
        for period in ("morning", "midday", "afternoon", "sunset", "night"):
            self.assertIn(f'"{period}"', view)
        for phase in (
            "full",
            "new",
            "waxing-crescent",
            "first-quarter",
            "waxing-gibbous",
            "waning-gibbous",
            "last-quarter",
            "waning-crescent",
        ):
            self.assertIn(f'"{phase}"', view + icon)
        self.assertIn("controller.frameSource", view)
        self.assertIn('objectName: "weatherCompactFace"', view)
        self.assertIn("x: 684; y: 5; width: 108; height: 65", view)
        self.assertNotIn("x: 635; y: 6; width: 91; height: 52", view)
        self.assertIn("DragHandler", view)
        self.assertIn("weather_debug_speak", view)
        self.assertIn("hourlyForecasts.width / Math.max", view)
        self.assertIn("clip: true", scene)
        self.assertIn("SequentialAnimation on y", scene)
        self.assertIn("WeatherBolt", scene)
        self.assertIn("drawSnowflake", icon)
        self.assertIn("drawIceCube", icon)
        self.assertNotIn("☀", view + scene + icon)
        self.assertNotIn("🌧", view + scene + icon)

    def test_preview_menu_uses_namespaced_project_icon_references(self) -> None:
        items = preview_menu_catalog().items

        self.assertEqual(items[0].name, "mode:matching_game")
        self.assertEqual(items[1].name, "mode:twenty_questions")
        self.assertTrue(all(item.icon_path.parent.name == "icons" for item in items))

    def test_configured_menu_uses_extension_metadata_instead_of_preview(
        self,
    ) -> None:
        with patch(
            "bmo.qt.app.load_config",
            return_value={
                "features": [{"module": "bmo.features.set_timer"}],
                "modes": [],
            },
        ):
            result = configured_menu_catalog()

        self.assertEqual(result.failures, ())
        self.assertEqual(
            tuple(item.name for item in result.catalog.items),
            ("feature:set_timer",),
        )


if __name__ == "__main__":
    unittest.main()
