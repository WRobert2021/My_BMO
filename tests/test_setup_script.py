"""Static contract tests for the Raspberry Pi setup script."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from bmo.config import DEFAULT_CONFIG


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPOSITORY_ROOT / "setup.sh"


class SetupScriptTests(unittest.TestCase):
    def test_setup_script_has_valid_bash_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SETUP_SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_whisper_artifacts_match_runtime_defaults(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")

        binary_match = re.search(
            r'^WHISPER_BINARY_RELATIVE="([^"]+)"$', script, re.MULTILINE
        )
        model_match = re.search(
            r'^WHISPER_MODEL_RELATIVE="([^"]+)"$', script, re.MULTILINE
        )

        self.assertIsNotNone(binary_match)
        self.assertIsNotNone(model_match)
        self.assertEqual(binary_match.group(1), DEFAULT_CONFIG["whisper_binary"])
        self.assertEqual(model_match.group(1), DEFAULT_CONFIG["whisper_model"])

    def test_whisper_setup_clones_builds_downloads_and_verifies(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('WHISPER_CPP_VERSION="${WHISPER_CPP_VERSION:-v1.9.2}"', script)
        self.assertIn('git clone --depth 1 --branch "$WHISPER_CPP_VERSION"', script)
        self.assertIn('cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build"', script)
        self.assertIn('cmake --build "$WHISPER_DIR/build"', script)
        self.assertIn(
            'sh "$WHISPER_DIR/models/download-ggml-model.sh" base.en', script
        )
        self.assertIn('[ ! -x "$WHISPER_BINARY" ]', script)
        self.assertIn('[ ! -s "$WHISPER_MODEL" ]', script)


if __name__ == "__main__":
    unittest.main()
