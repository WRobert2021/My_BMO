from __future__ import annotations

from itertools import count
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import unittest

from iphone_relay import (
    Attachment,
    AttachmentAvailability,
    AttachmentComponent,
    AttachmentComponentRole,
    Direction,
    EventKind,
    MediaCategory,
    MessageEvent,
    QueueStatus,
    RelayStateStore,
    RetryPolicy,
    ScanBatch,
    Sender,
    SenderKind,
    apple_nanoseconds_to_datetime,
)
from iphone_relay.sender import (
    DeliveryDisposition,
    HTTPEventTransport,
    RelaySender,
    TransportResponse,
)
from kiosk_receiver import (
    ATTACHMENT_SESSION_PATH,
    EVENT_PATH,
    MAX_ATTACHMENT_CHUNK_BYTES,
    IngestResult,
    ReceiverApplication,
    ReceiverServer,
    ReceiverStateStore,
    RequestAuthenticator,
    attachment_chunk_path,
    decode_attachment_chunk_path,
    decode_attachment_chunk_response,
    decode_event_envelope,
    decode_upload_session_request,
    decode_upload_session_response,
    encode_event_envelope,
    upload_session_response_body,
)
from kiosk_receiver.protocol import (
    ProtocolError,
    attachment_chunk_response_body,
    encode_upload_session_request,
)
from kiosk_receiver.store import AttachmentDigestError


SECRET = b"invented-stage-seven-secret-at-least-32-bytes"
NOW_SECONDS = 2_000_000_000
JSON_HEADERS = {"content-type": "application/json"}


class AttachmentProtocolTests(unittest.TestCase):
    def test_manifest_session_and_chunk_contracts_are_strict_and_bounded(self) -> None:
        event = _event(
            1,
            "EVENT-ATTACHMENT",
            attachments=(
                _attachment(
                    event_id="EVENT-ATTACHMENT",
                    attachment_id="ATTACHMENT-ONE",
                    source_path=Path("/invented/not-read.bin"),
                    size=7,
                ),
            ),
        )
        envelope = decode_event_envelope(encode_event_envelope(event, "event-request"))
        self.assertEqual(
            [(item.blob_id, item.expected_bytes) for item in envelope.attachment_requirements],
            [("ATTACHMENT-ONE", 7)],
        )

        body = encode_upload_session_request(
            request_id="session-request",
            event_id=event.event_id,
            blob_id="ATTACHMENT-ONE",
            expected_bytes=7,
            content_sha256=hashlib.sha256(b"content").hexdigest(),
        )
        request = decode_upload_session_request(body)
        response = decode_upload_session_response(
            upload_session_response_body(
                request_id=request.request_id,
                upload_id="upload-1",
                next_offset=3,
                expected_bytes=7,
                status="ready",
            )
        )
        path = attachment_chunk_path(
            upload_id=response.upload_id,
            offset=response.next_offset,
            request_id="chunk-request",
        )
        self.assertEqual(
            decode_attachment_chunk_path(path),
            ("upload-1", 3, "chunk-request"),
        )
        chunk_response = decode_attachment_chunk_response(
            attachment_chunk_response_body(
                request_id="chunk-request",
                upload_id="upload-1",
                next_offset=7,
                status="complete",
            )
        )
        self.assertEqual(chunk_response.next_offset, 7)

        with self.assertRaises(ProtocolError):
            decode_attachment_chunk_path(
                "/v1/attachment-chunks/upload-1/03/chunk-request"
            )
        with self.assertRaises(ProtocolError):
            encode_upload_session_request(
                request_id="oversized",
                event_id=event.event_id,
                blob_id="ATTACHMENT-ONE",
                expected_bytes=2 * 1024 * 1024 * 1024 + 1,
                content_sha256="0" * 64,
            )


class AttachmentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_path = self.root / "receiver.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_partial_upload_resumes_across_restart_and_promotes_only_when_complete(self) -> None:
        content = b"a" * MAX_ATTACHMENT_CHUNK_BYTES + b"bounded-tail"
        event = _event_with_file(self.root, "EVENT-RESUME", content)
        envelope = decode_event_envelope(encode_event_envelope(event, "event-1"))
        request = decode_upload_session_request(
            encode_upload_session_request(
                request_id="session-1",
                event_id=event.event_id,
                blob_id="ATTACHMENT-EVENT-RESUME",
                expected_bytes=len(content),
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
        )

        with ReceiverStateStore(self.state_path) as store:
            self.assertEqual(
                store.ingest(envelope, received_at_ms=1),
                IngestResult.ATTACHMENTS_PENDING,
            )
            session = store.begin_attachment_upload(request, updated_at_ms=2)
            self.assertTrue(session.created)
            first = store.append_attachment_chunk(
                upload_id=session.upload_id,
                offset=0,
                chunk=content[:MAX_ATTACHMENT_CHUNK_BYTES],
                updated_at_ms=3,
            )
            self.assertFalse(first.complete)
            self.assertIsNone(store.get_event_json(event.event_id))

        with ReceiverStateStore(self.state_path) as reopened:
            resumed = reopened.begin_attachment_upload(request, updated_at_ms=4)
            self.assertFalse(resumed.created)
            self.assertEqual(resumed.next_offset, MAX_ATTACHMENT_CHUNK_BYTES)
            duplicate = reopened.append_attachment_chunk(
                upload_id=resumed.upload_id,
                offset=0,
                chunk=content[:MAX_ATTACHMENT_CHUNK_BYTES],
                updated_at_ms=5,
            )
            self.assertEqual(duplicate.next_offset, MAX_ATTACHMENT_CHUNK_BYTES)
            completed = reopened.append_attachment_chunk(
                upload_id=resumed.upload_id,
                offset=MAX_ATTACHMENT_CHUNK_BYTES,
                chunk=content[MAX_ATTACHMENT_CHUNK_BYTES:],
                updated_at_ms=6,
            )
            self.assertTrue(completed.complete)
            self.assertEqual(
                reopened.ingest(envelope, received_at_ms=7),
                IngestResult.ACCEPTED,
            )
            attachment = reopened.get_attachment(
                event.event_id,
                "ATTACHMENT-EVENT-RESUME",
            )
            self.assertTrue(attachment.complete)
            self.assertEqual(_sha256(attachment.storage_path), hashlib.sha256(content).hexdigest())
            self.assertEqual(stat.S_IMODE(attachment.storage_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(reopened.attachment_root.stat().st_mode), 0o700)
            self.assertEqual(reopened.summary().event_count, 1)
            self.assertEqual(reopened.summary().pending_event_count, 0)

    def test_digest_mismatch_resets_partial_state_without_acknowledging_event(self) -> None:
        content = b"invented attachment"
        event = _event_with_file(self.root, "EVENT-DIGEST", content)
        envelope = decode_event_envelope(encode_event_envelope(event, "event-1"))
        with ReceiverStateStore(self.state_path) as store:
            self.assertEqual(
                store.ingest(envelope, received_at_ms=1),
                IngestResult.ATTACHMENTS_PENDING,
            )
            wrong = decode_upload_session_request(
                encode_upload_session_request(
                    request_id="wrong",
                    event_id=event.event_id,
                    blob_id="ATTACHMENT-EVENT-DIGEST",
                    expected_bytes=len(content),
                    content_sha256="0" * 64,
                )
            )
            session = store.begin_attachment_upload(wrong, updated_at_ms=2)
            with self.assertRaises(AttachmentDigestError):
                store.append_attachment_chunk(
                    upload_id=session.upload_id,
                    offset=0,
                    chunk=content,
                    updated_at_ms=3,
                )
            attachment = store.get_attachment(
                event.event_id,
                "ATTACHMENT-EVENT-DIGEST",
            )
            self.assertEqual(attachment.received_bytes, 0)
            self.assertFalse(attachment.complete)
            self.assertIsNone(store.get_event_json(event.event_id))

    def test_version_one_receiver_store_migrates_without_losing_receipts(self) -> None:
        _create_version_one_receiver(self.state_path)
        with ReceiverStateStore(self.state_path) as store:
            self.assertEqual(store.get_event_json("LEGACY-EVENT"), "{}")
            self.assertEqual(store.summary().event_count, 1)
        raw = sqlite3.connect(self.state_path)
        try:
            self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 2)
            tables = {
                row[0]
                for row in raw.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertIn("pending_events", tables)
            self.assertIn("attachment_uploads", tables)
        finally:
            raw.close()


class AttachmentSenderAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.relay_path = self.root / "relay.db"
        self.receiver_path = self.root / "receiver.db"
        self.policy = RetryPolicy(
            initial_delay_ms=10,
            multiplier=2,
            max_delay_ms=20,
            max_attempts=3,
            lease_duration_ms=5,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_sender_streams_bounded_chunks_and_requires_attachment_complete_ack(self) -> None:
        content = bytes(range(251)) * 600
        event = _event_with_file(self.root, "EVENT-STREAM", content)
        source_path = Path(event.attachments[0].source_path)
        source_digest = _sha256(source_path)
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as relay_store:
            relay_store.commit_scan(ScanBatch((event,), (), 1, 1), expected_after_rowid=0, now_ms=1)
            with ReceiverStateStore(self.receiver_path) as receiver_store:
                transport = ApplicationTransport(_application(receiver_store))
                sender = _sender(relay_store, transport, prefix="stream")
                result = sender.deliver_once(now_ms=10)
                sender.close()

                self.assertEqual(result.disposition, DeliveryDisposition.ACKNOWLEDGED)
                self.assertEqual(
                    relay_store.get_entry(event.event_id).status,
                    QueueStatus.ACKNOWLEDGED,
                )
                self.assertEqual(receiver_store.summary().event_count, 1)
                self.assertGreater(len(transport.put_sizes), 1)
                self.assertLessEqual(max(transport.put_sizes), MAX_ATTACHMENT_CHUNK_BYTES)
                attachment = receiver_store.get_attachment(
                    event.event_id,
                    "ATTACHMENT-EVENT-STREAM",
                )
                self.assertEqual(
                    _sha256(attachment.storage_path),
                    hashlib.sha256(content).hexdigest(),
                )
                self.assertEqual(_sha256(source_path), source_digest)

    def test_interrupted_chunk_resumes_from_durable_offset_after_both_restarts(self) -> None:
        content = b"r" * MAX_ATTACHMENT_CHUNK_BYTES + b"resume-tail"
        event = _event_with_file(self.root, "EVENT-RESTART", content)
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as relay_store:
            relay_store.commit_scan(ScanBatch((event,), (), 1, 1), expected_after_rowid=0, now_ms=1)
            with ReceiverStateStore(self.receiver_path) as receiver_store:
                first_transport = ApplicationTransport(
                    _application(receiver_store),
                    drop_after_put_count=1,
                )
                first_sender = _sender(relay_store, first_transport, prefix="first")
                first = first_sender.deliver_once(now_ms=10)
                first_sender.close()
                self.assertEqual(first.disposition, DeliveryDisposition.RETRY_SCHEDULED)
                partial = receiver_store.get_attachment(
                    event.event_id,
                    "ATTACHMENT-EVENT-RESTART",
                )
                self.assertEqual(partial.received_bytes, MAX_ATTACHMENT_CHUNK_BYTES)

        with RelayStateStore(self.relay_path, retry_policy=self.policy) as relay_reopened:
            with ReceiverStateStore(self.receiver_path) as receiver_reopened:
                second_transport = ApplicationTransport(_application(receiver_reopened))
                second_sender = _sender(relay_reopened, second_transport, prefix="second")
                second = second_sender.deliver_once(now_ms=20)
                second_sender.close()
                self.assertEqual(second.disposition, DeliveryDisposition.ACKNOWLEDGED)
                self.assertEqual(second_transport.put_offsets, [MAX_ATTACHMENT_CHUNK_BYTES])
                self.assertEqual(receiver_reopened.summary().event_count, 1)

    def test_live_photo_transfers_each_component_once(self) -> None:
        still_content = b"s" * (MAX_ATTACHMENT_CHUNK_BYTES + 1)
        motion_content = b"invented-motion"
        still_path = self.root / "invented-still.heic"
        motion_path = self.root / "invented-motion.mov"
        still_path.write_bytes(still_content)
        motion_path.write_bytes(motion_content)
        event = _event(
            1,
            "EVENT-LIVE",
            attachments=(
                Attachment(
                    attachment_id="ATTACHMENT-LIVE",
                    parent_message_id="EVENT-LIVE",
                    transfer_name="invented.heic",
                    uti="public.heic",
                    mime_type="image/heic",
                    media_category=MediaCategory.LIVE_PHOTO,
                    source_path=str(still_path),
                    declared_bytes=len(still_content),
                    actual_bytes=len(still_content),
                    availability=AttachmentAvailability.AVAILABLE,
                    components=(
                        AttachmentComponent(
                            component_id="ATTACHMENT-LIVE:still",
                            role=AttachmentComponentRole.STILL,
                            source_path=str(still_path),
                            actual_bytes=len(still_content),
                        ),
                        AttachmentComponent(
                            component_id="ATTACHMENT-LIVE:motion",
                            role=AttachmentComponentRole.MOTION,
                            source_path=str(motion_path),
                            actual_bytes=len(motion_content),
                        ),
                    ),
                ),
            ),
        )
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as relay_store:
            relay_store.commit_scan(
                ScanBatch((event,), (), 1, 1),
                expected_after_rowid=0,
                now_ms=1,
            )
            with ReceiverStateStore(self.receiver_path) as receiver_store:
                transport = ApplicationTransport(_application(receiver_store))
                sender = _sender(relay_store, transport, prefix="live")
                result = sender.deliver_once(now_ms=10)
                sender.close()
                self.assertEqual(result.disposition, DeliveryDisposition.ACKNOWLEDGED)
                self.assertIsNone(
                    receiver_store.get_attachment(event.event_id, "ATTACHMENT-LIVE")
                )
                still = receiver_store.get_attachment(
                    event.event_id,
                    "ATTACHMENT-LIVE:still",
                )
                motion = receiver_store.get_attachment(
                    event.event_id,
                    "ATTACHMENT-LIVE:motion",
                )
                self.assertEqual(
                    _sha256(still.storage_path),
                    hashlib.sha256(still_content).hexdigest(),
                )
                self.assertEqual(
                    _sha256(motion.storage_path),
                    hashlib.sha256(motion_content).hexdigest(),
                )
                self.assertEqual(receiver_store.summary().complete_attachment_count, 2)

    def test_unavailable_source_and_legacy_metadata_only_ack_fail_closed(self) -> None:
        unavailable = _event(
            1,
            "EVENT-UNAVAILABLE",
            attachments=(
                Attachment(
                    attachment_id="ATTACHMENT-UNAVAILABLE",
                    parent_message_id="EVENT-UNAVAILABLE",
                    transfer_name="missing.jpg",
                    uti="public.jpeg",
                    mime_type="image/jpeg",
                    media_category=MediaCategory.PHOTO,
                    source_path=str(self.root / "missing.jpg"),
                    declared_bytes=10,
                    actual_bytes=None,
                    availability=AttachmentAvailability.MISSING,
                ),
            ),
        )
        content = b"legacy-ack"
        available = _event_with_file(self.root, "EVENT-LEGACY", content, rowid=2)
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as relay_store:
            relay_store.commit_scan(
                ScanBatch((unavailable, available), (), 2, 2),
                expected_after_rowid=0,
                now_ms=1,
            )
            transport = LegacyAckTransport()
            sender = _sender(relay_store, transport, prefix="failure")
            missing_result = sender.deliver_once(now_ms=10)
            legacy_result = sender.deliver_once(now_ms=10)
            sender.close()
            self.assertEqual(missing_result.error_code, "attachment_source_unavailable")
            self.assertEqual(legacy_result.error_code, "malformed_response")
            self.assertEqual(transport.calls, 1)
            self.assertEqual(relay_store.summary().acknowledged_count, 0)

    def test_real_loopback_http_streams_attachment_without_whole_file_request(self) -> None:
        content = b"h" * (MAX_ATTACHMENT_CHUNK_BYTES + 17)
        event = _event_with_file(self.root, "EVENT-HTTP", content)
        relay_store = RelayStateStore(self.relay_path, retry_policy=self.policy)
        relay_store.commit_scan(ScanBatch((event,), (), 1, 1), expected_after_rowid=0, now_ms=1)
        receiver_store = ReceiverStateStore(self.receiver_path)
        server = ReceiverServer(
            ("127.0.0.1", 0),
            _application(receiver_store, live_clock=True),
            max_request_bytes=4096,
            request_timeout_seconds=2,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        transport = HTTPEventTransport(
            f"http://127.0.0.1:{server.server_address[1]}",
            timeout_seconds=2,
            allow_insecure_loopback=True,
        )
        sender = RelaySender(
            store=relay_store,
            transport=transport,
            key_id="test-client",
            shared_secret=SECRET,
        )
        try:
            result = sender.deliver_once(now_ms=10)
            self.assertEqual(result.disposition, DeliveryDisposition.ACKNOWLEDGED)
            self.assertEqual(receiver_store.summary().complete_attachment_count, 1)
        finally:
            sender.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            receiver_store.close()
            relay_store.close()
        self.assertFalse(thread.is_alive())


class ApplicationTransport:
    def __init__(
        self,
        application: ReceiverApplication,
        *,
        drop_after_put_count: int | None = None,
    ) -> None:
        self.application = application
        self.drop_after_put_count = drop_after_put_count
        self.put_sizes: list[int] = []
        self.put_offsets: list[int] = []
        self.closed = False

    def send(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        path: str = EVENT_PATH,
        method: str = "POST",
    ) -> TransportResponse:
        response = self.application.handle(
            method=method,
            path=path,
            headers=headers,
            body=body,
        )
        if method == "PUT":
            self.put_sizes.append(len(body))
            _, offset, _ = decode_attachment_chunk_path(path)
            self.put_offsets.append(offset)
            if self.drop_after_put_count == len(self.put_sizes):
                raise TimeoutError
        return TransportResponse(response.status_code, JSON_HEADERS, response.body)

    def close(self) -> None:
        self.closed = True


class LegacyAckTransport:
    def __init__(self) -> None:
        self.calls = 0

    def send(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        path: str = EVENT_PATH,
        method: str = "POST",
    ) -> TransportResponse:
        del headers, path, method
        self.calls += 1
        envelope = decode_event_envelope(body)
        legacy = {
            "protocol_version": 1,
            "request_id": envelope.request_id,
            "result": "ack",
            "status": "accepted",
            "event_id": envelope.event_id,
        }
        return TransportResponse(
            201,
            JSON_HEADERS,
            json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode(),
        )

    def close(self) -> None:
        pass


def _sender(
    store: RelayStateStore,
    transport,
    *,
    prefix: str,
) -> RelaySender:
    identifiers = count(1)
    return RelaySender(
        store=store,
        transport=transport,
        key_id="test-client",
        shared_secret=SECRET,
        clock=lambda: NOW_SECONDS,
        identifier_factory=lambda: f"{prefix}-{next(identifiers)}",
    )


def _application(
    store: ReceiverStateStore,
    *,
    live_clock: bool = False,
) -> ReceiverApplication:
    clock = None if live_clock else (lambda: NOW_SECONDS)
    authenticator = RequestAuthenticator(
        key_id="test-client",
        shared_secret=SECRET,
        max_clock_skew_seconds=300,
        **({} if live_clock else {"clock": clock}),
    )
    return ReceiverApplication(
        store=store,
        authenticator=authenticator,
        **({} if live_clock else {"clock": clock}),
    )


def _event_with_file(
    root: Path,
    event_id: str,
    content: bytes,
    *,
    rowid: int = 1,
) -> MessageEvent:
    source = root / f"{event_id}.bin"
    source.write_bytes(content)
    return _event(
        rowid,
        event_id,
        attachments=(
            _attachment(
                event_id=event_id,
                attachment_id=f"ATTACHMENT-{event_id}",
                source_path=source,
                size=len(content),
            ),
        ),
    )


def _event(
    rowid: int,
    event_id: str,
    *,
    attachments: tuple[Attachment, ...] = (),
) -> MessageEvent:
    timestamp = rowid * 1_000_000_000
    return MessageEvent(
        schema_version=1,
        event_kind=EventKind.MESSAGE,
        event_id=event_id,
        message_id=event_id,
        source_rowid=rowid,
        chat_id="INVENTED-CHAT",
        participant_ids=("INVENTED-PARTICIPANT",),
        sender=Sender(SenderKind.REMOTE_HANDLE, "INVENTED-PARTICIPANT"),
        direction=Direction.INCOMING,
        timestamp_raw_ns=timestamp,
        timestamp_utc=apple_nanoseconds_to_datetime(timestamp),
        text="invented attachment message",
        attachments=attachments,
    )


def _attachment(
    *,
    event_id: str,
    attachment_id: str,
    source_path: Path,
    size: int,
) -> Attachment:
    return Attachment(
        attachment_id=attachment_id,
        parent_message_id=event_id,
        transfer_name="invented.bin",
        uti="public.data",
        mime_type="application/octet-stream",
        media_category=MediaCategory.UNKNOWN,
        source_path=str(source_path),
        declared_bytes=size,
        actual_bytes=size,
        availability=AttachmentAvailability.AVAILABLE,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(MAX_ATTACHMENT_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _create_version_one_receiver(path: Path) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE received_events (
            event_id TEXT PRIMARY KEY NOT NULL,
            event_kind TEXT NOT NULL,
            event_json TEXT NOT NULL,
            event_digest TEXT NOT NULL,
            first_request_id TEXT NOT NULL,
            received_at_ms INTEGER NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE authentication_nonces (
            key_id TEXT NOT NULL,
            nonce TEXT NOT NULL,
            signed_at_seconds INTEGER NOT NULL,
            received_at_seconds INTEGER NOT NULL,
            PRIMARY KEY(key_id, nonce)
        ) WITHOUT ROWID;
        INSERT INTO received_events VALUES (
            'LEGACY-EVENT', 'message', '{}',
            '0000000000000000000000000000000000000000000000000000000000000000',
            'legacy-request', 1
        );
        PRAGMA application_id = 1229802322;
        PRAGMA user_version = 1;
        """
    )
    connection.commit()
    connection.close()


if __name__ == "__main__":
    unittest.main()
