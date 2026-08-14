"""Configuration and integration tests for interaction-mode loading."""

from __future__ import annotations

import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

from bmo.app import BotGUI
from bmo.modes import InputPolicy, InputPolicyKind, ModeRuntimeContext
from bmo.modes.loader import DEFAULT_MODE_MODULES, load_mode_registry


class ConfigurableStubMode:
    def __init__(self, name: str, start_phrase: str) -> None:
        self.name = name
        self.start_phrase = start_phrase
        self.active = False
        self.started_with: list[str] = []
        self.inputs: list[str] = []
        self.close_count = 0

    def matches_start_request(self, user_text: str) -> bool:
        return user_text == self.start_phrase

    def start(self, user_text: str) -> None:
        self.started_with.append(user_text)
        self.active = True

    def handle_input(self, user_text: str) -> None:
        self.inputs.append(user_text)
        if user_text == "done":
            self.active = False

    def is_active(self) -> bool:
        return self.active

    def input_policy(self) -> InputPolicy:
        return InputPolicy.continuous(
            initial_silence_timeout=9,
            listening_status="Listening",
            no_speech_status="Again",
            empty_transcript_status="Repeat",
        )

    def close(self) -> None:
        self.close_count += 1
        self.active = False


def make_context() -> ModeRuntimeContext:
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


def make_module(name: str, register) -> types.ModuleType:
    module = types.ModuleType(name)
    module.register = register
    return module


