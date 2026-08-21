"""Qt/QML face-shell tests for the incremental GUI migration."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from bmo.face_config import CompactFaceConfig, CompactFaceState  # noqa: E402
from bmo.features.weather_config import WeatherLocationConfig  # noqa: E402
from bmo.features.weather_view import WeatherPageData  # noqa: E402
from bmo.location import Location  # noqa: E402
from bmo.menu_catalog import MenuCatalog, MenuOwner  # noqa: E402
from bmo.menu_model import IconMenuItem  # noqa: E402
from bmo.qt.app import (  # noqa: E402
    QML_PATH,
    configured_menu_catalog,
    preview_menu_catalog,
)
from bmo.qt.controller import QtFaceController  # noqa: E402
from bmo.qt.view_host import QtViewHost  # noqa: E402
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
            controller.menuPressed(50, 100)
            controller.menuReleased(50, 100)
            controller.menuPressed(700, 300)
            controller.menuReleased(100, 300)

            self.assertEqual(selected, ["feature:item-0"])
            self.assertEqual(requests[0].owner, MenuOwner.FEATURE)
            self.assertEqual(requests[0].name, "item-0")
            self.assertEqual(controller.menuSelection, "Item 0")
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


class QtQmlShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication(["pytest-qml-shell"])

    def test_main_qml_loads_with_controller_context(self) -> None:
        controller = QtFaceController(
            start_timer=False,
            menu_catalog=preview_menu_catalog(),
        )
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("bmoUi", controller)

        engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))

        self.assertTrue(engine.rootObjects())
        engine.deleteLater()

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
