"""Menu-only routing and lifecycle tests for BMO Pre-K Learning."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bmo.features import FeatureMenuContext, ToolResultKind
from bmo.features.learning import (
    CURRICULUM,
    LEARNING_MENU_ITEM,
    LearningConfig,
    LearningTool,
)
from bmo.features.loader import load_feature_registry
from bmo.features.learning.view_model import (
    ChoiceSnapshot,
    InteractionController,
    QuestionSnapshot,
)
from bmo.prompts import build_routing_prompt, build_system_prompt


class LearningRegistrationTests(unittest.TestCase):
    def test_learning_registers_only_as_the_exact_menu_item(self) -> None:
        result = load_feature_registry(
            {
                "features": [
                    {
                        "module": "bmo.features.learning",
                        "enabled": True,
                        "settings": {
                            "config_path": "config/does-not-exist-learning.json"
                        },
                    }
                ]
            },
            reporter=Mock(),
        )
        self.addCleanup(result.registry.close)

        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.actions, set())
        self.assertEqual(result.registry.aliases, {})
        self.assertEqual(result.registry.capabilities, ())
        self.assertEqual(result.registry.menu_items, (LEARNING_MENU_ITEM,))
        self.assertEqual(
            LEARNING_MENU_ITEM.icon_path,
            Path(__file__).resolve().parents[1]
            / "graphics"
            / "icons"
            / "learning.png",
        )
        tool = result.registry.get("learning")
        self.assertIsNotNone(tool)
        self.assertIsNone(tool.match_direct_action("start learning"))
        self.assertEqual(tool.execute({}).kind, ToolResultKind.INVALID_ACTION)
        self.assertIsNone(
            result.registry.prepare_model_request({"action": "learning"})
        )
        for prompt in (
            build_routing_prompt(result.registry),
            build_system_prompt({}, result.registry),
        ):
            self.assertNotIn("learning", prompt.casefold())

    def test_disabled_learning_is_skipped_before_import(self) -> None:
        with patch("bmo.features.loader._load_module") as load_module:
            result = load_feature_registry(
                {
                    "features": [
                        {
                            "module": "bmo.features.learning",
                            "enabled": False,
                            "settings": "ignored before validation",
                        }
                    ]
                }
            )

        load_module.assert_not_called()
        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.menu_items, ())

    def test_hidden_private_config_registers_no_alternate_surface(self) -> None:
        with patch(
            "bmo.features.learning.load_learning_config",
            return_value=LearningConfig(show_in_menu=False),
        ):
            result = load_feature_registry(
                {
                    "features": [
                        {
                            "module": "bmo.features.learning",
                            "enabled": True,
                            "settings": {},
                        }
                    ]
                }
            )

        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.actions, set())
        self.assertEqual(result.registry.menu_items, ())
        self.assertIsNone(result.registry.get("learning"))


class LearningLifecycleTests(unittest.TestCase):
    def make_tool(self, **config_values: object) -> tuple[LearningTool, Mock]:
        app = Mock()
        factory = Mock(return_value=app)
        tool = LearningTool(
            LearningConfig(**config_values),
            catalog=CURRICULUM,
            engine=Mock(),
            store=Mock(),
            app_factory=factory,
        )
        return tool, factory

    @staticmethod
    def make_context() -> tuple[FeatureMenuContext, Mock, Mock]:
        on_close = Mock()
        announcer = Mock()
        announcer.available = True
        announcer.speak.return_value = True
        context = FeatureMenuContext(
            master="ROOT",
            on_close=on_close,
            face_provider=Mock(return_value=None),
            announcer=announcer,
        )
        return context, announcer, on_close

    def test_open_wires_only_narrow_services_and_returns_to_same_menu(self) -> None:
        tool, factory = self.make_tool()
        context, announcer, on_close = self.make_context()

        tool.open_menu(context)
        tool.open_menu(context)

        factory.assert_called_once()
        self.assertEqual(factory.call_args.args, ("ROOT",))
        kwargs = factory.call_args.kwargs
        self.assertIs(kwargs["config"], tool.config)
        self.assertIs(kwargs["catalog"], tool.catalog)
        self.assertIs(kwargs["engine"], tool.engine)
        self.assertIs(kwargs["store"], tool.store)
        self.assertTrue(kwargs["announcements_available"])
        self.assertTrue(kwargs["announce"]("Find the letter A.", Mock()))
        announcer.speak.assert_called_once()

        kwargs["on_close"]()
        kwargs["on_close"]()

        announcer.cancel.assert_called_once_with()
        on_close.assert_called_once_with()

    def test_default_store_root_is_anchored_to_the_project(self) -> None:
        tool = LearningTool(LearningConfig(), engine=Mock())

        self.assertEqual(
            tool.store.data_directory,
            Path(__file__).resolve().parents[1] / "bmo" / "data" / "learning",
        )

    def test_speech_setting_visibly_disables_announcements(self) -> None:
        tool, factory = self.make_tool(speech_enabled=False)
        context, announcer, _ = self.make_context()

        tool.open_menu(context)

        kwargs = factory.call_args.kwargs
        self.assertFalse(kwargs["announcements_available"])
        self.assertFalse(kwargs["announce"]("Visual lesson stays usable", None))
        announcer.speak.assert_not_called()

    def test_missing_optional_face_and_speech_providers_keep_core_ui_available(self) -> None:
        tool, factory = self.make_tool()
        on_close = Mock()
        context = FeatureMenuContext(master="ROOT", on_close=on_close)

        tool.open_menu(context)

        kwargs = factory.call_args.kwargs
        self.assertFalse(kwargs["announcements_available"])
        self.assertFalse(kwargs["announce"]("Visual lesson stays usable", None))
        self.assertIsNone(kwargs["face_provider"]())
        kwargs["on_close"]()
        on_close.assert_called_once_with()

    def test_factory_failure_cancels_scope_and_reveals_menu(self) -> None:
        tool, factory = self.make_tool()
        factory.side_effect = RuntimeError("view failed")
        context, announcer, on_close = self.make_context()

        with self.assertRaisesRegex(RuntimeError, "view failed"):
            tool.open_menu(context)

        announcer.cancel.assert_called_once_with()
        on_close.assert_called_once_with()
        self.assertIsNone(tool._menu_ui)

    def test_close_is_idempotent(self) -> None:
        tool, factory = self.make_tool()
        context, _, _ = self.make_context()
        tool.open_menu(context)
        app = factory.return_value

        tool.close()
        tool.close()

        app.close.assert_called_once_with()


class LearningViewModelTests(unittest.TestCase):
    def test_ordering_builds_an_ordered_response_and_truncates_on_retap(self) -> None:
        controller = InteractionController(
            QuestionSnapshot(
                interaction="ordered_sequence",
                choices=(ChoiceSnapshot("a", "A"), ChoiceSnapshot("b", "B")),
                requires_submit=True,
                categories=(),
            )
        )

        controller.choose("b")
        controller.choose("a")
        self.assertTrue(controller.submit_ready)
        self.assertEqual(controller.response(), ("b", "a"))

        controller.choose("b")
        self.assertFalse(controller.submit_ready)
        self.assertEqual(controller.response(), ())

    def test_category_sorting_cycles_assignments_and_requires_every_choice(self) -> None:
        controller = InteractionController(
            QuestionSnapshot(
                interaction="category_sorting",
                choices=(ChoiceSnapshot("cat", "Cat"), ChoiceSnapshot("car", "Car")),
                requires_submit=True,
                categories=("animal", "vehicle"),
            )
        )

        controller.choose("cat")
        controller.choose("car")
        controller.choose("car")

        self.assertTrue(controller.submit_ready)
        self.assertEqual(
            controller.response(),
            {"cat": "animal", "car": "vehicle"},
        )


if __name__ == "__main__":
    unittest.main()
