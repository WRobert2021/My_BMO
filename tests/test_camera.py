"""Camera feature and GUI coordination tests."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from bmo.app import BotGUI
from bmo.features.camera import CAPTURE_TIMEOUT_SECONDS, capture_image
from bmo.state import BotStates


class CameraFeatureTests(unittest.TestCase):
    def test_capture_uses_raspberry_pi_command_and_timeout(self) -> None:
        output_path = Path("/tmp/camera-output.jpg")

        with patch("bmo.features.camera.subprocess.run") as run:
            result = capture_image(output_path)

        self.assertEqual(result, str(output_path))
        run.assert_called_once_with(
            [
                "rpicam-still",
                "-t",
                "500",
                "-n",
                "--width",
                "4608",
                "--height",
                "2592",
                "-o",
                str(output_path),
            ],
            check=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )

    def test_capture_rotates_the_camera_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "camera.jpg"
            Image.new("RGB", (3, 2), color="blue").save(output_path)

            with patch("bmo.features.camera.subprocess.run"):
                capture_image(output_path, rotation=90)

            with Image.open(output_path) as rotated:
                self.assertEqual(rotated.size, (2, 3))

    def test_capture_preserves_subprocess_timeout_errors(self) -> None:
        timeout = subprocess.TimeoutExpired("rpicam-still", 15)
        with patch(
            "bmo.features.camera.subprocess.run",
            side_effect=timeout,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                capture_image("/tmp/camera-output.jpg")


class CameraCoordinatorTests(unittest.TestCase):
    @staticmethod
    def make_gui() -> BotGUI:
        gui = BotGUI.__new__(BotGUI)
        gui.config = {"camera_rotation": 180}
        gui.set_state = Mock()
        gui.current_interaction = Mock()
        gui.current_interaction.image_path.return_value = Path(
            "/tmp/archive-camera.jpg"
        )
        return gui

    def test_gui_preserves_capture_state_rotation_and_archive_event(self) -> None:
        gui = self.make_gui()

        with patch(
            "bmo.app.capture_camera_image",
            return_value="/tmp/archive-camera.jpg",
        ) as camera_capture:
            result = BotGUI.capture_image(gui)

        self.assertEqual(result, "/tmp/archive-camera.jpg")
        gui.set_state.assert_called_once_with(
            BotStates.CAPTURING,
            "Watching...",
        )
        camera_capture.assert_called_once_with(
            Path("/tmp/archive-camera.jpg"),
            rotation=180,
        )
        gui.current_interaction.event.assert_called_once_with(
            "image_captured",
            {"path": "/tmp/archive-camera.jpg", "rotation": 180},
        )

    def test_gui_preserves_camera_error_event_and_return_value(self) -> None:
        gui = self.make_gui()

        with patch(
            "bmo.app.capture_camera_image",
            side_effect=subprocess.TimeoutExpired("rpicam-still", 15),
        ):
            result = BotGUI.capture_image(gui)

        self.assertIsNone(result)
        gui.current_interaction.event.assert_called_once_with(
            "image_capture_failed",
            {"error": "Command 'rpicam-still' timed out after 15 seconds"},
        )


if __name__ == "__main__":
    unittest.main()
