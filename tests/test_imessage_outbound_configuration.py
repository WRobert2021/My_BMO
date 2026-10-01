"""Tests for the private Stage 13 outbound feature switch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from bmo.features.imessage_relay.tools.configure_outbound import (
    OutboundConfigurationError,
    configure_outbound,
    main,
)


def private_features(path: Path, *, enabled: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "modes": [{"module": "invented.mode", "enabled": False}],
                "features": [
                    {
                        "module": "bmo.features.imessage_relay",
                        "enabled": enabled,
                        "settings": {
                            "outbound_enabled": False,
                            "retained": "invented",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


class OutboundConfigurationTests(unittest.TestCase):
    def test_enable_changes_only_outbound_gate_and_keeps_file_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.json"
            private_features(path)

            configure_outbound(path, enabled=True)

            value = json.loads(path.read_text(encoding="utf-8"))
            feature = value["features"][0]
            self.assertTrue(feature["settings"]["outbound_enabled"])
            self.assertEqual(feature["settings"]["retained"], "invented")
            self.assertEqual(value["modes"][0]["module"], "invented.mode")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_disable_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.json"
            private_features(path)

            configure_outbound(path, enabled=False)
            configure_outbound(path, enabled=False)

            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(
                value["features"][0]["settings"]["outbound_enabled"]
            )

    def test_refuses_non_private_or_symlinked_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "features.json"
            private_features(path)
            path.chmod(0o640)
            with self.assertRaisesRegex(
                OutboundConfigurationError, "private_features_not_private"
            ):
                configure_outbound(path, enabled=True)

            path.chmod(0o600)
            link = root / "features-link.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(
                OutboundConfigurationError, "private_features_unsafe"
            ):
                configure_outbound(link, enabled=True)

    def test_refuses_disabled_missing_or_duplicate_relay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            disabled = root / "disabled.json"
            private_features(disabled, enabled=False)
            with self.assertRaisesRegex(
                OutboundConfigurationError, "relay_feature_disabled"
            ):
                configure_outbound(disabled, enabled=True)

            missing = root / "missing.json"
            missing.write_text('{"features": []}', encoding="utf-8")
            missing.chmod(0o600)
            with self.assertRaisesRegex(
                OutboundConfigurationError, "relay_feature_ambiguous"
            ):
                configure_outbound(missing, enabled=True)

            duplicate = root / "duplicate.json"
            private_features(duplicate)
            value = json.loads(duplicate.read_text(encoding="utf-8"))
            value["features"].append(value["features"][0].copy())
            duplicate.write_text(json.dumps(value), encoding="utf-8")
            duplicate.chmod(0o600)
            with self.assertRaisesRegex(
                OutboundConfigurationError, "relay_feature_ambiguous"
            ):
                configure_outbound(duplicate, enabled=True)

    def test_cli_reports_only_bounded_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.json"
            private_features(path)
            self.assertEqual(main(["enable", "--features-path", str(path)]), 0)


if __name__ == "__main__":
    unittest.main()
