"""Authenticated kiosk client for replay-safe Stage 13 outbound commands."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import ssl
import time
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from ..phone_control import PhoneControlConfig
from ..receiver.auth import sign_request
from .protocol import (
    MAX_OUTBOUND_REQUEST_BYTES,
    OUTBOUND_COMMAND_PATH,
    OUTBOUND_STATUS_PATH,
    OutboundCommand,
    OutboundCommandAck,
    OutboundProtocolError,
    decode_command_response,
    encode_status_request,
    encode_submit_request,
)
from .state import OutboundCommandRecord, OutboundStateError, OutboundStateStore


MAX_OUTBOUND_RESPONSE_BYTES = 64 * 1024


class OutboundClientError(RuntimeError):
    """An outbound operation failed without exposing message content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OutboundTransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class OutboundTransport(Protocol):
    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str,
    ) -> OutboundTransportResponse:
        """Send one authenticated outbound request."""

    def close(self) -> None:
        """Release transport resources; repeated calls are safe."""


class HTTPOutboundTransport:
    """Bounded HTTP(S) transport for the phone outbound listener."""

    def __init__(
        self,
        config: PhoneControlConfig,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if not isinstance(config, PhoneControlConfig):
            raise TypeError("config must be PhoneControlConfig")
        parsed = urlsplit(config.endpoint)
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._timeout_seconds = float(config.request_timeout_seconds)
        self._ssl_context = ssl_context
        self._closed = False

    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str,
    ) -> OutboundTransportResponse:
        if self._closed:
            raise OutboundClientError("outbound_client_closed")
        if path not in {OUTBOUND_COMMAND_PATH, OUTBOUND_STATUS_PATH}:
            raise ValueError("outbound path is unsupported")
        if not isinstance(body, bytes) or len(body) > MAX_OUTBOUND_REQUEST_BYTES:
            raise ValueError("outbound request is invalid")
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
            connection.request("POST", path, body=body, headers=dict(headers))
            response = connection.getresponse()
            response_body = response.read(MAX_OUTBOUND_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_OUTBOUND_RESPONSE_BYTES:
                raise OutboundClientError("outbound_response_too_large")
            return OutboundTransportResponse(
                status_code=response.status,
                headers={name.lower(): value for name, value in response.getheaders()},
                body=response_body,
            )
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True


class OutboundCommandClient:
    """Persist, authenticate, submit, and resolve outbound commands."""

    def __init__(
        self,
        config: PhoneControlConfig,
        store: OutboundStateStore,
        *,
        transport: OutboundTransport | None = None,
        clock: Callable[[], float] = time.time,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, PhoneControlConfig):
            raise TypeError("config must be PhoneControlConfig")
        if not isinstance(store, OutboundStateStore):
            raise TypeError("store must be OutboundStateStore")
        ssl_context: ssl.SSLContext | None = None
        if config.endpoint.startswith("https://"):
            ssl_context = ssl.create_default_context(
                cafile=str(config.tls_ca_path) if config.tls_ca_path else None
            )
        self.config = config
        self._store = store
        self._transport = transport or HTTPOutboundTransport(
            config,
            ssl_context=ssl_context,
        )
        self._clock = clock
        self._identifier_factory = identifier_factory or (lambda: uuid4().hex)
        self._closed = False

    def submit(self, command: OutboundCommand) -> OutboundCommandRecord:
        self._require_open()
        record = self._store.enqueue(command)
        if record.state in {"sent", "failed"}:
            return record
        if record.state in {"executing", "uncertain"}:
            raise OutboundClientError("outbound_status_required")
        request_id = self._identifier_factory()
        body = encode_submit_request(request_id=request_id, command=command)
        headers = self._headers(path=OUTBOUND_COMMAND_PATH, body=body)
        self._store.record_attempt(command.command_id, request_id)
        try:
            response = self._transport.send(
                body=body,
                headers=headers,
                path=OUTBOUND_COMMAND_PATH,
            )
            ack = self._decode_response(
                response,
                request_id=request_id,
                command_id=command.command_id,
                accepted_statuses={200, 202},
            )
            return self._store.apply_ack(ack)
        except OutboundClientError as exc:
            self._mark_uncertain(command.command_id, exc.code)
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            self._mark_uncertain(command.command_id, "phone_unreachable")
            raise OutboundClientError("phone_unreachable") from exc

    def status(self, command_id: str) -> OutboundCommandRecord:
        self._require_open()
        record = self._store.get(command_id)
        if record is None:
            raise OutboundClientError("outbound_command_missing")
        request_id = self._identifier_factory()
        body = encode_status_request(request_id=request_id, command_id=command_id)
        headers = self._headers(path=OUTBOUND_STATUS_PATH, body=body)
        try:
            response = self._transport.send(
                body=body,
                headers=headers,
                path=OUTBOUND_STATUS_PATH,
            )
            ack = self._decode_response(
                response,
                request_id=request_id,
                command_id=command_id,
                accepted_statuses={200},
            )
            return self._store.apply_ack(ack)
        except OutboundClientError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise OutboundClientError("phone_unreachable") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def _headers(self, *, path: str, body: bytes) -> dict[str, str]:
        nonce = self._identifier_factory()
        headers = sign_request(
            self.config.shared_secret,
            key_id=self.config.key_id,
            method="POST",
            path=path,
            timestamp=int(self._clock()),
            nonce=nonce,
            body=body,
        )
        headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )
        return headers

    @staticmethod
    def _decode_response(
        response: OutboundTransportResponse,
        *,
        request_id: str,
        command_id: str,
        accepted_statuses: set[int],
    ) -> OutboundCommandAck:
        if response.status_code not in accepted_statuses:
            raise OutboundClientError("outbound_request_rejected")
        content_type = response.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise OutboundClientError("outbound_response_invalid")
        try:
            return decode_command_response(
                response.body,
                expected_request_id=request_id,
                expected_command_id=command_id,
            )
        except OutboundProtocolError as exc:
            raise OutboundClientError("outbound_response_invalid") from exc

    def _mark_uncertain(self, command_id: str, error_code: str) -> None:
        try:
            self._store.mark_uncertain(command_id, error_code)
        except OutboundStateError as exc:
            raise OutboundClientError("outbound_state_unavailable") from exc

    def _require_open(self) -> None:
        if self._closed:
            raise OutboundClientError("outbound_client_closed")


__all__ = [
    "HTTPOutboundTransport",
    "MAX_OUTBOUND_RESPONSE_BYTES",
    "OutboundClientError",
    "OutboundCommandClient",
    "OutboundTransport",
    "OutboundTransportResponse",
]
