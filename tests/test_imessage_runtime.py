"""Stage 10 opt-in lifecycle, reconciliation, and status UI coverage."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
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
from bmo.features.loader import DEFAULT_FEATURE_MODULES, load_feature_registry
from bmo.menu_loader import load_menu_catalog
from bmo.qt.views.imessage_relay import QtIMessageRelayView
from bmo.features.imessage_relay.relay import MessagesReader, RelayStateStore
from bmo.features.imessage_relay.relay.sender import HTTPEventTransport
from bmo.features.imessage_relay.relay.timestamps import APPLE_EPOCH
from bmo.features.imessage_relay.receiver import (
    EVENT_PATH,
    encode_event_envelope,
    sign_request,
)


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


def write_configs(root: Path) -> tuple[Path, Path, Path]:
    receiver_state = root / "receiver.db"
    relay_state = root / "relay.db"
    receiver_config = root / "receiver.json"
    relay_config = root / "relay.json"
    receiver_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bind_host": "127.0.0.1",
                "port": 0,
                "state_path": str(receiver_state),
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
    relay_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state_path": str(relay_state),
                "retry_policy": {
                    "initial_delay_seconds": 1,
                    "multiplier": 2,
                    "max_delay_seconds": 8,
                    "max_attempts": 5,
                    "lease_duration_seconds": 5,
                },
            }
        ),
        encoding="utf-8",
    )
    return receiver_config, relay_config, relay_state


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
            patch("bmo.features.imessage_relay.feature.load_state_config") as relay,
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
        relay.assert_not_called()
        server.assert_not_called()
        self.assertEqual(registry.menu_items, (IMESSAGE_RELAY_MENU_ITEM,))
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
                                "receiver_config_path": root / "missing.json",
                                "relay_config_path": root / "missing-relay.json",
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
            receiver_config, relay_config, _ = write_configs(root)
            with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
                result = load_feature_registry(
                    {
                        "features": [
                            {
                                "module": "bmo.features.imessage_relay",
                                "enabled": True,
                                "settings": {
                                    "receiver_config_path": receiver_config,
                                    "relay_config_path": relay_config,
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
                self.assertEqual(status.service_state, "available")
                self.assertEqual(status.reconciliation_error_code, "source_not_configured")
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

    def test_missing_relay_config_does_not_create_default_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receiver_config, _relay_config, _relay_state = write_configs(root)
            missing_relay_config = root / "missing-relay.json"
            with (
                patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}),
                patch("bmo.features.imessage_relay.feature.load_state_config") as loader,
            ):
                service = RelayRuntimeService(
                    RelayFeatureConfig(
                        receiver_config_path=receiver_config,
                        relay_config_path=missing_relay_config,
                        messages_root=root / "SMS",
                    )
                )
                try:
                    status = service.status()
                finally:
                    service.close()

            loader.assert_not_called()
            self.assertEqual(status.service_state, "available")
            self.assertEqual(
                status.reconciliation_error_code,
                "relay_config_invalid",
            )


class IMessageRuntimeReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = RuntimeMessagesFixture(self.root)
        self.receiver_config, self.relay_config, self.relay_state = write_configs(
            self.root
        )

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def make_service(self, messages_root: Path | None = None) -> RelayRuntimeService:
        return RelayRuntimeService(
            RelayFeatureConfig(
                receiver_config_path=self.receiver_config,
                relay_config_path=self.relay_config,
                messages_root=messages_root,
                reconciliation_recent_days=7,
            )
        )

    def test_recent_reconciliation_requeues_missing_acknowledged_event(self) -> None:
        reader = MessagesReader(
            self.fixture.database_path,
            messages_root=self.fixture.messages_root,
        )
        batch = reader.scan(limit=10)
        with RelayStateStore(self.relay_state) as store:
            store.commit_scan(batch, expected_after_rowid=0, now_ms=0)
            lease = store.claim_next(now_ms=0)
            assert lease is not None
            store.acknowledge(lease.event.event_id, now_ms=1)
        hashes_before = _trio_hashes(self.fixture.messages_root)
        complete = threading.Event()

        with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
            service = self.make_service(self.fixture.messages_root)
            try:
                self.assertTrue(service.reconcile_recent(complete.set))
                self.assertTrue(complete.wait(5))
                recent_status = service.status()
                complete.clear()
                now = datetime.now(timezone.utc)
                self.assertTrue(
                    service.reconcile_month(now.year, now.month, complete.set)
                )
                self.assertTrue(complete.wait(5))
                month_status = service.status()
            finally:
                service.close()

        self.assertEqual(recent_status.reconciliation_state, "complete")
        self.assertEqual(recent_status.last_reconciliation["candidate_count"], 1)
        self.assertEqual(recent_status.last_reconciliation["missing_count"], 1)
        self.assertEqual(recent_status.last_reconciliation["requeued_count"], 1)
        self.assertEqual(
            month_status.last_reconciliation["window_kind"],
            "calendar_month",
        )
        self.assertEqual(_trio_hashes(self.fixture.messages_root), hashes_before)
        with RelayStateStore(self.relay_state) as reopened:
            self.assertEqual(reopened.summary().queued_count, 1)
        rendered = json.dumps(month_status.last_reconciliation, sort_keys=True)
        for private in (
            "invented-runtime-handle",
            "invented-runtime-chat",
            "invented-runtime-message",
            "invented runtime text",
            str(self.fixture.messages_root),
            SECRET_TEXT,
        ):
            self.assertNotIn(private, rendered)

    def test_listener_receipt_updates_content_free_runtime_status(self) -> None:
        event = MessagesReader(
            self.fixture.database_path,
            messages_root=self.fixture.messages_root,
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
            service = self.make_service()
            transport = HTTPEventTransport(
                f"http://127.0.0.1:{service._server.server_address[1]}",
                allow_insecure_loopback=True,
            )
            try:
                response = transport.send(body=body, headers=headers)
                status = service.status()
            finally:
                transport.close()
                service.close()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(status.received_events, 1)
        rendered = json.dumps(status.last_reconciliation, sort_keys=True)
        self.assertNotIn("invented runtime text", rendered)

    def test_missing_source_fails_closed_with_bounded_status(self) -> None:
        complete = threading.Event()
        with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
            service = self.make_service(self.root / "missing-source")
            try:
                self.assertTrue(service.reconcile_recent(complete.set))
                self.assertTrue(complete.wait(5))
                status = service.status()
            finally:
                service.close()

        self.assertEqual(status.reconciliation_state, "failed")
        self.assertEqual(status.reconciliation_error_code, "source_unavailable")
        self.assertFalse(self.relay_state.exists())

    def test_second_reconciliation_is_rejected_while_job_is_running(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def hold(window, callback) -> None:
            del window, callback
            entered.set()
            release.wait(5)

        with patch.dict(os.environ, {SECRET_ENV: SECRET_TEXT}):
            service = self.make_service(self.fixture.messages_root)
            with patch.object(service, "_run_reconciliation", hold):
                self.assertTrue(service.reconcile_recent())
                self.assertTrue(entered.wait(2))
                self.assertFalse(service.reconcile_recent())
                release.set()
                service._job_thread.join(2)
            service.close()


class IMessageRuntimeViewTests(unittest.TestCase):
    def status(self, **changes: object) -> RelayRuntimeStatus:
        values: dict[str, object] = {
            "service_state": "available",
            "service_error_code": None,
            "listening": True,
            "received_events": 4,
            "pending_events": 1,
            "complete_attachments": 2,
            "partial_attachments": 0,
            "reconciliation_state": "idle",
            "reconciliation_error_code": None,
            "reconciliation_available": True,
            "last_reconciliation": None,
        }
        values.update(changes)
        return RelayRuntimeStatus(**values)

    def test_qt_view_payload_and_actions_are_content_free(self) -> None:
        host = Mock()
        recent = Mock(return_value=True)
        month = Mock(return_value=True)
        closed = Mock()
        view = QtIMessageRelayView(
            host,
            status_provider=self.status,
            reconcile_recent=recent,
            reconcile_month=month,
            on_close=closed,
        )

        payload = view.payload()
        view.handle_action("relay_reconcile_recent", "")
        view.handle_action("relay_reconcile_month", "2026-09")
        view.handle_action("relay_reconcile_month", "private-value")
        invalid_payload = view.payload()
        view.close()

        self.assertEqual(payload["receivedEvents"], 4)
        self.assertEqual(payload["serviceMessage"], "Receiver is listening.")
        recent.assert_called_once()
        month.assert_called_once()
        self.assertEqual(invalid_payload["error"], "Enter a UTC month as YYYY-MM.")
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _trio_hashes(messages_root: Path) -> dict[str, str]:
    return {
        name: _sha256(messages_root / name)
        for name in ("sms.db", "sms.db-wal", "sms.db-shm")
    }


if __name__ == "__main__":
    unittest.main()
