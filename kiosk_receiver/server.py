"""Standard-library HTTPS service for authenticated relay ingestion."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import ssl
import time
from typing import Mapping

from .auth import AuthenticationError, RequestAuthenticator
from .config import ReceiverConfig, ReceiverConfigError, load_receiver_config
from .protocol import (
    ATTACHMENT_CHUNK_PATH_PREFIX,
    ATTACHMENT_SESSION_PATH,
    EVENT_PATH,
    MAX_ATTACHMENT_CHUNK_BYTES,
    PROTOCOL_VERSION,
    RECONCILIATION_PATH,
    ProtocolError,
    attachment_chunk_response_body,
    decode_attachment_chunk_path,
    decode_event_envelope,
    decode_reconciliation_request,
    decode_upload_session_request,
    reconciliation_response_body,
    response_body,
    upload_session_response_body,
)
from .store import (
    AttachmentStoreError,
    EventConflictError,
    IngestResult,
    ReceiverStateStore,
    ReceiverStoreError,
    ReplayError,
)


SERVER_NAME = "imessage-kiosk-receiver"


@dataclass(frozen=True, slots=True)
class ApplicationResponse:
    status_code: int
    body: bytes


class ReceiverApplication:
    """Transport-neutral request handling and durable ACK/NACK semantics."""

    def __init__(
        self,
        *,
        store: ReceiverStateStore,
        authenticator: RequestAuthenticator,
        clock=time.time,
    ) -> None:
        self.store = store
        self.authenticator = authenticator
        self._clock = clock
        self._started_at = int(clock())

    def handle(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ApplicationResponse:
        request_id: str | None = None
        try:
            authentication = self.authenticator.verify(method, path, headers, body)
            now_seconds = int(self._clock())
            self.store.reserve_nonce(
                key_id=authentication.key_id,
                nonce=authentication.nonce,
                signed_at_seconds=authentication.timestamp,
                now_seconds=now_seconds,
                retention_seconds=self.authenticator.max_clock_skew_seconds * 2 + 1,
            )
            if method == "GET" and path == "/v1/health":
                return _json_response(
                    200,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "service": SERVER_NAME,
                        "status": "ok",
                    },
                )
            if method == "GET" and path == "/v1/status":
                summary = self.store.summary()
                return _json_response(
                    200,
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "service": SERVER_NAME,
                        "status": "ok",
                        "event_count": summary.event_count,
                        "pending_event_count": summary.pending_event_count,
                        "partial_attachment_count": summary.partial_attachment_count,
                        "complete_attachment_count": summary.complete_attachment_count,
                        "last_received_at_ms": summary.last_received_at_ms,
                        "uptime_seconds": max(0, now_seconds - self._started_at),
                    },
                )
            if method == "POST" and path == ATTACHMENT_SESSION_PATH:
                upload_request = decode_upload_session_request(body)
                request_id = upload_request.request_id
                session = self.store.begin_attachment_upload(
                    upload_request,
                    updated_at_ms=now_seconds * 1_000,
                )
                return ApplicationResponse(
                    201 if session.created else 200,
                    upload_session_response_body(
                        request_id=request_id,
                        upload_id=session.upload_id,
                        next_offset=session.next_offset,
                        expected_bytes=session.expected_bytes,
                        status="complete" if session.complete else "ready",
                    ),
                )
            if method == "PUT" and path.startswith(ATTACHMENT_CHUNK_PATH_PREFIX):
                upload_id, offset, request_id = decode_attachment_chunk_path(path)
                if not 1 <= len(body) <= MAX_ATTACHMENT_CHUNK_BYTES:
                    raise ProtocolError(
                        "attachment_chunk_size_invalid",
                        "attachment chunk size is outside the supported range",
                        http_status=413,
                    )
                chunk = self.store.append_attachment_chunk(
                    upload_id=upload_id,
                    offset=offset,
                    chunk=body,
                    updated_at_ms=now_seconds * 1_000,
                )
                return ApplicationResponse(
                    200,
                    attachment_chunk_response_body(
                        request_id=request_id,
                        upload_id=chunk.upload_id,
                        next_offset=chunk.next_offset,
                        status="complete" if chunk.complete else "partial",
                    ),
                )
            if method == "POST" and path == RECONCILIATION_PATH:
                reconciliation = decode_reconciliation_request(body)
                request_id = reconciliation.request_id
                receipts = self.store.reconcile_receipts(reconciliation.candidates)
                return ApplicationResponse(
                    200,
                    reconciliation_response_body(
                        request_id=request_id,
                        receipts=receipts,
                    ),
                )
            if method != "POST" or path != EVENT_PATH:
                return ApplicationResponse(
                    404,
                    response_body(
                        request_id=None,
                        result="nack",
                        error_code="not_found",
                    ),
                )
            envelope = decode_event_envelope(body)
            request_id = envelope.request_id
            result = self.store.ingest(
                envelope,
                received_at_ms=now_seconds * 1_000,
            )
            if result is IngestResult.ATTACHMENTS_PENDING:
                return ApplicationResponse(
                    202,
                    response_body(
                        request_id=request_id,
                        result="pending",
                        status=result.value,
                        event_id=envelope.event_id,
                        attachment_status="partial",
                    ),
                )
            status_code = 201 if result is IngestResult.ACCEPTED else 200
            return ApplicationResponse(
                status_code,
                response_body(
                    request_id=request_id,
                    result="ack",
                    status=result.value,
                    event_id=envelope.event_id,
                    attachment_status=(
                        "complete" if envelope.attachment_requirements else None
                    ),
                ),
            )
        except AuthenticationError as exc:
            return ApplicationResponse(
                exc.http_status,
                response_body(request_id=None, result="nack", error_code=exc.code),
            )
        except ReplayError:
            return ApplicationResponse(
                409,
                response_body(request_id=None, result="nack", error_code="replay_detected"),
            )
        except ProtocolError as exc:
            return ApplicationResponse(
                exc.http_status,
                response_body(request_id=request_id, result="nack", error_code=exc.code),
            )
        except EventConflictError:
            return ApplicationResponse(
                409,
                response_body(
                    request_id=request_id,
                    result="nack",
                    error_code="event_conflict",
                ),
            )
        except AttachmentStoreError as exc:
            return ApplicationResponse(
                exc.http_status,
                response_body(
                    request_id=request_id,
                    result="nack",
                    error_code=exc.code,
                ),
            )
        except ReceiverStoreError:
            return ApplicationResponse(
                503,
                response_body(
                    request_id=request_id,
                    result="nack",
                    error_code="storage_unavailable",
                ),
            )


class ReceiverServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        application: ReceiverApplication,
        *,
        max_request_bytes: int,
        request_timeout_seconds: int,
    ) -> None:
        self.application = application
        self.max_request_bytes = max_request_bytes
        self.request_timeout_seconds = request_timeout_seconds
        super().__init__(server_address, ReceiverRequestHandler)

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        request, address = super().get_request()
        request.settimeout(self.request_timeout_seconds)
        return request, address


class ReceiverRequestHandler(BaseHTTPRequestHandler):
    server: ReceiverServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._dispatch(body=b"")

    def do_POST(self) -> None:
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            self._send_nack(400, "unsupported_transfer_encoding")
            return
        length_raw = self.headers.get("Content-Length")
        try:
            length = int(length_raw) if length_raw is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._send_nack(411, "content_length_required")
            return
        if length > self.server.max_request_bytes:
            self.close_connection = True
            self._send_nack(413, "request_too_large")
            return
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self.close_connection = True
            self._send_nack(415, "unsupported_media_type")
            return
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError):
            self.close_connection = True
            self._send_nack(408, "request_timeout")
            return
        if len(body) != length:
            self.close_connection = True
            self._send_nack(400, "incomplete_request")
            return
        self._dispatch(body=body)

    def do_PUT(self) -> None:
        if not self.path.startswith(ATTACHMENT_CHUNK_PATH_PREFIX):
            self._send_nack(405, "method_not_allowed")
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            self._send_nack(400, "unsupported_transfer_encoding")
            return
        length_raw = self.headers.get("Content-Length")
        try:
            length = int(length_raw) if length_raw is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._send_nack(411, "content_length_required")
            return
        if length == 0 or length > MAX_ATTACHMENT_CHUNK_BYTES:
            self.close_connection = True
            self._send_nack(413, "attachment_chunk_size_invalid")
            return
        if self.headers.get_content_type() != "application/octet-stream":
            self.close_connection = True
            self._send_nack(415, "unsupported_media_type")
            return
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError):
            self.close_connection = True
            self._send_nack(408, "request_timeout")
            return
        if len(body) != length:
            self.close_connection = True
            self._send_nack(400, "incomplete_request")
            return
        self._dispatch(body=body)

    def do_DELETE(self) -> None:
        self._send_nack(405, "method_not_allowed")

    def do_HEAD(self) -> None:
        self._send_nack(405, "method_not_allowed")

    def _dispatch(self, *, body: bytes) -> None:
        response = self.server.application.handle(
            method=self.command,
            path=self.path,
            headers=self.headers,
            body=body,
        )
        self._send(response.status_code, response.body)

    def _send_nack(self, status_code: int, code: str) -> None:
        self._send(
            status_code,
            response_body(request_id=None, result="nack", error_code=code),
        )

    def _send(self, status_code: int, body: bytes) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, format: str, *args: object) -> None:
        # Content-free logging is the default; deployment may wrap this explicitly.
        del format, args


def build_server(config: ReceiverConfig) -> tuple[ReceiverServer, ReceiverStateStore]:
    """Create the service and its owned store; caller owns shutdown and close."""

    tls_context: ssl.SSLContext | None = None
    if config.tls_cert_path is not None and config.tls_key_path is not None:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(config.tls_cert_path, config.tls_key_path)
    store = ReceiverStateStore(config.state_path)
    server: ReceiverServer | None = None
    try:
        authenticator = RequestAuthenticator(
            key_id=config.key_id,
            shared_secret=config.shared_secret,
            max_clock_skew_seconds=config.max_clock_skew_seconds,
        )
        application = ReceiverApplication(store=store, authenticator=authenticator)
        server = ReceiverServer(
            (config.bind_host, config.port),
            application,
            max_request_bytes=config.max_request_bytes,
            request_timeout_seconds=config.request_timeout_seconds,
        )
        if tls_context is not None:
            server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        return server, store
    except Exception:
        if server is not None:
            server.server_close()
        store.close()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the kiosk iMessage relay receiver")
    parser.add_argument("--config", required=True, help="private receiver configuration path")
    arguments = parser.parse_args(argv)
    try:
        config = load_receiver_config(arguments.config)
        server, store = build_server(config)
    except (ReceiverConfigError, ReceiverStoreError, OSError, ssl.SSLError) as exc:
        parser.error(str(exc))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


def _json_response(status_code: int, value: object) -> ApplicationResponse:
    body = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ApplicationResponse(status_code, body)


if __name__ == "__main__":
    raise SystemExit(main())
