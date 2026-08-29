from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from itertools import count
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from iphone_relay import (
    MessagesReader,
    QueueStatus,
    RelayStateStore,
    RetryPolicy,
    ScanBatch,
)
from iphone_relay.reconciliation import (
    ReconciliationError,
    ReconciliationWindow,
    ReconciliationWindowKind,
    RelayReconciler,
)
from iphone_relay.sender import EVENT_PATH, RelaySender, TransportResponse
from kiosk_receiver import (
    RECONCILIATION_PATH,
    ReceiverApplication,
    ReceiverStateStore,
    ReconciliationReceipt,
    RequestAuthenticator,
    decode_event_envelope,
    encode_event_envelope,
    reconciliation_response_body,
)


SECRET = b"invented-stage-six-secret-at-least-32-bytes"
NOW_SECONDS = 2_000_000_000
JSON_HEADERS = {"content-type": "application/json"}


class ReconciliationWindowTests(unittest.TestCase):
    def test_recent_and_calendar_month_windows_are_exact_half_open_utc_ranges(self) -> None:
        end = datetime(2025, 2, 1, tzinfo=timezone.utc)
        recent = ReconciliationWindow.recent(end_utc=end, days=7)
        month = ReconciliationWindow.calendar_month(year=2025, month=1)

        self.assertEqual(recent.kind, ReconciliationWindowKind.RECENT)
        self.assertEqual(
            recent.end_timestamp_raw_ns - recent.start_timestamp_raw_ns,
            7 * 86_400 * 1_000_000_000,
        )
        self.assertEqual(month.kind, ReconciliationWindowKind.CALENDAR_MONTH)
        self.assertEqual(
            month.end_timestamp_raw_ns - month.start_timestamp_raw_ns,
            31 * 86_400 * 1_000_000_000,
        )
        self.assertTrue(month.contains(month.start_timestamp_raw_ns))
        self.assertFalse(month.contains(month.end_timestamp_raw_ns))

        with self.assertRaises(ValueError):
            ReconciliationWindow.recent(end_utc=end.replace(tzinfo=None), days=7)
        with self.assertRaises(ValueError):
            ReconciliationWindow.recent(end_utc=end, days=32)
        with self.assertRaises(ValueError):
            ReconciliationWindow.calendar_month(year=2025, month=13)


class StageSixEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_path = self.root / "invented_messages.db"
        self.relay_path = self.root / "relay.db"
        self.receiver_path = self.root / "receiver.db"
        self.window = ReconciliationWindow.calendar_month(year=2025, month=1)
        day = 86_400 * 1_000_000_000
        _create_messages_database(
            self.source_path,
            (
                ("EVENT-A", "invented a", self.window.start_timestamp_raw_ns + 4 * day),
                ("EVENT-B", "invented b", self.window.start_timestamp_raw_ns + 5 * day),
                ("EVENT-D", "invented d", self.window.start_timestamp_raw_ns + 6 * day),
                ("EVENT-C", "invented c", self.window.end_timestamp_raw_ns + 4 * day),
                ("EVENT-E", "invented e", self.window.start_timestamp_raw_ns + 7 * day),
            ),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_month_reconciliation_repairs_only_missing_and_preserves_kiosk_only(self) -> None:
        reader = MessagesReader(self.source_path)
        source_hash = _sha256(self.source_path)
        source_batch = reader.scan(limit=10)
        by_id = {event.event_id: event for event in source_batch.events}
        initial_events = tuple(
            by_id[event_id]
            for event_id in ("EVENT-A", "EVENT-B", "EVENT-C", "EVENT-E")
        )
        policy = RetryPolicy(
            initial_delay_ms=10,
            multiplier=2,
            max_delay_ms=20,
            max_attempts=2,
            lease_duration_ms=10,
        )

        with RelayStateStore(self.relay_path, retry_policy=policy) as relay_store:
            relay_store.commit_scan(
                ScanBatch(
                    events=initial_events,
                    issues=(),
                    scanned_row_count=5,
                    scanned_through_rowid=5,
                ),
                expected_after_rowid=0,
                now_ms=1,
            )
            for expected_id in ("EVENT-A", "EVENT-B", "EVENT-C", "EVENT-E"):
                lease = relay_store.claim_next(now_ms=10)
                self.assertEqual(lease.event.event_id, expected_id)
                relay_store.acknowledge(expected_id, now_ms=11)

            with ReceiverStateStore(self.receiver_path) as receiver_store:
                _ingest(receiver_store, by_id["EVENT-A"], "seed-a")
                _ingest(receiver_store, by_id["EVENT-C"], "seed-c")
                _ingest(
                    receiver_store,
                    replace(by_id["EVENT-E"], text="conflicting invented e"),
                    "seed-e-conflict",
                )
                kiosk_only = replace(
                    by_id["EVENT-A"],
                    event_id="KIOSK-ONLY",
                    message_id="KIOSK-ONLY",
                    source_rowid=99,
                    text="invented kiosk-only",
                )
                _ingest(receiver_store, kiosk_only, "seed-kiosk-only")
                application = ReceiverApplication(
                    store=receiver_store,
                    authenticator=RequestAuthenticator(
                        key_id="test-client",
                        shared_secret=SECRET,
                        max_clock_skew_seconds=300,
                        clock=lambda: NOW_SECONDS,
                    ),
                    clock=lambda: NOW_SECONDS,
                )
                transport = ApplicationTransport(application)
                identifiers = _identifiers()
                reconciler = RelayReconciler(
                    reader=reader,
                    store=relay_store,
                    transport=transport,
                    key_id="test-client",
                    shared_secret=SECRET,
                    page_size=2,
                    clock=lambda: NOW_SECONDS,
                    identifier_factory=identifiers,
                )

                report = reconciler.reconcile(self.window, now_ms=100)

                self.assertEqual(report.source_rows_scanned, 4)
                self.assertEqual(report.source_events_inserted, 1)
                self.assertEqual(report.request_count, 3)
                self.assertEqual(report.candidate_count, 4)
                self.assertEqual(report.present_count, 1)
                self.assertEqual(report.missing_count, 2)
                self.assertEqual(report.conflict_count, 1)
                self.assertEqual(report.requeued_count, 1)
                self.assertEqual(transport.candidate_page_sizes, [2, 1, 1])
                self.assertEqual(relay_store.source_cursor(), 5)
                self.assertEqual(
                    relay_store.get_entry("EVENT-A").status,
                    QueueStatus.ACKNOWLEDGED,
                )
                self.assertEqual(
                    relay_store.get_entry("EVENT-B").status,
                    QueueStatus.QUEUED,
                )
                self.assertEqual(
                    relay_store.get_entry("EVENT-D").status,
                    QueueStatus.QUEUED,
                )
                self.assertEqual(
                    relay_store.get_entry("EVENT-E").status,
                    QueueStatus.ACKNOWLEDGED,
                )
                self.assertEqual(receiver_store.summary().event_count, 4)
                self.assertIsNotNone(receiver_store.get_event_json("KIOSK-ONLY"))

                repeated = reconciler.reconcile(self.window, now_ms=101)
                self.assertEqual(repeated.source_events_inserted, 0)
                self.assertEqual(repeated.missing_count, 2)
                self.assertEqual(repeated.requeued_count, 0)
                self.assertEqual(repeated.conflict_count, 1)

                with RelaySender(
                    store=relay_store,
                    transport=transport,
                    key_id="test-client",
                    shared_secret=SECRET,
                    clock=lambda: NOW_SECONDS,
                    identifier_factory=identifiers,
                ) as sender:
                    sender.deliver_once(now_ms=100)
                    sender.deliver_once(now_ms=100)

                self.assertEqual(relay_store.summary().acknowledged_count, 5)
                self.assertEqual(receiver_store.summary().event_count, 6)
                self.assertIsNotNone(receiver_store.get_event_json("KIOSK-ONLY"))
                self.assertEqual(_sha256(self.source_path), source_hash)

    def test_recent_reconciliation_uses_the_same_bounded_pipeline(self) -> None:
        window = ReconciliationWindow.recent(
            end_utc=datetime(2025, 1, 8, tzinfo=timezone.utc),
            days=3,
        )
        source_hash = _sha256(self.source_path)
        with RelayStateStore(self.relay_path) as relay_store:
            with ReceiverStateStore(self.receiver_path) as receiver_store:
                application = ReceiverApplication(
                    store=receiver_store,
                    authenticator=RequestAuthenticator(
                        key_id="test-client",
                        shared_secret=SECRET,
                        clock=lambda: NOW_SECONDS,
                    ),
                    clock=lambda: NOW_SECONDS,
                )
                transport = ApplicationTransport(application)
                report = RelayReconciler(
                    reader=MessagesReader(self.source_path),
                    store=relay_store,
                    transport=transport,
                    key_id="test-client",
                    shared_secret=SECRET,
                    page_size=2,
                    clock=lambda: NOW_SECONDS,
                    identifier_factory=_identifiers(),
                ).reconcile(window, now_ms=10)

                self.assertEqual(report.window_kind, ReconciliationWindowKind.RECENT)
                self.assertEqual(report.source_rows_scanned, 3)
                self.assertEqual(report.source_events_inserted, 3)
                self.assertEqual(report.candidate_count, 3)
                self.assertEqual(report.missing_count, 3)
                self.assertEqual(report.request_count, 2)
                self.assertEqual(relay_store.source_cursor(), 0)
                self.assertEqual(relay_store.summary().queued_count, 3)
                self.assertEqual(receiver_store.summary().event_count, 0)
                self.assertEqual(transport.candidate_page_sizes, [2, 1])
                self.assertEqual(_sha256(self.source_path), source_hash)

    def test_mismatched_receipt_response_fails_without_selective_state_changes(self) -> None:
        window = ReconciliationWindow.recent(
            end_utc=datetime(2025, 1, 8, tzinfo=timezone.utc),
            days=3,
        )
        with RelayStateStore(self.relay_path) as relay_store:
            reconciler = RelayReconciler(
                reader=MessagesReader(self.source_path),
                store=relay_store,
                transport=MismatchedTransport(),
                key_id="test-client",
                shared_secret=SECRET,
                page_size=2,
                clock=lambda: NOW_SECONDS,
                identifier_factory=_identifiers(),
            )

            with self.assertRaises(ReconciliationError) as raised:
                reconciler.reconcile(window, now_ms=10)

            self.assertEqual(raised.exception.code, "reconciliation_response_mismatch")
            self.assertEqual(relay_store.source_cursor(), 0)
            self.assertEqual(relay_store.summary().queued_count, 3)


class ApplicationTransport:
    def __init__(self, application: ReceiverApplication) -> None:
        self.application = application
        self.closed = False
        self.candidate_page_sizes: list[int] = []

    def send(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        path: str = EVENT_PATH,
    ) -> TransportResponse:
        if path == RECONCILIATION_PATH:
            value = _json(body)
            self.candidate_page_sizes.append(len(value["candidates"]))
        response = self.application.handle(
            method="POST",
            path=path,
            headers=headers,
            body=body,
        )
        return TransportResponse(response.status_code, JSON_HEADERS, response.body)

    def close(self) -> None:
        self.closed = True


class MismatchedTransport:
    def send(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        path: str = EVENT_PATH,
    ) -> TransportResponse:
        del headers, path
        value = _json(body)
        candidates = value["candidates"]
        assert isinstance(candidates, list)
        receipts = tuple(
            ReconciliationReceipt(candidate["event_id"], "missing")
            for candidate in candidates
        )
        return TransportResponse(
            200,
            JSON_HEADERS,
            reconciliation_response_body(
                request_id="wrong-request",
                receipts=receipts,
            ),
        )

    def close(self) -> None:
        pass


def _identifiers():
    sequence = count(1)
    return lambda: f"stage-six-{next(sequence)}"


def _ingest(store: ReceiverStateStore, event, request_id: str) -> None:
    store.ingest(
        decode_event_envelope(encode_event_envelope(event, request_id)),
        received_at_ms=1,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(body: bytes) -> dict[str, object]:
    value = json.loads(body)
    assert isinstance(value, dict)
    return value


def _create_messages_database(
    path: Path,
    events: tuple[tuple[str, str, int], ...],
) -> None:
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
    for event_id, text, timestamp in events:
        cursor = connection.execute(
            """
            INSERT INTO message(
                guid, text, attributedBody, handle_id, service, account_guid,
                date, is_from_me, associated_message_guid,
                associated_message_type, associated_message_range_location,
                associated_message_range_length, reply_to_guid
            ) VALUES (?, ?, NULL, 1, 'iMessage', NULL, ?, 0, NULL, 0, 0, 0, NULL)
            """,
            (event_id, text, timestamp),
        )
        connection.execute(
            "INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, ?)",
            (int(cursor.lastrowid),),
        )
    connection.commit()
    connection.close()


if __name__ == "__main__":
    unittest.main()
