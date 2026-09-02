from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts import validate_imessage_live_readonly as live_validation


class LiveValidationFixture:
    def __init__(self, root: Path) -> None:
        self.messages_root = root / "SMS"
        attachment_root = self.messages_root / "Attachments" / "aa"
        attachment_root.mkdir(parents=True)
        (attachment_root / "photo.jpg").write_bytes(b"invented image bytes")
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
                VALUES (1, 'private-handle', 'iMessage');
            INSERT INTO chat(ROWID, guid, service_name)
                VALUES (1, 'private-chat', 'iMessage');
            INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 1);
            INSERT INTO message(
                ROWID, guid, text, handle_id, service, date, is_from_me,
                associated_message_type
            ) VALUES (
                1, 'private-message-guid', 'private message text', 1,
                'iMessage', 1000000000, 0, 0
            );
            INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, 1);
            INSERT INTO message(
                ROWID, guid, text, handle_id, service, date, is_from_me,
                associated_message_type
            ) VALUES (
                2, 'private-outgoing-guid', 'private outgoing text', 1,
                'iMessage', 2000000000, 1, 0
            );
            INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, 2);
            INSERT INTO attachment(
                ROWID, guid, filename, uti, mime_type, transfer_name, total_bytes
            ) VALUES (
                1, 'private-attachment-guid',
                '~/Library/SMS/Attachments/aa/photo.jpg',
                'public.jpeg', 'image/jpeg', 'private-name.jpg', 20
            );
            INSERT INTO message_attachment_join(message_id, attachment_id)
                VALUES (1, 1);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class IMessageLiveValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.fixture = LiveValidationFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary_directory.cleanup()

    def test_validates_disposable_copy_and_emits_only_aggregate_diagnostics(self) -> None:
        source_before = _trio_hashes(self.fixture.messages_root)
        attachment = self.fixture.messages_root / "Attachments" / "aa" / "photo.jpg"
        attachment_before = _sha256(attachment)

        report = live_validation.validate_live_readonly(
            self.fixture.messages_root,
            scan_limit=10,
        )

        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["source"]["database_opened_directly"])
        self.assertTrue(report["source"]["trio_stable_during_validation"])
        self.assertEqual(report["database"]["quick_check"], "ok")
        self.assertEqual(report["database"]["journal_mode"], "wal")
        self.assertTrue(report["database"]["query_only"])
        self.assertTrue(report["database"]["rowid_range_query_plan"])
        self.assertEqual(report["scan"]["rows_examined"], 2)
        self.assertEqual(
            report["scan"]["source_directions"],
            {"incoming": 1, "outgoing": 1},
        )
        self.assertTrue(report["scan"]["ordinary_outgoing_events_omitted"])
        self.assertEqual(report["attachments"]["referenced"], 1)
        self.assertEqual(report["attachments"]["verified_files"], 1)
        self.assertTrue(report["attachments"]["unchanged_during_reads"])
        self.assertEqual(_trio_hashes(self.fixture.messages_root), source_before)
        self.assertEqual(_sha256(attachment), attachment_before)

        rendered = json.dumps(report, sort_keys=True)
        for private_value in (
            "private-handle",
            "private-chat",
            "private-message-guid",
            "private message text",
            "private-outgoing-guid",
            "private outgoing text",
            "private-attachment-guid",
            "private-name.jpg",
            "photo.jpg",
        ):
            self.assertNotIn(private_value, rendered)

    def test_rejects_a_missing_database_wal_shm_member(self) -> None:
        (self.fixture.messages_root / "sms.db-shm").unlink()

        with self.assertRaisesRegex(
            live_validation.LiveValidationError,
            "messages_trio_unreadable",
        ):
            live_validation.validate_live_readonly(self.fixture.messages_root)

    def test_source_change_during_copy_is_inconclusive_and_not_parsed(self) -> None:
        original_copy = live_validation._copy_trio

        def copy_then_change(source_paths: tuple[Path, ...], destination: Path) -> Path:
            copied = original_copy(source_paths, destination)
            self.fixture.connection.execute(
                "UPDATE message SET date = date + 1 WHERE ROWID = 1"
            )
            self.fixture.connection.commit()
            return copied

        with mock.patch.object(live_validation, "_copy_trio", copy_then_change):
            report = live_validation.validate_live_readonly(self.fixture.messages_root)

        self.assertEqual(report["status"], "inconclusive_source_changed")
        self.assertFalse(report["source"]["trio_stable_during_copy"])
        self.assertNotIn("database", report)

    def test_scan_limit_is_bounded(self) -> None:
        for invalid in (0, live_validation.MAX_SCAN_LIMIT + 1, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    live_validation.LiveValidationError,
                    "invalid_scan_limit",
                ):
                    live_validation.validate_live_readonly(
                        self.fixture.messages_root,
                        scan_limit=invalid,
                    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _trio_hashes(messages_root: Path) -> dict[str, str]:
    return {
        name: _sha256(messages_root / name)
        for name in live_validation.TRIO_NAMES
    }


if __name__ == "__main__":
    unittest.main()
