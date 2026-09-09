"""Opt-in kiosk receiver lifecycle, feed, and status UI coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from bmo.features import FeatureMenuContext, ToolRegistry
from bmo.features.imessage_relay import (
    IMESSAGE_RELAY_MENU_ITEM,
    IMessageRelayTool,
    RelayFeatureConfig,
    RelayRuntimeService,
    RelayRuntimeStatus,
    register_metadata,
)
from bmo.features.imessage_relay.receiver import (
    EVENT_PATH,
    decode_event_envelope,
    encode_event_envelope,
    sign_request,
)
from bmo.features.imessage_relay.phone_control import PhoneControlRuntimeStatus
from bmo.features.imessage_relay.relay import (
    Direction,
    EventKind,
    MessagesReader,
    ReactionEvent,
    ReactionKind,
    Sender,
    SenderKind,
    apple_nanoseconds_to_datetime,
)
from bmo.features.imessage_relay.relay.sender import HTTPEventTransport
from bmo.features.imessage_relay.relay.timestamps import APPLE_EPOCH
from bmo.features.loader import DEFAULT_FEATURE_MODULES, load_feature_registry
from bmo.menu_loader import load_menu_catalog
from bmo.qt.views.imessage_relay import QtIMessageRelayView


SECRET_ENV = "TEST_IMESSAGE_RUNTIME_SECRET"
SECRET_TEXT = "invented-runtime-secret-material-1234567890"


class RuntimeMessagesFixture:
    def __init__(self, root: Path) -> None:
        self.messages_root = root / "SMS"
        self.messages_root.mkdir()
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
                VALUES (1, 'invented-runtime-handle', 'iMessage');
            INSERT INTO chat(ROWID, guid, service_name)
                VALUES (1, 'invented-runtime-chat', 'iMessage');
            INSERT INTO chat_handle_join(chat_id, handle_id) VALUES (1, 1);
            """
        )
        now = datetime.now(timezone.utc)
        delta = now - APPLE_EPOCH
        timestamp_ns = (
            delta.days * 86_400 * 1_000_000_000
            + delta.seconds * 1_000_000_000
            + delta.microseconds * 1_000
        )
        self.connection.execute(
            """
            INSERT INTO message(
                ROWID, guid, text, handle_id, service, date, is_from_me,
                associated_message_type
            ) VALUES (
                1, 'invented-runtime-message', 'invented runtime text',
                1, 'iMessage', ?, 0, 0
            )
            """,
            (timestamp_ns,),
        )
        self.connection.execute(
            "INSERT INTO chat_message_join(chat_id, message_id) VALUES (1, 1)"
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def write_receiver_config(root: Path) -> Path:
    receiver_config = root / "receiver.json"
    receiver_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bind_host": "127.0.0.1",
                "port": 0,
                "state_path": str(root / "receiver.db"),
                "tls_cert_path": None,
                "tls_key_path": None,
                "allow_insecure_loopback": True,
                "key_id": "invented-runtime-key",
                "shared_secret_env": SECRET_ENV,
                "max_clock_skew_seconds": 300,
                "max_request_bytes": 2 * 1024 * 1024,
                "request_timeout_seconds": 2,
            }
        ),
        encoding="utf-8",
    )
    return receiver_config


