"""Tests for UI-neutral conversation collaborators."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from bmo.config import OLLAMA_OPTIONS
from bmo.conversation import LoggedModelClient, ToolResultPresenter
from bmo.features import ToolAttachment, ToolPresentation, ToolResult
from bmo.state import BotStates


class LoggedModelClientTests(unittest.TestCase):
    def test_non_streaming_call_records_request_and_response(self) -> None:
        interaction = Mock()
        response = {"message": {"content": "Hello"}}
        chat = Mock(return_value=response)
        clock = Mock(side_effect=[10.0, 12.5])
        client = LoggedModelClient(chat, lambda: interaction, clock=clock)

        result = client(model="test", messages=[], stream=False)

        self.assertIs(result, response)
        self.assertEqual(
            interaction.append_json.call_args_list,
            [
                call(
                    "output",
                    "model_calls.jsonl",
                    {
                        "phase": "request",
                        "request": {
                            "model": "test",
                            "messages": [],
                            "stream": False,
                        },
                    },
                ),
                call(
                    "output",
                    "model_calls.jsonl",
                    {
                        "phase": "response",
                        "response": response,
                        "duration_seconds": 2.5,
                    },
                ),
            ],
        )

    def test_streaming_call_records_complete_content_after_consumption(self) -> None:
        interaction = Mock()
        chunks = iter(
            (
                {"message": {"content": "Hello "}},
                {"message": {"content": "there"}},
            )
        )
        client = LoggedModelClient(
            Mock(return_value=chunks),
            lambda: interaction,
            clock=Mock(side_effect=[5.0, 8.0]),
        )

        received = list(client(model="test", stream=True))

        self.assertEqual(len(received), 2)
        response_record = interaction.append_json.call_args_list[-1].args[2]
        self.assertEqual(response_record["phase"], "response")
        self.assertEqual(response_record["response"], {"content": "Hello there"})
        self.assertEqual(response_record["duration_seconds"], 3.0)

    def test_stream_failure_records_partial_content_and_reraises(self) -> None:
        interaction = Mock()

        def broken_stream():
            yield {"message": {"content": "Partial"}}
            raise RuntimeError("stream failed")

        client = LoggedModelClient(
            Mock(return_value=broken_stream()),
            lambda: interaction,
            clock=Mock(side_effect=[2.0, 4.0]),
        )

        with self.assertRaisesRegex(RuntimeError, "stream failed"):
            list(client(model="test", stream=True))

        error_record = interaction.append_json.call_args_list[-1].args[2]
        self.assertEqual(error_record["phase"], "stream_error")
        self.assertEqual(error_record["partial_content"], "Partial")
        self.assertEqual(error_record["duration_seconds"], 2.0)

    def test_disabled_archive_still_calls_the_model(self) -> None:
        response = {"message": {"content": "Hello"}}
        chat = Mock(return_value=response)
        client = LoggedModelClient(chat, lambda: None)

        self.assertIs(client(model="test", stream=False), response)
        chat.assert_called_once_with(model="test", stream=False)


class ToolResultPresenterTests(unittest.TestCase):
    def make_presenter(self, **overrides):
        values = {
            "model_chat": Mock(
                return_value={"message": {"content": "  Short summary.  "}}
            ),
            "model_options": OLLAMA_OPTIONS,
            "set_state": Mock(),
            "set_thinking_active": Mock(),
            "speak_complete_response": Mock(),
            "remember_turn": Mock(),
            "request_vision_follow_up": Mock(),
        }
        values.update(overrides)
        return ToolResultPresenter(**values), values

    def test_direct_result_needs_no_gui_or_model_types(self) -> None:
        presenter, values = self.make_presenter()

        presenter.present(
            "Read the sensor",
            ToolResult.direct("The sensor is ready."),
            image_path=None,
            model_to_use="test-model",
            direct=True,
        )

        values["model_chat"].assert_not_called()
        values["speak_complete_response"].assert_called_once_with(
            "The sensor is ready.",
            None,
        )
        values["remember_turn"].assert_called_once_with(
            "Read the sensor",
            "The sensor is ready.",
        )

    def test_summary_result_uses_owned_prompt_and_callbacks(self) -> None:
        presentation = ToolPresentation.summarize(
            system_prompt="Summarize the reading.",
            user_prompt_template="Question: {user_text}\nData: {content}",
            strip_response=True,
        )
        presenter, values = self.make_presenter()

        presenter.present(
            "How is the room?",
            ToolResult.summarized(
                "temperature=21",
                presentation=presentation,
            ),
            image_path="/tmp/original.jpg",
            model_to_use="test-model",
            direct=False,
        )

        values["set_state"].assert_called_once_with(
            BotStates.THINKING,
            "Reading...",
        )
        values["set_thinking_active"].assert_called_once_with(True)
        values["model_chat"].assert_called_once_with(
            model="test-model",
            messages=[
                {"role": "system", "content": "Summarize the reading."},
                {
                    "role": "user",
                    "content": "Question: How is the room?\nData: temperature=21",
                },
            ],
            stream=False,
            options=OLLAMA_OPTIONS,
        )
        values["speak_complete_response"].assert_called_once_with(
            "Short summary.",
            "/tmp/original.jpg",
        )

    def test_vision_follow_up_uses_generic_callback(self) -> None:
        presenter, values = self.make_presenter()

        presenter.present(
            "What is this?",
            ToolResult.vision_follow_up(
                ToolAttachment.image("/tmp/capture.jpg")
            ),
            image_path=None,
            model_to_use="test-model",
            direct=True,
        )

        values["request_vision_follow_up"].assert_called_once_with(
            "What is this?",
            "/tmp/capture.jpg",
        )
        values["speak_complete_response"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
