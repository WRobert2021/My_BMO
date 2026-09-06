"""Stage 12 persistent incoming source, worker, and configuration coverage."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bmo.features.imessage_relay.incoming import IncomingRelayWorker
from bmo.features.imessage_relay.receiver import (
    ReceiverApplication,
    ReceiverStateStore,
    RequestAuthenticator,
)
from bmo.features.imessage_relay.relay import RelayStateConfig, RetryPolicy
from bmo.features.imessage_relay.source_mount import (
    IncomingSourceConfig,
    ReadOnlySSHFS,
    SourceMountError,
    load_source_config,
)
from bmo.features.imessage_relay.tools import configure_incoming
from bmo.features.imessage_relay.tools.configure_incoming import configure


SECRET = b"invented-production-incoming-secret-material"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeMountCommands:
    def __init__(self, source: str) -> None:
        self.source = source
        self.mounted = False
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []

    def __call__(self, command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        supplied = kwargs.get("input")
        self.calls.append((command, supplied if isinstance(supplied, bytes) else None))
        if command[0] == "findmnt":
            if self.mounted:
                output = f"{self.source} fuse.sshfs ro,nosuid,nodev\n".encode()
                return subprocess.CompletedProcess(command, 0, output, b"")
            return subprocess.CompletedProcess(command, 1, b"", b"")
        if command[0] == "sshfs":
            self.mounted = True
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[0] == "fusermount3":
            self.mounted = False
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError(command)


class _LocalMount:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.closed = False

    @property
    def mounted(self) -> bool:
        return not self.closed

    def ensure_mounted(self) -> Path:
        if self.closed:
            raise SourceMountError("source_mount_failed")
        return self.root

    def close(self) -> None:
        self.closed = True


class ProductionIncomingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def source_config(self) -> tuple[Path, IncomingSourceConfig]:
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("invented host key\n", encoding="utf-8")
        password = self.root / "password"
        password.write_text("invented-password\n", encoding="utf-8")
        password.chmod(0o600)
        mount_path = self.root / "mount" / "SMS"
        config_path = self.root / "source.json"
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "host": "192.0.2.10",
                    "username": "pi-bmo",
                    "port": 22,
                    "remote_path": "/SMS",
                    "mount_path": str(mount_path),
                    "known_hosts_path": str(known_hosts),
                    "password_file": str(password),
                    "poll_interval_seconds": 5,
                    "scan_limit": 100,
                    "delivery_limit": 500,
                }
            ),
            encoding="utf-8",
        )
        return config_path, load_source_config(config_path)

    def test_strict_source_config_and_private_password_permissions(self) -> None:
        path, config = self.source_config()
        self.assertEqual(config.username, "pi-bmo")
        self.assertEqual(config.remote_path, "/SMS")

        config.password_file.chmod(0o644)
        mount = ReadOnlySSHFS(config, run=_FakeMountCommands("unused"))
        with self.assertRaisesRegex(SourceMountError, "source_password_permissions_invalid"):
            mount.ensure_mounted()
        self.assertNotIn("invented-password", repr(config))
        self.assertTrue(path.is_file())

    def test_mount_uses_password_stdin_and_unmounts_owned_source(self) -> None:
        _, config = self.source_config()
        source = f"{config.username}@{config.host}:{config.remote_path}"
        commands = _FakeMountCommands(source)
        mount = ReadOnlySSHFS(config, run=commands)

        self.assertEqual(mount.ensure_mounted(), config.mount_path)
        self.assertTrue(mount.mounted)
        mount.close()

        sshfs_call = next(item for item in commands.calls if item[0][0] == "sshfs")
        flattened = " ".join(sshfs_call[0])
        self.assertEqual(sshfs_call[1], b"invented-password\n")
        self.assertNotIn("invented-password", flattened)
        self.assertIn("ro,password_stdin", flattened)
        self.assertNotIn("ClearAllForwardings", flattened)
        self.assertFalse(commands.mounted)

    def test_verified_existing_mount_is_adopted_but_not_unmounted(self) -> None:
        _, config = self.source_config()
        source = f"{config.username}@{config.host}:{config.remote_path}"
        commands = _FakeMountCommands(source)
        commands.mounted = True
        mount = ReadOnlySSHFS(config, run=commands)

        self.assertEqual(mount.ensure_mounted(), config.mount_path)
        mount.close()

        self.assertTrue(commands.mounted)
        self.assertFalse(any(call[0][0] == "fusermount3" for call in commands.calls))

    def test_continuous_cycle_discovers_delivers_and_is_idempotent(self) -> None:
        messages_root, connection = _messages_fixture(self.root)
        receiver_store = ReceiverStateStore(self.root / "receiver.db")
        application = ReceiverApplication(
            store=receiver_store,
            authenticator=RequestAuthenticator(
                key_id="incoming-test",
                shared_secret=SECRET,
            ),
        )
        mount = _LocalMount(messages_root)
        source = IncomingSourceConfig(
            host="192.0.2.10",
            username="pi-bmo",
            port=22,
            remote_path="/SMS",
            mount_path=messages_root,
            known_hosts_path=self.root / "known_hosts",
            password_file=self.root / "password",
            poll_interval_seconds=5,
            scan_limit=100,
            delivery_limit=500,
        )
        worker = IncomingRelayWorker(
            source_config=source,
            relay_config=RelayStateConfig(
                state_path=self.root / "relay.db",
                retry_policy=RetryPolicy(),
            ),
            receiver_application=application,
            key_id="incoming-test",
            shared_secret=SECRET,
            mount=mount,  # type: ignore[arg-type]
        )
        try:
            first = worker.run_once()
            second = worker.run_once()
        finally:
            worker.close()
            receiver_store.close()
            connection.close()

        self.assertEqual(first.state, "active")
        self.assertEqual(first.scanned_rows, 1)
        self.assertEqual(first.delivered_events, 1)
        self.assertEqual(second.delivered_events, 0)
        self.assertTrue(mount.closed)

    def test_configurator_persists_login_without_exposing_password(self) -> None:
        config_root = self.root / "config"
        config_root.mkdir()
        features_path = config_root / "features.json"
        features_path.write_text(
            json.dumps({"features": [], "modes": []}),
            encoding="utf-8",
        )
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("invented host key\n", encoding="utf-8")
        args = argparse.Namespace(
            project_root=self.root,
            features_path=Path("config/features.json"),
            known_hosts_path=known_hosts,
            mount_path=Path("/var/tmp/invented-imessage/SMS"),
            host="192.0.2.10",
            username="pi-bmo",
            port=22,
            poll_interval=5.0,
            reuse_existing_password=False,
        )
        with patch("getpass.getpass", return_value="invented-password"):
            configure(args)

        source_text = (config_root / "imessage_source.json").read_text(encoding="utf-8")
        feature_text = features_path.read_text(encoding="utf-8")
        self.assertNotIn("invented-password", source_text)
        self.assertNotIn("invented-password", feature_text)
        self.assertEqual(
            (config_root / "private/imessage_source.password").stat().st_mode & 0o777,
            0o600,
        )
        relay_state_root = self.root / "bmo/data/imessage_relay"
        self.assertTrue(relay_state_root.is_dir())
        self.assertEqual(relay_state_root.stat().st_mode & 0o777, 0o700)
        feature = json.loads(feature_text)["features"][0]
        self.assertTrue(feature["enabled"])
        self.assertEqual(
            feature["settings"]["source_config_path"],
            "config/imessage_source.json",
        )

    def test_configurator_reports_safe_actionable_failure(self) -> None:
        output = io.StringIO()
        with (
            patch.object(configure_incoming, "parse_args"),
            patch.object(
                configure_incoming,
                "configure",
                side_effect=ValueError("private features configuration is unavailable"),
            ),
            redirect_stdout(output),
        ):
            result = configure_incoming.main()

        self.assertEqual(result, 1)
        self.assertIn("private features configuration is unavailable", output.getvalue())
        self.assertNotIn("password", output.getvalue())

    def test_configurator_can_resume_with_existing_private_password(self) -> None:
        config_root = self.root / "config"
        private_root = config_root / "private"
        private_root.mkdir(parents=True)
        password_path = private_root / "imessage_source.password"
        password_path.write_text("already-stored\n", encoding="utf-8")
        password_path.chmod(0o600)
        features_path = config_root / "features.json"
        features_path.write_text(
            json.dumps({"features": [], "modes": []}),
            encoding="utf-8",
        )
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("invented host key\n", encoding="utf-8")
        args = argparse.Namespace(
            project_root=self.root,
            features_path=Path("config/features.json"),
            known_hosts_path=known_hosts,
            mount_path=Path("/var/tmp/invented-imessage/SMS"),
            host="192.0.2.10",
            username="pi-bmo",
            port=22,
            poll_interval=5.0,
            reuse_existing_password=True,
        )

        with patch("getpass.getpass") as password_prompt:
            configure(args)

        password_prompt.assert_not_called()
        self.assertEqual(password_path.read_text(encoding="utf-8"), "already-stored\n")
        self.assertTrue(json.loads(features_path.read_text())["features"][0]["enabled"])

    def test_configurator_initializes_missing_features_from_tracked_example(self) -> None:
        config_root = self.root / "config"
        private_root = config_root / "private"
        private_root.mkdir(parents=True)
        password_path = private_root / "imessage_source.password"
        password_path.write_text("already-stored\n", encoding="utf-8")
        password_path.chmod(0o600)
        (config_root / "example.features.json").write_text(
            json.dumps(
                {
                    "features": [
                        {
                            "module": "bmo.features.say_hello",
                            "enabled": True,
                            "settings": {},
                        }
                    ],
                    "modes": [],
                }
            ),
            encoding="utf-8",
        )
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("invented host key\n", encoding="utf-8")
        args = argparse.Namespace(
            project_root=self.root,
            features_path=Path("config/features.json"),
            known_hosts_path=known_hosts,
            mount_path=Path("/var/tmp/invented-imessage/SMS"),
            host="192.0.2.10",
            username="pi-bmo",
            port=22,
            poll_interval=5.0,
            reuse_existing_password=True,
        )

        configure(args)

        features = json.loads((config_root / "features.json").read_text())
        self.assertEqual(features["features"][0]["module"], "bmo.features.say_hello")
        relay = next(
            entry
            for entry in features["features"]
            if entry["module"] == "bmo.features.imessage_relay"
        )
        self.assertTrue(relay["enabled"])
        self.assertEqual((config_root / "features.json").stat().st_mode & 0o777, 0o600)

    def test_phone_publisher_is_syntax_valid_bounded_and_read_only_to_apple(self) -> None:
        script_path = (
            PROJECT_ROOT
            / "bmo/features/imessage_relay/phone/refresh_snapshot.sh"
        )
        script = script_path.read_text(encoding="utf-8")
        completed = subprocess.run(
            ("sh", "-n", str(script_path)),
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertIn("source_root=/private/var/mobile/Library/SMS", script)
        self.assertIn("next_snapshot=$relay_root/.SMS.next", script)
        self.assertIn('"$sha_tool" -c', script)
        self.assertNotIn("sqlite3", script)
        self.assertNotRegex(script, r'(chmod|chown)[^\n]*"\$source_root')

        plist_path = (
            PROJECT_ROOT
            / "bmo/features/imessage_relay/phone/"
            "com.bmo.imessage-relay-snapshot.plist.example"
        )
        with plist_path.open("rb") as handle:
            values = plistlib.load(handle)
        self.assertEqual(values["StartInterval"], 5)
        self.assertEqual(values["StandardOutPath"], "/dev/null")
        self.assertEqual(values["StandardErrorPath"], "/dev/null")


def _messages_fixture(root: Path) -> tuple[Path, sqlite3.Connection]:
    messages_root = root / "SMS"
    (messages_root / "Attachments").mkdir(parents=True)
    database_path = messages_root / "sms.db"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE message (
            guid TEXT, text TEXT, attributedBody BLOB, handle_id INTEGER,
            service TEXT, account_guid TEXT, date INTEGER,
            is_from_me INTEGER, associated_message_guid TEXT,
            associated_message_type INTEGER NOT NULL DEFAULT 0,
            associated_message_range_location INTEGER,
            associated_message_range_length INTEGER, reply_to_guid TEXT
        );
        CREATE TABLE handle (id TEXT, service TEXT);
        CREATE TABLE chat (guid TEXT, service_name TEXT);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
        CREATE TABLE attachment (
            guid TEXT, filename TEXT, uti TEXT, mime_type TEXT,
            transfer_name TEXT, total_bytes INTEGER
        );
        CREATE TABLE message_attachment_join (
            message_id INTEGER, attachment_id INTEGER
        );
        INSERT INTO handle(ROWID, id, service)
            VALUES (1, 'invented-sender', 'iMessage');
        INSERT INTO chat(ROWID, guid, service_name)
            VALUES (1, 'invented-chat', 'iMessage');
        INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 1);
        INSERT INTO message(
            ROWID, guid, text, handle_id, service, date,
            is_from_me, associated_message_type
        ) VALUES (
            1, 'invented-message', 'invented hello', 1, 'iMessage',
            1000000000, 0, 0
        );
        INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, 1);
        """
    )
    connection.commit()
    return messages_root, connection


if __name__ == "__main__":
    unittest.main()
