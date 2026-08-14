"""Qt/QML face-shell tests for the incremental GUI migration."""

from __future__ import annotations

import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from bmo.face_config import CompactFaceConfig, CompactFaceState  # noqa: E402
from bmo.qt.app import QML_PATH  # noqa: E402
from bmo.qt.controller import QtFaceController  # noqa: E402
from bmo.state import BotStates  # noqa: E402


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

        self.assertTrue(controller.hudVisible)
        self.assertEqual(menu_requests, [True])

    def test_unknown_state_uses_idle_frames_without_losing_state_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            controller = self.make_controller(Path(directory))

            controller.set_state("not-configured", "Fallback")

        self.assertEqual(controller.state, "not-configured")
        self.assertTrue(controller.frameSource.toLocalFile().endswith("00.png"))

    def test_qt_controller_import_does_not_import_tkinter(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bmo.qt.controller; "
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


class QtQmlShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication(["pytest-qml-shell"])

    def test_main_qml_loads_with_controller_context(self) -> None:
        controller = QtFaceController(start_timer=False)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("bmoUi", controller)

        engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))

        self.assertTrue(engine.rootObjects())
        engine.deleteLater()


if __name__ == "__main__":
    unittest.main()
