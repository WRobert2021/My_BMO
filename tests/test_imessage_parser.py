from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from iphone_relay import (
    AttachmentAvailability,
    AttributedBodyError,
    Direction,
    EventKind,
    MediaCategory,
    MessageEvent,
    MessagesReader,
    ReactionEvent,
    ReactionKind,
    SenderKind,
    SourceDatabaseError,
    SourceRecordError,
    SourceSchemaError,
    apple_nanoseconds_to_datetime,
    apple_seconds_to_datetime,
    open_read_only_database,
)
from iphone_relay.attributed_body import (
    MAX_ATTRIBUTED_BODY_BYTES,
    OBSERVED_ATTRIBUTED_STRING_PREFIX,
    extract_attributed_body_text,
    extract_message_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ParserFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.messages_root = root / "SMS"
        self.attachments_root = self.messages_root / "Attachments"
        self.attachments_root.mkdir(parents=True)
        self.database_path = self.messages_root / "sms.db"
        self.connection = sqlite3.connect(self.database_path)
        self._create_schema()
        self.connection.execute(
            "INSERT INTO handle(ROWID, id, service) VALUES (1, ?, 'iMessage')",
            ("+15550000001",),
        )
        self.connection.execute(
            "INSERT INTO chat(ROWID, guid, service_name) VALUES (1, ?, 'iMessage')",
            ("iMessage;-;+15550000001",),
        )
        self.connection.execute(
            "INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 1)"
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()

    def add_message(
        self,
        *,
        guid: str,
        text: object = "hello",
        attributed_body: object = None,
        service: str = "iMessage",
        is_from_me: int = 0,
        associated_type: int = 0,
        associated_guid: str | None = None,
        reply_to_guid: str | None = None,
        handle_id: int = 1,
        chat_id: int | None = 1,
        date: object = 1_000_000_000,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO message(
                guid, text, attributedBody, handle_id, service, account_guid,
                date, is_from_me, associated_message_guid,
                associated_message_type, associated_message_range_location,
                associated_message_range_length, reply_to_guid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (
                guid,
                text,
                attributed_body,
                handle_id,
                service,
                "self-account" if is_from_me else None,
                date,
                is_from_me,
                associated_guid,
                associated_type,
                reply_to_guid,
            ),
        )
        rowid = int(cursor.lastrowid)
        if chat_id is not None:
            self.connection.execute(
                "INSERT INTO chat_message_join(chat_id, message_id) VALUES (?, ?)",
                (chat_id, rowid),
            )
        self.connection.commit()
        return rowid

    def add_attachment(
        self,
        message_rowid: int,
        *,
        guid: str,
        relative_path: str,
        mime_type: str | None,
        uti: str | None,
        transfer_name: str,
        total_bytes: int,
    ) -> None:
        cursor = self.connection.execute(
            """
            INSERT INTO attachment(
                guid, filename, uti, mime_type, transfer_name, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guid,
                f"~/Library/SMS/Attachments/{relative_path}",
                uti,
                mime_type,
                transfer_name,
                total_bytes,
            ),
        )
        self.connection.execute(
            "INSERT INTO message_attachment_join(message_id, attachment_id) VALUES (?, ?)",
            (message_rowid, int(cursor.lastrowid)),
        )
        self.connection.commit()

    def reader(self) -> MessagesReader:
        self.connection.commit()
        return MessagesReader(self.database_path, messages_root=self.messages_root)

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE message (
                guid TEXT,
                text TEXT,
                attributedBody BLOB,
                handle_id INTEGER,
                service TEXT,
                account_guid TEXT,
                date INTEGER,
                is_from_me INTEGER,
                associated_message_guid TEXT,
                associated_message_type INTEGER NOT NULL DEFAULT 0,
                associated_message_range_location INTEGER,
                associated_message_range_length INTEGER,
                reply_to_guid TEXT
            );
            CREATE TABLE handle (id TEXT, service TEXT);
            CREATE TABLE chat (guid TEXT, service_name TEXT);
            CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
            CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
            CREATE TABLE attachment (
                guid TEXT,
                filename TEXT,
                uti TEXT,
                mime_type TEXT,
                transfer_name TEXT,
                total_bytes INTEGER
            );
            CREATE TABLE message_attachment_join (
                message_id INTEGER,
                attachment_id INTEGER
            );
            """
        )


class IMessageParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.fixture = ParserFixture(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary_directory.cleanup()

    def test_normalizes_incoming_text_sender_chat_and_timestamp(self) -> None:
        rowid = self.fixture.add_message(guid="MSG-IN", text="sanitized hello")

        batch = self.fixture.reader().scan()

        self.assertEqual(batch.scanned_row_count, 1)
        self.assertEqual(batch.scanned_through_rowid, rowid)
        self.assertEqual(batch.issues, ())
        self.assertEqual(len(batch.events), 1)
        event = batch.events[0]
        self.assertIsInstance(event, MessageEvent)
        self.assertEqual(event.event_id, "MSG-IN")
        self.assertEqual(event.message_id, "MSG-IN")
        self.assertEqual(event.direction, Direction.INCOMING)
        self.assertEqual(event.sender.kind, SenderKind.REMOTE_HANDLE)
        self.assertEqual(event.sender.identifier, "+15550000001")
        self.assertEqual(event.chat_id, "iMessage;-;+15550000001")
        self.assertEqual(event.participant_ids, ("+15550000001",))
        self.assertEqual(event.text, "sanitized hello")
        self.assertEqual(event.timestamp_utc.isoformat(), "2001-01-01T00:00:01+00:00")

    def test_excludes_sms_and_outgoing_ordinary_messages(self) -> None:
        self.fixture.add_message(guid="SMS", service="SMS")
        outgoing = self.fixture.add_message(guid="OUT", is_from_me=1)
        incoming = self.fixture.add_message(guid="IN")

        batch = self.fixture.reader().scan()

        self.assertEqual([event.event_id for event in batch.events], ["IN"])
        self.assertEqual(batch.scanned_row_count, 2)
        self.assertEqual(batch.scanned_through_rowid, incoming)
        self.assertGreater(incoming, outgoing)

    def test_group_participants_follow_service_scoped_chat_joins(self) -> None:
        self.fixture.connection.execute(
            "INSERT INTO handle(ROWID, id, service) VALUES (2, ?, 'iMessage')",
            ("member@example.invalid",),
        )
        self.fixture.connection.execute(
            "INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 2)"
        )
        self.fixture.connection.commit()
        self.fixture.add_message(guid="GROUP-SHAPE")

        event = self.fixture.reader().scan().events[0]

        self.assertEqual(
            event.participant_ids,
            ("+15550000001", "member@example.invalid"),
        )

    def test_normalizes_sent_and_received_reaction_events(self) -> None:
        self.fixture.add_message(
            guid="REACTION-ADD",
            text=None,
            is_from_me=1,
            associated_type=2000,
            associated_guid="p:0/TARGET-GUID",
        )
        self.fixture.add_message(
            guid="REACTION-REMOVE",
            text=None,
            associated_type=3001,
            associated_guid="p:2/TARGET-GUID",
            reply_to_guid="REACTION-ADD",
        )

        batch = self.fixture.reader().scan()

        added, removed = batch.events
        self.assertIsInstance(added, ReactionEvent)
        self.assertEqual(added.event_kind, EventKind.REACTION_ADDED)
        self.assertEqual(added.direction, Direction.OUTGOING)
        self.assertEqual(added.sender.kind, SenderKind.SELF)
        self.assertEqual(added.reaction_kind, ReactionKind.HEART)
        self.assertEqual(added.target_message_id, "TARGET-GUID")
        self.assertEqual(added.target_part, 0)
        self.assertEqual(removed.event_kind, EventKind.REACTION_REMOVED)
        self.assertEqual(removed.direction, Direction.INCOMING)
        self.assertEqual(removed.reaction_kind, ReactionKind.THUMBS_UP)
        self.assertEqual(removed.removed_event_id, "REACTION-ADD")
        self.assertEqual(removed.target_part, 2)

    def test_preserves_unproven_reaction_type_as_unknown(self) -> None:
        self.fixture.add_message(
            guid="REACTION-UNKNOWN",
            text=None,
            associated_type=2099,
            associated_guid="p:0/TARGET-GUID",
        )

        event = self.fixture.reader().scan().events[0]

        self.assertEqual(event.reaction_kind, ReactionKind.UNKNOWN)
        self.assertEqual(event.source_reaction_type, 2099)

    def test_maps_all_six_observed_standard_reactions(self) -> None:
        expected = {
            2000: ReactionKind.HEART,
            2001: ReactionKind.THUMBS_UP,
            2002: ReactionKind.THUMBS_DOWN,
            2003: ReactionKind.HAHA,
            2004: ReactionKind.EMPHASIZE,
            2005: ReactionKind.QUESTION,
        }
        for source_type in expected:
            self.fixture.add_message(
                guid=f"REACTION-{source_type}",
                text=None,
                associated_type=source_type,
                associated_guid="p:0/TARGET-GUID",
            )

        events = self.fixture.reader().scan().events

        self.assertEqual(
            {event.source_reaction_type: event.reaction_kind for event in events},
            expected,
        )

    def test_malformed_row_does_not_block_later_rows_or_cursor(self) -> None:
        invalid_rowid = self.fixture.add_message(guid="BAD", chat_id=None)
        valid_rowid = self.fixture.add_message(guid="GOOD")

        batch = self.fixture.reader().scan()

        self.assertEqual([event.event_id for event in batch.events], ["GOOD"])
        self.assertEqual(batch.scanned_through_rowid, valid_rowid)
        self.assertEqual(batch.issues[0].source_rowid, invalid_rowid)
        self.assertEqual(batch.issues[0].code, "message_invalid")

    def test_cursor_and_limit_are_source_row_based(self) -> None:
        first = self.fixture.add_message(guid="ONE")
        self.fixture.add_message(guid="OUT", is_from_me=1)
        third = self.fixture.add_message(guid="THREE")

        batch_one = self.fixture.reader().scan(limit=2)
        batch_two = self.fixture.reader().scan(after_rowid=batch_one.scanned_through_rowid)

        self.assertEqual([event.event_id for event in batch_one.events], ["ONE"])
        self.assertEqual(batch_one.scanned_row_count, 2)
        self.assertGreater(batch_one.scanned_through_rowid, first)
        self.assertEqual([event.event_id for event in batch_two.events], ["THREE"])
        self.assertEqual(batch_two.scanned_through_rowid, third)

    def test_repeating_same_scan_is_stable_for_caller_deduplication(self) -> None:
        self.fixture.add_message(guid="STABLE-GUID")

        first = self.fixture.reader().scan()
        repeated = self.fixture.reader().scan()

        self.assertEqual(first.events, repeated.events)
        self.assertEqual(first.events[0].event_id, "STABLE-GUID")

    def test_schema_validation_fails_before_scanning(self) -> None:
        self.fixture.close()
        bad_path = Path(self.temporary_directory.name) / "bad.db"
        connection = sqlite3.connect(bad_path)
        connection.execute("CREATE TABLE message(guid TEXT)")
        connection.close()
        self.fixture.connection = sqlite3.connect(self.fixture.database_path)

        with self.assertRaises(SourceSchemaError):
            MessagesReader(bad_path).scan()

    def test_source_database_is_enforced_read_only_and_unchanged(self) -> None:
        self.fixture.add_message(guid="READ-ONLY")
        self.fixture.close()
        before = _sha256(self.fixture.database_path)

        with self.assertRaises(SourceDatabaseError):
            with open_read_only_database(self.fixture.database_path) as connection:
                connection.execute("INSERT INTO message(guid) VALUES ('FORBIDDEN')")

        self.assertEqual(_sha256(self.fixture.database_path), before)
        self.fixture.connection = sqlite3.connect(self.fixture.database_path)

    def test_timestamp_conversion_uses_apple_epoch_and_integer_units(self) -> None:
        self.assertEqual(
            apple_nanoseconds_to_datetime(1_234_567_890).isoformat(),
            "2001-01-01T00:00:01.234567+00:00",
        )
        self.assertEqual(
            apple_seconds_to_datetime(86_400).isoformat(),
            "2001-01-02T00:00:00+00:00",
        )
        with self.assertRaises(SourceRecordError):
            apple_nanoseconds_to_datetime(-1)
        with self.assertRaises(SourceRecordError):
            apple_nanoseconds_to_datetime(10**40)

    def test_attributed_body_decoder_handles_observed_variant(self) -> None:
        archive = _typedstream("sanitized fallback text")

        self.assertEqual(
            extract_message_text(None, archive, has_attachments=False),
            "sanitized fallback text",
        )
        self.assertEqual(extract_attributed_body_text(_typedstream("x" * 200)), "x" * 200)

    def test_attributed_body_decoder_fails_closed(self) -> None:
        with self.assertRaises(AttributedBodyError):
            extract_attributed_body_text(b"random binary sanitized text")
        with self.assertRaises(AttributedBodyError):
            extract_attributed_body_text(_typedstream("hello")[:-1])
        with self.assertRaises(AttributedBodyError):
            extract_attributed_body_text(b"x" * (MAX_ATTRIBUTED_BODY_BYTES + 1))

    def test_bad_attributed_body_emits_issue_but_keeps_message(self) -> None:
        self.fixture.add_message(guid="BODY-BAD", text=None, attributed_body=b"unsupported")

        batch = self.fixture.reader().scan()

        self.assertEqual(batch.events[0].event_id, "BODY-BAD")
        self.assertIsNone(batch.events[0].text)
        self.assertEqual(batch.issues[0].code, "text_decode_failed")

    def test_photo_video_and_live_photo_classification(self) -> None:
        photo_row = self.fixture.add_message(guid="PHOTO", text="\ufffc")
        video_row = self.fixture.add_message(guid="VIDEO", text="\ufffc")
        live_row = self.fixture.add_message(guid="LIVE", text="\ufffc")
        self._write_attachment("aa/photo.jpg", b"photo")
        self._write_attachment("bb/video.mov", b"video")
        self._write_attachment("cc/live.jpg", b"still")
        self._write_attachment("cc/live.mov", b"motion")
        self._write_attachment("cc/cc.pvt/metadata.plist", b"metadata")
        self.fixture.add_attachment(
            photo_row,
            guid="ATT-PHOTO",
            relative_path="aa/photo.jpg",
            mime_type="image/jpeg",
            uti="public.jpeg",
            transfer_name="photo.jpg",
            total_bytes=999,
        )
        self.fixture.add_attachment(
            video_row,
            guid="ATT-VIDEO",
            relative_path="bb/video.mov",
            mime_type="video/quicktime",
            uti="com.apple.quicktime-movie",
            transfer_name="video.mov",
            total_bytes=5,
        )
        self.fixture.add_attachment(
            live_row,
            guid="ATT-LIVE",
            relative_path="cc/live.jpg",
            mime_type="image/jpeg",
            uti="public.jpeg",
            transfer_name="live.jpg",
            total_bytes=5,
        )

        batch = self.fixture.reader().scan()

        photo, video, live = batch.events
        self.assertIsNone(photo.text)
        self.assertEqual(photo.attachments[0].media_category, MediaCategory.PHOTO)
        self.assertEqual(photo.attachments[0].declared_bytes, 999)
        self.assertEqual(photo.attachments[0].actual_bytes, 5)
        self.assertEqual(video.attachments[0].media_category, MediaCategory.VIDEO)
        self.assertEqual(live.attachments[0].media_category, MediaCategory.LIVE_PHOTO)
        self.assertEqual(len(live.attachments[0].components), 2)
        self.assertEqual(batch.issues, ())

    def test_missing_and_unsafe_attachments_are_contained_failures(self) -> None:
        missing_row = self.fixture.add_message(guid="MISSING", text="\ufffc")
        unsafe_row = self.fixture.add_message(guid="UNSAFE", text="\ufffc")
        self.fixture.add_attachment(
            missing_row,
            guid="ATT-MISSING",
            relative_path="dd/missing.jpg",
            mime_type="image/jpeg",
            uti="public.jpeg",
            transfer_name="missing.jpg",
            total_bytes=1,
        )
        cursor = self.fixture.connection.execute(
            """
            INSERT INTO attachment(guid, filename, uti, mime_type, transfer_name, total_bytes)
            VALUES ('ATT-UNSAFE', '~/Library/SMS/Attachments/../escape.jpg',
                    'public.jpeg', 'image/jpeg', 'escape.jpg', 1)
            """
        )
        self.fixture.connection.execute(
            "INSERT INTO message_attachment_join(message_id, attachment_id) VALUES (?, ?)",
            (unsafe_row, int(cursor.lastrowid)),
        )
        self.fixture.connection.commit()

        batch = self.fixture.reader().scan()

        self.assertEqual(
            [event.attachments[0].availability for event in batch.events],
            [AttachmentAvailability.MISSING, AttachmentAvailability.UNSAFE],
        )
        self.assertEqual(
            [issue.code for issue in batch.issues],
            ["attachment_missing", "attachment_unsafe"],
        )

    def test_attachment_symlink_cannot_escape_messages_root(self) -> None:
        message_rowid = self.fixture.add_message(guid="SYMLINK", text="\ufffc")
        outside = self.fixture.root / "outside.jpg"
        outside.write_bytes(b"outside")
        link = self.fixture.attachments_root / "ee" / "linked.jpg"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        self.fixture.add_attachment(
            message_rowid,
            guid="ATT-SYMLINK",
            relative_path="ee/linked.jpg",
            mime_type="image/jpeg",
            uti="public.jpeg",
            transfer_name="linked.jpg",
            total_bytes=7,
        )

        batch = self.fixture.reader().scan()

        self.assertEqual(
            batch.events[0].attachments[0].availability,
            AttachmentAvailability.UNSAFE,
        )
        self.assertEqual(batch.issues[0].code, "attachment_unsafe")

    def _write_attachment(self, relative_path: str, data: bytes) -> None:
        path = self.fixture.attachments_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class SnapshotAcceptanceTests(unittest.TestCase):
    def test_current_snapshot_if_available(self) -> None:
        source = PROJECT_ROOT / "iphone_snapshot" / "SMS"
        required = [source / "sms.db", source / "sms.db-wal", source / "sms.db-shm"]
        if not all(path.is_file() for path in required):
            self.skipTest("ignored local Messages snapshot is unavailable")

        with tempfile.TemporaryDirectory() as temporary_directory:
            copied = Path(temporary_directory)
            for path in required:
                shutil.copy2(path, copied / path.name)
            batch = MessagesReader(
                copied / "sms.db",
                messages_root=source,
            ).scan(limit=100)

        self.assertEqual(batch.issues, ())
        self.assertEqual(batch.scanned_row_count, 36)
        self.assertEqual(batch.scanned_through_rowid, 38)
        self.assertEqual(len(batch.events), 35)
        messages = [event for event in batch.events if isinstance(event, MessageEvent)]
        reactions = [event for event in batch.events if isinstance(event, ReactionEvent)]
        self.assertEqual(len(messages), 24)
        self.assertEqual(len(reactions), 11)
        media = [attachment.media_category for event in messages for attachment in event.attachments]
        self.assertEqual(media.count(MediaCategory.PHOTO), 2)
        self.assertEqual(media.count(MediaCategory.VIDEO), 1)
        self.assertEqual(media.count(MediaCategory.LIVE_PHOTO), 1)


def _typedstream(text: str) -> bytes:
    encoded = text.encode("utf-8")
    if len(encoded) <= 0x7F:
        length = bytes([len(encoded)])
    elif len(encoded) <= 0x7FFF:
        length = b"\x81" + len(encoded).to_bytes(2, "little", signed=True)
    else:
        length = b"\x82" + len(encoded).to_bytes(4, "little", signed=True)
    return OBSERVED_ATTRIBUTED_STRING_PREFIX + length + encoded + b"\x86"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
