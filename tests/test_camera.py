"""Configured camera feature and generic image-result tests."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from PIL import Image

from bmo.app import BotGUI
from bmo.config import OLLAMA_OPTIONS
from bmo.features import (
    ToolAttachment,
    ToolAttachmentKind,
    ToolContext,
    ToolContract,
    ToolEvent,
    ToolRegistry,
    ToolResult,
    ToolStatusUpdate,
)
from bmo.features.capture_image import (
    CAMERA_FAILURE_TEXT,
    CAPTURE_TIMEOUT_SECONDS,
    CaptureImageTool,
)
from bmo.features.loader import load_feature_registry
from bmo.prompts import build_routing_prompt
from bmo.state import BotStates
from bmo.tools import ToolRouter


class CameraFeatureTests(unittest.TestCase):
    @staticmethod
    def make_context(
        output_path: Path,
    ) -> tuple[ToolContext, list[ToolEvent], list[ToolStatusUpdate]]:
        events: list[ToolEvent] = []
        statuses: list[ToolStatusUpdate] = []
        context = ToolContext(
            artifact_allocator=lambda kind, suffix: output_path,
            event_recorder=events.append,
            status_requester=statuses.append,
        )
        return context, events, statuses

    def test_enabled_camera_matches_and_runs_raspberry_pi_command(self) -> None:
        output_path = Path("/tmp/archive-camera.jpg")
        context, events, statuses = self.make_context(output_path)
        registry = ToolRegistry((CaptureImageTool(),))

        with patch("bmo.features.capture_image.subprocess.run") as run:
            result = registry.execute(
                {"action": "look"},
                context=context,
            )

        self.assertEqual(
            result,
            ToolResult.vision_follow_up(ToolAttachment.image(output_path)),
        )
        self.assertEqual(
            registry.match_direct_action("Take a picture."),
            {"action": "capture_image"},
        )
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
        self.assertEqual(
            statuses,
            [ToolStatusUpdate("capturing", "Watching...")],
        )
        self.assertEqual(
            events,
            [
                ToolEvent(
                    "image_captured",
                    {"path": str(output_path), "rotation": 0},
                )
            ],
        )

    def test_disabled_camera_is_not_imported_prompted_matched_or_run(self) -> None:
        config = {
            "features": [
                {
                    "module": "bmo.features.capture_image",
                    "enabled": False,
                    "settings": {},
                }
            ]
        }

        with patch("bmo.features.loader._load_module") as load_module:
            result = load_feature_registry(config)

        load_module.assert_not_called()
        self.assertEqual(result.registry.actions, set())
        self.assertIsNone(result.registry.match_direct_action("Take a picture."))
        self.assertNotIn("capture_image", build_routing_prompt(result.registry))

        router = ToolRouter(config)
        with patch("subprocess.run") as run:
            self.assertEqual(
                router.execute({"action": "capture_image"}),
                ToolResult.invalid_action(),
            )
        run.assert_not_called()

    def test_timed_out_capture_returns_failure_and_records_event(self) -> None:
        output_path = Path("/tmp/archive-camera.jpg")
        context, events, statuses = self.make_context(output_path)
        timeout = subprocess.TimeoutExpired("rpicam-still", 15)

        with patch(
            "bmo.features.capture_image.subprocess.run",
            side_effect=timeout,
        ):
            result = ToolRegistry((CaptureImageTool(),)).execute(
                {"action": "capture_image"},
                context=context,
            )

        self.assertEqual(result, ToolResult.error(CAMERA_FAILURE_TEXT))
        self.assertEqual(
            events,
            [
                ToolEvent(
                    "image_capture_failed",
                    {
                        "error": (
                            "Command 'rpicam-still' timed out after 15 seconds"
                        )
                    },
                )
            ],
        )
        self.assertEqual(
            statuses,
            [ToolStatusUpdate("capturing", "Watching...")],
        )

    def test_configured_rotation_is_applied_to_captured_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "camera.jpg"
            Image.new("RGB", (3, 2), color="blue").save(output_path)
            context, events, _ = self.make_context(output_path)
            router = ToolRouter(
                {
                    "camera_rotation": 90,
                    "features": [
                        {
                            "module": "bmo.features.capture_image",
                            "enabled": True,
                            "settings": {},
                        }
                    ],
                }
            )

            with patch("bmo.features.capture_image.subprocess.run"):
                result = router.execute(
                    {"action": "capture_image"},
                    context=context,
                )

            with Image.open(output_path) as rotated:
                self.assertEqual(rotated.size, (2, 3))
            self.assertEqual(
                result,
                ToolResult.vision_follow_up(
                    ToolAttachment.image(output_path)
                ),
            )
            self.assertEqual(events[0].data["rotation"], 90)

    def test_missing_execution_context_does_not_start_camera(self) -> None:
        registry = ToolRegistry((CaptureImageTool(),))

        with patch("bmo.features.capture_image.subprocess.run") as run:
            result = registry.execute({"action": "capture_image"})

        self.assertEqual(result, ToolResult.error(CAMERA_FAILURE_TEXT))
        run.assert_not_called()

    def test_gui_context_preserves_interaction_image_archive_path(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.current_interaction = Mock()
        gui.current_interaction.image_path.return_value = Path(
            "/tmp/interaction/images/capture-stamp.jpg"
        )
        gui.set_state = Mock()
        context = gui._tool_context()

        path = context.allocate_artifact(ToolAttachmentKind.IMAGE, ".jpg")
        context.record_event("image_captured", {"path": str(path)})
        context.request_status("capturing", "Watching...")

        self.assertEqual(
            path,
            Path("/tmp/interaction/images/capture-stamp.jpg"),
        )
        gui.current_interaction.image_path.assert_called_once_with(".jpg")
        gui.current_interaction.event.assert_called_once_with(
            "image_captured",
            {"path": str(path)},
        )
        gui.set_state.assert_called_once_with("capturing", "Watching...")


class GenericImageResultTests(unittest.TestCase):
    def test_non_camera_feature_returns_and_presents_image_attachment(self) -> None:
        image = ToolAttachment.image("/tmp/generated-map.png")
        registry = ToolRegistry(
            (
                ToolContract(
                    "render_map",
                    lambda request: ToolResult.image_attachment(
                        image,
                        "Here is the map.",
                    ),
                ),
            )
        )
        result = registry.execute({"action": "render_map"})
        gui = BotGUI.__new__(BotGUI)
        gui._speak_complete_response = Mock()
        gui._remember_turn = Mock()

        gui._process_tool_result(
            "Show the route",
            result,
            image_path=None,
            model_to_use="text-model",
            direct=True,
        )

        gui._speak_complete_response.assert_called_once_with(
            "Here is the map.",
            "/tmp/generated-map.png",
        )
        gui._remember_turn.assert_called_once_with(
            "Show the route",
            "Here is the map.",
        )

    def test_vision_follow_up_is_processed_without_feature_identity(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.chat_and_respond = Mock()
        attachment = ToolAttachment.image("/tmp/inspection.jpg")

        gui._process_tool_result(
            "Inspect this",
            ToolResult.vision_follow_up(attachment),
            image_path=None,
            model_to_use="text-model",
            direct=True,
        )

        gui.chat_and_respond.assert_called_once_with(
            "Inspect this",
            image_path="/tmp/inspection.jpg",
        )

    def test_image_follow_up_preserves_vision_request_and_overlay_path(
        self,
    ) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.mode_registry = Mock()
        gui.vision_model = "vision-model"
        gui.text_model = "text-model"
        gui.set_state = Mock()
        gui.thinking_sound_active = Mock()
        gui._run_thinking_sound_loop = Mock()
        gui._logged_chat = Mock(
            return_value=iter(
                [{"message": {"content": "I see a blue chair."}}]
            )
        )
        gui.interrupted = Mock()
        gui.interrupted.is_set.return_value = False
        gui.current_state = BotStates.THINKING
        gui.append_to_text = Mock()
        gui._stream_to_text = Mock()
        gui.enqueue_speech = Mock()
        gui._archive_assistant_text = Mock()
        gui._remember_turn = Mock()
        gui.wait_for_tts = Mock()
        image_path = "/tmp/inspection.jpg"

        with patch("bmo.app.threading.Thread") as thread:
            gui.chat_and_respond("What do you see?", image_path=image_path)

        gui._logged_chat.assert_called_once_with(
            model="vision-model",
            messages=[
                {
                    "role": "user",
                    "content": "What do you see?",
                    "images": [image_path],
                }
            ],
            stream=True,
            options=OLLAMA_OPTIONS,
        )
        self.assertIn(
            call(BotStates.THINKING, "Thinking...", image_path),
            gui.set_state.call_args_list,
        )
        self.assertIn(
            call(BotStates.SPEAKING, "Speaking...", image_path),
            gui.set_state.call_args_list,
        )
        thread.return_value.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
