"""Characterization coverage for the current tool-routing contract."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

from bmo.app import BotGUI
from bmo.config import OLLAMA_OPTIONS
from bmo.features import ToolResult
from bmo.intent import infer_tool_action
from bmo.location import Location, LocationError, LocationNotConfigured
from bmo.prompts import build_routing_prompt
from bmo.tools import ToolRouter
from bmo.weather import WeatherError


EXPECTED_TOOLS = {
    "get_time",
    "set_timer",
    "get_location",
    "get_weather",
    "search_web",
    "capture_image",
}

EXPECTED_ALIASES = {
    "google": "search_web",
    "browser": "search_web",
    "news": "search_web",
    "search_news": "search_web",
    "look": "capture_image",
    "see": "capture_image",
    "check_time": "get_time",
    "timer": "set_timer",
    "location": "get_location",
    "where_am_i": "get_location",
    "weather": "get_weather",
    "forecast": "get_weather",
    "check_weather": "get_weather",
}

EXACT_DIRECT_REQUESTS = {
    "what time is it": {"action": "get_time"},
    "what's the time": {"action": "get_time"},
    "whats the time": {"action": "get_time"},
    "tell me the time": {"action": "get_time"},
    "what is the current time": {"action": "get_time"},
    "current time": {"action": "get_time"},
    "set a timer for five minutes": {
        "action": "set_timer",
        "duration": "five minutes",
    },
    "cancel all timers": {
        "action": "set_timer",
        "operation": "cancel_all",
    },
    "where am i": {"action": "get_location"},
    "what is my location": {"action": "get_location"},
    "what's my location": {"action": "get_location"},
    "whats my location": {"action": "get_location"},
    "what city am i in": {"action": "get_location"},
    "where are we": {"action": "get_location"},
    "weather": {"action": "get_weather"},
    "weather today": {"action": "get_weather"},
    "today's weather": {"action": "get_weather"},
    "todays weather": {"action": "get_weather"},
    "what is the weather": {"action": "get_weather"},
    "what's the weather": {"action": "get_weather"},
    "whats the weather": {"action": "get_weather"},
    "what is the weather like today": {"action": "get_weather"},
    "what's the weather like today": {"action": "get_weather"},
    "whats the weather like today": {"action": "get_weather"},
    "how is the weather": {"action": "get_weather"},
    "how's the weather": {"action": "get_weather"},
    "hows the weather": {"action": "get_weather"},
    "what is it like outside": {"action": "get_weather"},
    "what's it like outside": {"action": "get_weather"},
    "whats it like outside": {"action": "get_weather"},
    "take a photo": {"action": "capture_image"},
    "take a picture": {"action": "capture_image"},
    "capture a photo": {"action": "capture_image"},
    "capture a picture": {"action": "capture_image"},
    "what do you see": {"action": "capture_image"},
    "what can you see": {"action": "capture_image"},
    "look around": {"action": "capture_image"},
}

WEATHER_PREFIXES = (
    "what is the weather in ",
    "what's the weather in ",
    "whats the weather in ",
    "what is the weather like in ",
    "what's the weather like in ",
    "whats the weather like in ",
    "how is the weather in ",
    "how's the weather in ",
    "hows the weather in ",
    "weather in ",
    "weather for ",
    "forecast for ",
    "forecast in ",
)

SEARCH_PREFIXES = (
    "search the web for ",
    "do a web search for ",
    "run a web search for ",
    "perform a web search for ",
    "search online for ",
    "search for ",
    "look up ",
    "google ",
)


class RoutingVocabularyCharacterizationTests(unittest.TestCase):
    def test_current_tool_names_are_exactly_characterized(self) -> None:
        self.assertEqual(ToolRouter.VALID_TOOLS, EXPECTED_TOOLS)

    def test_current_aliases_are_exactly_characterized(self) -> None:
        self.assertEqual(ToolRouter.ALIASES, EXPECTED_ALIASES)

    def test_every_tool_name_and_alias_normalizes_to_its_current_action(
        self,
    ) -> None:
        normalized_actions = {name: name for name in EXPECTED_TOOLS}
        normalized_actions.update(EXPECTED_ALIASES)

        for supplied_action, expected_action in normalized_actions.items():
            with self.subTest(supplied_action=supplied_action):
                self.assertEqual(
                    ToolRouter.normalize_action({"action": supplied_action}),
                    expected_action,
                )

    def test_action_normalization_lowercases_strips_and_stringifies(self) -> None:
        cases = (
            ({"action": "  CHECK_TIME  "}, "get_time"),
            ({"action": " Get_Weather "}, "get_weather"),
            ({"action": None}, "none"),
            ({}, ""),
        )
        for action_data, expected in cases:
            with self.subTest(action_data=action_data):
                self.assertEqual(
                    ToolRouter.normalize_action(action_data),
                    expected,
                )

    def test_every_exact_direct_request_routes_to_its_current_action(self) -> None:
        for user_text, expected in EXACT_DIRECT_REQUESTS.items():
            with self.subTest(user_text=user_text):
                self.assertEqual(
                    ToolRouter.match_direct_action(user_text),
                    expected,
                )

    def test_every_weather_prefix_routes_and_preserves_the_cleaned_place(
        self,
    ) -> None:
        for prefix in WEATHER_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    ToolRouter.match_direct_action(
                        f"{prefix}Austin, Texas right now?"
                    ),
                    {
                        "action": "get_weather",
                        "location": "austin, texas",
                    },
                )

    def test_every_search_prefix_routes_and_preserves_the_query(self) -> None:
        for prefix in SEARCH_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    ToolRouter.match_direct_action(f"{prefix}Robot News?"),
                    {"action": "search_web", "query": "robot news"},
                )

    def test_direct_request_input_is_case_space_and_end_punctuation_normalized(
        self,
    ) -> None:
        self.assertEqual(
            ToolRouter.match_direct_action("  WhAt   TiMe IS  It?!  "),
            {"action": "get_time"},
        )

    def test_empty_prefixed_requests_and_conversation_do_not_route(self) -> None:
        for user_text in (
            "search the web for",
            "look up",
            "weather in",
            "forecast for",
            "why do search engines rank pages?",
            "hello there",
            "",
        ):
            with self.subTest(user_text=user_text):
                self.assertIsNone(ToolRouter.match_direct_action(user_text))


class ToolExecutionCharacterizationTests(unittest.TestCase):
    @staticmethod
    def make_router() -> ToolRouter:
        # A nonempty explicit config ensures tests never consult config.json.
        return ToolRouter({"online_timeout_seconds": 6})

    def test_every_canonical_tool_name_executes_its_current_branch(self) -> None:
        router = self.make_router()

        with patch("bmo.tools.datetime.datetime") as datetime_mock:
            datetime_mock.now.return_value.strftime.return_value = "04:05 PM"
            self.assertEqual(
                router.execute({"action": "get_time"}),
                ToolResult.success("The current time is 04:05 PM."),
            )

        router.location_service = Mock(
            resolve=Mock(
                return_value=Location(
                    name="Austin, Texas",
                    latitude=30.27,
                    longitude=-97.74,
                )
            )
        )
        self.assertEqual(
            router.execute({"action": "get_location"}),
            ToolResult.success(
                "Your configured location is Austin, Texas."
            ),
        )

        router.weather_service = Mock(
            current_report=Mock(return_value="CURRENT WEATHER REPORT")
        )
        self.assertEqual(
            router.execute(
                {
                    "action": "get_weather",
                    "location": "Dallas, Texas today",
                }
            ),
            ToolResult.success("CURRENT WEATHER REPORT"),
        )
        router.weather_service.current_report.assert_called_once_with(
            "Dallas, Texas"
        )

        with patch.object(
            router,
            "_search_web",
            return_value=ToolResult.success("FORMATTED SEARCH RESULTS"),
        ) as search_web:
            self.assertEqual(
                router.execute(
                    {"action": "search_web", "query": "robot news"}
                ),
                ToolResult.success("FORMATTED SEARCH RESULTS"),
            )
        search_web.assert_called_once_with("robot news")

        self.assertEqual(
            router.execute({"action": "capture_image"}),
            ToolResult.capture_image(),
        )

    def test_symbolic_execute_results_are_characterized(self) -> None:
        router = self.make_router()
        cases = (
            ({"action": "dance"}, ToolResult.invalid_action()),
            (
                {"action": "dance", "value": "one"},
                ToolResult.invalid_action(),
            ),
            (
                {"action": "dance", "value": "answer in plain text"},
                ToolResult.chat_fallback("answer in plain text"),
            ),
            ({"action": "capture_image"}, ToolResult.capture_image()),
            ({"action": "search_web"}, ToolResult.empty()),
        )
        for action_data, expected in cases:
            with self.subTest(action_data=action_data):
                self.assertEqual(router.execute(action_data), expected)

    def test_location_result_messages_are_characterized(self) -> None:
        router = self.make_router()
        cases = (
            (
                LocationNotConfigured("missing"),
                "I do not have a home location configured yet. "
                "Add one in config.json.",
            ),
            (
                LocationError("lookup failed"),
                "I cannot check the configured location right now.",
            ),
            (
                OSError("offline"),
                "I cannot check the configured location right now.",
            ),
            (
                TimeoutError("slow"),
                "I cannot check the configured location right now.",
            ),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                router.location_service = Mock(
                    resolve=Mock(side_effect=error)
                )
                self.assertEqual(
                    router.execute({"action": "get_location"}),
                    ToolResult.success(expected),
                )

    def test_weather_result_messages_are_characterized(self) -> None:
        router = self.make_router()
        cases = (
            (
                LocationNotConfigured("missing"),
                "I need a home location in config.json, or you can ask "
                "for the weather in a named city.",
            ),
            (
                LocationError("I could not find that place."),
                "I could not find that place.",
            ),
            (
                WeatherError("bad data"),
                "I cannot reach the weather service right now.",
            ),
            (
                OSError("offline"),
                "I cannot reach the weather service right now.",
            ),
            (
                TimeoutError("slow"),
                "I cannot reach the weather service right now.",
            ),
            (
                RuntimeError("unexpected"),
                "I cannot reach the weather service right now.",
            ),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                router.weather_service = Mock(
                    current_report=Mock(side_effect=error)
                )
                self.assertEqual(
                    router.execute({"action": "get_weather"}),
                    ToolResult.success(expected),
                )

    def test_search_empty_status_and_details_are_characterized(self) -> None:
        class EmptyDDGS:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def news(self, query, region, max_results):
                return []

            def text(self, query, region, max_results):
                return []

        router = self.make_router()
        fake_ddgs = types.SimpleNamespace(DDGS=EmptyDDGS)
        with patch.dict(sys.modules, {"ddgs": fake_ddgs}):
            self.assertEqual(
                router._search_web("robot news"),
                ToolResult.empty(),
            )
        self.assertEqual(
            router.last_tool_details,
            {"query": "robot news", "results": []},
        )

    def test_search_error_status_and_details_are_characterized(self) -> None:
        class BrokenDDGS:
            def __init__(self):
                raise OSError("offline")

        router = self.make_router()
        fake_ddgs = types.SimpleNamespace(DDGS=BrokenDDGS)
        with patch.dict(sys.modules, {"ddgs": fake_ddgs}):
            self.assertEqual(
                router._search_web("robot news"),
                ToolResult.error(),
            )
        self.assertEqual(
            router.last_tool_details,
            {"query": "robot news", "error": "offline"},
        )

    def test_search_success_result_and_details_are_characterized(self) -> None:
        result = {
            "title": "Robot update",
            "source": "Example News",
            "body": "Robots are learning new tasks.",
            "url": "https://example.test/robots",
        }

        class SuccessfulDDGS:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def news(self, query, region, max_results):
                return [result]

        router = self.make_router()
        fake_ddgs = types.SimpleNamespace(DDGS=SuccessfulDDGS)
        with patch.dict(sys.modules, {"ddgs": fake_ddgs}):
            response = router._search_web("robot news")

        self.assertEqual(
            response,
            ToolResult.success(
                "SEARCH RESULTS for 'robot news':\n\n"
                "Result 1:\n"
                "Title: Robot update\n"
                "Source: Example News\n"
                "Snippet: Robots are learning new tasks.\n"
                "URL: https://example.test/robots"
            ),
        )
        self.assertEqual(
            router.last_tool_details,
            {"query": "robot news", "results": [result]},
        )


class PromptCharacterizationTests(unittest.TestCase):
    @staticmethod
    def make_gui(*, action_name: str, tool_result: ToolResult) -> BotGUI:
        gui = BotGUI.__new__(BotGUI)
        gui.text_model = "text-model"
        gui.tool_router = Mock()
        gui.tool_router.normalize_action.return_value = action_name
        gui._execute_tool = Mock(return_value=tool_result)
        gui.set_state = Mock()
        gui.capture_image = Mock(return_value=None)
        gui.chat_and_respond = Mock()
        gui._logged_chat = Mock(
            return_value={"message": {"content": "Generated summary.  "}}
        )
        gui._speak_complete_response = Mock()
        gui._remember_turn = Mock()
        gui.wait_for_tts = Mock()
        gui.thinking_sound_active = Mock()
        return gui

    def test_router_model_receives_the_current_generated_prompt(self) -> None:
        captured = {}
        router = ToolRouter({"online_timeout_seconds": 6})

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {"message": {"content": '{"action":"check_time"}'}}

        self.assertEqual(
            infer_tool_action(
                "router-model",
                "Could you tell me the time?",
                fake_chat,
                router,
            ),
            {"action": "get_time"},
        )
        self.assertEqual(
            captured,
            {
                "model": "router-model",
                "messages": [
                    {
                        "role": "system",
                        "content": build_routing_prompt(router.registry),
                    },
                    {
                        "role": "user",
                        "content": "Could you tell me the time?",
                    },
                ],
                "stream": False,
                "format": "json",
                "options": {**OLLAMA_OPTIONS, "temperature": 0},
            },
        )

    def test_direct_search_uses_the_current_summary_prompt_and_strips_reply(
        self,
    ) -> None:
        gui = self.make_gui(
            action_name="search_web",
            tool_result=ToolResult.success("RAW SEARCH RESULTS"),
        )

        BotGUI._handle_direct_action(
            gui,
            "Search the web for robot news",
            {"action": "search_web", "query": "robot news"},
        )

        gui._logged_chat.assert_called_once_with(
            model="text-model",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are reading current web-search results for the user. "
                        "Briefly report the useful information contained in the results. "
                        "The user's words may be a search command rather than a question. "
                        "Do not claim the results are irrelevant when their titles or "
                        "snippets clearly concern the requested subject. "
                        "Use only the supplied results. Answer in one or two short sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Search request: Search the web for robot news\n\n"
                        "Web-search results:\nRAW SEARCH RESULTS\n\n"
                        "Report what these results say."
                    ),
                },
            ],
            stream=False,
            options=OLLAMA_OPTIONS,
        )
        gui._speak_complete_response.assert_called_once_with(
            "Generated summary.",
            None,
        )
        gui._remember_turn.assert_called_once_with(
            "Search the web for robot news",
            "Generated summary.",
        )

    def test_direct_result_statuses_have_the_current_user_facing_text(self) -> None:
        cases = (
            (ToolResult.invalid_action(), "I am not sure how to do that."),
            (
                ToolResult.empty(),
                "I searched, but I couldn't find anything about that.",
            ),
            (ToolResult.error(), "I cannot reach the internet right now."),
        )
        for tool_result, expected in cases:
            with self.subTest(tool_result=tool_result):
                gui = self.make_gui(
                    action_name="get_weather",
                    tool_result=tool_result,
                )
                BotGUI._handle_direct_action(
                    gui,
                    "user request",
                    {"action": "get_weather"},
                )
                gui._speak_complete_response.assert_called_once_with(
                    expected,
                    None,
                )
                gui._remember_turn.assert_called_once_with(
                    "user request",
                    expected,
                )

    def test_direct_camera_failure_has_the_current_user_facing_text(self) -> None:
        gui = self.make_gui(
            action_name="capture_image",
            tool_result=ToolResult.capture_image(),
        )

        BotGUI._handle_direct_action(
            gui,
            "Take a photo",
            {"action": "capture_image"},
        )

        gui._speak_complete_response.assert_called_once_with(
            "I could not use the camera right now.",
            None,
        )
        gui._remember_turn.assert_called_once_with(
            "Take a photo",
            "I could not use the camera right now.",
        )

    def test_generated_tool_result_uses_the_current_summary_prompt(self) -> None:
        gui = self.make_gui(
            action_name="get_weather",
            tool_result=ToolResult.success("RAW WEATHER RESULT"),
        )

        BotGUI._handle_action_response(
            gui,
            "Will I need an umbrella?",
            "/tmp/camera.jpg",
            "vision-model",
            '{"action":"get_weather"}',
        )

        gui._logged_chat.assert_called_once_with(
            model="vision-model",
            messages=[
                {
                    "role": "system",
                    "content": "Summarize this result in one short sentence.",
                },
                {
                    "role": "user",
                    "content": (
                        "RESULT: RAW WEATHER RESULT\n"
                        "User Question: Will I need an umbrella?"
                    ),
                },
            ],
            stream=False,
            options=OLLAMA_OPTIONS,
        )
        gui._speak_complete_response.assert_called_once_with(
            "Generated summary.  ",
            "/tmp/camera.jpg",
        )
        gui._remember_turn.assert_called_once_with(
            "Will I need an umbrella?",
            "Generated summary.  ",
        )

    def test_generated_result_statuses_have_the_current_user_facing_text(
        self,
    ) -> None:
        cases = (
            (ToolResult.invalid_action(), "I am not sure how to do that."),
            (
                ToolResult.empty(),
                "I searched, but I couldn't find any news about that.",
            ),
            (ToolResult.error(), "I cannot reach the internet right now."),
        )
        for tool_result, expected in cases:
            with self.subTest(tool_result=tool_result):
                gui = self.make_gui(
                    action_name="get_weather",
                    tool_result=tool_result,
                )
                BotGUI._handle_action_response(
                    gui,
                    "user request",
                    None,
                    "text-model",
                    '{"action":"get_weather"}',
                )
                gui._speak_complete_response.assert_called_once_with(
                    expected,
                    None,
                )
                gui._remember_turn.assert_called_once_with(
                    "user request",
                    expected,
                )
                gui._logged_chat.assert_not_called()

    def test_generated_time_result_is_presented_without_summary_prompt(self) -> None:
        gui = self.make_gui(
            action_name="get_time",
            tool_result=ToolResult.success(
                "The current time is 04:05 PM."
            ),
        )

        BotGUI._handle_action_response(
            gui,
            "What time is it?",
            None,
            "text-model",
            '{"action":"get_time"}',
        )

        gui._speak_complete_response.assert_called_once_with(
            "The current time is 04:05 PM.",
            None,
        )
        gui._remember_turn.assert_called_once_with(
            "What time is it?",
            "The current time is 04:05 PM.",
        )
        gui._logged_chat.assert_not_called()

    def test_generated_chat_fallback_prefix_is_removed_for_user(self) -> None:
        gui = self.make_gui(
            action_name="not_a_tool",
            tool_result=ToolResult.chat_fallback(
                "Answer in ordinary text"
            ),
        )

        BotGUI._handle_action_response(
            gui,
            "user request",
            None,
            "text-model",
            '{"action":"not_a_tool","value":"Answer in ordinary text"}',
        )

        gui._speak_complete_response.assert_called_once_with(
            "Answer in ordinary text",
            None,
        )
        gui._remember_turn.assert_called_once_with(
            "user request",
            "Answer in ordinary text",
        )
        gui._logged_chat.assert_not_called()

    def test_generated_camera_status_recaptures_and_reprompts_with_image(
        self,
    ) -> None:
        gui = self.make_gui(
            action_name="capture_image",
            tool_result=ToolResult.capture_image(),
        )
        gui.capture_image.return_value = "/tmp/new-image.jpg"

        BotGUI._handle_action_response(
            gui,
            "What do you see?",
            None,
            "text-model",
            '{"action":"capture_image"}',
        )

        gui.chat_and_respond.assert_called_once_with(
            "What do you see?",
            image_path="/tmp/new-image.jpg",
        )
        gui._speak_complete_response.assert_not_called()
        gui._logged_chat.assert_not_called()

    def test_generated_camera_failure_uses_the_camera_error_text(self) -> None:
        gui = self.make_gui(
            action_name="capture_image",
            tool_result=ToolResult.capture_image(),
        )

        BotGUI._handle_action_response(
            gui,
            "What do you see?",
            None,
            "text-model",
            '{"action":"capture_image"}',
        )

        gui._speak_complete_response.assert_called_once_with(
            "I could not use the camera right now.",
            None,
        )
        gui._remember_turn.assert_called_once_with(
            "What do you see?",
            "I could not use the camera right now.",
        )
        gui._logged_chat.assert_not_called()

    def test_empty_generated_content_produces_no_user_facing_response(self) -> None:
        gui = self.make_gui(
            action_name="get_weather",
            tool_result=ToolResult.success(""),
        )

        BotGUI._handle_action_response(
            gui,
            "Weather?",
            None,
            "text-model",
            '{"action":"get_weather"}',
        )

        gui._speak_complete_response.assert_not_called()
        gui._remember_turn.assert_not_called()
        gui._logged_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
