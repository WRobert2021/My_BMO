"""Stage 13 outbound command and durable kiosk-state tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from bmo.features.imessage_relay.outbound import (
    OUTBOUND_APPLICATION_ID,
    OUTBOUND_SCHEMA_VERSION,
    OutboundCommandAck,
    OutboundDestination,
    OutboundMediaCommand,
    OutboundMediaReference,
    OutboundProtocolError,
    OutboundReactionCommand,
    OutboundStateError,
    OutboundStateStore,
    OutboundTextCommand,
    decode_command_response,
    decode_status_request,
    decode_submit_request,
    encode_command,
    encode_command_response,
    encode_status_request,
    encode_submit_request,
)


CREATED_AT = "2026-09-12T12:34:56+00:00"


def destination(*, reply: bool = False) -> OutboundDestination:
    return OutboundDestination(
        ("+15555550100",),
        chat_id="chat-invented-1" if reply else None,
        reply_to_message_id="message-invented-1" if reply else None,
    )


def text_command(command_id: str = "command-1", text: str = "Invented hello"):
    return OutboundTextCommand(
        command_id=command_id,
        created_at_utc=CREATED_AT,
        destination=destination(),
        text=text,
    )


class OutboundProtocolTests(unittest.TestCase):
    def test_text_request_is_canonical_and_round_trips(self) -> None:
        command = text_command()
        body = encode_submit_request(request_id="request-1", command=command)

        self.assertEqual(
            body,
            b'{"command":{"command_id":"command-1","created_at_utc":'
            b'"2026-09-12T12:34:56+00:00","destination":{"chat_id":null,'
            b'"recipient_ids":["+15555550100"],"reply_to_message_id":null},'
            b'"kind":"text","schema_version":1,"text":"Invented hello"},'
            b'"protocol_version":1,"request_id":"request-1"}',
        )
        self.assertEqual(decode_submit_request(body), ("request-1", command))

    def test_destination_requires_canonical_explicit_recipients(self) -> None:
        with self.assertRaises(OutboundProtocolError):
            OutboundDestination(())
        with self.assertRaises(OutboundProtocolError):
            OutboundDestination(("555-555-0100",))
        with self.assertRaises(OutboundProtocolError):
            OutboundDestination(("+15555550100", "+15555550100"))
        with self.assertRaises(OutboundProtocolError):
            OutboundDestination(
                ("+15555550100",), reply_to_message_id="message-invented-1"
            )

        self.assertEqual(
            OutboundDestination(("invented@example.test",)).recipient_ids,
            ("invented@example.test",),
        )

    def test_timestamp_and_text_are_bounded(self) -> None:
        for timestamp in (
            "2026-09-12T12:34:56",
            "2026-09-12T12:34:56Z",
            "2026-09-12T12:34:56.1+00:00",
            "2026-09-12T07:34:56-05:00",
        ):
            with self.subTest(timestamp=timestamp), self.assertRaises(
                OutboundProtocolError
            ):
                OutboundTextCommand("command-1", timestamp, destination(), "hello")
        for text in ("", " \n\t", "bad\x00text", "x" * (32 * 1024 + 1)):
            with self.subTest(text_length=len(text)), self.assertRaises(
                OutboundProtocolError
            ):
                text_command(text=text)

    def test_media_command_is_path_free_and_round_trips(self) -> None:
        media = OutboundMediaReference(
            blob_id="blob-1",
            transfer_name="invented-photo.jpg",
            media_category="photo",
            mime_type="image/jpeg",
            expected_bytes=1234,
            sha256="a" * 64,
        )
        command = OutboundMediaCommand(
            "command-media-1", CREATED_AT, destination(), (media,), "caption"
        )

        encoded = encode_command(command)
        self.assertNotIn(b"/home/", encoded)
        self.assertEqual(decode_submit_request(encode_submit_request(
            request_id="request-media-1", command=command
        ))[1], command)

        for name in ("../photo.jpg", "folder/photo.jpg", r"folder\photo.jpg"):
            with self.subTest(name=name), self.assertRaises(OutboundProtocolError):
                OutboundMediaReference(
                    "blob-1", name, "photo", "image/jpeg", 1, "a" * 64
                )
        with self.assertRaises(OutboundProtocolError):
            OutboundMediaReference(
                "blob-1", "empty.jpg", "photo", "image/jpeg", 0, "a" * 64
            )
        with self.assertRaises(OutboundProtocolError):
            OutboundMediaReference(
                "blob-1", "wrong.jpg", "photo", "video/mp4", 1, "a" * 64
            )

    def test_reaction_requires_stable_target_and_supported_operation(self) -> None:
        command = OutboundReactionCommand(
            "command-reaction-1",
            CREATED_AT,
            destination(reply=True),
            "message-invented-1",
            0,
            "thumbs_up",
            "add",
        )
        self.assertEqual(
            decode_submit_request(
                encode_submit_request(request_id="request-reaction-1", command=command)
            )[1],
            command,
        )
        with self.assertRaises(OutboundProtocolError):
            OutboundReactionCommand(
                "command-reaction-2",
                CREATED_AT,
                destination(reply=True),
                "message-invented-1",
                0,
                "like",
                "add",
            )

    def test_decoder_rejects_unknown_and_duplicate_fields(self) -> None:
        command = text_command()
        value = json.loads(encode_submit_request(request_id="request-1", command=command))
        value["unexpected"] = True
        with self.assertRaises(OutboundProtocolError):
            decode_submit_request(json.dumps(value).encode())
        with self.assertRaises(OutboundProtocolError):
            decode_submit_request(
                b'{"protocol_version":1,"protocol_version":1,'
                b'"request_id":"request-1","command":{}}'
            )

    def test_status_request_and_response_require_exact_identity(self) -> None:
        status_request = encode_status_request(
            request_id="request-2", command_id="command-1"
        )
        self.assertEqual(
            status_request,
            b'{"action":"status","command_id":"command-1",'
            b'"protocol_version":1,"request_id":"request-2"}',
        )
        self.assertEqual(
            decode_status_request(status_request), ("request-2", "command-1")
        )
        response = encode_command_response(
            request_id="request-2",
            ack=OutboundCommandAck("command-1", "status", "sent"),
        )
        self.assertEqual(
            decode_command_response(
                response,
                expected_request_id="request-2",
                expected_command_id="command-1",
            ),
            OutboundCommandAck("command-1", "status", "sent"),
        )
        with self.assertRaises(OutboundProtocolError):
            decode_command_response(
                response,
                expected_request_id="different-request",
                expected_command_id="command-1",
            )

    def test_failure_ack_requires_bounded_error_and_success_forbids_it(self) -> None:
        with self.assertRaises(OutboundProtocolError):
            OutboundCommandAck("command-1", "accepted", "failed")
        with self.assertRaises(OutboundProtocolError):
            OutboundCommandAck("command-1", "accepted", "sent", "unexpected")
        self.assertEqual(
            OutboundCommandAck("command-1", "status", "uncertain", "ack_timeout"),
            OutboundCommandAck("command-1", "status", "uncertain", "ack_timeout"),
        )


class OutboundStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.path = self.root / "outbound.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_creates_private_identified_database(self) -> None:
        with OutboundStateStore(self.path):
            pass

        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(
                connection.execute("PRAGMA application_id").fetchone()[0],
                OUTBOUND_APPLICATION_ID,
            )
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                OUTBOUND_SCHEMA_VERSION,
            )
        finally:
            connection.close()

    def test_enqueue_is_durable_idempotent_and_conflict_safe(self) -> None:
        command = text_command()
        with OutboundStateStore(self.path) as store:
            first = store.enqueue(command, now_ms=100)
            duplicate = store.enqueue(command, now_ms=200)
            self.assertEqual(first, duplicate)
            self.assertEqual(first.state, "queued")
            self.assertEqual(first.attempt_count, 0)
            with self.assertRaises(OutboundStateError):
                store.enqueue(text_command(text="Different content"), now_ms=300)

        with OutboundStateStore(self.path) as reopened:
            self.assertEqual(reopened.get("command-1"), first)
            self.assertEqual(reopened.summary().queued_commands, 1)

    def test_attempt_uncertain_and_terminal_ack_survive_restart(self) -> None:
        with OutboundStateStore(self.path) as store:
            store.enqueue(text_command(), now_ms=100)
            attempt = store.record_attempt("command-1", "request-1", now_ms=110)
            self.assertEqual(attempt.state, "executing")
            self.assertEqual(attempt.attempt_count, 1)
            uncertain = store.mark_uncertain(
                "command-1", "ack_timeout", now_ms=120
            )
            self.assertEqual(uncertain.state, "uncertain")
            second = store.record_attempt("command-1", "request-2", now_ms=130)
            self.assertEqual(second.state, "executing")
            self.assertEqual(second.attempt_count, 2)
            sent = store.apply_ack(
                OutboundCommandAck("command-1", "duplicate", "sent"),
                now_ms=140,
            )
            self.assertEqual(sent.state, "sent")

        with OutboundStateStore(self.path) as reopened:
            self.assertEqual(reopened.get("command-1").state, "sent")
            with self.assertRaises(OutboundStateError):
                reopened.record_attempt("command-1", "request-3", now_ms=150)
            with self.assertRaises(OutboundStateError):
                reopened.mark_uncertain("command-1", "ack_timeout", now_ms=160)

    def test_pending_order_summary_and_close_are_bounded(self) -> None:
        store = OutboundStateStore(self.path)
        store.enqueue(text_command("command-b"), now_ms=100)
        store.enqueue(text_command("command-a"), now_ms=100)
        store.enqueue(text_command("command-c"), now_ms=200)
        store.apply_ack(
            OutboundCommandAck("command-c", "accepted", "failed", "send_rejected"),
            now_ms=210,
        )

        self.assertEqual(
            [record.command_id for record in store.pending()],
            ["command-a", "command-b"],
        )
        summary = store.summary()
        self.assertEqual(summary.total_commands, 3)
        self.assertEqual(summary.queued_commands, 2)
        self.assertEqual(summary.failed_commands, 1)
        with self.assertRaises(ValueError):
            store.pending(0)
        store.close()
        store.close()
        with self.assertRaises(OutboundStateError):
            store.summary()

    def test_rejects_apple_path_symlink_and_exposed_existing_file(self) -> None:
        for name in ("sms.db", "chat.db"):
            with self.subTest(name=name), self.assertRaises(OutboundStateError):
                OutboundStateStore(self.root / name)

        target = self.root / "target.db"
        target.write_bytes(b"")
        os.chmod(target, 0o600)
        link = self.root / "link.db"
        link.symlink_to(target)
        with self.assertRaises(OutboundStateError):
            OutboundStateStore(link)

        exposed = self.root / "exposed.db"
        exposed.write_bytes(b"")
        os.chmod(exposed, 0o644)
        with self.assertRaises(OutboundStateError):
            OutboundStateStore(exposed)


if __name__ == "__main__":
    unittest.main()
