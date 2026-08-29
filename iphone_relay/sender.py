"""Stage 5 sender for simulated, at-least-once relay delivery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from kiosk_receiver.auth import sign_request
from kiosk_receiver.protocol import (
    EVENT_PATH,
    PROTOCOL_VERSION,
    RECONCILIATION_PATH,
    ProtocolError,
    encode_event_envelope,
)

from .state import QueueStatus, RelayStateStore, StateSummary


MAX_RESPONSE_BYTES = 64 * 1024
_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_ACK_STATUSES = {"accepted": 201, "duplicate": 200}
_KNOWN_NACK_CODES = {
    "authentication_required",
    "duplicate_field",
    "event_conflict",
    "incomplete_request",
    "invalid_authentication",
    "invalid_schema",
    "invalid_signature",
    "malformed_json",
    "method_not_allowed",
    "not_found",
    "replay_detected",
    "request_timeout",
    "request_too_large",
    "stale_request",
    "storage_unavailable",
    "unknown_client",
    "unsupported_event_version",
    "unsupported_media_type",
    "unsupported_protocol_version",
    "unsupported_transfer_encoding",
}


class DeliveryDisposition(StrEnum):
    IDLE = "idle"
    ACKNOWLEDGED = "acknowledged"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTERED = "dead_lettered"


class SenderClosedError(RuntimeError):
    """A closed sender or transport cannot start another attempt."""


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class EventTransport(Protocol):
    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str = EVENT_PATH,
    ) -> TransportResponse:
        """Send one event request and return the complete bounded response."""

    def close(self) -> None:
        """Release transport resources; repeated calls must be safe."""


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    disposition: DeliveryDisposition
    error_code: str | None


@dataclass(frozen=True, slots=True)
class SenderStatus:
    scanned_through_rowid: int
    queued_count: int
    in_flight_count: int
    retry_wait_count: int
    acknowledged_count: int
    dead_letter_count: int
    issue_count: int
    attempts_started: int
    attempts_acknowledged: int
    attempts_failed: int
    last_error_code: str | None

    @property
    def pending_count(self) -> int:
        return self.queued_count + self.in_flight_count + self.retry_wait_count


class HTTPEventTransport:
    """One-request HTTP(S) transport with explicit loopback-development policy."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        allow_insecure_loopback: bool = False,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.hostname is None
        ):
            raise ValueError("relay endpoint must be an HTTP(S) origin")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("relay endpoint port is invalid") from exc
        if parsed.scheme == "http" and (
            not allow_insecure_loopback or not _is_loopback(parsed.hostname)
        ):
            raise ValueError("plain HTTP is allowed only for explicit loopback simulation")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds > 120
        ):
            raise ValueError("transport timeout must be between 0 and 120 seconds")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= MAX_RESPONSE_BYTES
        ):
            raise ValueError("maximum response bytes is outside the supported range")
        if parsed.scheme == "http" and ssl_context is not None:
            raise ValueError("an SSL context cannot be used with plain HTTP")

        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = port or (443 if parsed.scheme == "https" else 80)
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._ssl_context = ssl_context
        self._closed = False

    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str = EVENT_PATH,
    ) -> TransportResponse:
        if self._closed:
            raise SenderClosedError("relay sender transport is closed")
        if path not in {EVENT_PATH, RECONCILIATION_PATH}:
            raise ValueError("relay request path is unsupported")
        connection: http.client.HTTPConnection
        if self._scheme == "https":
            connection = http.client.HTTPSConnection(
                self._host,
                self._port,
                timeout=self._timeout_seconds,
                context=self._ssl_context,
            )
        else:
            connection = http.client.HTTPConnection(
                self._host,
                self._port,
                timeout=self._timeout_seconds,
            )
        try:
            connection.request(
                "POST",
                path,
                body=body,
                headers=dict(headers),
            )
            response = connection.getresponse()
            response_body = response.read(self._max_response_bytes + 1)
            if len(response_body) > self._max_response_bytes:
                raise http.client.HTTPException("receiver response exceeds size limit")
            response_headers = {
                name.lower(): value for name, value in response.getheaders()
            }
            return TransportResponse(response.status, response_headers, response_body)
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True


