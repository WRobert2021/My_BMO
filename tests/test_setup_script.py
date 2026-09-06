"""Static contract tests for the Raspberry Pi setup script."""

from __future__ import annotations

import re
import subprocess
import unittest
from json import loads
from pathlib import Path
from tempfile import TemporaryDirectory

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
        self.assertIn('"$WHISPER_MODEL_URL" "$WHISPER_MODEL" 100000000', script)
        self.assertIn('[ ! -x "$WHISPER_BINARY" ]', script)

    def test_download_helper_is_atomic_and_reuses_valid_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.bin"
            destination = directory / "destination.bin"
            source.write_bytes(b"first payload")
            command = (
                f'source "{SETUP_SCRIPT}"; '
                f'download_file "file://{source}" "{destination}" 5 fixture'
            )

            first = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(destination.read_bytes(), b"first payload")

            source.write_bytes(b"second payload")
            second = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(destination.read_bytes(), b"first payload")
            self.assertEqual(list(directory.glob("destination.bin.part.*")), [])

    def test_download_helper_rejects_small_files_without_overwriting(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.bin"
            destination = directory / "destination.bin"
            source.write_bytes(b"tiny")
            destination.write_bytes(b"old")
            command = (
                f'source "{SETUP_SCRIPT}"; '
                f'download_file "file://{source}" "{destination}" 10 fixture'
            )

            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(destination.read_bytes(), b"old")
            self.assertEqual(list(directory.glob("destination.bin.part.*")), [])

    def test_setup_installs_commands_it_uses(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")

        for package in ("ca-certificates", "curl", "python3-venv"):
            self.assertRegex(script, rf"(?m)^\s*{re.escape(package)}$", package)

    def test_setup_creates_refactored_runtime_directories(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")

        for relative_path in (
            "audio/sounds/greeting_sounds",
            "audio/sounds/thinking_sounds",
            "audio/sounds/ack_sounds",
            "audio/sounds/error_sounds",
            "graphics/faces/idle",
            "graphics/faces/listening",
            "graphics/faces/thinking",
            "graphics/faces/speaking",
            "graphics/faces/error",
            "graphics/faces/warmup",
            "bmo/data/matching_game",
        ):
            self.assertIn(f'"$BASE_DIR/{relative_path}"', script)

        self.assertNotIn('"$BASE_DIR/sounds/', script)
        self.assertNotIn('"$BASE_DIR/faces/', script)

    def test_setup_uses_supported_model_sources(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('BMO_VOICE_RELEASE="v1.0-voice"', script)
        self.assertIn('download_models(model_names=["hey_jarvis_v0.1"])', script)
        self.assertIn('models_directory / "melspectrogram.onnx"', script)
        self.assertIn('models_directory / "embedding_model.onnx"', script)
        self.assertIn('version("openwakeword") != "0.6.0"', script)
        self.assertIn('inference_framework="onnx"', script)
        self.assertNotIn("releases/latest/download", script)
        self.assertNotIn("openWakeWord/raw/main", script)

    def test_python_setup_forces_onnx_compatible_openwakeword(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")
        requirements = (REPOSITORY_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'pip install --no-deps "openwakeword==0.6.0"', script
        )
        self.assertNotIn("--force-reinstall", script)
        self.assertIn("requests>=2,<3", requirements)
        self.assertIn("tqdm>=4,<5", requirements)
        self.assertIn("scikit-learn>=1,<2", requirements)
        self.assertIn("PySide6-Essentials==6.11.1", requirements)
        self.assertIn(
            'openwakeword==0.6.0; platform_system != "Linux" or '
            'python_version < "3.12"',
            requirements,
        )
        for module in (
            "QtCore",
            "QtGui",
            "QtQml",
            "QtQuick",
            "QtQuickControls2",
        ):
            self.assertIn(module, script)
        self.assertIn('PySide6.__version__ != "6.11.1"', script)
        self.assertIn('QtCore.qVersion() != "6.11.1"', script)

    def test_setup_and_launcher_use_the_documented_virtual_environment(self) -> None:
        setup = SETUP_SCRIPT.read_text(encoding="utf-8")
        launcher = (REPOSITORY_ROOT / "start_agent.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('VENV_DIR="$BASE_DIR/.venv"', setup)
        self.assertIn('PYTHON_BIN="$BASE_DIR/venv/bin/python"', launcher)
        self.assertIn('PYTHON_BIN="$BASE_DIR/.venv/bin/python"', launcher)
        self.assertIn('exec "$PYTHON_BIN" agent.py', launcher)

    def test_ollama_model_matches_runtime_and_example_defaults(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")
        model_match = re.search(r'^TEXT_MODEL="([^"]+)"$', script, re.MULTILINE)
        example = loads(
            (REPOSITORY_ROOT / "config/example.settings.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIsNotNone(model_match)
        self.assertEqual(model_match.group(1), DEFAULT_CONFIG["text_model"])
        self.assertEqual(example["text_model"], DEFAULT_CONFIG["text_model"])


if __name__ == "__main__":
    unittest.main()
