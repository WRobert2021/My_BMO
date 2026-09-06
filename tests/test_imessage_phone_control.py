"""Stage 12 kiosk-to-phone control contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from bmo.features.imessage_relay.phone_control import (
    CONTROL_HEALTH_PATH,
    CONTROL_RECONCILIATION_PATH,
    CONTROL_RESUME_PATH,
    ControlTransportResponse,
    HTTPPhoneControlTransport,
    PhoneControlClient,
    PhoneControlCoordinator,
    PhoneControlConfig,
    PhoneControlConfigError,
    PhoneControlError,
    encode_control_request,
    load_phone_control_config,
)
from bmo.features.imessage_relay.receiver.auth import sign_request


SECRET = b"invented-stage12-control-secret-material"


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, bytes, dict[str, str]]] = []
        self.closed = False
        self.status_code = 200
        self.response_status = "available"

    def send(self, *, body, headers, path):
        self.requests.append((path, body, dict(headers)))
        request = json.loads(body)
        response: dict[str, object] = {
            "protocol_version": 1,
            "request_id": request["request_id"],
            "result": "ack",
            "status": self.response_status,
        }
        if self.response_status == "resumed":
            response["backlog_count"] = 3
        elif self.response_status == "scheduled":
            response["reconciliation_id"] = "invented-reconciliation-1"
        return ControlTransportResponse(
            self.status_code,
            {"content-type": "application/json"},
            json.dumps(response, separators=(",", ":"), sort_keys=True).encode(),
        )

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self) -> None:
        self.resume_calls = 0
        self.health_calls = 0
        self.reconciliations: list[tuple[object, ...]] = []
        self.closed = False

    def resume(self):
        self.resume_calls += 1
        from bmo.features.imessage_relay.phone_control import PhoneControlAck

        return PhoneControlAck("resumed", backlog_count=4)

    def health(self):
        self.health_calls += 1
        from bmo.features.imessage_relay.phone_control import PhoneControlAck

        return PhoneControlAck("available")

    def reconcile_recent(self, days):
        self.reconciliations.append(("recent", days))
        from bmo.features.imessage_relay.phone_control import PhoneControlAck

        return PhoneControlAck("scheduled", reconciliation_id="recent-id")

    def reconcile_month(self, year, month):
        self.reconciliations.append(("month", year, month))
        from bmo.features.imessage_relay.phone_control import PhoneControlAck

        return PhoneControlAck("scheduled", reconciliation_id="month-id")

    def close(self):
        self.closed = True


def config() -> PhoneControlConfig:
    return PhoneControlConfig(
        endpoint="http://127.0.0.1:8080",
        key_id="invented-control-key",
        shared_secret=SECRET,
        allow_insecure_loopback=True,
    )


class PhoneControlConfigTests(unittest.TestCase):
    def test_loads_private_configuration_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "secret"
            secret.write_bytes(SECRET + b"\n")
            os.chmod(secret, 0o600)
            path = root / "control.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "endpoint": "https://192.0.2.2:8443",
                        "key_id": "kiosk-control-1",
                        "shared_secret_file": "secret",
                        "tls_ca_path": None,
                        "allow_insecure_loopback": False,
                        "request_timeout_seconds": 5,
                        "network_probe_seconds": 60,
                        "reconciliation_interval_hours": 168,
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_phone_control_config(path, base_directory=root)

        self.assertEqual(loaded.endpoint, "https://192.0.2.2:8443")
        self.assertEqual(loaded.shared_secret, SECRET)
        self.assertEqual(loaded.network_probe_seconds, 60)

    def test_rejects_plain_lan_and_unsafe_secret(self) -> None:
        with self.assertRaises(PhoneControlConfigError):
            PhoneControlConfig(
                endpoint="http://192.0.2.2:8080",
                key_id="key",
                shared_secret=SECRET,
                allow_insecure_loopback=True,
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "secret"
            secret.write_bytes(SECRET)
            os.chmod(secret, 0o644)
            path = root / "control.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "endpoint": "https://192.0.2.2:8443",
                        "key_id": "key",
                        "shared_secret_file": "secret",
                        "tls_ca_path": None,
                        "allow_insecure_loopback": False,
                        "request_timeout_seconds": 5,
                        "network_probe_seconds": 60,
                        "reconciliation_interval_hours": 168,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(PhoneControlConfigError):
                load_phone_control_config(path, base_directory=root)


class PhoneControlProtocolTests(unittest.TestCase):
    def test_canonical_requests_are_exact(self) -> None:
        self.assertEqual(
            encode_control_request(request_id="request-1", action="resume"),
            b'{"action":"resume","protocol_version":1,"request_id":"request-1"}',
        )
        self.assertEqual(
            encode_control_request(
                request_id="request-2",
                action="reconcile",
                window={"kind": "recent", "days": 7},
            ),
            b'{"action":"reconcile","protocol_version":1,"request_id":"request-2","window":{"days":7,"kind":"recent"}}',
        )

    def test_client_signs_and_validates_each_ack(self) -> None:
        transport = FakeTransport()
        identifiers = iter(
            [
                "health-request",
                "health-nonce",
                "resume-request",
                "resume-nonce",
                "recent-request",
                "recent-nonce",
                "month-request",
                "month-nonce",
            ]
        )
        client = PhoneControlClient(
            config(),
            transport=transport,
            clock=lambda: 2_000_000_000,
            identifier_factory=lambda: next(identifiers),
        )

        self.assertEqual(client.health().status, "available")
        transport.response_status = "resumed"
        self.assertEqual(client.resume().backlog_count, 3)
        transport.status_code = 202
        transport.response_status = "scheduled"
        self.assertIsNotNone(client.reconcile_recent(7).reconciliation_id)
        self.assertIsNotNone(client.reconcile_month(2026, 9).reconciliation_id)
        client.close()
        client.close()

        self.assertEqual(
            [request[0] for request in transport.requests],
            [
                CONTROL_HEALTH_PATH,
                CONTROL_RESUME_PATH,
                CONTROL_RECONCILIATION_PATH,
                CONTROL_RECONCILIATION_PATH,
            ],
        )
        for _path, _body, headers in transport.requests:
            self.assertIn("X-Relay-Signature", headers)
            self.assertNotIn(SECRET.decode(), repr(headers))
        self.assertTrue(transport.closed)

    def test_phone_shared_resume_signature_vector(self) -> None:
        body = encode_control_request(
            request_id="vector-request-1", action="resume"
        )
        signature = sign_request(
            SECRET,
            key_id="kiosk-control-1",
            method="POST",
            path=CONTROL_RESUME_PATH,
            timestamp=2_000_000_000,
            nonce="vector-nonce-1",
            body=body,
        )["X-Relay-Signature"]
        self.assertEqual(
            signature,
            "eaa0225ee37309b87c3834bd87a64fb6769a3925acbc65813da4538f6b0245b0",
        )

    def test_client_rejects_mismatched_or_non_json_response(self) -> None:
        transport = FakeTransport()
        client = PhoneControlClient(
            config(),
            transport=transport,
            identifier_factory=lambda: "invented-id",
        )
        transport.response_status = "wrong"
        with self.assertRaisesRegex(PhoneControlError, "response_invalid"):
            client.health()

    def test_transport_rejects_plain_lan_and_unknown_paths(self) -> None:
        with self.assertRaises(PhoneControlConfigError):
            HTTPPhoneControlTransport(
                "http://192.0.2.2:8080",
                allow_insecure_loopback=True,
            )
        transport = HTTPPhoneControlTransport(
            "http://127.0.0.1:8080",
            allow_insecure_loopback=True,
        )
        with self.assertRaises(ValueError):
            transport.send(body=b"{}", headers={}, path="/unknown")
        transport.close()


class PhoneControlCoordinatorTests(unittest.TestCase):
    def test_start_resumes_and_reconciliation_is_single_flight(self) -> None:
        client = FakeClient()
        coordinator = PhoneControlCoordinator(config(), recent_days=7, client=client)
        coordinator.start()
        self.assertTrue(
            wait_until(lambda: coordinator.status().phone_state == "available")
        )
        self.assertEqual(client.resume_calls, 1)
        completed: list[bool] = []

        self.assertTrue(coordinator.reconcile_recent(lambda: completed.append(True)))
        self.assertFalse(coordinator.reconcile_month(2026, 9))
        self.assertTrue(wait_until(lambda: bool(completed)))
        self.assertEqual(client.reconciliations, [("recent", 7)])
        self.assertEqual(coordinator.status().reconciliation_state, "complete")
        coordinator.close()
        coordinator.close()

        self.assertTrue(client.closed)
        self.assertEqual(coordinator.status().phone_state, "closed")


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


if __name__ == "__main__":
    unittest.main()