class RelaySender:
    """Claim Stage 3 queue entries and deliver them under the Stage 4 protocol."""

    def __init__(
        self,
        *,
        store: RelayStateStore,
        transport: EventTransport,
        key_id: str,
        shared_secret: bytes,
        clock: Callable[[], float] = time.time,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(shared_secret, bytes) or len(shared_secret) < 32:
            raise ValueError("shared secret must contain at least 32 bytes")
        self.store = store
        self.transport = transport
        self.key_id = key_id
        self._shared_secret = shared_secret
        sign_request(
            shared_secret,
            key_id=key_id,
            method="POST",
            path=EVENT_PATH,
            timestamp=0,
            nonce="sender-validation",
        )
        self._clock = clock
        self._identifier_factory = identifier_factory or (lambda: str(uuid4()))
        self._closed = False
        self._attempts_started = 0
        self._attempts_acknowledged = 0
        self._attempts_failed = 0
        self._last_error_code: str | None = None

    def __enter__(self) -> RelaySender:
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.transport.close()

    def deliver_once(self, *, now_ms: int | None = None) -> DeliveryResult:
        """Attempt one eligible queue item and durably record the outcome."""

        self._require_open()
        lease = self.store.claim_next(now_ms=now_ms)
        if lease is None:
            return DeliveryResult(DeliveryDisposition.IDLE, None)
        self._attempts_started += 1

        request_id = self._fresh_identifier("request")
        nonce = self._fresh_identifier("nonce")
        try:
            body = encode_event_envelope(lease.event, request_id)
            timestamp = int(self._clock())
            headers = sign_request(
                self._shared_secret,
                key_id=self.key_id,
                method="POST",
                path=EVENT_PATH,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
            )
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
            response = self.transport.send(body=body, headers=headers)
            error_code = _response_error(
                response,
                expected_request_id=request_id,
                expected_event_id=lease.event.event_id,
            )
        except (TimeoutError, socket.timeout):
            error_code = "ack_timeout"
        except ProtocolError:
            error_code = "payload_rejected"
        except http.client.HTTPException:
            error_code = "malformed_response"
        except (ConnectionError, OSError):
            error_code = "transport_unavailable"

        if error_code is None:
            self.store.acknowledge(lease.event.event_id, now_ms=now_ms)
            self._attempts_acknowledged += 1
            self._last_error_code = None
            return DeliveryResult(DeliveryDisposition.ACKNOWLEDGED, None)

        entry = self.store.record_failure(
            lease.attempt_id,
            error_code=error_code,
            now_ms=now_ms,
        )
        self._attempts_failed += 1
        self._last_error_code = error_code
        disposition = (
            DeliveryDisposition.DEAD_LETTERED
            if entry.status is QueueStatus.DEAD_LETTER
            else DeliveryDisposition.RETRY_SCHEDULED
        )
        return DeliveryResult(disposition, error_code)

    def status(self) -> SenderStatus:
        """Return content-free queue and attempt counters."""

        self._require_open()
        return _sender_status(
            self.store.summary(),
            attempts_started=self._attempts_started,
            attempts_acknowledged=self._attempts_acknowledged,
            attempts_failed=self._attempts_failed,
            last_error_code=self._last_error_code,
        )

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        wait: Callable[[float], None] = time.sleep,
        on_status: Callable[[SenderStatus], None] | None = None,
    ) -> SenderStatus:
        """Run a manual loop until Ctrl-C, then close transport resources."""

        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or poll_interval_seconds <= 0
            or poll_interval_seconds > 60
        ):
            raise ValueError("poll interval must be between 0 and 60 seconds")
        self._require_open()
        final_status: SenderStatus | None = None
        try:
            while True:
                result = self.deliver_once()
                final_status = self.status()
                if on_status is not None:
                    on_status(final_status)
                if result.disposition is DeliveryDisposition.IDLE:
                    wait(float(poll_interval_seconds))
        except KeyboardInterrupt:
            if final_status is None:
                final_status = self.status()
            return final_status
        finally:
            self.close()

    def _fresh_identifier(self, label: str) -> str:
        value = self._identifier_factory()
        if not isinstance(value, str):
            raise ValueError(f"{label} identifier factory must return a string")
        return value

    def _require_open(self) -> None:
        if self._closed:
            raise SenderClosedError("relay sender is closed")


def _response_error(
    response: TransportResponse,
    *,
    expected_request_id: str,
    expected_event_id: str,
) -> str | None:
    if len(response.body) > MAX_RESPONSE_BYTES:
        return "malformed_response"
    content_type = next(
        (
            value
            for name, value in response.headers.items()
            if name.lower() == "content-type"
        ),
        "",
    )
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return "malformed_response"
    try:
        value = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        return "malformed_response"
    if not isinstance(value, dict):
        return "malformed_response"
    version = value.get("protocol_version")
    if type(version) is not int or version != PROTOCOL_VERSION:
        return "malformed_response"

    if value.get("result") == "ack":
        if set(value) != {
            "protocol_version",
            "request_id",
            "result",
            "status",
            "event_id",
        }:
            return "malformed_response"
        status = value.get("status")
        if (
            value.get("request_id") != expected_request_id
            or value.get("event_id") != expected_event_id
            or not isinstance(status, str)
            or status not in _ACK_STATUSES
            or response.status_code != _ACK_STATUSES[status]
        ):
            return "ack_mismatch"
        return None

    if value.get("result") == "nack":
        if set(value) != {"protocol_version", "request_id", "result", "error"}:
            return "malformed_response"
        request_id = value.get("request_id")
        if request_id not in {None, expected_request_id}:
            return "malformed_response"
        error = value.get("error")
        if not isinstance(error, dict) or set(error) != {"code"}:
            return "malformed_response"
        code = error.get("code")
        if not isinstance(code, str) or not _SAFE_ERROR_CODE.fullmatch(code):
            return "malformed_response"
        if 200 <= response.status_code < 300:
            return "malformed_response"
        return code if code in _KNOWN_NACK_CODES else "receiver_nack"

    return "malformed_response"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ValueError("non-finite response number")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _sender_status(
    summary: StateSummary,
    *,
    attempts_started: int,
    attempts_acknowledged: int,
    attempts_failed: int,
    last_error_code: str | None,
) -> SenderStatus:
    return SenderStatus(
        scanned_through_rowid=summary.scanned_through_rowid,
        queued_count=summary.queued_count,
        in_flight_count=summary.in_flight_count,
        retry_wait_count=summary.retry_wait_count,
        acknowledged_count=summary.acknowledged_count,
        dead_letter_count=summary.dead_letter_count,
        issue_count=summary.issue_count,
        attempts_started=attempts_started,
        attempts_acknowledged=attempts_acknowledged,
        attempts_failed=attempts_failed,
        last_error_code=last_error_code,
    )
