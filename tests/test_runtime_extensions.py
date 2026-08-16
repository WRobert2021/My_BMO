"""Tests for UI-neutral extension ownership and menu-action scheduling."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from bmo.features.contracts import FeatureMenuItem
from bmo.menu_catalog import MenuOwner, MenuSelectionRequest
from bmo.modes.contracts import ModeMenuItem
from bmo.runtime_extensions import (
    RuntimeExtensionCoordinator,
    RuntimeVisionRequest,
)


class RuntimeExtensionCoordinatorTests(unittest.TestCase):
    def make_runtime(self):
        mode_registry = Mock()
        mode_registry.menu_items = (
            ModeMenuItem(
                "matching_game",
                "Matching Game",
                Path("matching.png"),
                "Start matching",
            ),
        )
        feature_registry = Mock()
        feature_registry.menu_items = (
            FeatureMenuItem("album", "Album", Path("album.png")),
        )
        launch_feature = Mock()
        runtime = RuntimeExtensionCoordinator(
            mode_registry,
            feature_registry,
            launch_feature=launch_feature,
        )
        return runtime, mode_registry, feature_registry, launch_feature

    def test_live_catalog_and_typed_dispatch_share_registry_ownership(self) -> None:
        runtime, mode_registry, _feature_registry, launch_feature = (
            self.make_runtime()
        )

        runtime.dispatch_menu(
            MenuSelectionRequest(MenuOwner.MODE, "matching_game")
        )
        runtime.dispatch_menu(MenuSelectionRequest(MenuOwner.FEATURE, "album"))

        self.assertTrue(runtime.wake_event.is_set())
        self.assertTrue(runtime.start_pending_mode())
        mode_registry.start_menu_item.assert_called_once_with("matching_game")
        launch_feature.assert_called_once_with("album")
        self.assertFalse(runtime.wake_event.is_set())
        self.assertEqual(
            tuple(item.name for item in runtime.catalog().items),
            ("mode:matching_game", "feature:album"),
        )

    def test_vision_requests_keep_priority_and_wake_until_all_work_drains(
        self,
    ) -> None:
        runtime, mode_registry, _feature_registry, _launch_feature = (
            self.make_runtime()
        )
        complete = Mock()
        runtime.queue_mode("matching_game")
        runtime.queue_vision(Path("photo.jpg"), complete)

        vision = runtime.take_pending_vision()

        self.assertEqual(
            vision,
            RuntimeVisionRequest(Path("photo.jpg"), complete),
        )
        self.assertTrue(runtime.wake_event.is_set())
        self.assertTrue(runtime.start_pending_mode())
        mode_registry.start_menu_item.assert_called_once_with("matching_game")
        self.assertFalse(runtime.wake_event.is_set())

    def test_mode_completion_runs_even_when_mode_start_fails(self) -> None:
        runtime, mode_registry, _feature_registry, _launch_feature = (
            self.make_runtime()
        )
        completion = Mock()
        mode_registry.start_menu_item.side_effect = RuntimeError("start failed")
        runtime.queue_mode("matching_game")

        with self.assertRaisesRegex(RuntimeError, "start failed"):
            runtime.start_pending_mode(on_complete=completion)

        completion.assert_called_once_with()
        self.assertFalse(runtime.wake_event.is_set())

    def test_vision_request_requires_a_path_and_completion(self) -> None:
        with self.assertRaisesRegex(TypeError, "pathlib.Path"):
            RuntimeVisionRequest("photo.jpg", Mock())  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "must be callable"):
            RuntimeVisionRequest(Path("photo.jpg"), None)  # type: ignore[arg-type]

    def test_close_is_idempotent_and_rejects_new_requests(self) -> None:
        runtime, mode_registry, feature_registry, _launch_feature = (
            self.make_runtime()
        )
        runtime.queue_mode("matching_game")

        runtime.close()
        runtime.close()

        feature_registry.close.assert_called_once_with()
        mode_registry.close.assert_called_once_with()
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.wake_event.is_set())
        self.assertFalse(runtime.start_pending_mode())
        with self.assertRaisesRegex(RuntimeError, "after shutdown"):
            runtime.queue_mode("matching_game")
        with self.assertRaisesRegex(RuntimeError, "after shutdown"):
            runtime.queue_vision(Path("photo.jpg"), Mock())
        with self.assertRaisesRegex(RuntimeError, "after shutdown"):
            runtime.dispatch_menu(
                MenuSelectionRequest(MenuOwner.MODE, "matching_game")
            )

    def test_one_registry_close_failure_does_not_block_the_other(self) -> None:
        runtime, mode_registry, feature_registry, _launch_feature = (
            self.make_runtime()
        )
        feature_registry.close.side_effect = RuntimeError("feature close failed")

        runtime.close()

        feature_registry.close.assert_called_once_with()
        mode_registry.close.assert_called_once_with()

    def test_import_does_not_load_tkinter_or_qt(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bmo.runtime_extensions; "
                    "assert 'tkinter' not in sys.modules; "
                    "assert 'PySide6' not in sys.modules"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
