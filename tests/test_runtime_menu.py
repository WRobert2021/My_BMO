"""Tests for UI-neutral live menu catalog and selection dispatch."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from bmo.features.contracts import FeatureMenuItem
from bmo.menu_catalog import MenuCatalog, MenuOwner, MenuSelectionRequest
from bmo.modes.contracts import ModeMenuItem
from bmo.runtime_menu import RuntimeMenuCoordinator


class RuntimeMenuCoordinatorTests(unittest.TestCase):
    def make_registries(self):
        modes = SimpleNamespace(
            menu_items=(
                ModeMenuItem(
                    "matching_game",
                    "Matching Game",
                    Path("matching.png"),
                    "Start matching",
                ),
            )
        )
        features = SimpleNamespace(
            menu_items=(
                FeatureMenuItem("album", "Album", Path("album.png")),
            )
        )
        return modes, features

    def test_registry_catalog_is_live_and_preserves_owner_order(self) -> None:
        modes, features = self.make_registries()
        coordinator = RuntimeMenuCoordinator.from_registries(
            modes,
            features,
            launch_mode=Mock(),
            launch_feature=Mock(),
        )

        first = coordinator.catalog()
        features.menu_items = ()
        second = coordinator.catalog()

        self.assertEqual(
            tuple(item.name for item in first.items),
            ("mode:matching_game", "feature:album"),
        )
        self.assertEqual(
            tuple(item.name for item in second.items),
            ("mode:matching_game",),
        )

    def test_dispatch_routes_typed_requests_to_the_owning_callback(self) -> None:
        modes, features = self.make_registries()
        launch_mode = Mock()
        launch_feature = Mock()
        coordinator = RuntimeMenuCoordinator.from_registries(
            modes,
            features,
            launch_mode=launch_mode,
            launch_feature=launch_feature,
        )

        coordinator.dispatch(MenuSelectionRequest(MenuOwner.MODE, "matching_game"))
        coordinator.dispatch(MenuSelectionRequest(MenuOwner.FEATURE, "album"))

        launch_mode.assert_called_once_with("matching_game")
        launch_feature.assert_called_once_with("album")

    def test_dispatch_rejects_item_removed_after_view_snapshot(self) -> None:
        modes, features = self.make_registries()
        launch_feature = Mock()
        coordinator = RuntimeMenuCoordinator.from_registries(
            modes,
            features,
            launch_mode=Mock(),
            launch_feature=launch_feature,
        )
        stale_request = MenuSelectionRequest(MenuOwner.FEATURE, "album")
        features.menu_items = ()

        with self.assertRaisesRegex(LookupError, "No visible menu item"):
            coordinator.dispatch(stale_request)

        launch_feature.assert_not_called()

    def test_invalid_provider_and_dispatch_types_are_rejected(self) -> None:
        coordinator = RuntimeMenuCoordinator(
            lambda: "not a catalog",  # type: ignore[return-value]
            launch_mode=Mock(),
            launch_feature=Mock(),
        )

        with self.assertRaisesRegex(TypeError, "must return MenuCatalog"):
            coordinator.catalog()
        with self.assertRaisesRegex(TypeError, "requires MenuSelectionRequest"):
            coordinator.dispatch("feature:album")  # type: ignore[arg-type]

    def test_runtime_menu_import_does_not_import_tkinter(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import bmo.runtime_menu; "
                    "raise SystemExit('tkinter' in sys.modules)"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