class ModeLoadingTests(unittest.TestCase):
    def test_missing_modes_loads_both_legacy_defaults_in_original_order(self) -> None:
        context = make_context()

        result = load_mode_registry(
            {},
            context=context,
            shared_settings={
                "game_answer_wait_seconds": 17.5,
                "twenty_questions_debug": True,
            },
        )

        self.assertEqual(result.modules, DEFAULT_MODE_MODULES)
        self.assertEqual(
            result.registry.names,
            ("matching_game", "twenty_questions"),
        )
        self.assertEqual(result.failures, ())
        twenty_questions = result.registry.get("twenty_questions")
        self.assertIsNotNone(twenty_questions)
        self.assertTrue(twenty_questions.game.debug)
        self.assertEqual(
            twenty_questions.input_policy().initial_silence_timeout,
            17.5,
        )

    def test_present_empty_modes_list_disables_every_mode(self) -> None:
        with patch("bmo.modes.loader._load_module") as load_module:
            result = load_mode_registry(
                {"modes": []},
                context=make_context(),
            )

        load_module.assert_not_called()
        self.assertEqual(result.registry.names, ())
        self.assertEqual(result.modules, ())
        self.assertEqual(
            result.registry.input_policy().kind,
            InputPolicyKind.WAKE_WORD,
        )
        self.assertEqual(result.registry.menu_items, ())

    def test_matching_game_menu_item_can_be_hidden_by_mode_settings(self) -> None:
        result = load_mode_registry(
            {
                "modes": [
                    {
                        "module": "bmo.modes.matching_game",
                        "settings": {"show_in_menu": False},
                    }
                ]
            },
            context=make_context(),
        )

        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.names, ("matching_game",))
        self.assertEqual(result.registry.menu_items, ())

    def test_twenty_questions_menu_item_is_visible_by_default(self) -> None:
        result = load_mode_registry(
            {
                "modes": [
                    {
                        "module": "bmo.modes.twenty_questions",
                        "settings": {},
                    }
                ]
            },
            context=make_context(),
        )
        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.menu_items[0].name, "twenty_questions")
        self.assertEqual(result.registry.menu_items[0].label, "20 Questions")
        self.assertEqual(
            result.registry.menu_items[0].icon_path.parts[-3:],
            ("graphics", "icons", "20_questions.png"),
        )

    def test_twenty_questions_menu_can_be_hidden_without_disabling_voice(self) -> None:
        result = load_mode_registry(
            {
                "modes": [
                    {
                        "module": "bmo.modes.twenty_questions",
                        "settings": {"show_in_menu": False},
                    }
                ]
            },
            context=make_context(),
        )
        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.menu_items, ())
        self.assertIsNotNone(result.registry.match_start_request("Start 20 questions"))

    def test_invalid_twenty_questions_menu_setting_is_isolated(self) -> None:
        result = load_mode_registry(
            {
                "modes": [
                    {
                        "module": "bmo.modes.twenty_questions",
                        "settings": {"show_in_menu": "false"},
                    }
                ]
            },
            context=make_context(),
        )
        self.assertEqual(result.registry.names, ())
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "register")

    def test_twenty_questions_rejects_history_path_collisions(self) -> None:
        result = load_mode_registry(
            {
                "modes": [
                    {
                        "module": "bmo.modes.twenty_questions",
                        "settings": {
                            "data_path": "data/20_questions/data.jsonl",
                            "learned_path": "data/20_questions/learned.jsonl",
                            "history_path": "data/20_questions/data.jsonl",
                        },
                    }
                ]
            },
            context=make_context(),
        )

        self.assertEqual(result.registry.names, ())
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "register")
        self.assertIn("history_path", result.failures[0].error)

    def test_malformed_modes_list_reports_configuration_failure(self) -> None:
        result = load_mode_registry(
            {"modes": {"module": "not-a-list"}},
            context=make_context(),
            reporter=Mock(),
        )

        self.assertEqual(result.registry.names, ())
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "configure")

    def test_disabled_entry_is_not_validated_or_imported(self) -> None:
        valid_mode = ConfigurableStubMode("valid", "start valid")

        def register_valid(registry, context, settings):
            del context, settings
            registry.register(valid_mode)

        valid_module = make_module("valid", register_valid)
        with patch(
            "bmo.modes.loader._load_module",
            return_value=valid_module,
        ) as load_module:
            result = load_mode_registry(
                {
                    "modes": [
                        {
                            "module": "disabled.and.missing",
                            "enabled": False,
                            "settings": "not an object",
                        },
                        {
                            "module": "valid",
                            "enabled": True,
                            "settings": {},
                        },
                    ]
                },
                context=make_context(),
            )

        load_module.assert_called_once_with("valid")
        self.assertEqual(result.registry.names, ("valid",))
        self.assertEqual(result.failures, ())

    def test_invalid_entries_and_modules_do_not_block_later_modes(self) -> None:
        no_hook = types.ModuleType("no_hook")
        def register_broken(registry, context, settings):
            del registry, context, settings
            raise RuntimeError("registration exploded")

        broken = make_module("broken", register_broken)
        valid_mode = ConfigurableStubMode("valid", "start valid")

        def register_valid(registry, context, settings):
            del context, settings
            registry.register(valid_mode)

        valid = make_module("valid", register_valid)
        modules = {"no_hook": no_hook, "broken": broken, "valid": valid}

        def load_module(name: str):
            if name == "missing":
                raise ModuleNotFoundError("missing")
            return modules[name]

        messages: list[str] = []
        with patch("bmo.modes.loader._load_module", side_effect=load_module):
            result = load_mode_registry(
                {
                    "modes": [
                        "not an object",
                        {"module": "ignored", "enabled": "yes"},
                        {"module": "", "enabled": True},
                        {
                            "module": "bad-settings",
                            "settings": "nope",
                        },
                        {"module": "missing"},
                        {"module": "no_hook"},
                        {"module": "broken"},
                        {"module": "valid"},
                    ]
                },
                context=make_context(),
                reporter=messages.append,
            )

        self.assertEqual(result.registry.names, ("valid",))
        self.assertEqual(
            [failure.stage for failure in result.failures],
            [
                "configure",
                "configure",
                "configure",
                "configure",
                "import",
                "register",
                "register",
            ],
        )
        self.assertEqual(len(messages), 7)

    def test_duplicate_name_failure_is_transactional_and_later_modes_load(
        self,
    ) -> None:
        alpha = ConfigurableStubMode("alpha", "start alpha")
        partial = ConfigurableStubMode("partial", "start partial")
        duplicate_alpha = ConfigurableStubMode("alpha", "duplicate alpha")
        beta = ConfigurableStubMode("beta", "start beta")

        def register_first(registry, context, settings):
            del context, settings
            registry.register(alpha)

        def register_duplicate(registry, context, settings):
            del context, settings
            registry.register(partial)
            registry.register(duplicate_alpha)

        def register_after(registry, context, settings):
            del context, settings
            registry.register(beta)

        modules = {
            "first": make_module("first", register_first),
            "duplicate": make_module("duplicate", register_duplicate),
            "after": make_module("after", register_after),
        }
        with patch(
            "bmo.modes.loader._load_module",
            side_effect=modules.__getitem__,
        ):
            result = load_mode_registry(
                {
                    "modes": [
                        {"module": name, "enabled": True, "settings": {}}
                        for name in modules
                    ]
                },
                context=make_context(),
            )

        self.assertEqual(result.registry.names, ("alpha", "beta"))
        self.assertEqual(result.modules, ("first", "after"))
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "register")
        self.assertIn("Duplicate mode name 'alpha'", result.failures[0].error)
        self.assertEqual(partial.close_count, 1)
        self.assertEqual(duplicate_alpha.close_count, 1)

    def test_context_and_merged_settings_reach_registration_hook(self) -> None:
        context = make_context()
        mode = ConfigurableStubMode("configured", "start configured")
        received: list[tuple[ModeRuntimeContext, dict[str, object]]] = []

        def register(registry, runtime_context, settings):
            received.append((runtime_context, dict(settings)))
            registry.register(mode)

        module = make_module("configured", register)
        with patch("bmo.modes.loader._load_module", return_value=module):
            result = load_mode_registry(
                {
                    "modes": [
                        {
                            "module": "configured",
                            "settings": {"answer": 42},
                        }
                    ]
                },
                context=context,
                shared_settings={"answer": 1, "shared": True},
            )

        self.assertEqual(
            received,
            [(context, {"answer": 42, "shared": True})],
        )
        self.assertEqual(result.registry.names, ("configured",))

    def test_enabled_mode_routes_before_prompt_driven_tool_inference(self) -> None:
        mode = ConfigurableStubMode("prompt_mode", "start prompt mode")

        def register(registry, context, settings):
            del context, settings
            registry.register(mode)

        module = make_module("prompt_mode", register)
        with patch("bmo.modes.loader._load_module", return_value=module):
            result = load_mode_registry(
                {"modes": [{"module": "prompt_mode"}]},
                context=make_context(),
            )

        gui = BotGUI.__new__(BotGUI)
        gui.mode_registry = result.registry
        gui.tool_router = Mock()

        gui.chat_and_respond("start prompt mode")

        self.assertEqual(mode.started_with, ["start prompt mode"])
        gui.tool_router.match_direct_action.assert_not_called()

    def test_bot_gui_module_does_not_import_concrete_game_modes(self) -> None:
        import bmo.app as app_module

        self.assertNotIn("MatchingGameMode", app_module.__dict__)
        self.assertNotIn("TwentyQuestionsMode", app_module.__dict__)
        self.assertNotIn("TwentyQuestionsGame", app_module.__dict__)

    def test_builtin_modules_do_not_import_disabled_game_engine(self) -> None:
        scenarios = (
            (
                "bmo.modes.matching_game",
                "bmo.modes.twenty_questions",
                "bmo.twenty_questions",
            ),
            (
                "bmo.modes.twenty_questions",
                "bmo.modes.matching_game",
                "bmo.matching_game",
            ),
        )
        for enabled_module, disabled_module, disabled_engine in scenarios:
            with self.subTest(enabled_module=enabled_module):
                script = f"""
import sys
from bmo.modes import ModeRuntimeContext, load_mode_registry

context = ModeRuntimeContext(
    master=object(),
    text_model="test-model",
    chat=lambda **kwargs: None,
    speak_response=lambda text, image: None,
    remember_turn=lambda user, response: None,
    wait_for_tts=lambda: None,
    set_state=lambda state, message: None,
    announce=lambda message: None,
    face_provider=lambda: None,
)
result = load_mode_registry(
    {{"modes": [
        {{"module": "{disabled_module}", "enabled": False}},
        {{"module": "{enabled_module}", "enabled": True}},
    ]}},
    context=context,
)
assert result.failures == ()
assert "{disabled_module}" not in sys.modules
assert "{disabled_engine}" not in sys.modules
"""
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stdout + completed.stderr,
                )


if __name__ == "__main__":
    unittest.main()