class IMessageRuntimeRegistrationTests(unittest.TestCase):
    def test_feature_is_opt_in_and_disabled_entry_is_not_imported(self) -> None:
        self.assertNotIn("bmo.features.imessage_relay", DEFAULT_FEATURE_MODULES)
        config = {
            "features": [
                {
                    "module": "bmo.features.imessage_relay",
                    "enabled": False,
                    "settings": {"receiver_config_path": "not validated"},
                }
            ]
        }

        with patch("bmo.features.loader._load_module") as load_module:
            result = load_feature_registry(config)

        load_module.assert_not_called()
        self.assertEqual(result.registry.menu_items, ())
        self.assertEqual(result.failures, ())

    def test_metadata_and_menu_discovery_are_resource_free(self) -> None:
        registry = ToolRegistry()
        with (
            patch("bmo.features.imessage_relay.feature.load_receiver_config") as receiver,
            patch("bmo.features.imessage_relay.feature.build_server") as server,
        ):
            register_metadata(registry, {"invalid": object()})
            menu = load_menu_catalog(
                {
                    "features": [
                        {
                            "module": "bmo.features.imessage_relay",
                            "enabled": True,
                            "settings": {"receiver_config_path": object()},
                        }
                    ],
                    "modes": [],
                }
            )

        receiver.assert_not_called()
        server.assert_not_called()
        self.assertEqual(registry.menu_items, (IMESSAGE_RELAY_MENU_ITEM,))
        self.assertEqual(
            IMESSAGE_RELAY_MENU_ITEM.icon_path.parts[-3:],
            ("graphics", "icons", "message.png"),
        )
        self.assertEqual(menu.catalog.items[0].name, "feature:imessage_relay")
        registry.close()

    def test_invalid_settings_are_isolated_and_later_feature_loads(self) -> None:
        result = load_feature_registry(
            {
                "features": [
                    {
                        "module": "bmo.features.imessage_relay",
                        "enabled": True,
                        "settings": {"reconciliation_recent_days": 0},
                    },
                    {
                        "module": "bmo.features.get_time",
                        "enabled": True,
                        "settings": {},
                    },
                ]
            },
            reporter=lambda _message: None,
        )

        self.assertEqual(result.registry.actions, {"get_time"})
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].module, "bmo.features.imessage_relay")
        result.registry.close()

    def test_missing_private_config_registers_visible_degraded_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = load_feature_registry(
                {
                    "features": [
                        {
                            "module": "bmo.features.imessage_relay",
                            "enabled": True,
                            "settings": {
                                "receiver_config_path": root / "missing.json"
                            },
                        },
                        {
                            "module": "bmo.features.get_time",
                            "enabled": True,
                            "settings": {},
                        },
                    ]
                }
            )
            tool = result.registry.get("imessage_relay")
            assert isinstance(tool, IMessageRelayTool)

            status = tool.service.status()

            self.assertEqual(result.failures, ())
            self.assertEqual(result.registry.actions, {"get_time"})
            self.assertEqual(status.service_state, "unavailable")
            self.assertEqual(status.service_error_code, "receiver_config_invalid")
            self.assertFalse(status.listening)
            result.registry.close()

    def test_enabled_service_starts_and_registry_close_releases_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receiver_config = write_receiver_config(root)
            with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
                result = load_feature_registry(
                    {
                        "features": [
                            {
                                "module": "bmo.features.imessage_relay",
                                "enabled": True,
                                "settings": {
                                    "receiver_config_path": receiver_config,
                                    "relay_config_path": "retired-value-is-ignored",
                                    "source_config_path": "retired-value-is-ignored",
                                },
                            }
                        ]
                    }
                )
                tool = result.registry.get("imessage_relay")
                assert isinstance(tool, IMessageRelayTool)
                status = tool.service.status()
                port = int(tool.service._server.server_address[1])

                self.assertEqual(result.failures, ())
                self.assertTrue(status.listening)
                self.assertEqual(status.incoming_state, "ready")
                self.assertEqual(
                    status.reconciliation_error_code,
                    "phone_control_config_invalid",
                )
                result.registry.close()
                result.registry.close()

            self.assertEqual(tool.service.status().service_state, "closed")
            self.assertFalse(tool.service._server_thread.is_alive())
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", port))
            finally:
                probe.close()


