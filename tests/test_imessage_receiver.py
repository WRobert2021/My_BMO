from __future__ import annotations

from dataclasses import replace
import http.client
import json
from pathlib import Path
import socket
import sqlite3
import stat
import tempfile
import threading
import time
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
    Sender,
    SenderKind,
    apple_nanoseconds_to_datetime,
)
from kiosk_receiver import (
    AuthenticationError,
    IngestResult,
    MAX_RECONCILIATION_CANDIDATES,
    ProtocolError,
    ReconciliationCandidate,
    ReconciliationReceipt,
    ReceiverApplication,
    ReceiverConfig,
    ReceiverConfigError,
    ReceiverServer,
    ReceiverStateStore,
    RequestAuthenticator,
    decode_event_envelope,
    decode_reconciliation_request,
    decode_reconciliation_response,
    encode_event_envelope,
    encode_reconciliation_request,
    event_wire_digest,
    event_to_wire_mapping,
    reconciliation_response_body,
    build_server,
    load_receiver_config,
    sign_request,
)
from kiosk_receiver.store import (
    EventConflictError,
    ReceiverStoreError,
    ReceiverStoreSecurityError,
    ReplayError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET = b"invented-test-secret-with-at-least-32-bytes"
NOW = 2_000_000_000


class ReceiverProtocolTests(unittest.TestCase):
    def test_wire_event_omits_source_rowid_and_all_source_paths(self) -> None:
        event = _message_event(attachments=(_attachment(),))

        mapping = event_to_wire_mapping(event)
        encoded = encode_event_envelope(event, "request-1")
        decoded = decode_event_envelope(encoded)

        self.assertNotIn("source_rowid", mapping)
        self.assertNotIn("source_path", encoded.decode("utf-8"))
        self.assertEqual(decoded.event_id, event.event_id)
        self.assertEqual(decoded.event_kind, "message")

    def test_envelope_has_deterministic_canonical_event_payload(self) -> None:
        event = _message_event()
        first = decode_event_envelope(encode_event_envelope(event, "request-1"))
        second_body = json.dumps(
            {
                "event": event_to_wire_mapping(event),
                "request_id": "request-2",
                "protocol_version": 1,
            },
            indent=2,
        ).encode()
        second = decode_event_envelope(second_body)

        self.assertEqual(first.event_json, second.event_json)
        self.assertEqual(first.event_digest, second.event_digest)

    def test_invalid_unknown_duplicate_and_nonfinite_fields_are_rejected(self) -> None:
        valid = json.loads(encode_event_envelope(_message_event(), "request-1"))
        cases = []
        unknown = json.loads(json.dumps(valid))
        unknown["unknown"] = True
        cases.append(json.dumps(unknown).encode())
        bad_version = json.loads(json.dumps(valid))
        bad_version["protocol_version"] = 2
        cases.append(json.dumps(bad_version).encode())
        cases.append(b'{"protocol_version":1,"protocol_version":1}')
        cases.append(b'{"protocol_version":NaN}')
        source_path = json.loads(json.dumps(valid))
        source_path["event"]["source_rowid"] = 123
        cases.append(json.dumps(source_path).encode())

        for index, body in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ProtocolError):
                decode_event_envelope(body)

    def test_attachment_and_timestamp_invariants_are_enforced(self) -> None:
        value = json.loads(encode_event_envelope(_message_event(attachments=(_attachment(),)), "r-1"))
        value["event"]["attachments"][0]["parent_message_id"] = "OTHER"
        with self.assertRaises(ProtocolError):
            decode_event_envelope(json.dumps(value).encode())

        value = json.loads(encode_event_envelope(_message_event(), "r-2"))
        value["event"]["timestamp_utc"] = "not-a-date+00:00"
        with self.assertRaises(ProtocolError):
            decode_event_envelope(json.dumps(value).encode())

        value = json.loads(encode_event_envelope(_message_event(), "r-3"))
        value["event"]["timestamp_utc"] = "2001-01-01T00:00:02+00:00"
        with self.assertRaises(ProtocolError):
            decode_event_envelope(json.dumps(value).encode())

    def test_reconciliation_request_and_response_are_strict_and_bounded(self) -> None:
        candidate = ReconciliationCandidate(
            "EVENT-INVENTED",
            event_wire_digest(_message_event()),
        )
        request = decode_reconciliation_request(
            encode_reconciliation_request((candidate,), "reconcile-1")
        )
        response = decode_reconciliation_response(
            reconciliation_response_body(
                request_id=request.request_id,
                receipts=(ReconciliationReceipt(candidate.event_id, "present"),),
            )
        )

        self.assertEqual(request.candidates, (candidate,))
        self.assertEqual(response.receipts[0].status, "present")

        duplicate = json.loads(encode_reconciliation_request((candidate,), "duplicate"))
        duplicate["candidates"].append(duplicate["candidates"][0])
        with self.assertRaises(ProtocolError):
            decode_reconciliation_request(json.dumps(duplicate).encode())
        with self.assertRaises(ProtocolError):
            encode_reconciliation_request(
                (candidate,) * (MAX_RECONCILIATION_CANDIDATES + 1),
                "oversized",
            )
        with self.assertRaises(ProtocolError):
            encode_reconciliation_request(
                (ReconciliationCandidate("EVENT-INVENTED", "not-a-digest"),),
                "bad-digest",
            )
        maximum_candidates = tuple(
            ReconciliationCandidate("\x01" * 510 + f"{index:02d}", "0" * 64)
            for index in range(MAX_RECONCILIATION_CANDIDATES)
        )
        maximum_receipts = tuple(
            ReconciliationReceipt(candidate.event_id, "missing")
            for candidate in maximum_candidates
        )
        self.assertLessEqual(
            len(encode_reconciliation_request(maximum_candidates, "maximum")),
            64 * 1024,
        )
        self.assertLessEqual(
            len(
                reconciliation_response_body(
                    request_id="maximum",
                    receipts=maximum_receipts,
                )
            ),
            64 * 1024,
        )

class ReceiverAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authenticator = RequestAuthenticator(
            key_id="test-client",
            shared_secret=SECRET,
            max_clock_skew_seconds=300,
            clock=lambda: NOW,
        )
        self.body = b'{"invented":true}'

    def test_valid_signature_authenticates_bound_method_path_and_body(self) -> None:
        headers = _headers("nonce-1", body=self.body)
        result = self.authenticator.verify("POST", "/v1/events", headers, self.body)
        self.assertEqual(result.key_id, "test-client")
        self.assertEqual(result.nonce, "nonce-1")

    def test_missing_unknown_stale_and_changed_requests_fail_closed(self) -> None:
        valid = _headers("nonce-1", body=self.body)
        cases = (
            ({}, self.body),
            ({**valid, "X-Relay-Key-Id": "unknown"}, self.body),
            (_headers("nonce-2", timestamp=NOW - 301, body=self.body), self.body),
            (valid, b'{"invented":false}'),
        )
        for index, (headers, body) in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(AuthenticationError):
                self.authenticator.verify("POST", "/v1/events", headers, body)


class ReceiverStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_path = self.root / "receiver.db"
        self.envelope = decode_event_envelope(encode_event_envelope(_message_event(), "request-1"))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_accept_duplicate_and_conflict_are_durable(self) -> None:
        with ReceiverStateStore(self.state_path) as store:
            self.assertEqual(store.ingest(self.envelope, received_at_ms=100), IngestResult.ACCEPTED)
            self.assertEqual(store.ingest(self.envelope, received_at_ms=200), IngestResult.DUPLICATE)
            self.assertEqual(store.summary().event_count, 1)

            changed = decode_event_envelope(
                encode_event_envelope(_message_event(text="changed"), "request-2")
            )
            with self.assertRaises(EventConflictError):
                store.ingest(changed, received_at_ms=300)

        with ReceiverStateStore(self.state_path) as reopened:
            self.assertEqual(reopened.summary().event_count, 1)
            self.assertEqual(reopened.get_event_json("EVENT-INVENTED"), self.envelope.event_json)

    def test_nonce_replay_is_rejected_across_restart(self) -> None:
        with ReceiverStateStore(self.state_path) as store:
            store.reserve_nonce(
                key_id="test-client",
                nonce="nonce-1",
                signed_at_seconds=NOW,
                now_seconds=NOW,
                retention_seconds=601,
            )
        with ReceiverStateStore(self.state_path) as reopened:
            with self.assertRaises(ReplayError):
                reopened.reserve_nonce(
                    key_id="test-client",
                    nonce="nonce-1",
                    signed_at_seconds=NOW,
                    now_seconds=NOW,
                    retention_seconds=601,
                )

    def test_state_file_is_private_and_schema_is_identified(self) -> None:
        with ReceiverStateStore(self.state_path):
            pass
        self.assertEqual(stat.S_IMODE(self.state_path.stat().st_mode), 0o600)
        raw = sqlite3.connect(self.state_path)
        self.assertEqual(raw.execute("PRAGMA application_id").fetchone()[0], 0x494D4B52)
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 2)
        raw.close()

    def test_symlink_and_broad_permissions_are_rejected(self) -> None:
        target = self.root / "target.db"
        target.touch(mode=0o600)
        link = self.root / "link.db"
        link.symlink_to(target)
        with self.assertRaises(ReceiverStoreSecurityError):
            ReceiverStateStore(link)

        target.chmod(0o644)
        with self.assertRaises(ReceiverStoreSecurityError):
            ReceiverStateStore(target)

    def test_storage_failure_rolls_back_without_an_ackable_commit(self) -> None:
        with ReceiverStateStore(self.state_path) as store:
            raw = sqlite3.connect(self.state_path)
            raw.execute(
                """
                CREATE TRIGGER fail_event BEFORE INSERT ON received_events
                BEGIN SELECT RAISE(ABORT, 'injected'); END
                """
            )
            raw.commit()
            raw.close()
            with self.assertRaises(ReceiverStoreError):
                store.ingest(self.envelope, received_at_ms=100)
            self.assertEqual(store.summary().event_count, 0)

    def test_reconciliation_classifies_candidates_without_deleting_kiosk_history(self) -> None:
        kiosk_only = decode_event_envelope(
            encode_event_envelope(
                replace(
                    _message_event(text="kiosk-only"),
                    event_id="KIOSK-ONLY",
                    message_id="KIOSK-ONLY",
                ),
                "kiosk-only-request",
            )
        )
        with ReceiverStateStore(self.state_path) as store:
            store.ingest(self.envelope, received_at_ms=100)
            store.ingest(kiosk_only, received_at_ms=101)
            receipts = store.reconcile_receipts(
                (
                    ReconciliationCandidate(
                        self.envelope.event_id,
                        self.envelope.event_digest,
                    ),
                    ReconciliationCandidate("MISSING", "0" * 64),
                    ReconciliationCandidate(
                        "KIOSK-ONLY",
                        "1" * 64,
                    ),
                )
            )

            self.assertEqual(
                [receipt.status for receipt in receipts],
                ["present", "missing", "conflict"],
            )
            self.assertEqual(store.summary().event_count, 2)
            self.assertIsNotNone(store.get_event_json("KIOSK-ONLY"))


class ReceiverApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = ReceiverStateStore(self.root / "receiver.db")
        self.app = ReceiverApplication(
            store=self.store,
            authenticator=RequestAuthenticator(
                key_id="test-client",
                shared_secret=SECRET,
                max_clock_skew_seconds=300,
                clock=lambda: NOW,
            ),
            clock=lambda: NOW,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_health_status_and_unknown_routes_require_authentication(self) -> None:
        unauthorized = self.app.handle(method="GET", path="/v1/health", headers={}, body=b"")
        health = self._request("GET", "/v1/health", b"", "health-1")
        status = self._request("GET", "/v1/status", b"", "status-1")
        missing = self._request("GET", "/v1/unknown", b"", "missing-1")

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(_json(health.body)["status"], "ok")
        self.assertEqual(_json(status.body)["event_count"], 0)
        self.assertEqual(missing.status_code, 404)

    def test_ack_follows_commit_duplicate_ack_is_stable_and_conflict_nacks(self) -> None:
        accepted_body = encode_event_envelope(_message_event(), "request-1")
        accepted = self._request("POST", "/v1/events", accepted_body, "event-1")
        duplicate_body = encode_event_envelope(_message_event(), "request-2")
        duplicate = self._request("POST", "/v1/events", duplicate_body, "event-2")
        conflict_body = encode_event_envelope(_message_event(text="changed"), "request-3")
        conflict = self._request("POST", "/v1/events", conflict_body, "event-3")

        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(_json(accepted.body)["result"], "ack")
        self.assertEqual(_json(accepted.body)["event_id"], "EVENT-INVENTED")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(_json(duplicate.body)["status"], "duplicate")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(_json(conflict.body)["error"]["code"], "event_conflict")
        self.assertEqual(self.store.summary().event_count, 1)

    def test_replay_malformed_and_storage_unavailable_return_nacks(self) -> None:
        body = encode_event_envelope(_message_event(), "request-1")
        first = self._request("POST", "/v1/events", body, "same-nonce")
        replay = self._request("POST", "/v1/events", body, "same-nonce")
        malformed = self._request("POST", "/v1/events", b"not-json", "malformed-1")
        self.store.close()
        unavailable = self._request("POST", "/v1/events", body, "storage-1")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(_json(replay.body)["error"]["code"], "replay_detected")
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(_json(malformed.body)["result"], "nack")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(_json(unavailable.body)["error"]["code"], "storage_unavailable")

    def test_authenticated_reconciliation_reports_only_requested_receipts(self) -> None:
        event_body = encode_event_envelope(_message_event(), "seed-request")
        self._request("POST", "/v1/events", event_body, "seed-nonce")
        candidate = ReconciliationCandidate(
            "EVENT-INVENTED",
            event_wire_digest(_message_event()),
        )
        body = encode_reconciliation_request(
            (candidate, ReconciliationCandidate("MISSING", "0" * 64)),
            "reconcile-request",
        )

        response = self._request(
            "POST",
            "/v1/reconciliation",
            body,
            "reconcile-nonce",
        )
        decoded = decode_reconciliation_response(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [receipt.status for receipt in decoded.receipts],
            ["present", "missing"],
        )
        self.assertEqual(self.store.summary().event_count, 1)

    def _request(self, method: str, path: str, body: bytes, nonce: str):
        return self.app.handle(
            method=method,
            path=path,
            headers=_headers(nonce, method=method, path=path, body=body),
            body=body,
        )


class ReceiverHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = ReceiverStateStore(self.root / "receiver.db")
        app = ReceiverApplication(
            store=self.store,
            authenticator=RequestAuthenticator(
                key_id="test-client",
                shared_secret=SECRET,
                max_clock_skew_seconds=300,
            ),
        )
        self.server = ReceiverServer(
            ("127.0.0.1", 0),
            app,
            max_request_bytes=4096,
            request_timeout_seconds=1,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()
        self.temporary_directory.cleanup()

    def test_loopback_http_serves_authenticated_json_and_rejects_oversize(self) -> None:
        timestamp = int(time.time())
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        health_headers = sign_request(
            SECRET,
            key_id="test-client",
            method="GET",
            path="/v1/health",
            timestamp=timestamp,
            nonce="http-health",
        )
        connection.request("GET", "/v1/health", headers=health_headers)
        health = connection.getresponse()
        health_body = health.read()
        self.assertEqual(health.status, 200)
        self.assertEqual(_json(health_body)["status"], "ok")

        event_body = encode_event_envelope(_message_event(), "http-request-1")
        event_headers = sign_request(
            SECRET,
            key_id="test-client",
            method="POST",
            path="/v1/events",
            timestamp=timestamp,
            nonce="http-event",
            body=event_body,
        )
        event_headers["Content-Type"] = "application/json"
        connection.request("POST", "/v1/events", body=event_body, headers=event_headers)
        event_response = connection.getresponse()
        self.assertEqual(event_response.status, 201)
        self.assertEqual(_json(event_response.read())["event_id"], "EVENT-INVENTED")
        self.assertEqual(self.store.summary().event_count, 1)

        reconciliation_body = encode_reconciliation_request(
            (
                ReconciliationCandidate(
                    "EVENT-INVENTED",
                    event_wire_digest(_message_event()),
                ),
            ),
            "http-reconcile-1",
        )
        reconciliation_headers = sign_request(
            SECRET,
            key_id="test-client",
            method="POST",
            path="/v1/reconciliation",
            timestamp=timestamp,
            nonce="http-reconciliation",
            body=reconciliation_body,
        )
        reconciliation_headers["Content-Type"] = "application/json"
        connection.request(
            "POST",
            "/v1/reconciliation",
            body=reconciliation_body,
            headers=reconciliation_headers,
        )
        reconciliation_response = connection.getresponse()
        decoded_reconciliation = decode_reconciliation_response(
            reconciliation_response.read()
        )
        self.assertEqual(reconciliation_response.status, 200)
        self.assertEqual(decoded_reconciliation.receipts[0].status, "present")

        oversized = b"{" + b"x" * 4096
        connection.request(
            "POST",
            "/v1/events",
            body=oversized,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        self.assertEqual(_json(response.read())["error"]["code"], "request_too_large")
        connection.close()

    def test_partial_request_times_out_with_json_nack(self) -> None:
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        connection.sendall(
            b"POST /v1/events HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Type: application/json\r\nContent-Length: 10\r\n\r\n{}"
        )
        response = b""
        while b"request_timeout" not in response:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response += chunk
        connection.close()
        self.assertIn(b"408", response)
        self.assertIn(b"request_timeout", response)


class ReceiverConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_example_config_resolves_paths_and_secret_from_environment(self) -> None:
        config = load_receiver_config(
            PROJECT_ROOT / "config" / "example.imessage_receiver.json",
            environ={"IMESSAGE_RELAY_SHARED_SECRET": SECRET.decode()},
            base_directory=self.root,
        )
        self.assertEqual(config.bind_host, "0.0.0.0")
        self.assertEqual(config.port, 8443)
        self.assertEqual(
            config.state_path,
            (self.root / "data/imessage_receiver/receiver.db").resolve(),
        )
        self.assertNotIn(SECRET.decode(), repr(config))

    def test_missing_secret_and_insecure_nonloopback_fail_before_service_start(self) -> None:
        example = PROJECT_ROOT / "config" / "example.imessage_receiver.json"
        with self.assertRaises(ReceiverConfigError):
            load_receiver_config(example, environ={}, base_directory=self.root)

        with self.assertRaises(ReceiverConfigError):
            ReceiverConfig(
                bind_host="0.0.0.0",
                port=8443,
                state_path=self.root / "receiver.db",
                tls_cert_path=None,
                tls_key_path=None,
                allow_insecure_loopback=True,
                key_id="test-client",
                shared_secret=SECRET,
            )
        self.assertFalse((self.root / "receiver.db").exists())

    def test_explicit_loopback_development_configuration_is_allowed(self) -> None:
        config = ReceiverConfig(
            bind_host="127.0.0.1",
            port=0,
            state_path=self.root / "receiver.db",
            tls_cert_path=None,
            tls_key_path=None,
            allow_insecure_loopback=True,
            key_id="test-client",
            shared_secret=SECRET,
        )
        self.assertTrue(config.allow_insecure_loopback)

    def test_unavailable_tls_files_fail_before_state_or_service_creation(self) -> None:
        config = ReceiverConfig(
            bind_host="127.0.0.1",
            port=0,
            state_path=self.root / "receiver.db",
            tls_cert_path=self.root / "missing.crt",
            tls_key_path=self.root / "missing.key",
            allow_insecure_loopback=False,
            key_id="test-client",
            shared_secret=SECRET,
        )
        with self.assertRaises(OSError):
            build_server(config)
        self.assertFalse(config.state_path.exists())


def _message_event(
    *,
    text: str = "invented hello",
    attachments: tuple[Attachment, ...] = (),
) -> MessageEvent:
    timestamp = 1_000_000_000
    return MessageEvent(
        schema_version=1,
        event_kind=EventKind.MESSAGE,
        event_id="EVENT-INVENTED",
        message_id="EVENT-INVENTED",
        source_rowid=42,
        chat_id="CHAT-INVENTED",
        participant_ids=("PARTICIPANT-INVENTED",),
        sender=Sender(SenderKind.REMOTE_HANDLE, "PARTICIPANT-INVENTED"),
        direction=Direction.INCOMING,
        timestamp_raw_ns=timestamp,
        timestamp_utc=apple_nanoseconds_to_datetime(timestamp),
        text=text,
        attachments=attachments,
    )


def _attachment() -> Attachment:
    return Attachment(
        attachment_id="ATTACHMENT-INVENTED",
        parent_message_id="EVENT-INVENTED",
        transfer_name="invented.jpg",
        uti="public.jpeg",
        mime_type="image/jpeg",
        media_category=MediaCategory.LIVE_PHOTO,
        source_path="/private/invented/photo.jpg",
        declared_bytes=100,
        actual_bytes=90,
        availability=AttachmentAvailability.AVAILABLE,
        components=(
            AttachmentComponent(
                component_id="COMPONENT-INVENTED",
                role=AttachmentComponentRole.STILL,
                source_path="/private/invented/still.jpg",
                actual_bytes=90,
            ),
        ),
    )


def _headers(
    nonce: str,
    *,
    method: str = "POST",
    path: str = "/v1/events",
    timestamp: int = NOW,
    body: bytes = b"",
) -> dict[str, str]:
    return sign_request(
        SECRET,
        key_id="test-client",
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )


def _json(body: bytes) -> dict[str, object]:
    value = json.loads(body)
    assert isinstance(value, dict)
    return value


if __name__ == "__main__":
    unittest.main()
