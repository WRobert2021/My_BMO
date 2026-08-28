"""HMAC request authentication for the private-LAN receiver protocol."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
import time
from typing import Mapping


AUTH_SCHEME = "IMESSAGE-RELAY-HMAC-V1"
KEY_ID_HEADER = "X-Relay-Key-Id"
TIMESTAMP_HEADER = "X-Relay-Timestamp"
NONCE_HEADER = "X-Relay-Nonce"
SIGNATURE_HEADER = "X-Relay-Signature"

_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_HEX_SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")


class AuthenticationError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    key_id: str
    timestamp: int
    nonce: str


class RequestAuthenticator:
    def __init__(
        self,
        *,
        key_id: str,
        shared_secret: bytes,
        max_clock_skew_seconds: int = 300,
        clock=time.time,
    ) -> None:
        if not _SAFE_TOKEN.fullmatch(key_id):
            raise ValueError("key ID is invalid")
        if not isinstance(shared_secret, bytes) or len(shared_secret) < 32:
            raise ValueError("shared secret must contain at least 32 bytes")
        if (
            isinstance(max_clock_skew_seconds, bool)
            or not isinstance(max_clock_skew_seconds, int)
            or not 1 <= max_clock_skew_seconds <= 3_600
        ):
            raise ValueError("maximum clock skew must be between 1 and 3600 seconds")
        self.key_id = key_id
        self._secret = shared_secret
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self._clock = clock

    def verify(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> AuthenticatedRequest:
        key_id = headers.get(KEY_ID_HEADER)
        timestamp_raw = headers.get(TIMESTAMP_HEADER)
        nonce = headers.get(NONCE_HEADER)
        signature = headers.get(SIGNATURE_HEADER)
        if not all(isinstance(item, str) for item in (key_id, timestamp_raw, nonce, signature)):
            raise AuthenticationError("authentication_required", "authentication is required")
        if not hmac.compare_digest(key_id, self.key_id):
            raise AuthenticationError("unknown_client", "client is not recognized")
        if not _SAFE_TOKEN.fullmatch(nonce):
            raise AuthenticationError("invalid_authentication", "nonce is invalid")
        try:
            timestamp = int(timestamp_raw)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("invalid_authentication", "timestamp is invalid") from exc
        if str(timestamp) != timestamp_raw or abs(int(self._clock()) - timestamp) > self.max_clock_skew_seconds:
            raise AuthenticationError("stale_request", "request timestamp is outside the accepted window")
        if not _HEX_SIGNATURE.fullmatch(signature):
            raise AuthenticationError("invalid_authentication", "signature is invalid")
        expected = _signature(self._secret, method, path, timestamp, nonce, body)
        if not hmac.compare_digest(signature, expected):
            raise AuthenticationError("invalid_signature", "request signature does not match")
        return AuthenticatedRequest(key_id=key_id, timestamp=timestamp, nonce=nonce)


def sign_request(
    shared_secret: bytes,
    *,
    key_id: str,
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    body: bytes = b"",
) -> dict[str, str]:
    """Build authentication headers; intended for local clients and tests."""

    if not isinstance(shared_secret, bytes) or len(shared_secret) < 32:
        raise ValueError("shared secret must contain at least 32 bytes")
    if not _SAFE_TOKEN.fullmatch(key_id) or not _SAFE_TOKEN.fullmatch(nonce):
        raise ValueError("key ID and nonce must be safe tokens")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("timestamp must be an integer")
    return {
        KEY_ID_HEADER: key_id,
        TIMESTAMP_HEADER: str(timestamp),
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: _signature(shared_secret, method, path, timestamp, nonce, body),
    }


def _signature(
    secret: bytes,
    method: str,
    path: str,
    timestamp: int,
    nonce: str,
    body: bytes,
) -> str:
    body_digest = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (AUTH_SCHEME, method.upper(), path, str(timestamp), nonce, body_digest)
    ).encode("utf-8")
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()
