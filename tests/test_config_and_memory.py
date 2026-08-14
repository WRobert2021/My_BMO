import json
import tempfile
import unittest
from pathlib import Path

from bmo.config import (
    DEFAULT_CONFIG,
    FEATURES_CONFIG_FILE,
    QUIET_HOURS_CONFIG_FILE,
    SETTINGS_CONFIG_FILE,
    WEATHER_CONFIG_FILE,
    load_config,
)
from bmo.memory import load_chat_history, save_chat_history
from bmo.prompts import BASE_SYSTEM_PROMPT, build_system_prompt


class ConfigTests(unittest.TestCase):
    def test_default_paths_use_split_config_directory(self):
        self.assertEqual(SETTINGS_CONFIG_FILE, Path("config/settings.json"))
        self.assertEqual(FEATURES_CONFIG_FILE, Path("config/features.json"))
        self.assertEqual(WEATHER_CONFIG_FILE, Path("config/weather.json"))
        self.assertEqual(
            QUIET_HOURS_CONFIG_FILE,
            Path("config/quiet_hours.json"),
        )

    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(Path(temp_dir) / "missing.json")
        self.assertEqual(config["text_model"], DEFAULT_CONFIG["text_model"])
        self.assertEqual(config["text_model"], "gemma3:1b")
        self.assertIn("whisper_binary", config)
        self.assertEqual(config["game_answer_wait_seconds"], 12)
        self.assertTrue(config["interaction_logging"])
        self.assertEqual(config["interaction_log_directory"], "interaction_logs")

    def test_user_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(json.dumps({"text_model": "gemma:2b"}), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config["text_model"], "gemma:2b")
        self.assertEqual(config["vision_model"], DEFAULT_CONFIG["vision_model"])

    def test_custom_settings_resolve_weather_config_beside_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")

            config = load_config(settings_path)

        self.assertEqual(
            config["weather_config_path"],
            settings_path.with_name("weather.json"),
        )
        self.assertEqual(
            config["quiet_hours_config_path"],
            settings_path.with_name("quiet_hours.json"),
        )

    def test_feature_config_is_merged_with_user_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            settings_path = directory / "settings.json"
            features_path = directory / "features.json"
            settings_path.write_text(
                json.dumps({"text_model": "gemma:2b"}),
                encoding="utf-8",
            )
            features = [{"module": "tests.example", "enabled": False}]
            modes = [{"module": "tests.example_mode", "enabled": False}]
            features_path.write_text(
                json.dumps({"features": features, "modes": modes}),
                encoding="utf-8",
            )

            config = load_config(settings_path, features_path)

        self.assertEqual(config["text_model"], "gemma:2b")
        self.assertEqual(config["features"], features)
        self.assertEqual(config["modes"], modes)

    def test_invalid_settings_do_not_prevent_feature_config_loading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            settings_path = directory / "settings.json"
            features_path = directory / "features.json"
            settings_path.write_text("[]", encoding="utf-8")
            features_path.write_text(
                json.dumps({"features": []}),
                encoding="utf-8",
            )

            config = load_config(settings_path, features_path)

        self.assertEqual(config["text_model"], DEFAULT_CONFIG["text_model"])
        self.assertEqual(config["features"], [])

    def test_extension_lists_are_rejected_from_user_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            settings_path = directory / "settings.json"
            features_path = directory / "features.json"
            settings_path.write_text(
                json.dumps({"text_model": "gemma:2b", "features": []}),
                encoding="utf-8",
            )
            features_path.write_text(
                json.dumps({"modes": []}),
                encoding="utf-8",
            )

            config = load_config(settings_path, features_path)

        self.assertEqual(config["text_model"], DEFAULT_CONFIG["text_model"])
        self.assertNotIn("features", config)
        self.assertEqual(config["modes"], [])

    def test_user_settings_are_rejected_from_feature_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            settings_path = directory / "settings.json"
            features_path = directory / "features.json"
            settings_path.write_text(
                json.dumps({"text_model": "gemma:2b"}),
                encoding="utf-8",
            )
            features_path.write_text(
                json.dumps({"features": [], "voice_model": "other.onnx"}),
                encoding="utf-8",
            )

            config = load_config(settings_path, features_path)

        self.assertEqual(config["text_model"], "gemma:2b")
        self.assertEqual(config["voice_model"], DEFAULT_CONFIG["voice_model"])
        self.assertNotIn("features", config)

    def test_explicit_prompt_and_extras_are_combined(self):
        prompt = build_system_prompt(
            {"system_prompt": "Base", "system_prompt_extras": "Extra"}
        )
        self.assertTrue(prompt.startswith("Base\n\nCAPABILITIES:"))
        self.assertIn("get_time", prompt)
        self.assertTrue(prompt.endswith("\n\nExtra"))

    def test_default_prompt_is_used_when_override_missing(self):
        prompt = build_system_prompt({})
        self.assertTrue(prompt.startswith(BASE_SYSTEM_PROMPT.strip()))
        self.assertIn("CAPABILITIES:", prompt)
        self.assertIn("capture_image", prompt)


