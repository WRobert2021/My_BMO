from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest

from iphone_relay import (
    Attachment,
    AttachmentAvailability,
    AttachmentComponent,
    AttachmentComponentRole,
    AttemptOutcome,
    CursorConflictError,
    Direction,
    EventKind,
    MediaCategory,
    MessageEvent,
    MessagesReader,
    ParseIssue,
    QueueStatus,
    ReactionEvent,
    ReactionKind,
    RelayStateStore,
    RelayStateConfig,
    RetryPolicy,
    ScanBatch,
    Sender,
    SenderKind,
    StateClosedError,
    StateConfigError,
    StateDatabaseError,
    StateIntegrityError,
    StateSchemaError,
    StateSecurityError,
    StateTransitionError,
    apple_nanoseconds_to_datetime,
    load_state_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RelayStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_path = self.root / "relay_state.db"
        self.policy = RetryPolicy(
            initial_delay_ms=100,
            multiplier=2,
            max_delay_ms=250,
            max_attempts=2,
            lease_duration_ms=50,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_commits_event_issue_and_cursor_atomically(self) -> None:
        event = _message_event(1, "EVENT-ONE")
        issue = ParseIssue(1, "attachment_missing", "sanitized diagnostic")
        batch = ScanBatch((event,), (issue,), 1, 1)

        with self._store() as store:
            store.commit_scan(batch, expected_after_rowid=0, now_ms=1_000)

            entry = store.get_entry("EVENT-ONE")
            self.assertEqual(entry.event, event)
            self.assertEqual(entry.status, QueueStatus.QUEUED)
            self.assertEqual(entry.attempt_count, 0)
            self.assertEqual(entry.discovered_at_ms, 1_000)
            self.assertEqual(store.source_cursor(), 1)
            self.assertEqual(store.list_issues()[0].code, "attachment_missing")
            summary = store.summary()
            self.assertEqual(summary.pending_count, 1)
            self.assertEqual(summary.issue_count, 1)

    def test_issue_only_row_is_durable_before_cursor_advances(self) -> None:
        batch = ScanBatch(
            events=(),
            issues=(ParseIssue(1, "message_invalid", "sanitized diagnostic"),),
            scanned_row_count=1,
            scanned_through_rowid=1,
        )

        with self._store() as store:
            store.commit_scan(batch, expected_after_rowid=0, now_ms=100)

        with self._store() as reopened:
            self.assertEqual(reopened.source_cursor(), 1)
            self.assertEqual(reopened.list_entries(), ())
            self.assertEqual(reopened.list_issues()[0].source_rowid, 1)

    def test_duplicate_scan_is_idempotent_and_conflicts_fail_closed(self) -> None:
        original = _message_event(1, "EVENT-ONE", text="original")
        original_batch = ScanBatch((original,), (), 1, 1)

        with self._store() as store:
            store.commit_scan(original_batch, expected_after_rowid=0, now_ms=100)
            store.commit_scan(original_batch, expected_after_rowid=0, now_ms=200)
            self.assertEqual(len(store.list_entries()), 1)
            self.assertEqual(store.source_cursor(), 1)

            conflicting = _message_event(1, "EVENT-ONE", text="changed")
            with self.assertRaises(StateIntegrityError):
                store.commit_scan(
                    ScanBatch((conflicting,), (), 1, 1),
                    expected_after_rowid=0,
                    now_ms=300,
                )

            self.assertEqual(store.get_entry("EVENT-ONE").event.text, "original")
            self.assertEqual(store.source_cursor(), 1)

    def test_stale_cursor_cannot_commit_a_partially_new_batch(self) -> None:
        with self._store() as store:
            store.commit_scan(
                ScanBatch((_message_event(1, "ONE"),), (), 1, 1),
                expected_after_rowid=0,
                now_ms=100,
            )

            with self.assertRaises(CursorConflictError):
                store.commit_scan(
                    ScanBatch((_message_event(2, "TWO"),), (), 1, 2),
                    expected_after_rowid=0,
                    now_ms=200,
                )

            self.assertIsNone(store.get_entry("TWO"))
            self.assertEqual(store.source_cursor(), 1)

    def test_database_failure_rolls_back_event_issue_and_cursor(self) -> None:
        with self._store() as store:
            raw = sqlite3.connect(self.state_path)
            raw.execute(
                """
                CREATE TRIGGER fail_relay_event_insert
                BEFORE INSERT ON relay_events
                BEGIN
                    SELECT RAISE(ABORT, 'injected test failure');
                END
                """
            )
            raw.commit()
            raw.close()
            batch = ScanBatch(
                (_message_event(1, "ONE"),),
                (ParseIssue(1, "message_invalid", "sanitized diagnostic"),),
                1,
                1,
            )

            with self.assertRaises(StateDatabaseError):
                store.commit_scan(batch, expected_after_rowid=0, now_ms=100)

            self.assertEqual(store.source_cursor(), 0)
            self.assertEqual(store.list_entries(), ())
            self.assertEqual(store.list_issues(), ())

    def test_queued_and_in_flight_state_survive_restart(self) -> None:
        self._commit_events(_message_event(1, "ONE"))

        with self._store() as store:
            self.assertEqual(store.get_entry("ONE").status, QueueStatus.QUEUED)
            lease = store.claim_next(now_ms=1_000)
            self.assertEqual(lease.attempt_number, 1)

        with self._store() as reopened:
            self.assertEqual(reopened.get_entry("ONE").status, QueueStatus.IN_FLIGHT)
            self.assertIsNone(reopened.claim_next(now_ms=1_049))

    def test_expired_lease_recovers_after_backoff_and_survives_restart(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        with self._store() as store:
            store.claim_next(now_ms=1_000)

        with self._store() as reopened:
            self.assertIsNone(reopened.claim_next(now_ms=1_050))
            entry = reopened.get_entry("ONE")
            self.assertEqual(entry.status, QueueStatus.RETRY_WAIT)
            self.assertEqual(entry.next_attempt_at_ms, 1_150)

        with self._store() as reopened_again:
            lease = reopened_again.claim_next(now_ms=1_150)
            self.assertEqual(lease.attempt_number, 2)
            attempts = reopened_again.list_attempts("ONE")
            self.assertEqual(attempts[0].outcome, AttemptOutcome.LEASE_EXPIRED)

    def test_lost_ack_retries_same_event_then_duplicate_ack_is_idempotent(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        with self._store() as store:
            first = store.claim_next(now_ms=1_000)
            failed = store.record_failure(
                first.attempt_id,
                error_code="ack_timeout",
                now_ms=1_010,
            )
            self.assertEqual(failed.status, QueueStatus.RETRY_WAIT)
            self.assertEqual(failed.next_attempt_at_ms, 1_110)
            self.assertIsNone(store.claim_next(now_ms=1_109))

        with self._store() as reopened:
            second = reopened.claim_next(now_ms=1_110)
            self.assertEqual(second.event.event_id, "ONE")
            self.assertEqual(second.attempt_number, 2)
            acknowledged = reopened.acknowledge("ONE", now_ms=1_120)
            repeated = reopened.acknowledge("ONE", now_ms=1_999)
            self.assertEqual(acknowledged.status, QueueStatus.ACKNOWLEDGED)
            self.assertEqual(repeated.acknowledged_at_ms, 1_120)
            self.assertEqual(len(reopened.list_entries()), 1)

    def test_poison_event_dead_letters_without_blocking_later_event(self) -> None:
        self._commit_events(
            _message_event(1, "POISON"),
            _message_event(2, "LATER"),
        )
        with self._store() as store:
            poison_one = store.claim_next(now_ms=1_000)
            store.record_failure(
                poison_one.attempt_id,
                error_code="payload_rejected",
                now_ms=1_010,
            )
            later = store.claim_next(now_ms=1_010)
            self.assertEqual(later.event.event_id, "LATER")
            store.acknowledge("LATER", now_ms=1_020)
            poison_two = store.claim_next(now_ms=1_110)
            dead = store.record_failure(
                poison_two.attempt_id,
                error_code="payload_rejected",
                now_ms=1_120,
            )
            self.assertEqual(dead.status, QueueStatus.DEAD_LETTER)
            self.assertEqual(store.summary().dead_letter_count, 1)

        with self._store() as reopened:
            self.assertEqual(
                reopened.get_entry("POISON").status,
                QueueStatus.DEAD_LETTER,
            )
            self.assertEqual(
                reopened.get_entry("LATER").status,
                QueueStatus.ACKNOWLEDGED,
            )

    def test_late_ack_can_resolve_a_dead_letter(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        with self._store() as store:
            first = store.claim_next(now_ms=100)
            store.record_failure(first.attempt_id, error_code="timeout", now_ms=110)
            second = store.claim_next(now_ms=210)
            store.record_failure(second.attempt_id, error_code="timeout", now_ms=220)
            self.assertEqual(store.get_entry("ONE").status, QueueStatus.DEAD_LETTER)

            resolved = store.acknowledge("ONE", now_ms=230)

            self.assertEqual(resolved.status, QueueStatus.ACKNOWLEDGED)
            self.assertEqual(store.summary().dead_letter_count, 0)

    def test_dead_letter_requeue_starts_new_cycle_without_erasing_history(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        with self._store() as store:
            first = store.claim_next(now_ms=100)
            store.record_failure(first.attempt_id, error_code="timeout", now_ms=110)
            second = store.claim_next(now_ms=210)
            store.record_failure(second.attempt_id, error_code="timeout", now_ms=220)

            requeued = store.requeue_dead_letter("ONE", now_ms=300)
            third = store.claim_next(now_ms=300)

            self.assertEqual(requeued.status, QueueStatus.QUEUED)
            self.assertEqual(requeued.attempt_count, 2)
            self.assertEqual(requeued.retry_cycle_attempt_count, 0)
            self.assertEqual(third.attempt_number, 3)
            self.assertEqual(store.get_entry("ONE").retry_cycle_attempt_count, 1)
            self.assertEqual(len(store.list_attempts("ONE")), 3)

    def test_reconciliation_commit_pagination_and_selective_requeue_are_bounded(self) -> None:
        with self._store() as store:
            store.commit_scan(
                ScanBatch(
                    (_message_event(1, "ONE"), _message_event(3, "THREE")),
                    (),
                    3,
                    3,
                ),
                expected_after_rowid=0,
                now_ms=10,
            )
            first_attempt = store.claim_next(now_ms=20)
            store.acknowledge(first_attempt.event.event_id, now_ms=21)

            lookback = ScanBatch((_message_event(2, "TWO"),), (), 1, 2)
            committed = store.commit_reconciliation_batch(
                lookback,
                expected_after_rowid=0,
                start_timestamp_raw_ns=0,
                end_timestamp_raw_ns=4_000_000_000,
                now_ms=30,
            )
            repeated = store.commit_reconciliation_batch(
                lookback,
                expected_after_rowid=0,
                start_timestamp_raw_ns=0,
                end_timestamp_raw_ns=4_000_000_000,
                now_ms=31,
            )

            page_one = store.list_entries_page(limit=1)
            page_two = store.list_entries_page(
                after_source_rowid=page_one[-1].event.source_rowid,
                after_event_id=page_one[-1].event.event_id,
                limit=1,
            )
            page_three = store.list_entries_page(
                after_source_rowid=page_two[-1].event.source_rowid,
                after_event_id=page_two[-1].event.event_id,
                limit=1,
            )

            self.assertEqual(store.source_cursor(), 3)
            self.assertEqual(committed.inserted_event_count, 1)
            self.assertEqual(repeated.inserted_event_count, 0)
            self.assertEqual(
                [page[0].event.event_id for page in (page_one, page_two, page_three)],
                ["ONE", "TWO", "THREE"],
            )
            self.assertTrue(
                store.requeue_acknowledged_for_reconciliation("ONE", now_ms=40)
            )
            self.assertFalse(
                store.requeue_acknowledged_for_reconciliation("ONE", now_ms=41)
            )
            self.assertEqual(store.get_entry("ONE").status, QueueStatus.QUEUED)

            with self.assertRaises(StateIntegrityError):
                store.commit_reconciliation_batch(
                    ScanBatch((_message_event(2, "TWO", text="changed"),), (), 1, 2),
                    expected_after_rowid=0,
                    start_timestamp_raw_ns=0,
                    end_timestamp_raw_ns=4_000_000_000,
                    now_ms=50,
                )
            self.assertEqual(store.get_entry("TWO").event.text, "hello")

    def test_ack_requires_a_known_attempted_event(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        with self._store() as store:
            with self.assertRaises(StateTransitionError):
                store.acknowledge("ONE", now_ms=100)
            with self.assertRaises(StateTransitionError):
                store.acknowledge("MISSING", now_ms=100)

    def test_retry_policy_is_bounded_and_validated(self) -> None:
        self.assertEqual(self.policy.delay_after_attempt(1), 100)
        self.assertEqual(self.policy.delay_after_attempt(2), 200)
        self.assertEqual(self.policy.delay_after_attempt(3), 250)
        self.assertEqual(self.policy.delay_after_attempt(20), 250)
        with self.assertRaises(ValueError):
            RetryPolicy(initial_delay_ms=0)
        with self.assertRaises(ValueError):
            RetryPolicy(initial_delay_ms=200, max_delay_ms=100)

    def test_error_codes_are_bounded_identifiers_not_private_messages(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        with self._store() as store:
            lease = store.claim_next(now_ms=100)
            with self.assertRaises(StateIntegrityError):
                store.record_failure(
                    lease.attempt_id,
                    error_code="timeout while sending private message text",
                    now_ms=110,
                )
            self.assertEqual(store.get_entry("ONE").status, QueueStatus.IN_FLIGHT)

    def test_message_attachment_and_reaction_payloads_round_trip(self) -> None:
        attachment = Attachment(
            attachment_id="ATTACHMENT-ONE",
            parent_message_id="MESSAGE-WITH-MEDIA",
            transfer_name="invented.jpg",
            uti="public.jpeg",
            mime_type="image/jpeg",
            media_category=MediaCategory.LIVE_PHOTO,
            source_path="/private/tmp/invented.jpg",
            declared_bytes=10,
            actual_bytes=12,
            availability=AttachmentAvailability.AVAILABLE,
            components=(
                AttachmentComponent(
                    component_id="ATTACHMENT-ONE:still",
                    role=AttachmentComponentRole.STILL,
                    source_path="/private/tmp/invented.jpg",
                    actual_bytes=12,
                ),
                AttachmentComponent(
                    component_id="ATTACHMENT-ONE:motion",
                    role=AttachmentComponentRole.MOTION,
                    source_path="/private/tmp/invented.mov",
                    actual_bytes=24,
                ),
            ),
        )
        message = _message_event(
            1,
            "MESSAGE-WITH-MEDIA",
            attachments=(attachment,),
        )
        reaction = _reaction_event(2, "REACTION-ONE")

        self._commit_events(message, reaction)

        with self._store() as store:
            self.assertEqual(store.get_entry(message.event_id).event, message)
            self.assertEqual(store.get_entry(reaction.event_id).event, reaction)

    def test_payload_tampering_is_detected_after_restart(self) -> None:
        self._commit_events(_message_event(1, "ONE"))
        raw = sqlite3.connect(self.state_path)
        raw.execute(
            "UPDATE relay_events SET payload_json = replace(payload_json, 'hello', 'altered')"
        )
        raw.commit()
        raw.close()

        with self._store() as store:
            with self.assertRaises(StateIntegrityError):
                store.get_entry("ONE")

    def test_state_path_is_private_and_cannot_target_apple_or_symlink(self) -> None:
        with self._store():
            permissions = stat.S_IMODE(self.state_path.stat().st_mode)
            self.assertEqual(permissions, 0o600)

        with self.assertRaises(StateSecurityError):
            RelayStateStore(self.root / "sms.db")

        broad = self.root / "broad.db"
        broad.touch(mode=0o644)
        os.chmod(broad, 0o644)
        with self.assertRaises(StateSecurityError):
            RelayStateStore(broad)

        target = self.root / "target.db"
        target.touch(mode=0o600)
        link = self.root / "linked.db"
        link.symlink_to(target)
        with self.assertRaises(StateSecurityError):
            RelayStateStore(link)

    def test_unrecognized_future_and_incomplete_schemas_fail_closed(self) -> None:
        unknown = self.root / "unknown.db"
        raw = sqlite3.connect(unknown)
        raw.execute("CREATE TABLE unrelated(value TEXT)")
        raw.close()
        os.chmod(unknown, 0o600)
        with self.assertRaises(StateSchemaError):
            RelayStateStore(unknown)

        with self._store():
            pass
        raw = sqlite3.connect(self.state_path)
        raw.execute("PRAGMA user_version = 999")
        raw.close()
        with self.assertRaises(StateSchemaError):
            self._store()

    def test_existing_empty_version_zero_file_initializes_as_first_schema(self) -> None:
        self.state_path.touch(mode=0o600)

        with self._store() as store:
            self.assertEqual(store.source_cursor(), 0)

        raw = sqlite3.connect(self.state_path)
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 1)
        raw.close()

        raw = sqlite3.connect(self.state_path)
        raw.execute("PRAGMA user_version = 1")
        raw.execute("DROP TABLE parse_issues")
        raw.close()
        with self.assertRaises(StateSchemaError):
            self._store()

    def test_close_is_idempotent_and_closed_store_rejects_use(self) -> None:
        store = self._store()
        store.close()
        store.close()
        with self.assertRaises(StateClosedError):
            store.source_cursor()

    def _store(self) -> RelayStateStore:
        return RelayStateStore(self.state_path, retry_policy=self.policy)

    def _commit_events(self, *events: MessageEvent | ReactionEvent) -> None:
        batch = ScanBatch(
            events=events,
            issues=(),
            scanned_row_count=len(events),
            scanned_through_rowid=max(event.source_rowid for event in events),
        )
        with self._store() as store:
            store.commit_scan(batch, expected_after_rowid=0, now_ms=10)


class RelayStateSnapshotIntegrationTests(unittest.TestCase):
    def test_parser_batch_commits_to_private_state_if_snapshot_is_available(self) -> None:
        source = PROJECT_ROOT / "iphone_snapshot" / "SMS"
        source_files = [
            source / "sms.db",
            source / "sms.db-wal",
            source / "sms.db-shm",
        ]
        if not all(path.is_file() for path in source_files):
            self.skipTest("ignored local Messages snapshot is unavailable")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            copied_source = root / "source"
            copied_source.mkdir()
            for path in source_files:
                shutil.copy2(path, copied_source / path.name)
            batch = MessagesReader(
                copied_source / "sms.db",
                messages_root=source,
            ).scan(limit=100)
            state_path = root / "relay_state.db"
            with RelayStateStore(state_path) as store:
                store.commit_scan(batch, expected_after_rowid=0, now_ms=100)

            with RelayStateStore(state_path) as reopened:
                self.assertEqual(reopened.source_cursor(), 38)
                self.assertEqual(reopened.summary().queued_count, 35)
                self.assertEqual(reopened.summary().issue_count, 0)


class RelayStateConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_missing_config_returns_in_memory_defaults_without_creating_files(self) -> None:
        path = self.root / "missing.json"

        config = load_state_config(path, base_directory=self.root)

        self.assertIsInstance(config, RelayStateConfig)
        self.assertEqual(
            config.state_path,
            (self.root / "data" / "imessage_relay" / "relay_state.db").resolve(),
        )
        self.assertEqual(config.retry_policy, RetryPolicy())
        self.assertFalse(path.exists())
        self.assertFalse(config.state_path.exists())

    def test_example_config_loads_relative_to_explicit_base(self) -> None:
        path = PROJECT_ROOT / "config" / "example.imessage_relay.json"

        config = load_state_config(path, base_directory=self.root)

        self.assertEqual(
            config.state_path,
            (self.root / "data" / "imessage_relay" / "relay_state.db").resolve(),
        )
        self.assertEqual(config.retry_policy.initial_delay_ms, 30_000)
        self.assertEqual(config.retry_policy.max_delay_ms, 900_000)
        self.assertEqual(config.retry_policy.max_attempts, 5)

    def test_invalid_duplicate_and_inconsistent_config_fails_closed(self) -> None:
        invalid_values = (
            """
            {"schema_version":1,"schema_version":1,"state_path":"state.db",
             "retry_policy":{"initial_delay_seconds":1,"multiplier":2,
             "max_delay_seconds":2,"max_attempts":2,"lease_duration_seconds":1}}
            """,
            """
            {"schema_version":1,"state_path":"state.db",
             "retry_policy":{"initial_delay_seconds":10,"multiplier":2,
             "max_delay_seconds":1,"max_attempts":2,"lease_duration_seconds":1}}
            """,
            """
            {"schema_version":1,"state_path":"state.db",
             "retry_policy":{"initial_delay_seconds":true,"multiplier":2,
             "max_delay_seconds":2,"max_attempts":2,"lease_duration_seconds":1}}
            """,
        )
        for index, content in enumerate(invalid_values):
            with self.subTest(index=index):
                path = self.root / f"invalid-{index}.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(StateConfigError):
                    load_state_config(path, base_directory=self.root)


def _message_event(
    source_rowid: int,
    event_id: str,
    *,
    text: str = "hello",
    attachments: tuple[Attachment, ...] = (),
) -> MessageEvent:
    timestamp = source_rowid * 1_000_000_000
    return MessageEvent(
        schema_version=1,
        event_kind=EventKind.MESSAGE,
        event_id=event_id,
        message_id=event_id,
        source_rowid=source_rowid,
        chat_id="CHAT-INVENTED",
        participant_ids=("PARTICIPANT-INVENTED",),
        sender=Sender(SenderKind.REMOTE_HANDLE, "PARTICIPANT-INVENTED"),
        direction=Direction.INCOMING,
        timestamp_raw_ns=timestamp,
        timestamp_utc=apple_nanoseconds_to_datetime(timestamp),
        text=text,
        attachments=attachments,
    )


def _reaction_event(source_rowid: int, event_id: str) -> ReactionEvent:
    timestamp = source_rowid * 1_000_000_000
    return ReactionEvent(
        schema_version=1,
        event_kind=EventKind.REACTION_ADDED,
        event_id=event_id,
        source_rowid=source_rowid,
        chat_id="CHAT-INVENTED",
        participant_ids=("PARTICIPANT-INVENTED",),
        sender=Sender(SenderKind.SELF, "SELF-INVENTED"),
        direction=Direction.OUTGOING,
        timestamp_raw_ns=timestamp,
        timestamp_utc=apple_nanoseconds_to_datetime(timestamp),
        target_message_id="TARGET-INVENTED",
        target_part=0,
        reaction_kind=ReactionKind.HEART,
        source_reaction_type=2000,
    )


if __name__ == "__main__":
    unittest.main()
