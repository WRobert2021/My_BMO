"""Focused tests for typed tool registration and ToolRouter delegation."""

from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

from bmo.features import (
    DuplicateToolError,
    FeatureMenuContext,
    FeatureMenuItem,
    GetLocationTool,
    GetTimeTool,
    GetWeatherTool,
    SearchWebTool,
    ToolArchive,
    ToolAttachment,
    ToolContract,
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolResultKind,
    UnknownToolError,
)
from bmo.features.search_web import SEARCH_SUMMARY_PRESENTATION
from bmo.location import Location
from bmo.tools import ToolRouter, default_metadata_router


class ToolRegistryTests(unittest.TestCase):
    def test_constructor_failure_closes_already_registered_tools(self) -> None:
        class ResourceTool:
            action = "status"
            aliases = ()

            def __init__(self) -> None:
                self.close = Mock()

        resource = ResourceTool()

        with self.assertRaisesRegex(DuplicateToolError, "Duplicate tool"):
            ToolRegistry(
                (
                    resource,
                    ToolContract("status", Mock()),
                )
            )

        resource.close.assert_called_once_with()

    def test_feature_menu_metadata_and_launch_stay_registry_driven(self) -> None:
        class MenuTool:
            action = "status"
            aliases = ()
            menu_item = FeatureMenuItem(
                "status",
                "Status",
                Path("icons/status.png"),
            )

            def __init__(self) -> None:
                self.open_menu = Mock()

        tool = MenuTool()
        registry = ToolRegistry([tool])
        context = FeatureMenuContext(master="ROOT", on_close=Mock())

        self.assertEqual(registry.menu_items, (tool.menu_item,))
        registry.open_menu_item(" STATUS ", context)

        tool.open_menu.assert_called_once_with(context)

    def test_feature_menu_requires_an_open_hook(self) -> None:
        class MenuToolWithoutOpen:
            action = "status"
            aliases = ()
            menu_item = FeatureMenuItem(
                "status",
                "Status",
                Path("icons/status.png"),
            )

        with self.assertRaisesRegex(TypeError, "must define open_menu"):
            ToolRegistry([MenuToolWithoutOpen()])

    def test_menu_only_tool_is_excluded_from_every_action_surface(self) -> None:
        class MenuOnlyTool:
            action = "album"
            aliases = ()
            menu_only = True
            menu_item = FeatureMenuItem(
                "album",
                "Album",
                Path("icons/album.png"),
            )
            description = "must not be prompted"
            schemas = ('{"action":"album"}',)
            prompt_guidance = ("must not be prompted",)
            prompt_examples = ()

            def open_menu(self, context):
                del context

            def execute(self, request):
                del request
                return ToolResult.success("must not execute")

            def match_direct_action(self, user_text):
                del user_text
                return {"action": "album"}

        registry = ToolRegistry((MenuOnlyTool(),))

        self.assertEqual(registry.actions, set())
        self.assertEqual(registry.aliases, {})
        self.assertEqual(len(registry.menu_items), 1)
        self.assertEqual(registry.capabilities, ())
        self.assertIsNone(registry.match_direct_action("open album"))
        self.assertIsNone(
            registry.prepare_model_request({"action": "album"})
        )
        with self.assertRaisesRegex(UnknownToolError, "only from the menu"):
            registry.execute({"action": "album"})

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

    def test_passes_context_only_to_features_that_opt_in(self) -> None:
        class ContextualTool:
            action = "artifact"
            aliases = ()
            uses_context = True

            def __init__(self) -> None:
                self.execute = Mock(
                    return_value=ToolResult.success("created")
                )

        contextual = ContextualTool()
        simple_handler = Mock(return_value=ToolResult.success("simple"))
        registry = ToolRegistry(
            (
                contextual,
                ToolContract("simple", simple_handler),
            )
        )
        context = ToolContext(
            artifact_allocator=lambda kind, suffix: Path("/tmp/output.jpg"),
            event_recorder=Mock(),
            status_requester=Mock(),
        )

        self.assertEqual(
            registry.execute({"action": "artifact"}, context=context),
            ToolResult.success("created"),
        )
        self.assertEqual(
            registry.execute({"action": "simple"}, context=context),
            ToolResult.success("simple"),
        )

        contextual.execute.assert_called_once_with(
            {"action": "artifact"},
            context,
        )
        simple_handler.assert_called_once_with({"action": "simple"})

    def test_prepares_model_requests_without_losing_json_fields_or_types(
        self,
    ) -> None:
        events = []

        def normalize(request):
            events.append(("normalize", dict(request)))
            return {
                **request,
                "color": str(request.get("color") or "").lower(),
            }

        def prepare(request):
            events.append(("prepare", dict(request)))
            return request if request.get("color") else None

        registry = ToolRegistry(
            [
                ToolContract(
                    "set_color",
                    Mock(return_value=ToolResult.success("ok")),
                    aliases=("color",),
                    request_normalizer=normalize,
                    model_request_preparer=prepare,
                )
            ]
        )
        request = {
            "action": " COLOR ",
            "color": "BLUE",
            "brightness": 40,
            "transition": {"seconds": 1.5, "enabled": True},
        }

        self.assertEqual(
            registry.prepare_model_request(request),
            {
                "action": "set_color",
                "color": "blue",
                "brightness": 40,
                "transition": {"seconds": 1.5, "enabled": True},
            },
        )
        self.assertEqual(
            [event[0] for event in events],
            ["normalize", "prepare"],
        )

    def test_model_request_preparation_rejects_unknown_and_invalid_actions(
        self,
    ) -> None:
        registry = ToolRegistry(
            [
                ToolContract(
                    "search",
                    Mock(return_value=ToolResult.success("ok")),
                    model_request_preparer=lambda request: (
                        request if request.get("query") else None
                    ),
                )
            ]
        )

        self.assertIsNone(
            registry.prepare_model_request({"action": "disabled"})
        )
        self.assertIsNone(registry.prepare_model_request({"action": "search"}))

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

    def test_closed_registry_cannot_execute_cleaned_up_tools(self) -> None:
        handler = Mock(return_value=ToolResult.success("ok"))
        registry = ToolRegistry([ToolContract("status", handler)])
        registry.close()

        with self.assertRaisesRegex(RuntimeError, "after closing"):
            registry.execute({"action": "status"})
        handler.assert_not_called()

    def test_closed_registry_rejects_every_registration_path(self) -> None:
        registry = ToolRegistry()
        registry.close()

        with self.assertRaisesRegex(RuntimeError, "after closing"):
            registry.register(ToolContract("status", Mock()))
        with self.assertRaisesRegex(RuntimeError, "after closing"):
            with registry.registration():
                pass

    def test_close_lookup_failure_does_not_skip_other_tools(self) -> None:
        class HealthyCloseTool:
            action = "healthy"
            aliases = ()

            def __init__(self) -> None:
                self.close = Mock()

        class BrokenCloseTool:
            action = "broken"
            aliases = ()

            @property
            def close(self):
                raise RuntimeError("close lookup exploded")

        healthy = HealthyCloseTool()
        registry = ToolRegistry((healthy, BrokenCloseTool()))

        output = StringIO()
        with redirect_stdout(output):
            registry.close()

        self.assertIn("Could not close 'broken'", output.getvalue())
        healthy.close.assert_called_once_with()

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
            ToolResult.model_summarized(
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
            ToolResult.model_summarized("CURRENT WEATHER REPORT"),
        )
        self.assertEqual(
            registry.execute(
                {"action": "google", "query": "robot news"}
            ),
            ToolResult.summarized(
                "FORMATTED SEARCH RESULTS",
                presentation=SEARCH_SUMMARY_PRESENTATION,
                archive=ToolArchive("web", "searches.jsonl"),
            ),
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
                "get_calendar",
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
                "calendar": "get_calendar",
                "schedule": "get_calendar",
                "plan": "get_calendar",
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
        result = ToolResult.vision_follow_up(
            ToolAttachment.image("/tmp/camera.jpg")
        )
        router.registry.execute.return_value = result

        self.assertEqual(
            router.execute({"action": "look"}),
            result,
        )
        router.registry.execute.assert_called_once_with({"action": "look"})

    def test_metadata_router_rejects_legacy_search_execution(self) -> None:
        router = default_metadata_router()

        self.assertTrue(router.registry.closed)
        with self.assertRaisesRegex(RuntimeError, "after closing"):
            router._search_web("must not run")


if __name__ == "__main__":
    unittest.main()
