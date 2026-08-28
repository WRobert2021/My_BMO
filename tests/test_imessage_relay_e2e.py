from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from iphone_relay import (
    Direction,
    EventKind,
    MessageEvent,
    MessagesReader,
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
    EVENT_PATH,
    HTTPEventTransport,
    RelaySender,
    SenderClosedError,
    TransportResponse,
)
from kiosk_receiver import (
    ReceiverApplication,
    ReceiverServer,
    ReceiverStateStore,
    RequestAuthenticator,
)
from kiosk_receiver.protocol import decode_event_envelope, response_body


SECRET = b"invented-stage-five-secret-at-least-32-bytes"
NOW_SECONDS = 2_000_000_000
JSON_HEADERS = {"content-type": "application/json"}


class SimulatedRelayAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.relay_path = self.root / "relay.db"
        self.receiver_path = self.root / "receiver.db"
        self.policy = RetryPolicy(
            initial_delay_ms=10,
            multiplier=2,
            max_delay_ms=20,
            max_attempts=2,
            lease_duration_ms=5,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_parser_queue_http_receiver_chain_is_durable_and_path_free(self) -> None:
        source_path = _create_messages_database(
            self.root / "source",
            (("EVENT-ONE", "invented one"), ("EVENT-TWO", "invented two")),
        )
        source_hash = _sha256(source_path)
        batch = MessagesReader(source_path).scan()

        relay_store = RelayStateStore(self.relay_path, retry_policy=self.policy)
        relay_store.commit_scan(batch, expected_after_rowid=0, now_ms=1)
        receiver_store = ReceiverStateStore(self.receiver_path)
        application = _application(receiver_store)
        server = ReceiverServer(
            ("127.0.0.1", 0),
            application,
            max_request_bytes=4096,
            request_timeout_seconds=1,
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
            clock=lambda: NOW_SECONDS,
        )
        try:
            first = sender.deliver_once(now_ms=10)
            second = sender.deliver_once(now_ms=10)
            idle = sender.deliver_once(now_ms=10)

            self.assertEqual(first.disposition, DeliveryDisposition.ACKNOWLEDGED)
            self.assertEqual(second.disposition, DeliveryDisposition.ACKNOWLEDGED)
            self.assertEqual(idle.disposition, DeliveryDisposition.IDLE)
            self.assertEqual(relay_store.summary().acknowledged_count, 2)
            self.assertEqual(receiver_store.summary().event_count, 2)
            received = receiver_store.get_event_json("EVENT-ONE")
            self.assertNotIn("source_rowid", received)
            self.assertNotIn(str(source_path), received)
            self.assertEqual(_sha256(source_path), source_hash)
        finally:
            sender.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            receiver_store.close()
            relay_store.close()
        self.assertFalse(thread.is_alive())

    def test_offline_before_and_during_send_schedule_bounded_retries(self) -> None:
        cases = (ConnectionRefusedError(), ConnectionResetError())
        for index, failure in enumerate(cases):
            with self.subTest(index=index):
                path = self.root / f"offline-{index}.db"
                with RelayStateStore(path, retry_policy=self.policy) as store:
                    _commit(store, _event(1, f"OFFLINE-{index}"))
                    transport = ScriptedTransport([failure])
                    with RelaySender(
                        store=store,
                        transport=transport,
                        key_id="test-client",
                        shared_secret=SECRET,
                        clock=lambda: NOW_SECONDS,
                    ) as sender:
                        result = sender.deliver_once(now_ms=100)

                    entry = store.get_entry(f"OFFLINE-{index}")
                    self.assertEqual(result.error_code, "transport_unavailable")
                    self.assertEqual(entry.status, QueueStatus.RETRY_WAIT)
                    self.assertEqual(entry.next_attempt_at_ms, 110)

    def test_lost_ack_retries_same_event_with_fresh_auth_after_both_restarts(self) -> None:
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as store:
            _commit(store, _event(1, "LOST-ACK"))
            with ReceiverStateStore(self.receiver_path) as receiver_store:
                first_transport = ApplicationTransport(
                    _application(receiver_store),
                    drop_after_commit=True,
                )
                with RelaySender(
                    store=store,
                    transport=first_transport,
                    key_id="test-client",
                    shared_secret=SECRET,
                    clock=lambda: NOW_SECONDS,
                    identifier_factory=_identifiers("first-request", "first-nonce"),
                ) as sender:
                    first = sender.deliver_once(now_ms=100)
                self.assertEqual(first.error_code, "ack_timeout")
                self.assertEqual(receiver_store.summary().event_count, 1)

        with RelayStateStore(self.relay_path, retry_policy=self.policy) as reopened:
            with ReceiverStateStore(self.receiver_path) as receiver_reopened:
                second_transport = ApplicationTransport(_application(receiver_reopened))
                with RelaySender(
                    store=reopened,
                    transport=second_transport,
                    key_id="test-client",
                    shared_secret=SECRET,
                    clock=lambda: NOW_SECONDS,
                    identifier_factory=_identifiers("second-request", "second-nonce"),
                ) as sender:
                    second = sender.deliver_once(now_ms=110)

                self.assertEqual(second.disposition, DeliveryDisposition.ACKNOWLEDGED)
                self.assertEqual(receiver_reopened.summary().event_count, 1)
                self.assertEqual(
                    decode_event_envelope(first_transport.bodies[0]).event_json,
                    decode_event_envelope(second_transport.bodies[0]).event_json,
                )
                self.assertNotEqual(
                    first_transport.headers[0]["X-Relay-Nonce"],
                    second_transport.headers[0]["X-Relay-Nonce"],
                )
                self.assertNotEqual(
                    json.loads(first_transport.bodies[0])["request_id"],
                    json.loads(second_transport.bodies[0])["request_id"],
                )

    def test_nacks_malformed_responses_and_ack_mismatch_never_acknowledge(self) -> None:
        nack = TransportResponse(
            401,
            JSON_HEADERS,
            response_body(
                request_id=None,
                result="nack",
                error_code="stale_request",
            ),
        )
        malformed = TransportResponse(201, JSON_HEADERS, b"not-json")
        mismatch = TransportResponse(
            201,
            JSON_HEADERS,
            response_body(
                request_id="wrong-request",
                result="ack",
                status="accepted",
                event_id="THIRD",
            ),
        )
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as store:
            _commit(
                store,
                _event(1, "FIRST"),
                _event(2, "SECOND"),
                _event(3, "THIRD"),
            )
            with RelaySender(
                store=store,
                transport=ScriptedTransport([nack, malformed, mismatch]),
                key_id="test-client",
                shared_secret=SECRET,
                clock=lambda: NOW_SECONDS,
            ) as sender:
                results = [sender.deliver_once(now_ms=100) for _ in range(3)]

            self.assertEqual(
                [result.error_code for result in results],
                ["stale_request", "malformed_response", "ack_mismatch"],
            )
            self.assertEqual(store.summary().acknowledged_count, 0)
            self.assertEqual(store.summary().retry_wait_count, 3)

    def test_backlog_order_poison_bypass_requeue_and_recovery(self) -> None:
        poison_nack = TransportResponse(
            400,
            JSON_HEADERS,
            response_body(
                request_id=None,
                result="nack",
                error_code="invalid_schema",
            ),
        )
        one_attempt = RetryPolicy(
            initial_delay_ms=10,
            multiplier=2,
            max_delay_ms=20,
            max_attempts=1,
            lease_duration_ms=5,
        )
        with RelayStateStore(self.relay_path, retry_policy=one_attempt) as store:
            _commit(
                store,
                _event(1, "POISON"),
                _event(2, "SECOND"),
                _event(3, "THIRD"),
            )
            transport = AckingTransport(first_response=poison_nack)
            with RelaySender(
                store=store,
                transport=transport,
                key_id="test-client",
                shared_secret=SECRET,
                clock=lambda: NOW_SECONDS,
            ) as sender:
                results = [sender.deliver_once(now_ms=100) for _ in range(3)]

            self.assertEqual(transport.event_ids, ["POISON", "SECOND", "THIRD"])
            self.assertEqual(results[0].disposition, DeliveryDisposition.DEAD_LETTERED)
            self.assertEqual(store.get_entry("POISON").status, QueueStatus.DEAD_LETTER)
            self.assertEqual(store.summary().acknowledged_count, 2)

            store.requeue_dead_letter("POISON", now_ms=200)
            recovery = AckingTransport()
            with RelaySender(
                store=store,
                transport=recovery,
                key_id="test-client",
                shared_secret=SECRET,
                clock=lambda: NOW_SECONDS,
            ) as sender:
                recovered = sender.deliver_once(now_ms=200)
            self.assertEqual(recovered.disposition, DeliveryDisposition.ACKNOWLEDGED)
            self.assertEqual(store.summary().acknowledged_count, 3)

    def test_sigint_closes_sender_and_status_contains_no_message_content(self) -> None:
        with RelayStateStore(self.relay_path, retry_policy=self.policy) as store:
            _commit(store, _event(1, "PRIVATE-EVENT", text="private invented text"))
            transport = AckingTransport()
            statuses = []

            def interrupt(_seconds: float) -> None:
                raise KeyboardInterrupt

            sender = RelaySender(
                store=store,
                transport=transport,
                key_id="test-client",
                shared_secret=SECRET,
                clock=lambda: NOW_SECONDS,
            )
            final_status = sender.run_forever(
                poll_interval_seconds=0.01,
                wait=interrupt,
                on_status=statuses.append,
            )

            self.assertTrue(transport.closed)
            self.assertEqual(final_status.acknowledged_count, 1)
            self.assertGreaterEqual(len(statuses), 2)
            status_text = repr(statuses)
            self.assertNotIn("PRIVATE-EVENT", status_text)
            self.assertNotIn("private invented text", status_text)
            with self.assertRaises(SenderClosedError):
                sender.deliver_once()


class SenderTransportContractTests(unittest.TestCase):
    def test_plain_http_requires_explicit_loopback_and_close_is_idempotent(self) -> None:
        with self.assertRaises(ValueError):
            HTTPEventTransport("http://127.0.0.1:8080")
        with self.assertRaises(ValueError):
            HTTPEventTransport(
                "http://192.0.2.1:8080",
                allow_insecure_loopback=True,
            )
        transport = HTTPEventTransport(
            "http://localhost:8080",
            allow_insecure_loopback=True,
        )
        transport.close()
        transport.close()
        with self.assertRaises(SenderClosedError):
            transport.send(body=b"{}", headers={})


class ScriptedTransport:
    def __init__(self, actions: list[TransportResponse | BaseException]) -> None:
        self.actions = list(actions)
        self.bodies: list[bytes] = []
        self.headers: list[dict[str, str]] = []
        self.closed = False

    def send(self, *, body: bytes, headers: dict[str, str]) -> TransportResponse:
        self.bodies.append(body)
        self.headers.append(dict(headers))
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    def close(self) -> None:
        self.closed = True


class ApplicationTransport(ScriptedTransport):
    def __init__(
        self,
        application: ReceiverApplication,
        *,
        drop_after_commit: bool = False,
    ) -> None:
        super().__init__([])
        self.application = application
        self.drop_after_commit = drop_after_commit

    def send(self, *, body: bytes, headers: dict[str, str]) -> TransportResponse:
        self.bodies.append(body)
        self.headers.append(dict(headers))
        response = self.application.handle(
            method="POST",
            path=EVENT_PATH,
            headers=headers,
            body=body,
        )
        if self.drop_after_commit:
            self.drop_after_commit = False
            raise TimeoutError
        return TransportResponse(response.status_code, JSON_HEADERS, response.body)


class AckingTransport(ScriptedTransport):
    def __init__(self, *, first_response: TransportResponse | None = None) -> None:
        super().__init__([])
        self.first_response = first_response
        self.event_ids: list[str] = []

    def send(self, *, body: bytes, headers: dict[str, str]) -> TransportResponse:
        self.bodies.append(body)
        self.headers.append(dict(headers))
        envelope = decode_event_envelope(body)
        self.event_ids.append(envelope.event_id)
        if self.first_response is not None:
            response = self.first_response
            self.first_response = None
            return response
        return TransportResponse(
            201,
            JSON_HEADERS,
            response_body(
                request_id=envelope.request_id,
                result="ack",
                status="accepted",
                event_id=envelope.event_id,
            ),
        )


def _application(store: ReceiverStateStore) -> ReceiverApplication:
    return ReceiverApplication(
        store=store,
        authenticator=RequestAuthenticator(
            key_id="test-client",
            shared_secret=SECRET,
            max_clock_skew_seconds=300,
            clock=lambda: NOW_SECONDS,
        ),
        clock=lambda: NOW_SECONDS,
    )


def _event(rowid: int, event_id: str, *, text: str = "invented text") -> MessageEvent:
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
        text=text,
        attachments=(),
    )


