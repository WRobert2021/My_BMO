"""Stage 13 outbound command and durable kiosk-state tests."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from bmo.features.imessage_relay.outbound import (
    OUTBOUND_APPLICATION_ID,
    OUTBOUND_COMMAND_PATH,
    OUTBOUND_MEDIA_CHUNK_PATH_PREFIX,
    OUTBOUND_MEDIA_SESSION_PATH,
    OUTBOUND_SCHEMA_VERSION,
    OUTBOUND_STATUS_PATH,
    OutboundClientError,
    OutboundCommandAck,
    OutboundCommandClient,
    OutboundDestination,
    OutboundMediaCommand,
    OutboundMediaChunkAck,
    OutboundMediaReference,
    OutboundMediaSessionAck,
    OutboundProtocolError,
    OutboundReactionCommand,
    OutboundStateError,
    OutboundStateStore,
    OutboundTextCommand,
    OutboundTransportResponse,
    decode_command_response,
    decode_media_chunk_path,
    decode_media_chunk_response,
    decode_media_session_request,
    decode_media_session_response,
    decode_status_request,
    decode_submit_request,
    encode_command,
    encode_command_response,
    encode_media_chunk_response,
    encode_media_session_request,
    encode_media_session_response,
    encode_status_request,
    encode_submit_request,
    media_chunk_path,
)
from bmo.features.imessage_relay.phone_control import PhoneControlConfig
from bmo.features.imessage_relay.receiver.auth import RequestAuthenticator


CREATED_AT = "2026-09-12T12:34:56+00:00"
SECRET = b"invented-stage13-outbound-secret-material"


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


class SimulatedPhoneTransport:
    """Execute invented commands only and retain a phone-side ID ledger."""

    def __init__(self, *, send_boundary=None) -> None:
        self.authenticator = RequestAuthenticator(
            key_id="invented-outbound-key",
            shared_secret=SECRET,
            clock=lambda: 2_000_000_000,
        )
        self.send_boundary = send_boundary
        self.commands: dict[str, tuple[str, str]] = {}
        self.uploads: dict[str, tuple[object, bytearray]] = {}
        self.chunk_sizes: list[int] = []
        self.executions: list[str] = []
        self.lose_next_ack = False
        self.lose_next_chunk_ack = False
        self.closed = False

    def send(self, *, body, headers, path):
        method = "PUT" if path.startswith(OUTBOUND_MEDIA_CHUNK_PATH_PREFIX) else "POST"
        self.authenticator.verify(method, path, headers, body)
        if path == OUTBOUND_COMMAND_PATH:
            request_id, command = decode_submit_request(body)
            digest = hashlib.sha256(encode_command(command)).hexdigest()
            prior = self.commands.get(command.command_id)
            if prior is not None and prior[0] != digest:
                raise AssertionError("simulated phone accepted conflicting command ID")
            if prior is None:
                if self.send_boundary is not None:
                    self.send_boundary(command.command_id)
                self.commands[command.command_id] = (digest, "sent")
                self.executions.append(command.command_id)
                status = "accepted"
            else:
                status = "duplicate"
            if self.lose_next_ack:
                self.lose_next_ack = False
                raise TimeoutError("invented lost ACK")
            ack = OutboundCommandAck(command.command_id, status, "sent")
            status_code = 202
            response_body = encode_command_response(request_id=request_id, ack=ack)
        elif path == OUTBOUND_STATUS_PATH:
            request_id, command_id = decode_status_request(body)
            prior = self.commands.get(command_id)
            if prior is None:
                ack = OutboundCommandAck(
                    command_id, "status", "failed", "command_not_found"
                )
            else:
                ack = OutboundCommandAck(command_id, "status", prior[1])
            status_code = 200
            response_body = encode_command_response(request_id=request_id, ack=ack)
        elif path == OUTBOUND_MEDIA_SESSION_PATH:
            request_id, command_id, media = decode_media_session_request(body)
            upload_id = "upload-" + media.blob_id
            prior = self.uploads.get(upload_id)
            if prior is None:
                content = bytearray()
                self.uploads[upload_id] = (media, content)
            else:
                prior_media, content = prior
                if prior_media != media:
                    raise AssertionError("simulated phone accepted conflicting media")
            status = "complete" if len(content) == media.expected_bytes else "ready"
            ack = OutboundMediaSessionAck(
                command_id, media.blob_id, upload_id, len(content), status
            )
            status_code = 200 if prior is not None else 201
            response_body = encode_media_session_response(
                request_id=request_id, ack=ack
            )
        elif path.startswith(OUTBOUND_MEDIA_CHUNK_PATH_PREFIX):
            upload_id, offset, request_id = decode_media_chunk_path(path)
            media, content = self.uploads[upload_id]
            if len(content) != offset:
                raise AssertionError("simulated phone accepted wrong media offset")
            content.extend(body)
            self.chunk_sizes.append(len(body))
            if len(content) > media.expected_bytes:
                raise AssertionError("simulated phone accepted oversized media")
            status = "complete" if len(content) == media.expected_bytes else "partial"
            if status == "complete":
                self.assert_digest(media, content)
            if self.lose_next_chunk_ack:
                self.lose_next_chunk_ack = False
                raise TimeoutError("invented lost chunk ACK")
            ack = OutboundMediaChunkAck(upload_id, len(content), status)
            status_code = 200
            response_body = encode_media_chunk_response(
                request_id=request_id, ack=ack
            )
        else:
            raise AssertionError("unexpected simulated phone path")
        return OutboundTransportResponse(
            status_code,
            {"content-type": "application/json"},
            response_body,
        )

    @staticmethod
    def assert_digest(media, content):
        if hashlib.sha256(content).hexdigest() != media.sha256:
            raise AssertionError("simulated phone accepted wrong media digest")

    def close(self):
        self.closed = True


def client_config() -> PhoneControlConfig:
    return PhoneControlConfig(
        endpoint="http://127.0.0.1:8080",
        key_id="invented-outbound-key",
        shared_secret=SECRET,
        allow_insecure_loopback=True,
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

    def test_media_session_and_chunk_contracts_require_exact_identity(self) -> None:
        media = OutboundMediaReference(
            "blob-1", "invented.jpg", "photo", "image/jpeg", 10, "a" * 64
        )
        request = encode_media_session_request(
            request_id="session-request",
            command_id="command-1",
            media=media,
        )
        self.assertEqual(
            decode_media_session_request(request),
            ("session-request", "command-1", media),
        )
        session_ack = OutboundMediaSessionAck(
            "command-1", "blob-1", "upload-1", 0, "ready"
        )
        response = encode_media_session_response(
            request_id="session-request", ack=session_ack
        )
        self.assertEqual(
            decode_media_session_response(
                response,
                expected_request_id="session-request",
                expected_command_id="command-1",
                expected_blob_id="blob-1",
            ),
            session_ack,
        )

        path = media_chunk_path(
            upload_id="upload-1", offset=0, request_id="chunk-request"
        )
        self.assertEqual(
            decode_media_chunk_path(path), ("upload-1", 0, "chunk-request")
        )
        with self.assertRaises(OutboundProtocolError):
            decode_media_chunk_path(path + "/unexpected")

        chunk_ack = OutboundMediaChunkAck("upload-1", 10, "complete")
        chunk_response = encode_media_chunk_response(
            request_id="chunk-request", ack=chunk_ack
        )
        self.assertEqual(
            decode_media_chunk_response(
                chunk_response,
                expected_request_id="chunk-request",
                expected_upload_id="upload-1",
            ),
            chunk_ack,
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


class OutboundClientSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = OutboundStateStore(self.root / "outbound.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_all_command_kinds_are_durable_before_invented_execution(self) -> None:
        media_bytes = b"invented photo bytes" * 10
        media_path = self.root / "invented.jpg"
        media_path.write_bytes(media_bytes)
        def assert_durable_boundary(command_id: str) -> None:
            record = self.store.get(command_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.state, "executing")
            self.assertEqual(record.attempt_count, 1)

        transport = SimulatedPhoneTransport(send_boundary=assert_durable_boundary)
        identifiers = iter(
            (
                "text-request", "text-nonce",
                "session-request", "session-nonce",
                "chunk-request", "chunk-nonce",
                "media-request", "media-nonce",
                "reaction-request", "reaction-nonce",
            )
        )
        client = OutboundCommandClient(
            client_config(),
            self.store,
            transport=transport,
            clock=lambda: 2_000_000_000,
            identifier_factory=lambda: next(identifiers),
        )
        commands = (
            text_command("text-command"),
            OutboundMediaCommand(
                "media-command",
                CREATED_AT,
                destination(),
                (
                    OutboundMediaReference(
                        "blob-1",
                        "invented.jpg",
                        "photo",
                        "image/jpeg",
                        len(media_bytes),
                        hashlib.sha256(media_bytes).hexdigest(),
                    ),
                ),
            ),
            OutboundReactionCommand(
                "reaction-command",
                CREATED_AT,
                destination(reply=True),
                "message-invented-1",
                0,
                "heart",
                "add",
            ),
        )

        self.assertEqual(client.submit(commands[0]).state, "sent")
        self.assertEqual(
            client.submit(
                commands[1], media_sources={"blob-1": media_path}
            ).state,
            "sent",
        )
        self.assertEqual(client.submit(commands[2]).state, "sent")
        client.close()

        self.assertEqual(
            transport.executions,
            ["text-command", "media-command", "reaction-command"],
        )
        self.assertTrue(transport.closed)
        self.assertEqual(self.store.summary().sent_commands, 3)
        self.assertEqual(bytes(transport.uploads["upload-blob-1"][1]), media_bytes)

    def test_lost_ack_requires_status_and_does_not_execute_twice(self) -> None:
        transport = SimulatedPhoneTransport()
        transport.lose_next_ack = True
        identifiers = iter(
            ("submit-request", "submit-nonce", "status-request", "status-nonce")
        )
        client = OutboundCommandClient(
            client_config(),
            self.store,
            transport=transport,
            clock=lambda: 2_000_000_000,
            identifier_factory=lambda: next(identifiers),
        )
        command = text_command()

        with self.assertRaisesRegex(OutboundClientError, "phone_unreachable"):
            client.submit(command)
        self.assertEqual(self.store.get("command-1").state, "uncertain")
        with self.assertRaisesRegex(OutboundClientError, "outbound_status_required"):
            client.submit(command)
        self.assertEqual(transport.executions, ["command-1"])

        resolved = client.status("command-1")

        self.assertEqual(resolved.state, "sent")
        self.assertEqual(transport.executions, ["command-1"])

    def test_invalid_response_is_uncertain_and_content_is_not_in_error(self) -> None:
        class InvalidTransport:
            def send(self, *, body, headers, path):
                del body, headers, path
                return OutboundTransportResponse(
                    202, {"content-type": "text/plain"}, b"private response"
                )

            def close(self):
                pass

        client = OutboundCommandClient(
            client_config(),
            self.store,
            transport=InvalidTransport(),
            identifier_factory=iter(("request-1", "nonce-1")).__next__,
        )

        with self.assertRaises(OutboundClientError) as caught:
            client.submit(text_command(text="never expose this text"))

        self.assertEqual(caught.exception.code, "outbound_response_invalid")
        self.assertNotIn("never expose this text", str(caught.exception))
        self.assertNotIn("private response", str(caught.exception))
        self.assertEqual(self.store.get("command-1").state, "uncertain")

    def test_media_upload_resumes_after_lost_chunk_ack(self) -> None:
        media_bytes = b"x" * (64 * 1024 + 123)
        media_path = self.root / "invented-video.mp4"
        media_path.write_bytes(media_bytes)
        command = OutboundMediaCommand(
            "media-command",
            CREATED_AT,
            destination(),
            (
                OutboundMediaReference(
                    "blob-video",
                    "invented-video.mp4",
                    "video",
                    "video/mp4",
                    len(media_bytes),
                    hashlib.sha256(media_bytes).hexdigest(),
                ),
            ),
        )
        transport = SimulatedPhoneTransport()
        transport.lose_next_chunk_ack = True
        identifiers = (f"invented-{value}" for value in itertools.count())
        client = OutboundCommandClient(
            client_config(),
            self.store,
            transport=transport,
            clock=lambda: 2_000_000_000,
            identifier_factory=identifiers.__next__,
        )

        with self.assertRaisesRegex(OutboundClientError, "phone_unreachable"):
            client.submit(
                command, media_sources={"blob-video": media_path}
            )
        self.assertEqual(self.store.get("media-command").state, "queued")
        self.assertEqual(transport.executions, [])

        result = client.submit(
            command, media_sources={"blob-video": media_path}
        )

        self.assertEqual(result.state, "sent")
        self.assertEqual(transport.executions, ["media-command"])
        self.assertEqual(
            bytes(transport.uploads["upload-blob-video"][1]), media_bytes
        )
        self.assertTrue(all(size <= 64 * 1024 for size in transport.chunk_sizes))

    def test_media_sources_are_exact_and_safe(self) -> None:
        media_bytes = b"invented"
        source = self.root / "invented.jpg"
        source.write_bytes(media_bytes)
        command = OutboundMediaCommand(
            "media-command",
            CREATED_AT,
            destination(),
            (
                OutboundMediaReference(
                    "blob-1",
                    "invented.jpg",
                    "photo",
                    "image/jpeg",
                    len(media_bytes),
                    hashlib.sha256(media_bytes).hexdigest(),
                ),
            ),
        )
        transport = SimulatedPhoneTransport()
        identifiers = (f"invented-{value}" for value in itertools.count())
        client = OutboundCommandClient(
            client_config(),
            self.store,
            transport=transport,
            identifier_factory=identifiers.__next__,
        )

        with self.assertRaisesRegex(
            OutboundClientError, "outbound_media_sources_required"
        ):
            client.submit(command)
        with self.assertRaisesRegex(
            OutboundClientError, "outbound_media_sources_invalid"
        ):
            client.submit(command, media_sources={"wrong-blob": source})

        link = self.root / "link.jpg"
        link.symlink_to(source)
        with self.assertRaisesRegex(
            OutboundClientError, "outbound_media_source_invalid"
        ):
            client.submit(command, media_sources={"blob-1": link})
        self.assertEqual(transport.executions, [])


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
