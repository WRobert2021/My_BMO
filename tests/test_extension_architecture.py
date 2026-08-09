"""End-to-end proof that extensions need configuration, not core edits."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from bmo.app import BotGUI
from bmo.features import ToolPresentationKind, ToolResultKind
from bmo.features.loader import (
    DEFAULT_FEATURE_MODULES,
    load_feature_registry,
)
from bmo.intent import infer_tool_action
from bmo.modes import InputPolicyKind, ModeRuntimeContext
from bmo.modes.loader import DEFAULT_MODE_MODULES, load_mode_registry
from bmo.prompts import build_routing_prompt, build_system_prompt
from bmo.tools import ToolRouter


FEATURE_MODULE = "tests.extension_modules.proof_feature"
MODE_MODULE = "tests.extension_modules.proof_mode"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_mode_context() -> ModeRuntimeContext:
    return ModeRuntimeContext(
        master=Mock(),
        text_model="test-model",
        chat=Mock(),
        speak_response=Mock(),
        remember_turn=Mock(),
        wait_for_tts=Mock(),
        set_state=Mock(),
        announce=Mock(),
        face_provider=Mock(return_value=None),
    )


def make_presentation_gui() -> BotGUI:
    gui = BotGUI.__new__(BotGUI)
    gui.set_state = Mock()
    gui.thinking_sound_active = Mock()
    gui._logged_chat = Mock()
    gui._speak_complete_response = Mock()
    gui._remember_turn = Mock()
    return gui


class ConfigurationOnlyFeatureTests(unittest.TestCase):
    def test_importable_feature_runs_end_to_end_from_one_config_entry(
        self,
    ) -> None:
        config = {
            "system_prompt": "Test assistant.",
            "features": [
                {
                    "module": FEATURE_MODULE,
                    "enabled": True,
                    "settings": {
                        "direct_phrase": "computer repeat",
                        "response_prefix": "Configured response",
                        "error_text": "The configured extension expectedly failed.",
                        "failure_token": "expected failure",
                        "max_repeat": 2,
                    },
                }
            ],
        }
        router = ToolRouter(config)
        self.addCleanup(router.close)

        self.assertEqual(router.feature_modules, (FEATURE_MODULE,))
        self.assertEqual(router.feature_failures, ())
        self.assertEqual(router.VALID_TOOLS, {"configured_echo"})
        self.assertEqual(
            router.ALIASES,
            {"echo_extension": "configured_echo"},
        )
        for prompt in (
            build_routing_prompt(router.registry),
            build_system_prompt(config, router.registry),
        ):
            self.assertIn("configured_echo", prompt)
            self.assertIn("numeric repeat", prompt)

        direct_request = router.match_direct_action(
            "Computer repeat bright signal!"
        )
        self.assertEqual(
            direct_request,
            {
                "action": "configured_echo",
                "message": "bright signal",
                "repeat": "1",
            },
        )
        direct_result = router.execute(direct_request)
        self.assertEqual(direct_result.kind, ToolResultKind.CONTENT)
        self.assertEqual(
            direct_result.content,
            "Configured response: bright signal",
        )
        self.assertEqual(
            direct_result.presentation.kind,
            ToolPresentationKind.DIRECT,
        )

        gui = make_presentation_gui()
        gui._process_tool_result(
            "Computer repeat bright signal!",
            direct_result,
            image_path=None,
            model_to_use="test-model",
            direct=True,
        )
        gui._logged_chat.assert_not_called()
        gui._speak_complete_response.assert_called_once_with(
            "Configured response: bright signal",
            None,
        )

        captured_request = {}

        def model_route(**kwargs):
            captured_request.update(kwargs)
            return {
                "message": {
                    "content": (
                        '{"action":"echo_extension",'
                        '"message":"  Model signal  ","repeat":2.0}'
                    )
                }
            }

        model_request = infer_tool_action(
            "test-model",
            "Repeat model signal twice.",
            model_route,
            router,
        )
        self.assertEqual(
            model_request,
            {
                "action": "configured_echo",
                "message": "Model signal",
                "repeat": 2,
            },
        )
        self.assertIn(
            '"message":"text","repeat":2',
            captured_request["messages"][0]["content"],
        )
        self.assertEqual(
            router.execute(model_request).content,
            "Configured response: Model signal | Model signal",
        )

        expected_error = router.execute(
            {
                "action": "echo_extension",
                "message": " expected   failure ",
                "repeat": 1,
            }
        )
        self.assertEqual(expected_error.kind, ToolResultKind.ERROR)
        self.assertEqual(
            expected_error.presentation.user_text,
            "The configured extension expectedly failed.",
        )

        tool = router.registry.get("configured_echo")
        self.assertIsNotNone(tool)
        router.close()
        router.close()
        self.assertEqual(tool.close_count, 1)

    def test_disabled_feature_entry_removes_every_integration_surface(
        self,
    ) -> None:
        router = ToolRouter(
            {
                "features": [
                    {
                        "module": FEATURE_MODULE,
                        "enabled": False,
                        "settings": "disabled settings are ignored",
                    }
                ]
            }
        )
        self.addCleanup(router.close)

        self.assertEqual(router.feature_modules, ())
        self.assertEqual(router.feature_failures, ())
        self.assertEqual(router.VALID_TOOLS, set())
        self.assertEqual(router.ALIASES, {})
        self.assertIsNone(
            router.match_direct_action("Computer repeat bright signal!")
        )
        self.assertNotIn(
            "configured_echo",
            build_routing_prompt(router.registry),
        )


class ConfigurationOnlyModeTests(unittest.TestCase):
    def test_importable_mode_is_enabled_and_disabled_by_its_config_entry(
        self,
    ) -> None:
        context = make_mode_context()
        enabled = load_mode_registry(
            {
                "modes": [
                    {
                        "module": MODE_MODULE,
                        "enabled": True,
                        "settings": {
                            "start_phrase": "enter proof mode",
                            "stop_phrase": "leave proof mode",
                            "response_text": "Configured mode started.",
                            "silence_timeout": 7.5,
                        },
                    }
                ]
            },
            context=context,
        )
        self.addCleanup(enabled.registry.close)

        self.assertEqual(enabled.modules, (MODE_MODULE,))
        self.assertEqual(enabled.failures, ())
        self.assertEqual(enabled.registry.names, ("configured_test_mode",))
        self.assertTrue(enabled.registry.route_input("enter proof mode"))
        mode = enabled.registry.get("configured_test_mode")
        self.assertIsNotNone(mode)
        self.assertEqual(mode.started_with, ["enter proof mode"])
        context.speak_response.assert_called_once_with(
            "Configured mode started.",
            None,
        )
        self.assertEqual(
            enabled.registry.input_policy().kind,
            InputPolicyKind.CONTINUOUS,
        )
        self.assertEqual(
            enabled.registry.input_policy().initial_silence_timeout,
            7.5,
        )
        self.assertTrue(enabled.registry.route_input("leave proof mode"))
        self.assertFalse(enabled.registry.is_active())
        enabled.registry.close()
        enabled.registry.close()
        self.assertEqual(mode.close_count, 1)

        disabled = load_mode_registry(
            {
                "modes": [
                    {
                        "module": MODE_MODULE,
                        "enabled": False,
                        "settings": "disabled settings are ignored",
                    }
                ]
            },
            context=make_mode_context(),
        )
        self.addCleanup(disabled.registry.close)
        self.assertEqual(disabled.modules, ())
        self.assertEqual(disabled.failures, ())
        self.assertEqual(disabled.registry.names, ())
        self.assertFalse(disabled.registry.route_input("enter proof mode"))

    def test_disabled_extension_modules_are_not_imported(self) -> None:
        script = f"""
