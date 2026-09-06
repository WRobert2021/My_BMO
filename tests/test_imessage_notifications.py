from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from bmo.features.imessage_relay import (
    NotificationCountError,
    new_message_count,
    received_message_count,
)
from bmo.features.imessage_relay.receiver import (
    IngestResult,
    ReceiverStateStore,
    decode_event_envelope,
    encode_event_envelope,
)
from bmo.features.imessage_relay.relay import (
    Direction,
    EventKind,
    MessageEvent,
    Sender,
    SenderKind,
    apple_nanoseconds_to_datetime,
)


class IMessageNotificationCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "receiver.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_counts_only_unique_durable_message_events(self) -> None:
        first = _envelope("MESSAGE-ONE", "request-1")
        second = _envelope("MESSAGE-TWO", "request-2")
        with ReceiverStateStore(self.database_path) as store:
            self.assertEqual(store.ingest(first), IngestResult.ACCEPTED)
            self.assertEqual(store.ingest(first), IngestResult.DUPLICATE)
            self.assertEqual(store.ingest(second), IngestResult.ACCEPTED)
        _insert_non_message_event(self.database_path)

        self.assertEqual(received_message_count(self.database_path), 2)
        self.assertEqual(new_message_count(self.database_path, 1), 1)
        self.assertEqual(new_message_count(self.database_path, 2), 0)
        self.assertEqual(new_message_count(self.database_path, 3), 0)

    def test_live_wal_commits_are_visible_without_opening_a_writer(self) -> None:
        with ReceiverStateStore(self.database_path) as store:
            self.assertEqual(received_message_count(self.database_path), 0)
            store.ingest(_envelope("MESSAGE-ONE", "request-1"))
            self.assertEqual(received_message_count(self.database_path), 1)

    def test_missing_invalid_public_and_symlink_state_fail_without_creation(self) -> None:
        missing = self.root / "missing.db"
        with self.assertRaises(NotificationCountError):
            received_message_count(missing)
        self.assertFalse(missing.exists())

        invalid = self.root / "invalid.db"
        invalid.write_text("not sqlite", encoding="utf-8")
        invalid.chmod(0o600)
        with self.assertRaises(NotificationCountError):
            received_message_count(invalid)

        with ReceiverStateStore(self.database_path):
            pass
        self.database_path.chmod(0o644)
        with self.assertRaises(NotificationCountError):
            received_message_count(self.database_path)

        self.database_path.chmod(0o600)
        link = self.root / "receiver-link.db"
        link.symlink_to(self.database_path)
        with self.assertRaises(NotificationCountError):
            received_message_count(link)

    def test_previous_total_is_strictly_validated(self) -> None:
        with ReceiverStateStore(self.database_path):
            pass
        for value in (-1, True, 1.5, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                new_message_count(self.database_path, value)  # type: ignore[arg-type]


def _envelope(event_id: str, request_id: str):
    timestamp = 1_000_000_000
    event = MessageEvent(
        schema_version=1,
        event_kind=EventKind.MESSAGE,
        event_id=event_id,
        message_id=event_id,
        source_rowid=1,
        chat_id="CHAT-INVENTED",
        participant_ids=("PARTICIPANT-INVENTED",),
        sender=Sender(SenderKind.REMOTE_HANDLE, "PARTICIPANT-INVENTED"),
        direction=Direction.INCOMING,
        timestamp_raw_ns=timestamp,
        timestamp_utc=apple_nanoseconds_to_datetime(timestamp),
        text="invented message",
        attachments=(),
    )
    return decode_event_envelope(encode_event_envelope(event, request_id))


def _insert_non_message_event(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        INSERT INTO received_events(
            event_id, event_kind, event_json, event_digest,
            first_request_id, received_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "REACTION-ONE",
            "reaction_added",
            "{}",
            "0" * 64,
            "reaction-request",
            1,
        ),
    )
    connection.commit()
    connection.close()


if __name__ == "__main__":
    unittest.main()
