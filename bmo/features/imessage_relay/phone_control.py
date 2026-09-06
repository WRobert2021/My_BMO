"""Authenticated kiosk-to-phone Stage 12 control client."""

from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import queue
import threading
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from bmo.jsonio import loads_json

from .receiver.auth import sign_request


CONTROL_PROTOCOL_VERSION = 1
CONTROL_HEALTH_PATH = "/v1/control/health"
CONTROL_RESUME_PATH = "/v1/control/resume"
CONTROL_RECONCILIATION_PATH = "/v1/control/reconciliation"
MAX_CONTROL_CONFIG_BYTES = 65_536
MAX_CONTROL_RESPONSE_BYTES = 64 * 1024

_CONTROL_PATHS = {
    CONTROL_HEALTH_PATH,
    CONTROL_RESUME_PATH,
    CONTROL_RECONCILIATION_PATH,
}
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SAFE_ERROR = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class PhoneControlConfigError(ValueError):
    """Private phone-control configuration is invalid or unavailable."""


class PhoneControlError(RuntimeError):
    """A control request failed without exposing private response content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PhoneControlConfig:
    endpoint: str
    key_id: str
    shared_secret: bytes = field(repr=False)
    tls_ca_path: Path | None = None
    allow_insecure_loopback: bool = False
    request_timeout_seconds: int = 5
    network_probe_seconds: int = 60
    reconciliation_interval_hours: int = 168

    def __post_init__(self) -> None:
        _validate_origin(self.endpoint, self.allow_insecure_loopback)
        if not _SAFE_TOKEN.fullmatch(self.key_id):
            raise PhoneControlConfigError("key ID is invalid")
        if not isinstance(self.shared_secret, bytes) or len(self.shared_secret) < 32:
            raise PhoneControlConfigError(
                "shared secret must contain at least 32 bytes"
            )
        if self.tls_ca_path is not None and not isinstance(self.tls_ca_path, Path):
            raise PhoneControlConfigError("TLS CA path must be a Path")
        if not isinstance(self.allow_insecure_loopback, bool):
            raise PhoneControlConfigError(
                "allow_insecure_loopback must be a boolean"
            )
        for value, label, lower, upper in (
            (self.request_timeout_seconds, "request timeout", 1, 120),
            (self.network_probe_seconds, "network probe", 15, 3_600),
            (
                self.reconciliation_interval_hours,
                "reconciliation interval",
                24,
                24 * 14,
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not lower <= value <= upper
            ):
                raise PhoneControlConfigError(
                    f"{label} is outside the supported range"
                )


@dataclass(frozen=True, slots=True)
class ControlTransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class PhoneControlAck:
    status: str
    backlog_count: int | None = None
    reconciliation_id: str | None = None


@dataclass(frozen=True, slots=True)
class PhoneControlRuntimeStatus:
    phone_state: str
    error_code: str | None
    backlog_count: int | None
    reconciliation_state: str
    reconciliation_error_code: str | None
    last_reconciliation: Mapping[str, int | str] | None


class ControlTransport(Protocol):
    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str,
    ) -> ControlTransportResponse:
        """Send one authenticated control request."""

    def close(self) -> None:
        """Release transport resources; repeated calls are safe."""


class HTTPPhoneControlTransport:
    """Bounded HTTP(S) transport for the phone control listener."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 5,
        allow_insecure_loopback: bool = False,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = _validate_origin(endpoint, allow_insecure_loopback)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 120
        ):
            raise ValueError("control timeout must be between 0 and 120 seconds")
        if parsed.scheme == "http" and ssl_context is not None:
            raise ValueError("an SSL context cannot be used with plain HTTP")
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._timeout_seconds = float(timeout_seconds)
        self._ssl_context = ssl_context
        self._closed = False

    def send(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        path: str,
    ) -> ControlTransportResponse:
        if self._closed:
            raise PhoneControlError("phone_control_closed")
        if path not in _CONTROL_PATHS:
            raise ValueError("phone control path is unsupported")
        if not isinstance(body, bytes) or len(body) > MAX_CONTROL_RESPONSE_BYTES:
            raise ValueError("phone control request is invalid")
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
            response_body = response.read(MAX_CONTROL_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_CONTROL_RESPONSE_BYTES:
                raise PhoneControlError("phone_control_response_too_large")
            return ControlTransportResponse(
                status_code=response.status,
                headers={name.lower(): value for name, value in response.getheaders()},
                body=response_body,
            )
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True


class PhoneControlClient:
    """Strict request/ACK client for phone health, resume, and reconciliation."""

    def __init__(
        self,
        config: PhoneControlConfig,
        *,
        transport: ControlTransport | None = None,
        clock: Callable[[], float] = time.time,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, PhoneControlConfig):
            raise TypeError("config must be PhoneControlConfig")
        ssl_context: ssl.SSLContext | None = None
        if config.endpoint.startswith("https://"):
            ssl_context = ssl.create_default_context(
                cafile=str(config.tls_ca_path) if config.tls_ca_path else None
            )
        self.config = config
        self._transport = transport or HTTPPhoneControlTransport(
            config.endpoint,
            timeout_seconds=config.request_timeout_seconds,
            allow_insecure_loopback=config.allow_insecure_loopback,
            ssl_context=ssl_context,
        )
        self._clock = clock
        self._identifier_factory = identifier_factory or (lambda: uuid4().hex)
        self._closed = False

    def health(self) -> PhoneControlAck:
        return self._request(
            CONTROL_HEALTH_PATH,
            action="health",
            expected_http_status=200,
            expected_status="available",
        )

    def resume(self) -> PhoneControlAck:
        return self._request(
            CONTROL_RESUME_PATH,
            action="resume",
            expected_http_status=200,
            expected_status="resumed",
        )

    def reconcile_recent(self, days: int) -> PhoneControlAck:
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ValueError("recent reconciliation days must be from 1 through 31")
        return self._request(
            CONTROL_RECONCILIATION_PATH,
            action="reconcile",
            window={"kind": "recent", "days": days},
            expected_http_status=202,
            expected_status="scheduled",
        )

    def reconcile_month(self, year: int, month: int) -> PhoneControlAck:
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not 2001 <= year <= 9999
            or isinstance(month, bool)
            or not isinstance(month, int)
            or not 1 <= month <= 12
        ):
            raise ValueError("calendar reconciliation month is invalid")
        return self._request(
            CONTROL_RECONCILIATION_PATH,
            action="reconcile",
            window={"kind": "month", "year": year, "month": month},
            expected_http_status=202,
            expected_status="scheduled",
        )

    def _request(
        self,
        path: str,
        *,
        action: str,
        expected_http_status: int,
        expected_status: str,
        window: Mapping[str, object] | None = None,
    ) -> PhoneControlAck:
        if self._closed:
            raise PhoneControlError("phone_control_closed")
        request_id = _identifier(self._identifier_factory(), "request ID")
        nonce = _identifier(self._identifier_factory(), "nonce")
        body = encode_control_request(
            request_id=request_id,
            action=action,
            window=window,
        )
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
        try:
            response = self._transport.send(body=body, headers=headers, path=path)
        except PhoneControlError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise PhoneControlError("phone_unreachable") from exc
        return decode_control_response(
            response,
            expected_request_id=request_id,
            expected_http_status=expected_http_status,
            expected_status=expected_status,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()


class PhoneControlCoordinator:
    """Own one control worker, connectivity probes, and bounded scheduling."""

    def __init__(
        self,
        config: PhoneControlConfig,
        *,
        recent_days: int,
        client: PhoneControlClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(config, PhoneControlConfig):
            raise TypeError("config must be PhoneControlConfig")
        if (
            isinstance(recent_days, bool)
            or not isinstance(recent_days, int)
            or not 1 <= recent_days <= 31
        ):
            raise ValueError("recent reconciliation days must be from 1 through 31")
        self.config = config
        self._recent_days = recent_days
        self._client = client or PhoneControlClient(config)
        self._monotonic = monotonic
        self._commands: queue.Queue[
            tuple[str, tuple[int, ...], Callable[[], None] | None]
        ] = queue.Queue()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._phone_state = "starting"
        self._error_code: str | None = None
        self._backlog_count: int | None = None
        self._reconciliation_state = "idle"
        self._reconciliation_error_code: str | None = None
        self._last_reconciliation: Mapping[str, int | str] | None = None

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise PhoneControlError("phone_control_closed")
            if self._thread is not None:
                return
            thread = threading.Thread(
                target=self._run,
                name="imessage-relay-phone-control",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def status(self) -> PhoneControlRuntimeStatus:
        with self._lock:
            return PhoneControlRuntimeStatus(
                phone_state=self._phone_state,
                error_code=self._error_code,
                backlog_count=self._backlog_count,
                reconciliation_state=self._reconciliation_state,
                reconciliation_error_code=self._reconciliation_error_code,
                last_reconciliation=self._last_reconciliation,
            )

    def reconcile_recent(self, on_complete: Callable[[], None] | None = None) -> bool:
        return self._queue_reconciliation("recent", (), on_complete)

    def reconcile_month(
        self,
        year: int,
        month: int,
        on_complete: Callable[[], None] | None = None,
    ) -> bool:
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not 2001 <= year <= 9999
            or isinstance(month, bool)
            or not isinstance(month, int)
            or not 1 <= month <= 12
        ):
            raise ValueError("calendar reconciliation month is invalid")
        return self._queue_reconciliation("month", (year, month), on_complete)

    def _queue_reconciliation(
        self,
        kind: str,
        values: tuple[int, ...],
        on_complete: Callable[[], None] | None,
    ) -> bool:
        if on_complete is not None and not callable(on_complete):
            raise TypeError("reconciliation completion must be callable")
        with self._lock:
            if (
                self._closed
                or self._phone_state != "available"
                or self._reconciliation_state == "running"
            ):
                return False
            self._reconciliation_state = "running"
            self._reconciliation_error_code = None
        self._commands.put((kind, values, on_complete))
        return True

    def _run(self) -> None:
        self._resume()
        next_probe = self._monotonic() + self.config.network_probe_seconds
        next_automatic = (
            self._monotonic() + self.config.reconciliation_interval_hours * 3_600
        )
        while not self._stop.is_set():
            now = self._monotonic()
            timeout = max(0.0, min(next_probe, next_automatic) - now)
            try:
                kind, values, callback = self._commands.get(timeout=timeout)
            except queue.Empty:
                now = self._monotonic()
                if now >= next_probe:
                    self._probe()
                    next_probe = now + self.config.network_probe_seconds
                if now >= next_automatic:
                    self._run_automatic_reconciliation()
                    next_automatic = (
                        now + self.config.reconciliation_interval_hours * 3_600
                    )
                continue
            if kind == "stop":
                break
            self._run_reconciliation(kind, values, callback)

    def _resume(self) -> None:
        try:
            ack = self._client.resume()
        except PhoneControlError as exc:
            with self._lock:
                if not self._closed:
                    self._phone_state = "unavailable"
                    self._error_code = _runtime_error_code(exc.code)
                    self._backlog_count = None
            return
        with self._lock:
            if not self._closed:
                self._phone_state = "available"
                self._error_code = None
                self._backlog_count = ack.backlog_count

    def _probe(self) -> None:
        with self._lock:
            was_available = self._phone_state == "available"
        try:
            self._client.health()
        except PhoneControlError as exc:
            with self._lock:
                if not self._closed:
                    self._phone_state = "unavailable"
                    self._error_code = _runtime_error_code(exc.code)
            return
        if not was_available:
            self._resume()

    def _run_automatic_reconciliation(self) -> None:
        with self._lock:
            if self._phone_state != "available" or self._closed:
                return
            self._reconciliation_state = "running"
            self._reconciliation_error_code = None
        self._run_reconciliation("recent", (), None)

    def _run_reconciliation(
        self,
        kind: str,
        values: tuple[int, ...],
        callback: Callable[[], None] | None,
    ) -> None:
        try:
            if kind == "recent":
                ack = self._client.reconcile_recent(self._recent_days)
                report: Mapping[str, int | str] = {
                    "window": "recent",
                    "days": self._recent_days,
                    "scheduled": 1,
                    "reconciliation_id": ack.reconciliation_id or "unknown",
                }
            else:
                year, month = values
                ack = self._client.reconcile_month(year, month)
                report = {
                    "window": "month",
                    "year": year,
                    "month": month,
                    "scheduled": 1,
                    "reconciliation_id": ack.reconciliation_id or "unknown",
                }
        except PhoneControlError as exc:
            with self._lock:
                if not self._closed:
                    self._reconciliation_state = "failed"
                    self._reconciliation_error_code = _runtime_error_code(exc.code)
        else:
            with self._lock:
                if not self._closed:
                    self._reconciliation_state = "complete"
                    self._reconciliation_error_code = None
                    self._last_reconciliation = report
        finally:
            if callback is not None:
                try:
                    callback()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._phone_state = "closed"
            thread = self._thread
        self._stop.set()
        self._commands.put(("stop", (), None))
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._client.close()


def _runtime_error_code(code: str) -> str:
    return code if _SAFE_ERROR.fullmatch(code) else "phone_control_failed"


def load_phone_control_config(
    config_path: Path | str,
    *,
    base_directory: Path | str | None = None,
) -> PhoneControlConfig:
    """Load strict private kiosk-to-phone configuration without logging secrets."""

    path = Path(config_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise PhoneControlConfigError(
            "phone control configuration must be a regular file"
        )
    try:
        if path.stat().st_size > MAX_CONTROL_CONFIG_BYTES:
            raise PhoneControlConfigError(
                "phone control configuration exceeds the size limit"
            )
        value = loads_json(path.read_bytes())
    except PhoneControlConfigError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PhoneControlConfigError(
            "phone control configuration is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise PhoneControlConfigError("phone control configuration must be an object")
    expected = {
        "schema_version",
        "endpoint",
        "key_id",
        "shared_secret_file",
        "tls_ca_path",
        "allow_insecure_loopback",
        "request_timeout_seconds",
        "network_probe_seconds",
        "reconciliation_interval_hours",
    }
    if set(value) != expected or value.get("schema_version") != 1:
        raise PhoneControlConfigError("phone control configuration fields are invalid")
    base = (
        Path(base_directory).expanduser().resolve(strict=False)
        if base_directory is not None
        else Path.cwd().resolve()
    )
    secret_path = _configured_path(
        value["shared_secret_file"], base, "shared secret file", optional=False
    )
    assert secret_path is not None
    tls_ca_path = _configured_path(
        value["tls_ca_path"], base, "TLS CA path", optional=True
    )
    return PhoneControlConfig(
        endpoint=_required_string(value["endpoint"], "endpoint"),
        key_id=_required_string(value["key_id"], "key ID"),
        shared_secret=_read_private_secret(secret_path),
        tls_ca_path=tls_ca_path,
        allow_insecure_loopback=_required_bool(
            value["allow_insecure_loopback"], "allow_insecure_loopback"
        ),
        request_timeout_seconds=_required_int(
            value["request_timeout_seconds"], "request timeout"
        ),
        network_probe_seconds=_required_int(
            value["network_probe_seconds"], "network probe"
        ),
        reconciliation_interval_hours=_required_int(
            value["reconciliation_interval_hours"], "reconciliation interval"
        ),
    )


def encode_control_request(
    *,
    request_id: str,
    action: str,
    window: Mapping[str, object] | None = None,
) -> bytes:
    """Encode the canonical phone-control request shared by both runtimes."""

    request_id = _identifier(request_id, "request ID")
    if action in {"health", "resume"}:
        if window is not None:
            raise ValueError("health and resume requests cannot contain a window")
        value: dict[str, object] = {
            "protocol_version": CONTROL_PROTOCOL_VERSION,
            "request_id": request_id,
            "action": action,
        }
    elif action == "reconcile":
        value = {
            "protocol_version": CONTROL_PROTOCOL_VERSION,
            "request_id": request_id,
            "action": action,
            "window": _reconciliation_window(window),
        }
    else:
        raise ValueError("phone control action is unsupported")
    return _canonical_json(value)


def decode_control_response(
    response: ControlTransportResponse,
    *,
    expected_request_id: str,
    expected_http_status: int,
    expected_status: str,
) -> PhoneControlAck:
    """Validate an exact phone-control ACK and return only bounded metadata."""

    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise PhoneControlError("phone_control_response_invalid")
    try:
        value = loads_json(response.body)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PhoneControlError("phone_control_response_invalid") from exc
    if not isinstance(value, dict):
        raise PhoneControlError("phone_control_response_invalid")
    if response.status_code != expected_http_status:
        code = _nack_code(value)
        raise PhoneControlError(code or "phone_control_rejected")
    common = {"protocol_version", "request_id", "result", "status"}
    if expected_status == "resumed":
        expected = common | {"backlog_count"}
    elif expected_status == "scheduled":
        expected = common | {"reconciliation_id"}
    else:
        expected = common
    if set(value) != expected:
        raise PhoneControlError("phone_control_response_invalid")
    if (
        value.get("protocol_version") != CONTROL_PROTOCOL_VERSION
        or value.get("request_id") != expected_request_id
        or value.get("result") != "ack"
        or value.get("status") != expected_status
    ):
        raise PhoneControlError("phone_control_response_invalid")
    backlog_count = value.get("backlog_count")
    if expected_status == "resumed" and (
        isinstance(backlog_count, bool)
        or not isinstance(backlog_count, int)
        or backlog_count < 0
    ):
        raise PhoneControlError("phone_control_response_invalid")
    reconciliation_id = value.get("reconciliation_id")
    if expected_status == "scheduled":
        try:
            reconciliation_id = _identifier(reconciliation_id, "reconciliation ID")
        except ValueError as exc:
            raise PhoneControlError("phone_control_response_invalid") from exc
    return PhoneControlAck(
        status=expected_status,
        backlog_count=backlog_count if isinstance(backlog_count, int) else None,
        reconciliation_id=(
            reconciliation_id if isinstance(reconciliation_id, str) else None
        ),
    )


def _nack_code(value: Mapping[str, Any]) -> str | None:
    error = value.get("error")
    if not isinstance(error, dict) or set(error) != {"code"}:
        return None
    code = error.get("code")
    return code if isinstance(code, str) and _SAFE_ERROR.fullmatch(code) else None


def _reconciliation_window(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("reconciliation window must be an object")
    kind = value.get("kind")
    if kind == "recent" and set(value) == {"kind", "days"}:
        days = value.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ValueError("recent reconciliation days are invalid")
        return {"kind": "recent", "days": days}
    if kind == "month" and set(value) == {"kind", "year", "month"}:
        year = value.get("year")
        month = value.get("month")
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not 2001 <= year <= 9999
            or isinstance(month, bool)
            or not isinstance(month, int)
            or not 1 <= month <= 12
        ):
            raise ValueError("calendar reconciliation month is invalid")
        return {"kind": "month", "year": year, "month": month}
    raise ValueError("reconciliation window is invalid")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def _validate_origin(endpoint: str, allow_insecure_loopback: bool):
    if not isinstance(endpoint, str):
        raise PhoneControlConfigError("phone endpoint is invalid")
    parsed = urlsplit(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise PhoneControlConfigError("phone endpoint port is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise PhoneControlConfigError("phone endpoint must be an HTTP(S) origin")
    if parsed.scheme == "http" and (
        not allow_insecure_loopback or not _is_loopback(parsed.hostname)
    ):
        raise PhoneControlConfigError(
            "TLS is required except for explicit loopback development"
        )
    return parsed


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _configured_path(
    value: object,
    base: Path,
    label: str,
    *,
    optional: bool,
) -> Path | None:
    if value is None and optional:
        return None
    text = _required_string(value, label)
    path = Path(text).expanduser()
    return path.resolve(strict=False) if path.is_absolute() else (base / path).resolve(strict=False)


def _read_private_secret(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PhoneControlConfigError("shared secret file is unavailable")
    try:
        metadata = path.stat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise PhoneControlConfigError("shared secret file permissions are unsafe")
        raw = path.read_bytes()
    except PhoneControlConfigError:
        raise
    except OSError as exc:
        raise PhoneControlConfigError("shared secret file is unavailable") from exc
    secret = raw[:-1] if raw.endswith(b"\n") else raw
    if len(secret) < 32 or any(item in secret for item in (b"\n", b"\r", b"\x00")):
        raise PhoneControlConfigError("shared secret file is invalid")
    return secret


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PhoneControlConfigError(f"{label} must be a non-empty string")
    return value


def _required_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise PhoneControlConfigError(f"{label} must be a boolean")
    return value


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PhoneControlConfigError(f"{label} must be an integer")
    return value


__all__ = [
    "CONTROL_HEALTH_PATH",
    "CONTROL_PROTOCOL_VERSION",
    "CONTROL_RECONCILIATION_PATH",
    "CONTROL_RESUME_PATH",
    "ControlTransportResponse",
    "HTTPPhoneControlTransport",
    "PhoneControlAck",
    "PhoneControlClient",
    "PhoneControlCoordinator",
    "PhoneControlConfig",
    "PhoneControlConfigError",
    "PhoneControlError",
    "PhoneControlRuntimeStatus",
    "decode_control_response",
    "encode_control_request",
    "load_phone_control_config",
]