import sys
from unittest.mock import Mock
from bmo.features.loader import load_feature_registry
from bmo.modes import ModeRuntimeContext
from bmo.modes.loader import load_mode_registry

feature_result = load_feature_registry({{"features": [{{
    "module": "{FEATURE_MODULE}",
    "enabled": False,
    "settings": "ignored",
}}]}})
context = ModeRuntimeContext(
    master=Mock(),
    text_model="test-model",
    chat=Mock(),
    speak_response=Mock(),
    remember_turn=Mock(),
    wait_for_tts=Mock(),
    set_state=Mock(),
    announce=Mock(),
    face_provider=Mock(return_value=None),
)
mode_result = load_mode_registry({{"modes": [{{
    "module": "{MODE_MODULE}",
    "enabled": False,
    "settings": "ignored",
}}]}}, context=context)
assert feature_result.failures == ()
assert mode_result.failures == ()
assert "{FEATURE_MODULE}" not in sys.modules
assert "{MODE_MODULE}" not in sys.modules
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


class ExtensionFailureIsolationTests(unittest.TestCase):
    def test_bad_extensions_do_not_block_configured_builtin_modules(
        self,
    ) -> None:
        default_features = load_feature_registry({}, reporter=Mock())
        self.addCleanup(default_features.registry.close)
        feature_entries = [
            {
                "module": FEATURE_MODULE,
                "enabled": True,
                "settings": "not an object",
            },
            {
                "module": "disabled.feature.does.not.exist",
                "enabled": False,
                "settings": "ignored",
            },
            *(
                {"module": module, "enabled": True, "settings": {}}
                for module in DEFAULT_FEATURE_MODULES
            ),
        ]
        feature_result = load_feature_registry(
            {"features": feature_entries},
            reporter=Mock(),
        )
        self.addCleanup(feature_result.registry.close)

        self.assertEqual(
            feature_result.registry.actions,
            default_features.registry.actions,
        )
        self.assertEqual(feature_result.modules, DEFAULT_FEATURE_MODULES)
        self.assertEqual(len(feature_result.failures), 1)
        self.assertEqual(feature_result.failures[0].stage, "configure")

        default_modes = load_mode_registry(
            {},
            context=make_mode_context(),
            reporter=Mock(),
        )
        self.addCleanup(default_modes.registry.close)
        mode_entries = [
            {
                "module": MODE_MODULE,
                "enabled": True,
                "settings": "not an object",
            },
            {
                "module": "disabled.mode.does.not.exist",
                "enabled": False,
                "settings": "ignored",
            },
            *(
                {"module": module, "enabled": True, "settings": {}}
                for module in DEFAULT_MODE_MODULES
            ),
        ]
        mode_result = load_mode_registry(
            {"modes": mode_entries},
            context=make_mode_context(),
            reporter=Mock(),
        )
        self.addCleanup(mode_result.registry.close)

        self.assertEqual(mode_result.registry.names, default_modes.registry.names)
        self.assertEqual(mode_result.modules, DEFAULT_MODE_MODULES)
        self.assertEqual(len(mode_result.failures), 1)
        self.assertEqual(mode_result.failures[0].stage, "configure")


