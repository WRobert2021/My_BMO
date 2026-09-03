from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from bmo.features.imessage_relay.relay.live_source import (
    LiveSourceError,
    disposable_messages_snapshot,
)
from bmo.features.imessage_relay.tools import run_live_delivery as live_delivery


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LiveDeliveryFixture:
    def __init__(self, root: Path) -> None:
        self.messages_root = root / "SMS"
        attachment_root = self.messages_root / "Attachments" / "aa"
        attachment_root.mkdir(parents=True)
        self.attachment_path = attachment_root / "photo.jpg"
        self.attachment_path.write_bytes(b"invented live delivery image")
        self.database_path = self.messages_root / "sms.db"
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
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
                VALUES (1, 'private-live-handle', 'iMessage');
            INSERT INTO chat(ROWID, guid, service_name)
                VALUES (1, 'private-live-chat', 'iMessage');
            INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 1);
            """
        )
        for index in range(1, 5):
            self.add_message(index)
        self.connection.execute(
            """
            INSERT INTO attachment(
                ROWID, guid, filename, uti, mime_type, transfer_name, total_bytes
            ) VALUES (
                1, 'private-live-attachment',
                '~/Library/SMS/Attachments/aa/photo.jpg',
                'public.jpeg', 'image/jpeg', 'private-photo.jpg', ?
            )
            """,
            (self.attachment_path.stat().st_size,),
        )
        self.connection.execute(
            "INSERT INTO message_attachment_join(message_id, attachment_id) VALUES (4, 1)"
        )
        self.connection.commit()

    def add_message(self, index: int) -> None:
        self.connection.execute(
            """
            INSERT INTO message(
                ROWID, guid, text, handle_id, service, date, is_from_me,
                associated_message_type
            ) VALUES (?, ?, ?, 1, 'iMessage', ?, 0, 0)
            """,
            (
                index,
                f"private-live-message-{index}",
                f"private live text {index}",
                index * 1_000_000_000,
            ),
        )
        self.connection.execute(
            "INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, ?)",
            (index,),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class IMessageLiveDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.fixture = LiveDeliveryFixture(self.root)
        self.work = self.root / "work"
        self.work.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary_directory.cleanup()

    def test_real_http_fault_matrix_restart_attachment_and_new_event(self) -> None:
        trio_before = _trio_hashes(self.fixture.messages_root)
        attachment_before = _sha256(self.fixture.attachment_path)

        first = live_delivery.run_live_delivery(
            messages_root=self.fixture.messages_root,
            work_directory=self.work,
            scan_limit=10,
            delivery_limit=20,
        )

        self.assertEqual(first["status"], "pass")
        self.assertEqual(first["discovery"]["rows"], 4)
        self.assertEqual(first["discovery"]["events"], {"message": 4})
        self.assertEqual(first["discovery"]["issues"], {})
        self.assertEqual(first["discovery"]["attachments"], 1)
        self.assertEqual(
            first["faults"],
            {
                "authentication": {
                    "disposition": "retry_scheduled",
                    "error_code": "invalid_signature",
                },
                "lost_ack": {
                    "disposition": "retry_scheduled",
                    "error_code": "ack_timeout",
                },
                "receiver_offline": {
                    "disposition": "retry_scheduled",
                    "error_code": "transport_unavailable",
                },
            },
        )
        self.assertEqual(first["delivery"]["acknowledged_events"], 4)
        self.assertEqual(first["delivery"]["receiver_events"], 4)
        self.assertEqual(first["delivery"]["complete_attachments"], 1)
        self.assertEqual(first["delivery"]["pending_events"], 0)
        self.assertEqual(first["delivery"]["partial_attachments"], 0)
        self.assertEqual(stat.S_IMODE((self.work / "relay.db").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.work / "receiver.db").stat().st_mode), 0o600)
        self.assertEqual(_trio_hashes(self.fixture.messages_root), trio_before)
        self.assertEqual(_sha256(self.fixture.attachment_path), attachment_before)

        rendered = json.dumps(first, sort_keys=True)
        for private_value in (
            "private-live-handle",
            "private-live-chat",
            "private-live-message",
            "private live text",
            "private-live-attachment",
            "private-photo.jpg",
            "photo.jpg",
        ):
            self.assertNotIn(private_value, rendered)

        self.fixture.add_message(5)
        second = live_delivery.run_live_delivery(
            messages_root=self.fixture.messages_root,
            work_directory=self.work,
            scan_limit=10,
            delivery_limit=20,
        )

        self.assertEqual(second["status"], "pass")
        self.assertEqual(second["discovery"]["rows"], 1)
        self.assertEqual(second["faults"], {})
        self.assertEqual(second["delivery"]["acknowledged_events"], 5)
        self.assertEqual(second["delivery"]["receiver_events"], 5)

    def test_disposable_snapshot_never_opens_or_changes_source(self) -> None:
        trio_before = _trio_hashes(self.fixture.messages_root)

        with disposable_messages_snapshot(self.fixture.messages_root) as snapshot:
            self.assertNotEqual(snapshot.database_path, self.fixture.database_path)
            self.assertTrue(snapshot.database_path.is_file())

        self.assertEqual(_trio_hashes(self.fixture.messages_root), trio_before)

    def test_source_change_during_copy_fails_closed(self) -> None:
        from bmo.features.imessage_relay.relay import live_source

        original_copy = live_source._copy_trio

        def copy_then_change(source_paths: tuple[Path, ...], destination: Path) -> Path:
            copied = original_copy(source_paths, destination)
            self.fixture.connection.execute(
                "UPDATE message SET date = date + 1 WHERE ROWID = 1"
            )
            self.fixture.connection.commit()
            return copied

        with mock.patch.object(live_source, "_copy_trio", copy_then_change):
            with self.assertRaisesRegex(LiveSourceError, "source_changed_during_copy"):
                with disposable_messages_snapshot(self.fixture.messages_root):
                    self.fail("an unstable source must not be yielded")

    def test_rejects_nonprivate_or_repository_work_directory(self) -> None:
        self.work.chmod(0o755)
        with self.assertRaisesRegex(
            live_delivery.LiveDeliveryError,
            "work_directory_not_private",
        ):
            live_delivery.run_live_delivery(
                messages_root=self.fixture.messages_root,
                work_directory=self.work,
            )

        with self.assertRaisesRegex(
            live_delivery.LiveDeliveryError,
            "work_directory_inside_repository",
        ):
            live_delivery._private_work_directory(PROJECT_ROOT)

    def test_direct_cli_help_resolves_project_imports(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "bmo.features.imessage_relay.tools.run_live_delivery",
                "--help",
            ],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("read-only mount", completed.stdout)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _trio_hashes(messages_root: Path) -> dict[str, str]:
    return {
        name: _sha256(messages_root / name)
        for name in ("sms.db", "sms.db-wal", "sms.db-shm")
    }


if __name__ == "__main__":
    unittest.main()
