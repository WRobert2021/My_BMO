"""Tests for the toolkit-neutral menu catalog and selection boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

from bmo.features.contracts import FeatureMenuItem
from bmo.menu_catalog import (
    MenuCatalog,
    MenuOwner,
    MenuSelectionRequest,
)
from bmo.menu_model import IconMenuItem
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


if __name__ == "__main__":
    unittest.main()