class IMessageRuntimeReceiverTests(unittest.TestCase):
    def test_listener_receipt_updates_runtime_status_and_feed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = RuntimeMessagesFixture(root)
            receiver_config = write_receiver_config(root)
            event = MessagesReader(
                fixture.database_path,
                messages_root=fixture.messages_root,
            ).scan(limit=10).events[0]
            request_id = "invented-runtime-request"
            body = encode_event_envelope(event, request_id)
            headers = sign_request(
                SECRET_TEXT.encode("utf-8"),
                key_id="invented-runtime-key",
                method="POST",
                path=EVENT_PATH,
                timestamp=int(time.time()),
                nonce="invented-runtime-nonce",
                body=body,
            )
            headers.update(
                {"Content-Type": "application/json", "Accept": "application/json"}
            )

            with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
                service = RelayRuntimeService(
                    RelayFeatureConfig(receiver_config_path=receiver_config)
                )
                transport = HTTPEventTransport(
                    f"http://127.0.0.1:{service._server.server_address[1]}",
                    allow_insecure_loopback=True,
                )
                try:
                    response = transport.send(body=body, headers=headers)
                    status = service.status()
                    feed = service.recent_items()
                finally:
                    transport.close()
                    service.close()
                    fixture.close()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(status.received_events, 1)
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0].sender, "invented-runtime-handle")
        self.assertEqual(feed[0].text, "invented runtime text")
        self.assertIsNone(status.last_reconciliation)

    def test_feed_renders_same_receipt_batch_in_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = RuntimeMessagesFixture(root)
            receiver_config = write_receiver_config(root)
            first = MessagesReader(
                fixture.database_path,
                messages_root=fixture.messages_root,
            ).scan(limit=10).events[0]
            with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
                service = RelayRuntimeService(
                    RelayFeatureConfig(receiver_config_path=receiver_config)
                )
                try:
                    for index, text in enumerate(("first", "second", "third"), 1):
                        timestamp = first.timestamp_raw_ns + index * 1_000_000_000
                        event = replace(
                            first,
                            event_id=f"EVENT-{4 - index}",
                            message_id=f"EVENT-{4 - index}",
                            source_rowid=index,
                            timestamp_raw_ns=timestamp,
                            timestamp_utc=apple_nanoseconds_to_datetime(timestamp),
                            text=text,
                        )
                        envelope = decode_event_envelope(
                            encode_event_envelope(event, f"REQUEST-{index}")
                        )
                        service._receiver_store.ingest(envelope, received_at_ms=100)
                    feed = service.recent_items()
                finally:
                    service.close()
                    fixture.close()

        self.assertEqual([item.text for item in feed], ["third", "second", "first"])

    def test_feed_applies_and_removes_reaction_badge_on_target_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = RuntimeMessagesFixture(root)
            receiver_config = write_receiver_config(root)
            message = MessagesReader(
                fixture.database_path,
                messages_root=fixture.messages_root,
            ).scan(limit=10).events[0]
            # Apple does not guarantee that a reaction sorts before its target.
            # Keep this addition older to verify order-independent folding.
            added_timestamp = message.timestamp_raw_ns - 1_000_000_000
            removed_timestamp = message.timestamp_raw_ns + 2_000_000_000
            added = ReactionEvent(
                schema_version=1,
                event_kind=EventKind.REACTION_ADDED,
                event_id="REACTION-ADDED",
                source_rowid=2,
                chat_id=message.chat_id,
                participant_ids=message.participant_ids,
                sender=Sender(kind=SenderKind.SELF, identifier="self"),
                direction=Direction.OUTGOING,
                timestamp_raw_ns=added_timestamp,
                timestamp_utc=apple_nanoseconds_to_datetime(added_timestamp),
                target_message_id=message.message_id,
                target_part=0,
                reaction_kind=ReactionKind.THUMBS_UP,
                source_reaction_type=2001,
            )
            replacement_timestamp = message.timestamp_raw_ns + 1_000_000_000
            replacement = ReactionEvent(
                schema_version=1,
                event_kind=EventKind.REACTION_ADDED,
                event_id="REACTION-REPLACEMENT",
                source_rowid=3,
                chat_id=message.chat_id,
                participant_ids=message.participant_ids,
                sender=Sender(kind=SenderKind.SELF, identifier="self"),
                direction=Direction.OUTGOING,
                timestamp_raw_ns=replacement_timestamp,
                timestamp_utc=apple_nanoseconds_to_datetime(replacement_timestamp),
                target_message_id=message.message_id,
                target_part=0,
                reaction_kind=ReactionKind.THUMBS_DOWN,
                source_reaction_type=2002,
            )
            removed = ReactionEvent(
                schema_version=1,
                event_kind=EventKind.REACTION_REMOVED,
                event_id="REACTION-REMOVED",
                source_rowid=4,
                chat_id=message.chat_id,
                participant_ids=message.participant_ids,
                sender=Sender(kind=SenderKind.SELF, identifier="self"),
                direction=Direction.OUTGOING,
                timestamp_raw_ns=removed_timestamp,
                timestamp_utc=apple_nanoseconds_to_datetime(removed_timestamp),
                target_message_id=message.message_id,
                target_part=0,
                reaction_kind=ReactionKind.UNKNOWN,
                source_reaction_type=3002,
                removed_event_id=replacement.event_id,
            )
            with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
                service = RelayRuntimeService(
                    RelayFeatureConfig(receiver_config_path=receiver_config)
                )
                try:
                    for event in (message, added):
                        envelope = decode_event_envelope(
                            encode_event_envelope(event, "REQUEST-" + event.event_id)
                        )
                        service._receiver_store.ingest(envelope, received_at_ms=100)
                    added_feed = service.recent_items()
                    service._receiver_store.ingest(
                        decode_event_envelope(
                            encode_event_envelope(replacement, "REQUEST-REPLACEMENT")
                        ),
                        received_at_ms=100,
                    )
                    replaced_feed = service.recent_items()
                    service._receiver_store.ingest(
                        decode_event_envelope(
                            encode_event_envelope(removed, "REQUEST-REMOVED")
                        ),
                        received_at_ms=100,
                    )
                    removed_feed = service.recent_items()
                finally:
                    service.close()
                    fixture.close()

        self.assertEqual(len(added_feed), 1)
        self.assertEqual(
            [(badge.kind, badge.count) for badge in added_feed[0].reactions],
            [("thumbs_up", 1)],
        )
        self.assertEqual(len(replaced_feed), 1)
        self.assertEqual(
            [(badge.kind, badge.count) for badge in replaced_feed[0].reactions],
            [("thumbs_down", 1)],
        )
        self.assertEqual(len(removed_feed), 1)
        self.assertEqual(removed_feed[0].reactions, ())

    def test_reconciliation_is_unavailable_until_phone_control_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receiver_config = write_receiver_config(root)
            with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
                service = RelayRuntimeService(
                    RelayFeatureConfig(receiver_config_path=receiver_config)
                )
                try:
                    self.assertFalse(service.reconcile_recent())
                    self.assertFalse(service.reconcile_month(2026, 9))
                    status = service.status()
                finally:
                    service.close()

        self.assertFalse(status.reconciliation_available)
        self.assertEqual(
            status.reconciliation_error_code,
            "phone_control_config_invalid",
        )

    def test_phone_control_starts_resumes_and_owns_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receiver_config = write_receiver_config(root)
            coordinator = Mock()
            coordinator.status.return_value = PhoneControlRuntimeStatus(
                phone_state="available",
                error_code=None,
                backlog_count=5,
                reconciliation_state="idle",
                reconciliation_error_code=None,
                last_reconciliation=None,
            )
            coordinator.reconcile_recent.return_value = True
            coordinator.reconcile_month.return_value = True
            with (
                patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}),
                patch(
                    "bmo.features.imessage_relay.feature.load_phone_control_config",
                    return_value=Mock(),
                ),
                patch(
                    "bmo.features.imessage_relay.feature.PhoneControlCoordinator",
                    return_value=coordinator,
                ),
            ):
                service = RelayRuntimeService(
                    RelayFeatureConfig(
                        receiver_config_path=receiver_config,
                        phone_control_config_path=root / "control.json",
                    )
                )
                try:
                    status = service.status()
                    self.assertTrue(service.reconcile_recent())
                    self.assertTrue(service.reconcile_month(2026, 9))
                finally:
                    service.close()

        coordinator.start.assert_called_once_with()
        self.assertEqual(status.incoming_state, "connected")
        self.assertTrue(status.reconciliation_available)
        self.assertEqual(status.phone_backlog_count, 5)
        coordinator.reconcile_recent.assert_called_once_with(None)
        coordinator.reconcile_month.assert_called_once_with(2026, 9, None)
        coordinator.close.assert_called_once_with()


