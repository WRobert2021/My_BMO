"""Tests for the toolkit-neutral menu catalog and selection boundary."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bmo.features.contracts import FeatureMenuItem
from bmo.menu_catalog import (
    MenuCatalog,
    MenuOwner,
    MenuSelectionRequest,
)
from bmo.menu_model import IconMenuItem
from bmo.menu_loader import load_menu_catalog
from bmo.modes.contracts import ModeMenuItem


class MenuCatalogTests(unittest.TestCase):
    def test_registry_contributions_preserve_mode_then_feature_order(self) -> None:
        catalog = MenuCatalog.from_contributions(
            modes=(
                ModeMenuItem(
                    "matching_game",
                    "Matching Game",
                    Path("matching.png"),
                    "Start matching",
                ),
            ),
            features=(
                FeatureMenuItem("set_timer", "Timers", Path("timer.png")),
                FeatureMenuItem("album", "Album", Path("album.png")),
            ),
        )

        self.assertEqual(
            tuple(item.name for item in catalog.items),
            ("mode:matching_game", "feature:set_timer", "feature:album"),
        )

    def test_visible_key_resolves_to_typed_selection_request(self) -> None:
        catalog = MenuCatalog(
            (IconMenuItem("feature:album", "Album", Path("album.png")),)
        )

        request = catalog.request_for("FEATURE:ALBUM")

        self.assertEqual(request.owner, MenuOwner.FEATURE)
        self.assertEqual(request.name, "album")
        self.assertEqual(request.key, "feature:album")

    def test_hidden_or_unknown_key_is_rejected(self) -> None:
        catalog = MenuCatalog(
            (IconMenuItem("feature:album", "Album", Path("album.png")),)
        )

        with self.assertRaisesRegex(LookupError, "No visible menu item"):
            catalog.request_for("feature:learning")

    def test_selection_parser_rejects_unknown_owner_and_malformed_name(self) -> None:
        for value in ("unknown:item", "feature:", "feature:bad:name", "plain"):
            with self.subTest(value=value), self.assertRaises(LookupError):
                MenuSelectionRequest.parse(value)

    def test_catalog_rejects_duplicate_namespaced_keys(self) -> None:
        item = IconMenuItem("feature:album", "Album", Path("album.png"))

        with self.assertRaisesRegex(ValueError, "must be unique"):
            MenuCatalog((item, item))


class ConfiguredMenuCatalogTests(unittest.TestCase):
    def test_configuration_controls_order_visibility_and_optional_hooks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory)
            config = {
                "features": [
                    {"module": "bmo.features.get_time"},
                    {"module": "bmo.features.set_timer"},
                    {
                        "module": "bmo.features.calendar",
                        "settings": {
                            "config_path": missing / "calendar.json",
                        },
                    },
                    {
                        "module": "bmo.features.get_weather",
                        "settings": {"show_in_menu": False},
                    },
                    {"module": "bmo.features.album"},
                    {
                        "module": "bmo.features.learning",
                        "settings": {
                            "config_path": missing / "learning.json",
                        },
                    },
                ],
                "modes": [
                    {
                        "module": "bmo.modes.matching_game",
                        "settings": {"show_in_menu": False},
                    },
                    {"module": "bmo.modes.twenty_questions"},
                ],
            }

            result = load_menu_catalog(config)

        self.assertEqual(result.failures, ())
        self.assertEqual(
            tuple(item.name for item in result.catalog.items),
            (
                "mode:twenty_questions",
                "feature:set_timer",
                "feature:get_calendar",
                "feature:album",
                "feature:learning",
            ),
        )
        self.assertEqual(
            result.feature_modules,
            tuple(entry["module"] for entry in config["features"]),
        )

    def test_failing_metadata_hook_rolls_back_without_blocking_others(
        self,
    ) -> None:
        failing = types.ModuleType("failing_menu")
        valid = types.ModuleType("valid_menu")

        def fail_after_register(registry, settings) -> None:
            del settings
            registry.register(
                FeatureMenuItem("partial", "Partial", Path("partial.png"))
            )
            registry.register(
                FeatureMenuItem("bad:name", "Bad", Path("bad.png"))
            )

        def register_valid(registry, settings) -> None:
            del settings
            registry.register(
                FeatureMenuItem("valid", "Valid", Path("valid.png"))
            )

        failing.register_menu_metadata = fail_after_register
        valid.register_menu_metadata = register_valid
        modules = {"failing_menu": failing, "valid_menu": valid}
        with patch(
            "bmo.menu_loader._load_module",
            side_effect=modules.__getitem__,
        ):
            result = load_menu_catalog(
                {
                    "features": [
                        {"module": "failing_menu"},
                        {"module": "valid_menu"},
                    ],
                    "modes": [],
                },
                reporter=lambda _message: None,
            )

        self.assertEqual(
            tuple(item.name for item in result.catalog.items),
            ("feature:valid",),
        )
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].module, "failing_menu")

    def test_builtin_metadata_load_constructs_no_ui_or_runtime_services(
        self,
    ) -> None:
        script = """
import sys
import tempfile
import threading
from pathlib import Path
from bmo.menu_loader import load_menu_catalog

with tempfile.TemporaryDirectory() as directory:
    missing = Path(directory)
    config = {
        "features": [
            {"module": "bmo.features.get_weather"},
            {"module": "bmo.features.calendar", "settings": {"config_path": missing / "calendar.json"}},
            {"module": "bmo.features.set_timer"},
            {"module": "bmo.features.album"},
            {"module": "bmo.features.learning", "settings": {"config_path": missing / "learning.json"}},
        ],
        "modes": [
            {"module": "bmo.modes.matching_game"},
            {"module": "bmo.modes.twenty_questions"},
        ],
    }
    before = tuple(thread.name for thread in threading.enumerate())
    result = load_menu_catalog(config)
    after = tuple(thread.name for thread in threading.enumerate())
    assert not result.failures
    assert before == after
    assert "tkinter" not in sys.modules
    assert "onnxruntime" not in sys.modules
    assert "openwakeword" not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