class MemoryTests(unittest.TestCase):
    def test_missing_memory_starts_with_system_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            history = load_chat_history(path, "system")
        self.assertEqual(history, [{"role": "system", "content": "system"}])

    def test_save_limits_conversation_and_reloads(self):
        permanent = [{"role": "system", "content": "system"}]
        session = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": str(index)}
            for index in range(14)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            save_chat_history(path, permanent, session, max_conversation_messages=10)
            history = load_chat_history(path, "other")
        self.assertEqual(len(history), 11)
        self.assertEqual(
            history[0],
            {"role": "system", "content": "other"},
        )
        self.assertEqual(history[1]["content"], "4")

    def test_load_replaces_stale_system_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            path.write_text(
                json.dumps(
                    [
                        {"role": "system", "content": "old tools"},
                        {"role": "user", "content": "Hello"},
                    ]
                ),
                encoding="utf-8",
            )

            history = load_chat_history(path, "current tools")

        self.assertEqual(
            history[0],
            {"role": "system", "content": "current tools"},
        )
        self.assertEqual(history[1]["content"], "Hello")

    def test_malformed_message_records_are_not_returned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            path.write_text(
                '[{"role":"user","content":"ok"},42]',
                encoding="utf-8",
            )

            history = load_chat_history(path, "safe system")

        self.assertEqual(
            history,
            [{"role": "system", "content": "safe system"}],
        )

    def test_unhashable_message_role_is_treated_as_malformed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            path.write_text(
                '[{"role":[],"content":"not safe"}]',
                encoding="utf-8",
            )

            history = load_chat_history(path, "safe system")

        self.assertEqual(
            history,
            [{"role": "system", "content": "safe system"}],
        )

    def test_zero_limit_persists_only_the_system_message(self):
        permanent = [{"role": "system", "content": "system"}]
        session = [{"role": "user", "content": "discard me"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            save_chat_history(
                path,
                permanent,
                session,
                max_conversation_messages=0,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(saved, permanent)

    def test_save_rejects_invalid_limits_and_messages(self):
        permanent = [{"role": "system", "content": "system"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            for invalid in (-1, True, 1.5):
                with self.subTest(limit=invalid), self.assertRaises(ValueError):
                    save_chat_history(
                        path,
                        permanent,
                        [],
                        max_conversation_messages=invalid,  # type: ignore[arg-type]
                    )
            with self.assertRaisesRegex(ValueError, "invalid message"):
                save_chat_history(
                    path,
                    permanent,
                    [{"role": "user", "content": 3}],  # type: ignore[dict-item]
                )

    def test_save_requires_the_system_message_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"

            with self.assertRaisesRegex(ValueError, "begin with a system"):
                save_chat_history(
                    path,
                    [{"role": "user", "content": "hello"}],
                    [],
                )

            self.assertFalse(path.exists())

    def test_later_system_messages_are_rejected_on_load_and_save(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "injected"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory.json"
            path.write_text(json.dumps(messages), encoding="utf-8")

            self.assertEqual(
                load_chat_history(path, "safe system"),
                [{"role": "system", "content": "safe system"}],
            )
            with self.assertRaisesRegex(ValueError, "later system"):
                save_chat_history(path, messages, [])


if __name__ == "__main__":
    unittest.main()
