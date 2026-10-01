#!/usr/bin/env python3
"""Enable or disable the kiosk's explicitly gated iMessage outbound UI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
from typing import Any

from bmo.jsonio import atomic_write_json, load_json


DEFAULT_FEATURES_PATH = Path("config/features.json")
RELAY_MODULE = "bmo.features.imessage_relay"


class OutboundConfigurationError(RuntimeError):
    """A private feature file could not be changed safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def configure_outbound(path: Path, *, enabled: bool) -> None:
    """Atomically change only the relay's outbound feature gate."""

    path = Path(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OutboundConfigurationError("private_features_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise OutboundConfigurationError("private_features_unsafe")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise OutboundConfigurationError("private_features_not_private")
    if metadata.st_uid != os.geteuid():
        raise OutboundConfigurationError("private_features_wrong_owner")

    try:
        with path.open("r", encoding="utf-8") as handle:
            value = load_json(handle)
    except (OSError, ValueError) as exc:
        raise OutboundConfigurationError("private_features_invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("features"), list):
        raise OutboundConfigurationError("private_features_invalid")

    matches = [
        feature
        for feature in value["features"]
        if isinstance(feature, dict) and feature.get("module") == RELAY_MODULE
    ]
    if len(matches) != 1:
        raise OutboundConfigurationError("relay_feature_ambiguous")
    feature: dict[str, Any] = matches[0]
    if feature.get("enabled") is not True:
        raise OutboundConfigurationError("relay_feature_disabled")
    settings = feature.get("settings")
    if not isinstance(settings, dict):
        raise OutboundConfigurationError("relay_settings_invalid")
    settings["outbound_enabled"] = enabled

    try:
        atomic_write_json(path, value, fsync_directory=True)
        os.chmod(path, 0o600)
    except OSError as exc:
        raise OutboundConfigurationError("private_features_write_failed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", choices=("enable", "disable"))
    parser.add_argument(
        "--features-path",
        type=Path,
        default=DEFAULT_FEATURES_PATH,
        help="private features file (default: config/features.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        configure_outbound(
            arguments.features_path,
            enabled=arguments.state == "enable",
        )
    except OutboundConfigurationError as exc:
        print(f"iMessage Relay outbound configuration failed: {exc.code}")
        return 1
    print(f"iMessage Relay outbound {arguments.state}d.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
