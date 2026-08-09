"""Focused tests for typed tool registration and ToolRouter delegation."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from bmo.features import (
    DuplicateToolError,
    GetLocationTool,
    GetTimeTool,
    GetWeatherTool,
    SearchWebTool,
    ToolContract,
    ToolRegistry,
    ToolResult,
    ToolResultKind,
    UnknownToolError,
)
from bmo.location import Location
from bmo.tools import ToolRouter


class ToolRegistryTests(unittest.TestCase):
    def test_tool_result_rejects_invalid_kind_and_content_combinations(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "content results require string content",
        ):
            ToolResult(ToolResultKind.CONTENT)
        with self.assertRaisesRegex(
            ValueError,
            "empty results cannot include content",
        ):
            ToolResult(ToolResultKind.EMPTY, "unexpected")

    def test_executes_canonical_actions_and_aliases(self) -> None:
        handler = Mock(return_value=ToolResult.success("TOOL RESPONSE"))
        registry = ToolRegistry(
            [ToolContract("status", handler, aliases=("check_status",))]
        )

        request = {"action": "  CHECK_STATUS  ", "value": "details"}

        self.assertEqual(registry.normalize_action(request), "status")
        self.assertEqual(
            registry.execute(request),
            ToolResult.success("TOOL RESPONSE"),
        )
        handler.assert_called_once_with(
            {"action": "status", "value": "details"}
        )
        self.assertEqual(registry.actions, {"status"})
        self.assertEqual(registry.aliases, {"check_status": "status"})

    def test_rejects_duplicate_action_names_without_partial_registration(
        self,
    ) -> None:
        first = ToolContract("status", Mock(), aliases=("state",))
        registry = ToolRegistry([first])

        with self.assertRaisesRegex(
            DuplicateToolError,
            "Duplicate tool action name 'status'",
        ):
            registry.register(ToolContract(" STATUS ", Mock()))

        self.assertEqual(registry.actions, {"status"})
        self.assertEqual(registry.aliases, {"state": "status"})

    def test_rejects_duplicate_aliases_without_partial_registration(
        self,
    ) -> None:
        registry = ToolRegistry(
            [ToolContract("status", Mock(), aliases=("inspect",))]
        )

        with self.assertRaisesRegex(
            DuplicateToolError,
            "Duplicate tool alias 'inspect'",
        ):
            registry.register(
                ToolContract("health", Mock(), aliases=("ready", "inspect"))
            )

        self.assertEqual(registry.actions, {"status"})
        self.assertNotIn("ready", registry.aliases)

    def test_rejects_action_and_alias_namespace_collisions(self) -> None:
        registry = ToolRegistry(
            [ToolContract("status", Mock(), aliases=("inspect",))]
        )

        with self.assertRaisesRegex(
            DuplicateToolError,
            "action name 'inspect' conflicts with an alias",
        ):
            registry.register(ToolContract("inspect", Mock()))

        with self.assertRaisesRegex(
            DuplicateToolError,
            "alias 'status' conflicts with the registered action name",
        ):
            registry.register(
                ToolContract("health", Mock(), aliases=("status",))
            )

    def test_unknown_actions_raise_a_clear_error(self) -> None:
        registry = ToolRegistry()

        with self.assertRaisesRegex(
            UnknownToolError,
            "No tool is registered for action 'missing'",
        ):
            registry.execute({"action": "missing"})

    def test_rejects_untyped_tool_results(self) -> None:
        registry = ToolRegistry(
            [ToolContract("legacy", Mock(return_value="SENTINEL"))]
        )

        with self.assertRaisesRegex(
            TypeError,
            "Tool 'legacy' returned str; expected ToolResult",
        ):
            registry.execute({"action": "legacy"})

    def test_registered_features_own_direct_phrase_matching(self) -> None:
        registry = ToolRegistry(
            (
                GetTimeTool(),
                GetLocationTool(Mock()),
                GetWeatherTool(Mock()),
                SearchWebTool(),
            )
        )
        cases = (
            ("What time is it?", {"action": "get_time"}),
            ("Where am I?", {"action": "get_location"}),
            (
                "Weather in Austin right now?",
                {"action": "get_weather", "location": "austin"},
            ),
            (
                "Search the web for robot news.",
                {"action": "search_web", "query": "robot news"},
            ),
            ("Take a picture.", None),
        )

        for user_text, expected in cases:
            with self.subTest(user_text=user_text):
                self.assertEqual(
                    registry.match_direct_action(user_text),
                    expected,
                )

    def test_individual_features_execute_through_the_registry(self) -> None:
        now = Mock()
        now.strftime.return_value = "04:05 PM"
        location_service = Mock(
            resolve=Mock(
                return_value=Location(
                    name="Austin, Texas",
                    latitude=30.27,
                    longitude=-97.74,
                )
            )
        )
        weather_service = Mock(
            current_report=Mock(return_value="CURRENT WEATHER REPORT")
        )
        searcher = Mock(
            return_value=ToolResult.success("FORMATTED SEARCH RESULTS")
        )
        registry = ToolRegistry(
            (
                GetTimeTool(now=lambda: now),
                GetLocationTool(location_service),
                GetWeatherTool(weather_service),
                SearchWebTool(searcher=searcher),
            )
        )

        self.assertEqual(
            registry.execute({"action": "check_time"}),
            ToolResult.success("The current time is 04:05 PM."),
        )
        self.assertEqual(
            registry.execute({"action": "where_am_i"}),
            ToolResult.success(
                "Your configured location is Austin, Texas."
            ),
        )
        self.assertEqual(
            registry.execute(
                {
                    "action": "forecast",
                    "location": "Dallas, Texas today",
                }
            ),
            ToolResult.success("CURRENT WEATHER REPORT"),
        )
        self.assertEqual(
            registry.execute(
                {"action": "google", "query": "robot news"}
            ),
            ToolResult.success("FORMATTED SEARCH RESULTS"),
        )
        weather_service.current_report.assert_called_once_with(
            "Dallas, Texas"
        )
        searcher.assert_called_once_with("robot news")


class ToolRouterRegistryDelegationTests(unittest.TestCase):
    @staticmethod
    def make_router() -> ToolRouter:
        return ToolRouter({"online_timeout_seconds": 6})

    def test_registered_action_execution_delegates_to_registry(self) -> None:
        router = self.make_router()
        router.registry = Mock()
        router.registry.execute.return_value = ToolResult.success(
            "REGISTRY RESPONSE"
        )

        self.assertEqual(
            router.execute({"action": "check_time"}),
            ToolResult.success("REGISTRY RESPONSE"),
        )
        router.registry.execute.assert_called_once_with(
            {"action": "check_time"}
        )

    def test_router_registry_contains_all_default_features(
        self,
    ) -> None:
        router = self.make_router()

        self.assertEqual(
            router.registry.actions,
            {
                "get_time",
                "set_timer",
                "get_location",
                "get_weather",
                "search_web",
                "capture_image",
            },
        )
        self.assertEqual(
            router.registry.aliases,
            {
                "check_time": "get_time",
                "timer": "set_timer",
                "location": "get_location",
                "where_am_i": "get_location",
                "weather": "get_weather",
                "forecast": "get_weather",
                "check_weather": "get_weather",
                "google": "search_web",
                "browser": "search_web",
                "news": "search_web",
                "search_news": "search_web",
                "look": "capture_image",
                "see": "capture_image",
            },
        )

    def test_router_preserves_feature_configuration_defaults_and_bounds(
        self,
    ) -> None:
        default_router = ToolRouter({"text_model": "test-model"})
        configured_router = ToolRouter(
            {
                "location": {"name": "Austin, Texas"},
                "online_timeout_seconds": 45,
                "weather_units": "metric",
            }
        )

        self.assertEqual(default_router.location_service.timeout, 6.0)
        self.assertEqual(default_router.weather_service.timeout, 6.0)
        self.assertEqual(default_router.weather_service.units, "imperial")
        self.assertEqual(configured_router.location_service.timeout, 30.0)
        self.assertEqual(configured_router.weather_service.timeout, 30.0)
        self.assertEqual(configured_router.weather_service.units, "metric")
        self.assertEqual(
            configured_router.location_service.home_location,
            {"name": "Austin, Texas"},
        )

    def test_camera_trigger_executes_through_registry(self) -> None:
        router = self.make_router()
        router.registry = Mock()
        router.registry.execute.return_value = ToolResult.capture_image()

        self.assertEqual(
            router.execute({"action": "look"}),
            ToolResult.capture_image(),
        )
        router.registry.execute.assert_called_once_with({"action": "look"})


if __name__ == "__main__":
    unittest.main()
