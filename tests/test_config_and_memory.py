import json
import tempfile
import unittest
from pathlib import Path

from bmo.config import DEFAULT_CONFIG, load_config
from bmo.memory import load_chat_history, save_chat_history
from bmo.prompts import BASE_SYSTEM_PROMPT, build_system_prompt


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(Path(temp_dir) / "missing.json")
        self.assertEqual(config["text_model"], DEFAULT_CONFIG["text_model"])
        self.assertIn("whisper_binary", config)
        self.assertEqual(config["game_answer_wait_seconds"], 12)
        self.assertTrue(config["interaction_logging"])
        self.assertEqual(config["interaction_log_directory"], "interaction_logs")

    def test_user_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"text_model": "gemma:2b"}), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config["text_model"], "gemma:2b")
        self.assertEqual(config["vision_model"], DEFAULT_CONFIG["vision_model"])

    def test_explicit_prompt_and_extras_are_combined(self):
        prompt = build_system_prompt(
            {"system_prompt": "Base", "system_prompt_extras": "Extra"}
        )
        self.assertEqual(prompt, "Base\n\nExtra")

    def test_default_prompt_is_used_when_override_missing(self):
        self.assertEqual(build_system_prompt({}), BASE_SYSTEM_PROMPT.strip())


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


if __name__ == "__main__":
    unittest.main()
