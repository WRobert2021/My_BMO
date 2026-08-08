"""Tests for local-model semantic intent routing."""

from __future__ import annotations

import unittest

from bmo.intent import (
    infer_game_answer,
    infer_game_candidates,
    infer_tool_action,
)


class IntentRoutingTests(unittest.TestCase):
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

    def test_empty_search_query_is_rejected(self) -> None:
        def fake_chat(**kwargs):
            return {"message": {"content": '{"action":"search_web"}'}}

        self.assertIsNone(
            infer_tool_action("gemma:2b", "Search for something", fake_chat)
        )

    def test_conversational_game_answer_can_use_local_model(self) -> None:
        def fake_chat(**kwargs):
            return {"message": {"content": '{"answer":"maybe"}'}}

        self.assertEqual(
            infer_game_answer(
                "gemma:2b",
                "Only under certain circumstances",
                fake_chat,
            ),
            "maybe",
        )

    def test_game_candidate_expansion_is_validated(self) -> None:
        def fake_chat(**kwargs):
            return {
                "message": {
                    "content": (
                        '{"candidates":[{"name":"a toaster",'
                        '"entity_type":"device","traits":'
                        '{"physical":0.99,"bad_key":1}}]}'
                    )
                }
            }

        candidates = infer_game_candidates(
            "gemma:2b",
            [
                {
                    "question_key": "physical",
                    "question": "Is it physical?",
                    "answer": "yes",
                    "was_guess": False,
                }
            ],
            ["physical", "electric"],
            fake_chat,
        )

        self.assertEqual(
            candidates[0]["name"],
            "a toaster",
        )
        self.assertEqual(candidates[0]["traits"], {"physical": 0.98})


if __name__ == "__main__":
    unittest.main()
