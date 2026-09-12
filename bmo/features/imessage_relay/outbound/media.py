"""Verified kiosk-to-phone staging for outbound photo and video bytes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import http.client
import os
from pathlib import Path
import ssl
import stat
import time
from typing import Protocol
from uuid import uuid4

from ..phone_control import PhoneControlConfig
from ..receiver.auth import sign_request
from .protocol import (
    MAX_OUTBOUND_MEDIA_CHUNK_BYTES,
    OUTBOUND_MEDIA_SESSION_PATH,
    OutboundMediaCommand,
    OutboundMediaReference,
    OutboundProtocolError,
    decode_media_chunk_response,
    decode_media_session_response,
    encode_media_session_request,
    media_chunk_path,
)


class OutboundMediaError(RuntimeError):
    """Media staging failed without exposing content or a local path."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MediaTransportResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class MediaTransport(Protocol):
    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str,
    ) -> MediaTransportResponse:
        """Send one session request or bounded raw chunk."""


class OutboundMediaUploader:
    """Stage exact command media without persisting kiosk filesystem paths."""

    def __init__(
        self,
        config: PhoneControlConfig,
        transport: MediaTransport,
        *,
        clock: Callable[[], float] = time.time,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, PhoneControlConfig):
            raise TypeError("config must be PhoneControlConfig")
        self.config = config
        self._transport = transport
        self._clock = clock
        self._identifier_factory = identifier_factory or (lambda: uuid4().hex)

    def stage(
        self,
        command: OutboundMediaCommand,
        source_paths: Mapping[str, Path | str],
    ) -> None:
        if not isinstance(command, OutboundMediaCommand):
            raise TypeError("command must be an OutboundMediaCommand")
        if not isinstance(source_paths, Mapping):
            raise TypeError("source_paths must be a mapping")
        expected_ids = {item.blob_id for item in command.media}
        if set(source_paths) != expected_ids:
            raise OutboundMediaError("outbound_media_sources_invalid")
        for media in command.media:
            self._stage_one(command.command_id, media, source_paths[media.blob_id])

    def _stage_one(
        self,
        command_id: str,
        media: OutboundMediaReference,
        source_path: Path | str,
    ) -> None:
        descriptor = _open_source(source_path)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size != media.expected_bytes:
                raise OutboundMediaError("outbound_media_source_invalid")
            digest = _digest_descriptor(descriptor)
            if digest != media.sha256:
                raise OutboundMediaError("outbound_media_digest_mismatch")

            session_request_id = self._identifier_factory()
            session_body = encode_media_session_request(
                request_id=session_request_id,
                command_id=command_id,
                media=media,
            )
            session_response = self._send(
                body=session_body,
                path=OUTBOUND_MEDIA_SESSION_PATH,
                accepted_statuses={200, 201},
            )
            try:
                session = decode_media_session_response(
                    session_response.body,
                    expected_request_id=session_request_id,
                    expected_command_id=command_id,
                    expected_blob_id=media.blob_id,
                )
            except OutboundProtocolError as exc:
                raise OutboundMediaError("outbound_media_response_invalid") from exc
            if session.next_offset > media.expected_bytes:
                raise OutboundMediaError("outbound_media_offset_invalid")
            if session.status == "complete":
                if session.next_offset != media.expected_bytes:
                    raise OutboundMediaError("outbound_media_offset_invalid")
                after = os.fstat(descriptor)
                if _file_identity(before) != _file_identity(after):
                    raise OutboundMediaError("outbound_media_source_changed")
                return
            if session.next_offset == media.expected_bytes:
                raise OutboundMediaError("outbound_media_response_invalid")

            os.lseek(descriptor, session.next_offset, os.SEEK_SET)
            offset = session.next_offset
            while offset < media.expected_bytes:
                length = min(
                    MAX_OUTBOUND_MEDIA_CHUNK_BYTES,
                    media.expected_bytes - offset,
                )
                chunk = os.read(descriptor, length)
                if len(chunk) != length:
                    raise OutboundMediaError("outbound_media_source_changed")
                chunk_request_id = self._identifier_factory()
                path = media_chunk_path(
                    upload_id=session.upload_id,
                    offset=offset,
                    request_id=chunk_request_id,
                )
                chunk_response = self._send(
                    body=chunk,
                    path=path,
                    accepted_statuses={200},
                )
                try:
                    chunk_ack = decode_media_chunk_response(
                        chunk_response.body,
                        expected_request_id=chunk_request_id,
                        expected_upload_id=session.upload_id,
                    )
                except OutboundProtocolError as exc:
                    raise OutboundMediaError(
                        "outbound_media_response_invalid"
                    ) from exc
                expected_offset = offset + len(chunk)
                expected_status = (
                    "complete"
                    if expected_offset == media.expected_bytes
                    else "partial"
                )
                if (
                    chunk_ack.next_offset != expected_offset
                    or chunk_ack.status != expected_status
                ):
                    raise OutboundMediaError("outbound_media_offset_invalid")
                offset = expected_offset

            after = os.fstat(descriptor)
            if _file_identity(before) != _file_identity(after):
                raise OutboundMediaError("outbound_media_source_changed")
        except OutboundMediaError:
            raise
        except OSError as exc:
            raise OutboundMediaError("outbound_media_source_unavailable") from exc
        finally:
            os.close(descriptor)

    def _send(
        self,
        *,
        body: bytes,
        path: str,
        accepted_statuses: set[int],
    ) -> MediaTransportResponse:
        nonce = self._identifier_factory()
        headers = sign_request(
            self.config.shared_secret,
            key_id=self.config.key_id,
            method="POST" if path == OUTBOUND_MEDIA_SESSION_PATH else "PUT",
            path=path,
            timestamp=int(self._clock()),
            nonce=nonce,
            body=body,
        )
        headers.update(
            {
                "Content-Type": (
                    "application/json"
                    if path == OUTBOUND_MEDIA_SESSION_PATH
                    else "application/octet-stream"
                ),
                "Accept": "application/json",
            }
        )
        try:
            response = self._transport.send(body=body, headers=headers, path=path)
        except OutboundMediaError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise OutboundMediaError("phone_unreachable") from exc
        if response.status_code not in accepted_statuses:
            raise OutboundMediaError("outbound_media_rejected")
        content_type = response.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise OutboundMediaError("outbound_media_response_invalid")
        return response


def _open_source(value: Path | str) -> int:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise OutboundMediaError("outbound_media_source_invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise OutboundMediaError("outbound_media_source_unavailable") from exc


def _digest_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, MAX_OUTBOUND_MEDIA_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


__all__ = ["OutboundMediaError", "OutboundMediaUploader"]
