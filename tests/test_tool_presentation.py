"""Tests for declarative feature result presentation and archival."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from bmo.app import BotGUI
from bmo.config import OLLAMA_OPTIONS
from bmo.features import (
    ToolArchive,
    ToolContract,
    ToolPresentation,
    ToolRegistry,
    ToolResult,
)


class ToolPresentationTests(unittest.TestCase):
    @staticmethod
    def make_gui() -> BotGUI:
        gui = BotGUI.__new__(BotGUI)
        gui.set_state = Mock()
        gui.thinking_sound_active = Mock()
        gui._logged_chat = Mock(
            return_value={"message": {"content": "  Condensed reading.  "}}
        )
        gui._speak_complete_response = Mock()
        gui._remember_turn = Mock()
        return gui

    def test_custom_direct_feature_result_is_presented_verbatim(self) -> None:
        registry = ToolRegistry(
            [
                ToolContract(
                    "read_switch",
                    lambda request: ToolResult.direct("The switch is on."),
                )
            ]
        )
        result = registry.execute({"action": "read_switch"})
        gui = self.make_gui()

        gui._process_tool_result(
            "Is the switch on?",
            result,
            image_path=None,
            model_to_use="local-model",
            direct=True,
        )

        gui._logged_chat.assert_not_called()
        gui._speak_complete_response.assert_called_once_with(
            "The switch is on.",
            None,
        )
        gui._remember_turn.assert_called_once_with(
            "Is the switch on?",
            "The switch is on.",
        )

    def test_custom_summarized_feature_owns_its_model_prompts(self) -> None:
        presentation = ToolPresentation.summarize(
            system_prompt="Summarize the sensor reading for a child.",
            user_prompt_template=(
                "Question: {user_text}\nSensor payload: {content}"
            ),
            strip_response=True,
        )
        registry = ToolRegistry(
            [
                ToolContract(
                    "read_environment",
                    lambda request: ToolResult.summarized(
                        "temperature_c=21.5; humidity_percent=45",
                        presentation=presentation,
                    ),
                )
            ]
        )
        result = registry.execute({"action": "read_environment"})
        gui = self.make_gui()

        gui._process_tool_result(
            "How does the room feel?",
            result,
            image_path=None,
            model_to_use="local-model",
            direct=False,
        )

        gui._logged_chat.assert_called_once_with(
            model="local-model",
            messages=[
                {
                    "role": "system",
                    "content": "Summarize the sensor reading for a child.",
                },
                {
                    "role": "user",
                    "content": (
                        "Question: How does the room feel?\n"
                        "Sensor payload: temperature_c=21.5; "
                        "humidity_percent=45"
                    ),
                },
            ],
            stream=False,
            options=OLLAMA_OPTIONS,
        )
        gui._speak_complete_response.assert_called_once_with(
            "Condensed reading.",
            None,
        )

    def test_custom_hardware_error_does_not_claim_internet_failure(self) -> None:
        registry = ToolRegistry(
            [
                ToolContract(
                    "read_gpio_sensor",
                    lambda request: ToolResult.error(
                        "I cannot read the GPIO sensor right now."
                    ),
                )
            ]
        )
        result = registry.execute({"action": "read_gpio_sensor"})
        gui = self.make_gui()

        gui._process_tool_result(
            "Check the hardware sensor.",
            result,
            image_path=None,
            model_to_use="local-model",
            direct=True,
        )

        spoken_text = gui._speak_complete_response.call_args.args[0]
        self.assertEqual(spoken_text, "I cannot read the GPIO sensor right now.")
        self.assertNotIn("internet", spoken_text.lower())
        gui._logged_chat.assert_not_called()

    def test_result_archive_metadata_controls_destination_and_details(self) -> None:
        details = {"device": "camera-board", "samples": [1, 0, 1]}
        result = ToolResult.direct(
            "Hardware check complete.",
            archive=ToolArchive(
                category="web",
                filename="hardware.jsonl",
                details=details,
            ),
        )
        gui = BotGUI.__new__(BotGUI)
        gui.current_interaction = Mock()
        gui.tool_router = Mock()
        gui.tool_router.normalize_action.return_value = "inspect_hardware"
        gui.tool_router.execute.return_value = result

        self.assertIs(
            gui._execute_tool({"action": "inspect_hardware"}),
            result,
        )

        archive_call = gui.current_interaction.append_json.call_args
        self.assertEqual(archive_call.args[:2], ("web", "hardware.jsonl"))
        self.assertEqual(archive_call.args[2]["details"], details)

    def test_archive_metadata_is_normalized_and_rejects_escaping_paths(self) -> None:
        archive = ToolArchive(" output ", " tools.jsonl ")

        self.assertEqual(archive.category, "output")
        self.assertEqual(archive.filename, "tools.jsonl")
        with self.assertRaisesRegex(ValueError, "Unknown archive category"):
            ToolArchive("other", "tools.jsonl")
        with self.assertRaisesRegex(ValueError, "leaf name"):
            ToolArchive("output", "../tools.jsonl")


if __name__ == "__main__":
    unittest.main()