class CoreCouplingAuditTests(unittest.TestCase):
    def test_core_routing_and_presentation_have_no_builtin_name_checks(
        self,
    ) -> None:
        builtin_identifiers = {
            "get_time",
            "set_timer",
            "get_location",
            "get_weather",
            "search_web",
            "capture_image",
            "matching_game",
            "twenty_questions",
        }
        core_paths = (
            PROJECT_ROOT / "bmo" / "app.py",
            PROJECT_ROOT / "bmo" / "intent.py",
            PROJECT_ROOT / "bmo" / "prompts.py",
            PROJECT_ROOT / "bmo" / "features" / "registry.py",
            PROJECT_ROOT / "bmo" / "modes" / "registry.py",
        )

        for path in core_paths:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                string_literals = {
                    node.value
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                }
                self.assertTrue(builtin_identifiers.isdisjoint(string_literals))

    def test_legacy_router_metadata_has_no_duplicated_default_constants(
        self,
    ) -> None:
        import bmo.tools as tools_module

        self.assertNotIn("_DEFAULT_ACTIONS", tools_module.__dict__)
        self.assertNotIn("_DEFAULT_ALIASES", tools_module.__dict__)
        default_router = ToolRouter({"online_timeout_seconds": 6})
        self.addCleanup(default_router.close)
        self.assertEqual(
            ToolRouter.VALID_TOOLS,
            default_router.registry.actions,
        )
        self.assertEqual(
            ToolRouter.ALIASES,
            default_router.registry.aliases,
        )


if __name__ == "__main__":
    unittest.main()
