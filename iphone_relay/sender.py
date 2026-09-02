"""Stage 5–7 sender for simulated, at-least-once relay delivery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from kiosk_receiver.auth import sign_request
from kiosk_receiver.protocol import (
    ATTACHMENT_CHUNK_PATH_PREFIX,
    ATTACHMENT_SESSION_PATH,
    EVENT_PATH,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_CHUNK_BYTES,
    PROTOCOL_VERSION,
    RECONCILIATION_PATH,
    ProtocolError,
    attachment_chunk_path,
    decode_attachment_chunk_response,
    decode_upload_session_response,
    encode_event_envelope,
    encode_upload_session_request,
)

from .contracts import AttachmentAvailability, MessageEvent, NormalizedEvent
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
    "attachment_chunk_size_invalid",
    "attachment_digest_mismatch",
    "attachment_offset_mismatch",
    "attachment_session_invalid",
    "attachment_storage_unavailable",
    "attachment_unavailable",
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
        method: str = "POST",
    ) -> TransportResponse:
        """Send one event request and return the complete bounded response."""

    def close(self) -> None:
        """Release transport resources; repeated calls must be safe."""


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    disposition: DeliveryDisposition
    error_code: str | None


@dataclass(frozen=True, slots=True)
class _AttachmentSource:
    blob_id: str
    path: Path
    expected_bytes: int


@dataclass(frozen=True, slots=True)
class _EventResponse:
    error_code: str | None
    attachments_pending: bool


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
        method: str = "POST",
    ) -> TransportResponse:
        if self._closed:
            raise SenderClosedError("relay sender transport is closed")
        if method == "POST" and path in {
            EVENT_PATH,
            RECONCILIATION_PATH,
            ATTACHMENT_SESSION_PATH,
        }:
            pass
        elif method == "PUT" and path.startswith(ATTACHMENT_CHUNK_PATH_PREFIX):
            pass
        else:
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
                method,
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
    """Claim queue entries and deliver events plus required attachment bytes."""

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

        try:
            attachment_sources = _attachment_sources(lease.event)
            event_response = self._send_event(
                lease.event,
                has_attachments=bool(attachment_sources),
            )
            error_code = event_response.error_code
            if error_code is None and event_response.attachments_pending:
                for source in attachment_sources:
                    self._upload_attachment(lease.event.event_id, source)
                final_response = self._send_event(
                    lease.event,
                    has_attachments=True,
                )
                error_code = final_response.error_code
                if error_code is None and final_response.attachments_pending:
                    error_code = "attachments_incomplete"
        except _AttachmentDeliveryError as exc:
            error_code = exc.code
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

    def _send_event(
        self,
        event: NormalizedEvent,
        *,
        has_attachments: bool,
    ) -> _EventResponse:
        request_id = self._fresh_identifier("request")
        nonce = self._fresh_identifier("nonce")
        body = encode_event_envelope(event, request_id)
        headers = sign_request(
            self._shared_secret,
            key_id=self.key_id,
            method="POST",
            path=EVENT_PATH,
            timestamp=int(self._clock()),
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
        return _event_response(
            response,
            expected_request_id=request_id,
            expected_event_id=event.event_id,
            has_attachments=has_attachments,
        )

    def _upload_attachment(self, event_id: str, source: _AttachmentSource) -> None:
        descriptor, fingerprint = _open_attachment_source(source)
        try:
            content_sha256 = _hash_descriptor(descriptor)
            request_id = self._fresh_identifier("request")
            nonce = self._fresh_identifier("nonce")
            body = encode_upload_session_request(
                request_id=request_id,
                event_id=event_id,
                blob_id=source.blob_id,
                expected_bytes=source.expected_bytes,
                content_sha256=content_sha256,
            )
            headers = sign_request(
                self._shared_secret,
                key_id=self.key_id,
                method="POST",
                path=ATTACHMENT_SESSION_PATH,
                timestamp=int(self._clock()),
                nonce=nonce,
                body=body,
            )
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
            response = self.transport.send(
                body=body,
                headers=headers,
                path=ATTACHMENT_SESSION_PATH,
            )
            session = _validated_upload_session_response(
                response,
                expected_request_id=request_id,
                expected_bytes=source.expected_bytes,
            )
            offset = session.next_offset
            os.lseek(descriptor, offset, os.SEEK_SET)
            while offset < source.expected_bytes:
                chunk = os.read(
                    descriptor,
                    min(MAX_ATTACHMENT_CHUNK_BYTES, source.expected_bytes - offset),
                )
                if not chunk:
                    raise _AttachmentDeliveryError("attachment_source_changed")
                chunk_request_id = self._fresh_identifier("request")
                chunk_path = attachment_chunk_path(
                    upload_id=session.upload_id,
                    offset=offset,
                    request_id=chunk_request_id,
                )
                chunk_headers = sign_request(
                    self._shared_secret,
                    key_id=self.key_id,
                    method="PUT",
                    path=chunk_path,
                    timestamp=int(self._clock()),
                    nonce=self._fresh_identifier("nonce"),
                    body=chunk,
                )
                chunk_headers.update(
                    {
                        "Content-Type": "application/octet-stream",
                        "Accept": "application/json",
                    }
                )
                chunk_response = self.transport.send(
                    body=chunk,
                    headers=chunk_headers,
                    path=chunk_path,
                    method="PUT",
                )
                offset = _validated_chunk_response(
                    chunk_response,
                    expected_request_id=chunk_request_id,
                    expected_upload_id=session.upload_id,
                    prior_offset=offset,
                    chunk_bytes=len(chunk),
                    expected_bytes=source.expected_bytes,
                )
            if _descriptor_fingerprint(descriptor) != fingerprint:
                raise _AttachmentDeliveryError("attachment_source_changed")
        finally:
            os.close(descriptor)

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


def _event_response(
    response: TransportResponse,
    *,
    expected_request_id: str,
    expected_event_id: str,
    has_attachments: bool,
) -> _EventResponse:
    if len(response.body) > MAX_RESPONSE_BYTES:
        return _EventResponse("malformed_response", False)
    content_type = next(
        (
            value
            for name, value in response.headers.items()
            if name.lower() == "content-type"
        ),
        "",
    )
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return _EventResponse("malformed_response", False)
    try:
        value = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        return _EventResponse("malformed_response", False)
    if not isinstance(value, dict):
        return _EventResponse("malformed_response", False)
    version = value.get("protocol_version")
    if type(version) is not int or version != PROTOCOL_VERSION:
        return _EventResponse("malformed_response", False)

    if value.get("result") == "ack":
        expected_keys = {
            "protocol_version",
            "request_id",
            "result",
            "status",
            "event_id",
        }
        if has_attachments:
            expected_keys.add("attachment_status")
        if set(value) != expected_keys:
            return _EventResponse("malformed_response", False)
        status = value.get("status")
        if (
            value.get("request_id") != expected_request_id
            or value.get("event_id") != expected_event_id
            or not isinstance(status, str)
            or status not in _ACK_STATUSES
            or response.status_code != _ACK_STATUSES[status]
            or (has_attachments and value.get("attachment_status") != "complete")
        ):
            return _EventResponse("ack_mismatch", False)
        return _EventResponse(None, False)

    if value.get("result") == "pending":
        if (
            not has_attachments
            or set(value)
            != {
                "protocol_version",
                "request_id",
                "result",
                "status",
                "event_id",
                "attachment_status",
            }
            or value.get("request_id") != expected_request_id
            or value.get("event_id") != expected_event_id
            or value.get("status") != "attachments_pending"
            or value.get("attachment_status") != "partial"
            or response.status_code != 202
        ):
            return _EventResponse("ack_mismatch", False)
        return _EventResponse(None, True)

    if value.get("result") == "nack":
        if set(value) != {"protocol_version", "request_id", "result", "error"}:
            return _EventResponse("malformed_response", False)
        request_id = value.get("request_id")
        if request_id not in {None, expected_request_id}:
            return _EventResponse("malformed_response", False)
        error = value.get("error")
        if not isinstance(error, dict) or set(error) != {"code"}:
            return _EventResponse("malformed_response", False)
        code = error.get("code")
        if not isinstance(code, str) or not _SAFE_ERROR_CODE.fullmatch(code):
            return _EventResponse("malformed_response", False)
        if 200 <= response.status_code < 300:
            return _EventResponse("malformed_response", False)
        return _EventResponse(
            code if code in _KNOWN_NACK_CODES else "receiver_nack",
            False,
        )

    return _EventResponse("malformed_response", False)


class _AttachmentDeliveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _attachment_sources(event: NormalizedEvent) -> tuple[_AttachmentSource, ...]:
    if not isinstance(event, MessageEvent):
        return ()
    sources: list[_AttachmentSource] = []
    seen: set[str] = set()
    for attachment in event.attachments:
        if attachment.availability is not AttachmentAvailability.AVAILABLE:
            raise _AttachmentDeliveryError("attachment_source_unavailable")
        if attachment.components:
            candidates = (
                (component.component_id, component.source_path, component.actual_bytes)
                for component in attachment.components
            )
        else:
            candidates = (
                (attachment.attachment_id, attachment.source_path, attachment.actual_bytes),
            )
        for blob_id, source_path, expected_bytes in candidates:
            if (
                blob_id in seen
                or source_path is None
                or expected_bytes is None
                or expected_bytes < 0
                or expected_bytes > MAX_ATTACHMENT_BYTES
            ):
                raise _AttachmentDeliveryError("attachment_source_unavailable")
            seen.add(blob_id)
            sources.append(
                _AttachmentSource(
                    blob_id=blob_id,
                    path=Path(source_path),
                    expected_bytes=expected_bytes,
                )
            )
    return tuple(sources)


def _open_attachment_source(
    source: _AttachmentSource,
) -> tuple[int, tuple[int, int, int, int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source.path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise _AttachmentDeliveryError("attachment_source_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != source.expected_bytes:
        os.close(descriptor)
        raise _AttachmentDeliveryError("attachment_source_changed")
    return descriptor, _metadata_fingerprint(metadata)


def _descriptor_fingerprint(descriptor: int) -> tuple[int, int, int, int, int]:
    return _metadata_fingerprint(os.fstat(descriptor))


def _metadata_fingerprint(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _hash_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, MAX_ATTACHMENT_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def _validated_upload_session_response(
    response: TransportResponse,
    *,
    expected_request_id: str,
    expected_bytes: int,
):
    body = _attachment_response_body(
        response,
        expected_request_id=expected_request_id,
        success_statuses={200, 201},
    )
    try:
        session = decode_upload_session_response(body)
    except ProtocolError as exc:
        raise _AttachmentDeliveryError("malformed_response") from exc
    if (
        session.request_id != expected_request_id
        or session.expected_bytes != expected_bytes
        or session.next_offset > expected_bytes
        or (session.status == "complete") != (session.next_offset == expected_bytes)
    ):
        raise _AttachmentDeliveryError("attachment_response_mismatch")
    return session


def _validated_chunk_response(
    response: TransportResponse,
    *,
    expected_request_id: str,
    expected_upload_id: str,
    prior_offset: int,
    chunk_bytes: int,
    expected_bytes: int,
) -> int:
    body = _attachment_response_body(
        response,
        expected_request_id=expected_request_id,
        success_statuses={200},
    )
    try:
        chunk = decode_attachment_chunk_response(body)
    except ProtocolError as exc:
        raise _AttachmentDeliveryError("malformed_response") from exc
    expected_offset = prior_offset + chunk_bytes
    if (
        chunk.request_id != expected_request_id
        or chunk.upload_id != expected_upload_id
        or chunk.next_offset != expected_offset
        or chunk.next_offset > expected_bytes
        or (chunk.status == "complete") != (chunk.next_offset == expected_bytes)
    ):
        raise _AttachmentDeliveryError("attachment_response_mismatch")
    return chunk.next_offset


def _attachment_response_body(
    response: TransportResponse,
    *,
    expected_request_id: str,
    success_statuses: set[int],
) -> bytes:
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise _AttachmentDeliveryError("malformed_response")
    content_type = next(
        (
            value
            for name, value in response.headers.items()
            if name.lower() == "content-type"
        ),
        "",
    )
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise _AttachmentDeliveryError("malformed_response")
    if response.status_code in success_statuses:
        return response.body
    try:
        value = json.loads(
            response.body.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise _AttachmentDeliveryError("malformed_response") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol_version", "request_id", "result", "error"}
        or value.get("protocol_version") != PROTOCOL_VERSION
        or value.get("result") != "nack"
        or value.get("request_id") not in {None, expected_request_id}
        or not isinstance(value.get("error"), dict)
        or set(value["error"]) != {"code"}
        or not isinstance(value["error"].get("code"), str)
        or _SAFE_ERROR_CODE.fullmatch(value["error"]["code"]) is None
    ):
        raise _AttachmentDeliveryError("malformed_response")
    code = value["error"]["code"]
    raise _AttachmentDeliveryError(
        code if code in _KNOWN_NACK_CODES else "receiver_nack"
    )


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
