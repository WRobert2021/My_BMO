"""Coverage for configuration-driven feature loading and prompts."""

from __future__ import annotations

import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from bmo.features import ToolContract, ToolRegistry, ToolResult
from bmo.features.loader import load_feature_registry
from bmo.prompts import build_routing_prompt, build_system_prompt
from bmo.tools import ToolRouter


class ResourceTool:
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def __init__(
        self,
        action: str,
        *,
        aliases: tuple[str, ...] = (),
        close_events: list[str] | None = None,
        fail_on_close: bool = False,
    ) -> None:
        self.action = action
        self.aliases = aliases
        self.close_events = close_events
        self.fail_on_close = fail_on_close
        self.close_count = 0

    def execute(self, request) -> ToolResult:
        del request
        return ToolResult.success(self.action)

    def match_direct_action(self, user_text: str):
        del user_text
        return None

    def close(self) -> None:
        self.close_count += 1
        if self.close_events is not None:
            self.close_events.append(self.action)
        if self.fail_on_close:
            raise RuntimeError("close exploded")


class FeatureLoadingTests(unittest.TestCase):
    def test_absent_features_setting_loads_every_current_capability(self) -> None:
        result = load_feature_registry({})

        self.assertEqual(
            result.registry.actions,
            {
                "get_time",
                "set_timer",
                "get_location",
                "get_weather",
                "search_web",
                "capture_image",
            },
        )
        self.assertEqual(result.failures, ())
        self.assertIn("bmo.features.album", result.modules)
        self.assertIn(
            "album",
            {item.name for item in result.registry.menu_items},
        )

    def test_disabled_entry_is_not_imported_or_registered(self) -> None:
        config = {
            "features": [
                {
                    "module": "disabled.module",
                    "enabled": False,
                    "settings": "not validated for disabled entries",
                }
            ]
        }

        with patch("bmo.features.loader._load_module") as load_module:
            result = load_feature_registry(config)

        load_module.assert_not_called()
        self.assertEqual(result.registry.actions, set())
        self.assertEqual(result.failures, ())

    def test_explicit_list_can_disable_a_default_capability(self) -> None:
        router = ToolRouter(
            {
                "features": [
                    {
                        "module": "bmo.features.get_time",
                        "enabled": False,
                        "settings": {},
                    },
                    {
                        "module": "bmo.features.capture_image",
                        "enabled": True,
                        "settings": {},
                    },
                ]
            }
        )

        self.assertEqual(router.VALID_TOOLS, {"capture_image"})
        self.assertIsNone(router.match_direct_action("What time is it?"))
        self.assertEqual(
            router.match_direct_action("Take a picture."),
            {"action": "capture_image"},
        )

    def test_invalid_enabled_module_is_reported_and_loading_continues(self) -> None:
        messages = []
        config = {
            "features": [
                {
                    "module": "does.not.exist",
                    "enabled": True,
                    "settings": {},
                },
                {
                    "module": "bmo.features.get_time",
                    "enabled": True,
                    "settings": {},
                },
            ]
        }

        result = load_feature_registry(config, reporter=messages.append)

        self.assertEqual(result.registry.actions, {"get_time"})
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "import")
        self.assertIn("does.not.exist", messages[0])

    def test_duplicate_registration_is_rolled_back_and_reported(self) -> None:
        first = types.ModuleType("first")
        duplicate = types.ModuleType("duplicate")
        after = types.ModuleType("after")
        close_events: list[str] = []
        partial = ResourceTool(
            "partial",
            aliases=("partial_alias",),
            close_events=close_events,
        )
        later_partial = ResourceTool(
            "later_partial",
            aliases=("later_alias",),
            close_events=close_events,
        )

        def register_first(registry, settings):
            del settings
            registry.register(
                ToolContract(
                    "alpha",
                    lambda request: ToolResult.success("alpha"),
                    aliases=("alpha_alias",),
                )
            )

        def register_duplicate(registry, settings):
            del settings
            registry.register(partial)
            registry.register(later_partial)
            registry.register(
                ToolContract(
                    "alpha",
                    lambda request: ToolResult.success("duplicate"),
                )
            )

        def register_after(registry, settings):
            del settings
            registry.register(
                ToolContract(
                    "beta",
                    lambda request: ToolResult.success("beta"),
                    aliases=("beta_alias",),
                )
            )

        first.register = register_first
        duplicate.register = register_duplicate
        after.register = register_after
        modules = {"first": first, "duplicate": duplicate, "after": after}
        messages = []

        with patch(
            "bmo.features.loader._load_module",
            side_effect=modules.__getitem__,
        ):
            result = load_feature_registry(
                {
                    "features": [
                        {"module": name, "enabled": True, "settings": {}}
                        for name in modules
                    ]
                },
                reporter=messages.append,
            )

        self.assertEqual(result.registry.actions, {"alpha", "beta"})
        self.assertNotIn("partial", result.registry.actions)
        self.assertNotIn("partial_alias", result.registry.aliases)
        self.assertNotIn("later_partial", result.registry.actions)
        self.assertNotIn("later_alias", result.registry.aliases)
        self.assertEqual(
            result.registry.aliases,
            {"alpha_alias": "alpha", "beta_alias": "beta"},
        )
        self.assertEqual(close_events, ["later_partial", "partial"])
        self.assertEqual(partial.close_count, 1)
        self.assertEqual(later_partial.close_count, 1)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "register")
        self.assertEqual(result.modules, ("first", "after"))
        self.assertIn("Duplicate tool action name 'alpha'", messages[0])

        result.registry.close()

        self.assertEqual(partial.close_count, 1)
        self.assertEqual(later_partial.close_count, 1)

    def test_rollback_close_failure_does_not_mask_registration_failure(
        self,
    ) -> None:
        existing = ResourceTool("existing", aliases=("existing_alias",))
        partial = ResourceTool(
            "partial",
            aliases=("partial_alias",),
            fail_on_close=True,
        )
        registry = ToolRegistry((existing,))
        registration_failure = RuntimeError("registration exploded")

        output = StringIO()
        with redirect_stdout(output), self.assertRaises(RuntimeError) as raised:
            with registry.registration():
                registry.register(partial)
                raise registration_failure

        self.assertIs(raised.exception, registration_failure)
        self.assertEqual(registry.actions, {"existing"})
        self.assertEqual(registry.aliases, {"existing_alias": "existing"})
        self.assertEqual(existing.close_count, 0)
        self.assertEqual(partial.close_count, 1)
        self.assertIn("Could not roll back 'partial'", output.getvalue())
        self.assertIn("close exploded", output.getvalue())

        registry.close()

        self.assertEqual(existing.close_count, 1)
        self.assertEqual(partial.close_count, 1)

    def test_settings_are_passed_to_the_module_registration_hook(self) -> None:
        module = types.ModuleType("configured")
        received = []

        def register(registry, settings):
            received.append(dict(settings))
            registry.register(
                ToolContract(
                    "configured",
                    lambda request: ToolResult.success("ok"),
                )
            )

        module.register = register
        with patch("bmo.features.loader._load_module", return_value=module):
            result = load_feature_registry(
                {
                    "features": [
                        {
                            "module": "configured",
                            "enabled": True,
                            "settings": {"answer": 42},
                        }
                    ]
                }
            )

        self.assertEqual(received, [{"answer": 42}])
        self.assertEqual(result.registry.actions, {"configured"})


class RegistryPromptTests(unittest.TestCase):
    def test_prompts_include_only_enabled_registry_capabilities(self) -> None:
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

        routing_prompt = build_routing_prompt(router.registry)
        assistant_prompt = build_system_prompt(
            {
                "system_prompt": "Custom identity.",
                "system_prompt_extras": "Stay concise.",
            },
            router.registry,
        )

        for prompt in (routing_prompt, assistant_prompt):
            self.assertIn("get_time", prompt)
            self.assertNotIn("get_weather", prompt)
            self.assertNotIn("search_web", prompt)
            self.assertNotIn("capture_image", prompt)
        self.assertTrue(assistant_prompt.startswith("Custom identity."))
        self.assertTrue(assistant_prompt.endswith("Stay concise."))


if __name__ == "__main__":
    unittest.main()