def _commit(store: RelayStateStore, *events: MessageEvent) -> None:
    store.commit_scan(
        ScanBatch(
            events=events,
            issues=(),
            scanned_row_count=len(events),
            scanned_through_rowid=max(event.source_rowid for event in events),
        ),
        expected_after_rowid=0,
        now_ms=1,
    )


def _identifiers(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_messages_database(
    root: Path,
    events: tuple[tuple[str, str], ...],
) -> Path:
    root.mkdir()
    path = root / "invented_messages.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE message (
            guid TEXT, text TEXT, attributedBody BLOB, handle_id INTEGER,
            service TEXT, account_guid TEXT, date INTEGER, is_from_me INTEGER,
            associated_message_guid TEXT, associated_message_type INTEGER,
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
            VALUES (1, 'INVENTED-PARTICIPANT', 'iMessage');
        INSERT INTO chat(ROWID, guid, service_name)
            VALUES (1, 'INVENTED-CHAT', 'iMessage');
        INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 1);
        """
    )
    for index, (event_id, text) in enumerate(events, start=1):
        cursor = connection.execute(
            """
            INSERT INTO message(
                guid, text, attributedBody, handle_id, service, account_guid,
                date, is_from_me, associated_message_guid,
                associated_message_type, associated_message_range_location,
                associated_message_range_length, reply_to_guid
            ) VALUES (?, ?, NULL, 1, 'iMessage', NULL, ?, 0, NULL, 0, 0, 0, NULL)
            """,
            (event_id, text, index * 1_000_000_000),
        )
        connection.execute(
            "INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, ?)",
            (int(cursor.lastrowid),),
        )
    connection.commit()
    connection.close()
    return path


if __name__ == "__main__":
    unittest.main()
