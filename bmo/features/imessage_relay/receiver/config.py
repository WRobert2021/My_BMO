"""Strict configuration loading for the standalone kiosk receiver."""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from bmo.repository_paths import relocated_repository_path


MAX_CONFIG_BYTES = 65_536
_SAFE_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
DEFAULT_PHOTO_DIRECTORY = Path("/home/pi-bmo/Pictures/bmo/messages")
DEFAULT_AUDIO_DIRECTORY = Path("/home/pi-bmo/Music/bmo/messages")
DEFAULT_VIDEO_DIRECTORY = Path("/home/pi-bmo/Videos/bmo/messages")


class ReceiverConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReceiverConfig:
    bind_host: str
    port: int
    state_path: Path
    tls_cert_path: Path | None
    tls_key_path: Path | None
    allow_insecure_loopback: bool
    key_id: str
    shared_secret: bytes = field(repr=False)
    max_clock_skew_seconds: int = 300
    max_request_bytes: int = 2 * 1024 * 1024
    request_timeout_seconds: int = 10
    photo_directory: Path = DEFAULT_PHOTO_DIRECTORY
    audio_directory: Path = DEFAULT_AUDIO_DIRECTORY
    video_directory: Path = DEFAULT_VIDEO_DIRECTORY

    def __post_init__(self) -> None:
        if not _is_host(self.bind_host):
            raise ReceiverConfigError("bind host is invalid")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 0 <= self.port <= 65_535:
            raise ReceiverConfigError("port is outside the supported range")
        if not isinstance(self.shared_secret, bytes) or len(self.shared_secret) < 32:
            raise ReceiverConfigError("shared secret must contain at least 32 bytes")
        if not isinstance(self.key_id, str) or not _SAFE_KEY_ID.fullmatch(self.key_id):
            raise ReceiverConfigError("key ID is invalid")
        if not isinstance(self.state_path, Path):
            raise ReceiverConfigError("state path must be a Path")
        if not isinstance(self.allow_insecure_loopback, bool):
            raise ReceiverConfigError("allow_insecure_loopback must be a boolean")
        if self.tls_cert_path is not None and not isinstance(self.tls_cert_path, Path):
            raise ReceiverConfigError("TLS certificate path must be a Path")
        if self.tls_key_path is not None and not isinstance(self.tls_key_path, Path):
            raise ReceiverConfigError("TLS key path must be a Path")
        for value, label in (
            (self.photo_directory, "photo directory"),
            (self.audio_directory, "audio directory"),
            (self.video_directory, "video directory"),
        ):
            if not isinstance(value, Path) or not value.is_absolute():
                raise ReceiverConfigError(f"{label} must be an absolute Path")
        for value, label, upper in (
            (self.max_clock_skew_seconds, "maximum clock skew", 3_600),
            (self.max_request_bytes, "maximum request bytes", 8 * 1024 * 1024),
            (self.request_timeout_seconds, "request timeout", 120),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
                raise ReceiverConfigError(f"{label} is outside the supported range")
        tls_complete = self.tls_cert_path is not None and self.tls_key_path is not None
        if (self.tls_cert_path is None) != (self.tls_key_path is None):
            raise ReceiverConfigError("TLS certificate and key must be configured together")
        if not tls_complete:
            if not self.allow_insecure_loopback or not _is_loopback(self.bind_host):
                raise ReceiverConfigError("TLS is required except for explicit loopback development")


def load_receiver_config(
    config_path: Path | str,
    *,
    environ: Mapping[str, str] | None = None,
    base_directory: Path | str | None = None,
) -> ReceiverConfig:
    path = Path(config_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ReceiverConfigError("receiver configuration must be a regular file")
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ReceiverConfigError("receiver configuration exceeds the size limit")
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReceiverConfigError("receiver configuration could not be read") from exc
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ReceiverConfigError("receiver configuration is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReceiverConfigError("receiver configuration must be an object")
    schema_version = _positive_int(value.get("schema_version"), "schema version")
    common_fields = {
        "schema_version",
        "bind_host",
        "port",
        "state_path",
        "tls_cert_path",
        "tls_key_path",
        "allow_insecure_loopback",
        "key_id",
        "max_clock_skew_seconds",
        "max_request_bytes",
        "request_timeout_seconds",
    }
    media_fields = {
        "photo_directory",
        "audio_directory",
        "video_directory",
    }
    if schema_version == 1:
        _configuration_keys(
            value,
            required=common_fields | {"shared_secret_env"},
            optional=media_fields,
        )
    elif schema_version == 2:
        _configuration_keys(
            value,
            required=common_fields | {"shared_secret_file"},
            optional=media_fields,
        )
    else:
        raise ReceiverConfigError("receiver configuration version is unsupported")
    base = (
        Path(base_directory).expanduser().resolve(strict=False)
        if base_directory is not None
        else Path.cwd().resolve()
    )
    bind_host = _string(value["bind_host"], "bind host")
    port = _nonnegative_int(value["port"], "port")
    state_path = _path(
        str(
            relocated_repository_path(
                _string(value["state_path"], "state path")
            )
        ),
        "state path",
        base,
        optional=False,
    )
    cert_path = _path(value["tls_cert_path"], "TLS certificate path", base, optional=True)
    key_path = _path(value["tls_key_path"], "TLS key path", base, optional=True)
    photo_directory = _path(
        value.get("photo_directory", str(DEFAULT_PHOTO_DIRECTORY)),
        "photo directory",
        base,
        optional=False,
    )
    audio_directory = _path(
        value.get("audio_directory", str(DEFAULT_AUDIO_DIRECTORY)),
        "audio directory",
        base,
        optional=False,
    )
    video_directory = _path(
        value.get("video_directory", str(DEFAULT_VIDEO_DIRECTORY)),
        "video directory",
        base,
        optional=False,
    )
    assert photo_directory is not None
    assert audio_directory is not None
    assert video_directory is not None
    allow_insecure = value["allow_insecure_loopback"]
    if not isinstance(allow_insecure, bool):
        raise ReceiverConfigError("allow_insecure_loopback must be a boolean")
    if schema_version == 1:
        secret_env = _string(
            value["shared_secret_env"],
            "shared secret environment variable",
        )
        environment = os.environ if environ is None else environ
        secret_text = environment.get(secret_env)
        if secret_text is None:
            raise ReceiverConfigError("shared secret environment variable is not set")
        try:
            shared_secret = secret_text.encode("utf-8")
        except UnicodeError as exc:
            raise ReceiverConfigError("shared secret could not be encoded") from exc
    else:
        secret_path = _path(
            value["shared_secret_file"],
            "shared secret file",
            base,
            optional=False,
        )
        assert secret_path is not None
        shared_secret = _read_private_secret(secret_path)
    return ReceiverConfig(
        bind_host=bind_host,
        port=port,
        state_path=state_path,
        tls_cert_path=cert_path,
        tls_key_path=key_path,
        allow_insecure_loopback=allow_insecure,
        key_id=_string(value["key_id"], "key ID"),
        shared_secret=shared_secret,
        max_clock_skew_seconds=_positive_int(value["max_clock_skew_seconds"], "maximum clock skew"),
        max_request_bytes=_positive_int(value["max_request_bytes"], "maximum request bytes"),
        request_timeout_seconds=_positive_int(value["request_timeout_seconds"], "request timeout"),
        photo_directory=photo_directory,
        audio_directory=audio_directory,
        video_directory=video_directory,
    )


def _is_host(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    if value == "localhost":
        return True
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _is_loopback(value: str) -> bool:
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _path(value: object, label: str, base: Path, *, optional: bool) -> Path | None:
    if value is None and optional:
        return None
    text = _string(value, label)
    path = Path(text).expanduser()
    return path.resolve(strict=False) if path.is_absolute() else (base / path).resolve(strict=False)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiverConfigError("receiver configuration has duplicate fields")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise ReceiverConfigError("receiver configuration contains a non-finite number")


def _configuration_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
) -> None:
    actual = set(value)
    if not required.issubset(actual) or not actual.issubset(required | optional):
        raise ReceiverConfigError("receiver configuration fields are invalid")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReceiverConfigError(f"{label} must be a non-empty string")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReceiverConfigError(f"{label} must be a nonnegative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ReceiverConfigError(f"{label} must be a positive integer")
    return result


def _read_private_secret(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReceiverConfigError("shared secret file is unavailable")
    try:
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ReceiverConfigError("shared secret file permissions are unsafe")
        raw = path.read_bytes()
    except ReceiverConfigError:
        raise
    except OSError as exc:
        raise ReceiverConfigError("shared secret file is unavailable") from exc
    secret = raw[:-1] if raw.endswith(b"\n") else raw
    if len(secret) < 32 or b"\n" in secret or b"\r" in secret or b"\x00" in secret:
        raise ReceiverConfigError("shared secret file is invalid")
    return secret
