"""Tests for local-model semantic intent routing."""

from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from bmo.features import ToolContract, ToolResult
from bmo.intent import (
    infer_game_answer,
    infer_game_guess,
    infer_tool_action,
)
from bmo.tools import ToolRouter


class IntentRoutingTests(unittest.TestCase):
    def test_configured_custom_feature_receives_every_model_argument(
        self,
    ) -> None:
        module = types.ModuleType("custom_color_feature")
        received = []

        def execute(request):
            received.append(dict(request))
            return ToolResult.success("Color set.")

        def register(registry, settings):
            del settings
            registry.register(
                ToolContract(
                    "set_color",
                    execute,
                    description="Set a display color and brightness.",
                    schemas=(
                        '{"action":"set_color","color":"name",'
                        '"brightness":40}',
                    ),
                )
            )

        module.register = register
        with patch(
            "bmo.features.loader._load_module",
            return_value=module,
        ):
            router = ToolRouter(
                {
                    "features": [
                        {
                            "module": "custom_color_feature",
                            "enabled": True,
                            "settings": {},
                        }
                    ]
                }
            )

        def fake_chat(**kwargs):
            return {
                "message": {
                    "content": (
                        '{"action":"set_color","color":"blue",'
                        '"brightness":40}'
                    )
                }
            }

        action = infer_tool_action(
            "gemma:2b",
            "Set the color to blue at 40 percent brightness",
            fake_chat,
            router,
        )

        self.assertEqual(
            action,
            {"action": "set_color", "color": "blue", "brightness": 40},
        )
        self.assertEqual(
            router.execute(action),
            ToolResult.success("Color set."),
        )
        self.assertEqual(
            received,
            [{"action": "set_color", "color": "blue", "brightness": 40}],
        )

    def test_disabled_action_is_absent_from_prompt_and_rejected(self) -> None:
        router = ToolRouter(
            {
                "features": [
                    {
                        "module": "bmo.features.get_time",
                        "enabled": True,
                        "settings": {},
                    }
                ]
            }
        )
        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {"message": {"content": '{"action":"get_weather"}'}}

        self.assertIsNone(
            infer_tool_action(
                "gemma:2b",
                "What's the weather?",
                fake_chat,
                router,
            )
        )
        routing_prompt = captured["messages"][0]["content"]
        self.assertIn("get_time", routing_prompt)
        self.assertNotIn("get_weather", routing_prompt)

    def test_natural_weather_wording_uses_model_location(self) -> None:
        def fake_chat(**kwargs):
            self.assertEqual(kwargs["format"], "json")
            self.assertEqual(kwargs["options"]["temperature"], 0)
            return {
                "message": {
                    "content": (
                        '{"action":"get_weather",'
                        '"location":"Houston, Texas"}'
                    )
                }
            }

        action = infer_tool_action(
            "gemma:2b",
            "what's weather like in Houston, Texas today?",
            fake_chat,
        )

        self.assertEqual(
            action,
            {"action": "get_weather", "location": "Houston, Texas"},
        )

    def test_transcription_variation_is_semantically_classified(self) -> None:
        def fake_chat(**kwargs):
            self.assertIn(
                "That's the weather I'd like today.",
                kwargs["messages"][1]["content"],
            )
            return {"message": {"content": '{"action":"get_weather"}'}}

        self.assertEqual(
            infer_tool_action(
                "gemma:2b",
                "That's the weather I'd like today.",
                fake_chat,
            ),
            {"action": "get_weather"},
        )

    def test_model_weather_location_is_cleaned(self) -> None:
        def fake_chat(**kwargs):
            return {
                "message": {
                    "content": (
                        '{"action":"get_weather",'
                        '"location":"California right now"}'
                    )
                }
            }

        self.assertEqual(
            infer_tool_action(
                "gemma:2b",
                "Weather in California right now",
                fake_chat,
            ),
            {"action": "get_weather", "location": "California"},
        )

    def test_chat_classification_does_not_execute_a_tool(self) -> None:
        def fake_chat(**kwargs):
            return {"message": {"content": '{"action":"chat"}'}}

        self.assertIsNone(
            infer_tool_action("gemma:2b", "Tell me a joke", fake_chat)
        )

    def test_timer_classification_preserves_operation_fields(self) -> None:
        def fake_chat(**kwargs):
            return {
                "message": {
                    "content": (
                        '{"action":"set_timer","duration":'
                        '"one hour and ten minutes","label":"laundry"}'
                    )
                }
            }

        self.assertEqual(
            infer_tool_action(
                "gemma:2b",
                "Remind me about the laundry in an hour and ten minutes",
                fake_chat,
            ),
            {
                "action": "set_timer",
                "duration": "one hour and ten minutes",
                "label": "laundry",
            },
        )

    def test_timer_classification_preserves_every_supported_field_type(
        self,
    ) -> None:
        def fake_chat(**kwargs):
            return {
                "message": {
                    "content": (
                        '{"action":"set_timer","operation":"cancel",'
                        '"duration":"90 seconds","duration_seconds":90,'
                        '"timer_id":7,"label":"tea"}'
                    )
                }
            }

        self.assertEqual(
            infer_tool_action(
                "gemma:2b",
                "Cancel tea timer number seven",
                fake_chat,
            ),
            {
                "action": "set_timer",
                "operation": "cancel",
                "duration": "90 seconds",
                "duration_seconds": 90,
                "timer_id": 7,
                "label": "tea",
            },
        )

    def test_empty_search_query_is_rejected(self) -> None:
        for content in (
            '{"action":"search_web"}',
            '{"action":"search_web","query":"  "}',
        ):
            with self.subTest(content=content):
                def fake_chat(**kwargs):
                    return {"message": {"content": content}}

                self.assertIsNone(
                    infer_tool_action(
                        "gemma:2b",
                        "Search for something",
                        fake_chat,
                    )
                )

    def test_conversational_game_answer_uses_canonical_sometimes(self) -> None:
        def fake_chat(**kwargs):
            return {"message": {"content": '{"answer":"sometimes"}'}}

        self.assertEqual(
            infer_game_answer(
                "gemma:2b",
                "Only under certain circumstances",
                fake_chat,
            ),
            "sometimes",
        )

    def test_legacy_model_answer_alias_is_normalized_without_candidate_expansion(
        self,
    ) -> None:
        def fake_chat(**kwargs):
            return {"message": {"content": '{"answer":"maybe"}'}}

        self.assertEqual(
            infer_game_answer(
            "gemma:2b",
            "Only under certain circumstances",
            fake_chat,
            ),
            "sometimes",
        )

    def test_fallback_game_guess_returns_one_non_excluded_object(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_chat(**kwargs):
            calls.append(kwargs)
            return {"message": {"content": '{"guess":"a toaster"}'} }

        guess = infer_game_guess(
            "gemma:2b",
            [{"question": "Is it warm?", "answer": "yes"}],
            fake_chat,
            excluded_names=("a kettle",),
        )

        self.assertEqual(guess, "a toaster")
        self.assertEqual(calls[0]["format"], "json")
        self.assertIn("a kettle", calls[0]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