class IMessageRuntimeViewTests(unittest.TestCase):
    def test_qml_keeps_a_stable_feed_model_between_status_refreshes(self) -> None:
        qml_root = Path(__file__).resolve().parents[1] / "bmo/qt/qml"
        source = (qml_root / "IMessageRelayView.qml").read_text(encoding="utf-8")

        self.assertIn("function syncMessages()", source)
        self.assertIn("model: root.displayedMessages", source)
        self.assertNotIn("model: viewModel.messages", source)
        self.assertIn("previousY = messageList.contentY", source)
        self.assertIn("id: reactionBadges", source)
        self.assertIn("model: modelData.reactions || []", source)
        self.assertIn("function reactionIcon(kind)", source)
        for name in (
            "heart.svg",
            "thumbs-up.svg",
            "thumbs-down.svg",
            "haha.svg",
            "emphasize.svg",
            "question.svg",
            "unknown.svg",
        ):
            self.assertTrue(
                (qml_root / "assets/imessage_reactions" / name).is_file(),
                name,
            )

    def status(self, **changes: object) -> RelayRuntimeStatus:
        values: dict[str, object] = {
            "service_state": "available",
            "service_error_code": None,
            "listening": True,
            "received_events": 4,
            "pending_events": 1,
            "complete_attachments": 2,
            "partial_attachments": 0,
            "reconciliation_state": "unavailable",
            "reconciliation_error_code": "phone_control_not_configured",
            "reconciliation_available": False,
            "last_reconciliation": None,
            "incoming_state": "ready",
            "incoming_error_code": None,
            "phone_backlog_count": None,
        }
        values.update(changes)
        return RelayRuntimeStatus(**values)

    def test_qt_view_payload_and_actions_are_content_free(self) -> None:
        host = Mock()
        recent = Mock(return_value=False)
        month = Mock(return_value=False)
        closed = Mock()
        view = QtIMessageRelayView(
            host,
            status_provider=self.status,
            reconcile_recent=recent,
            reconcile_month=month,
            on_close=closed,
            feed_provider=lambda: (
                {
                    "kind": "message",
                    "sender": "invented sender",
                    "timestamp": "2026-09-05T00:00:00+00:00",
                    "text": "invented message",
                    "attachments": (),
                    "reactions": ({"kind": "thumbs_up", "count": 1},),
                },
            ),
        )

        payload = view.payload()
        view.handle_action("relay_reconcile_recent", "")
        unavailable_payload = view.payload()
        view.handle_action("relay_reconcile_month", "private-value")
        invalid_payload = view.payload()
        view.close()

        self.assertEqual(payload["receivedEvents"], 4)
        self.assertIsNone(payload["phoneBacklogCount"])
        self.assertEqual(payload["serviceMessage"], "Receiver is listening.")
        self.assertEqual(payload["messages"][0]["text"], "invented message")
        self.assertEqual(payload["messages"][0]["attachments"], [])
        self.assertEqual(
            payload["messages"][0]["reactions"],
            [{"kind": "thumbs_up", "count": 1}],
        )
        self.assertEqual(unavailable_payload["error"], "Reconciliation is unavailable.")
        self.assertEqual(invalid_payload["error"], "Enter a UTC month as YYYY-MM.")
        recent.assert_called_once()
        month.assert_not_called()
        closed.assert_called_once_with()

    def test_tool_closes_view_before_service(self) -> None:
        service = Mock()
        menu = Mock()
        factory = Mock(return_value=menu)
        context = FeatureMenuContext(master=object(), on_close=Mock())
        tool = IMessageRelayTool(service, app_factory=factory)
        tool.open_menu(context)

        tool.close()

        menu.close.assert_called_once_with()
        service.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
