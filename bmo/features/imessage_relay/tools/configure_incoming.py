#!/usr/bin/env python3
"""Configure persistent incoming relay login and enablement without logging secrets."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any

from bmo.features.imessage_relay.relay import RelayStateError, load_state_config


def configure(args: argparse.Namespace) -> None:
    project_root = Path(args.project_root).expanduser().resolve()
    config_root = project_root / "config"
    features_path = Path(args.features_path).expanduser()
    if not features_path.is_absolute():
        features_path = project_root / features_path
    features = _load_features(
        features_path,
        fallback_path=config_root / "example.features.json",
    )

    private_root = config_root / "private"
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(private_root, 0o700)

    password_path = private_root / "imessage_source.password"
    receiver_secret_path = private_root / "imessage_receiver.secret"
    if args.reuse_existing_password:
        _validate_existing_password(password_path)
    else:
        password = getpass.getpass("Password for the restricted phone account: ")
        if not password or "\n" in password or "\r" in password or "\x00" in password:
            raise ValueError("password must be one non-empty line")
        _atomic_private_bytes(password_path, password.encode("utf-8") + b"\n")
        del password
    if not receiver_secret_path.exists():
        _atomic_private_bytes(receiver_secret_path, secrets.token_hex(32).encode("ascii"))

    source_path = config_root / "imessage_source.json"
    receiver_path = config_root / "imessage_receiver.json"
    relay_path = config_root / "imessage_relay.json"
    known_hosts = Path(args.known_hosts_path).expanduser().resolve()
    mount_path = Path(args.mount_path).expanduser()
    if not mount_path.is_absolute():
        raise ValueError("mount path must be absolute")

    _atomic_private_json(
        source_path,
        {
            "schema_version": 1,
            "host": args.host,
            "username": args.username,
            "port": args.port,
            "remote_path": "/SMS",
            "mount_path": str(mount_path),
            "known_hosts_path": str(known_hosts),
            "password_file": str(password_path),
            "poll_interval_seconds": args.poll_interval,
            "scan_limit": 100,
            "delivery_limit": 500,
        },
    )
    _atomic_private_json(
        receiver_path,
        {
            "schema_version": 2,
            "bind_host": "127.0.0.1",
            "port": 0,
            "state_path": "bmo/data/imessage_receiver/receiver.db",
            "tls_cert_path": None,
            "tls_key_path": None,
            "allow_insecure_loopback": True,
            "key_id": "kiosk-incoming-1",
            "shared_secret_file": str(receiver_secret_path),
            "max_clock_skew_seconds": 300,
            "max_request_bytes": 2_097_152,
            "request_timeout_seconds": 10,
        },
    )
    if not relay_path.exists():
        _atomic_private_json(
            relay_path,
            {
                "schema_version": 1,
                "state_path": "bmo/data/imessage_relay/relay_state.db",
                "retry_policy": {
                    "initial_delay_seconds": 30,
                    "multiplier": 2,
                    "max_delay_seconds": 900,
                    "max_attempts": 5,
                    "lease_duration_seconds": 60,
                },
            },
        )
    try:
        relay_config = load_state_config(relay_path, base_directory=project_root)
    except RelayStateError as error:
        raise ValueError("private relay state configuration is invalid") from error
    _ensure_private_directory(relay_config.state_path.parent)
    _enable_feature(features_path, features)


def _load_features(
    path: Path,
    *,
    fallback_path: Path | None = None,
) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("private features configuration is unavailable")
    source = path
    if not path.exists() and fallback_path is not None:
        source = fallback_path
    if not source.is_file():
        raise ValueError("private features configuration is unavailable")
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("features"), list):
        raise ValueError("private features configuration is invalid")
    return value


def _enable_feature(path: Path, value: dict[str, Any] | None = None) -> None:
    if value is None:
        value = _load_features(path)
    entries = value["features"]
    relay_entry: dict[str, Any] | None = None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("module") == "bmo.features.imessage_relay":
            relay_entry = entry
            break
    if relay_entry is None:
        relay_entry = {"module": "bmo.features.imessage_relay"}
        entries.append(relay_entry)
    relay_entry["enabled"] = True
    settings = relay_entry.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        relay_entry["settings"] = settings
    settings.pop("messages_root", None)
    settings.update(
        {
            "receiver_config_path": "config/imessage_receiver.json",
            "relay_config_path": "config/imessage_relay.json",
            "source_config_path": "config/imessage_source.json",
            "reconciliation_recent_days": 7,
        }
    )
    _atomic_private_json(path, value)


def _atomic_private_json(path: Path, value: object) -> None:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_private_bytes(path, encoded)


def _atomic_private_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _validate_existing_password(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("existing private phone password is unavailable")
    metadata = path.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError("existing private phone password permissions are invalid")
    password = path.read_bytes()
    if not password.endswith(b"\n") or not password[:-1] or b"\n" in password[:-1]:
        raise ValueError("existing private phone password must be one non-empty line")
    del password


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("private relay state directory is unavailable")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.stat()
        if not path.is_dir() or metadata.st_uid != os.getuid():
            raise ValueError("private relay state directory is unavailable")
        os.chmod(path, 0o700)
    except OSError as error:
        raise ValueError("private relay state directory is unavailable") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--features-path", type=Path, default=Path("config/features.json"))
    parser.add_argument(
        "--known-hosts-path",
        type=Path,
        default=Path.home() / ".ssh" / "known_hosts",
    )
    parser.add_argument(
        "--mount-path",
        type=Path,
        default=Path("/var/tmp/bmo-imessage-relay/SMS"),
    )
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument(
        "--reuse-existing-password",
        action="store_true",
        help="reuse the existing owner-only private password file without prompting",
    )
    return parser.parse_args()


def main() -> int:
    try:
        configure(parse_args())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Incoming relay configuration failed safely: {error}")
        return 1
    print("Incoming relay configured and enabled. Restart BMO to activate it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
