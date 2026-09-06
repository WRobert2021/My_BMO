"""Strict private configuration and lifecycle for the read-only phone mount."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


MAX_CONFIG_BYTES = 65_536
_SAFE_HOSTNAME = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
_SAFE_USERNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")


class SourceConfigError(ValueError):
    """Private incoming-source configuration is invalid."""


class SourceMountError(RuntimeError):
    """The configured source could not be mounted safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class IncomingSourceConfig:
    host: str
    username: str
    port: int
    remote_path: str
    mount_path: Path
    known_hosts_path: Path
    password_file: Path
    poll_interval_seconds: float
    scan_limit: int
    delivery_limit: int


def load_source_config(config_path: Path | str) -> IncomingSourceConfig:
    """Load private SSHFS source settings without retaining the password."""

    path = Path(config_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise SourceConfigError("source configuration must be a regular file")
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise SourceConfigError("source configuration exceeds the size limit")
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SourceConfigError("source configuration could not be read") from exc
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise SourceConfigError("source configuration is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SourceConfigError("source configuration must be an object")
    _exact_keys(
        value,
        {
            "schema_version",
            "host",
            "username",
            "port",
            "remote_path",
            "mount_path",
            "known_hosts_path",
            "password_file",
            "poll_interval_seconds",
            "scan_limit",
            "delivery_limit",
        },
    )
    if _positive_int(value["schema_version"], "schema version") != 1:
        raise SourceConfigError("source configuration version is unsupported")

    host = _string(value["host"], "host")
    if not _valid_host(host):
        raise SourceConfigError("source host is invalid")
    username = _string(value["username"], "username")
    if _SAFE_USERNAME.fullmatch(username) is None:
        raise SourceConfigError("source username is invalid")
    remote_path = _string(value["remote_path"], "remote path")
    if remote_path != "/SMS":
        raise SourceConfigError("source remote path must be /SMS")

    mount_path = _absolute_path(value["mount_path"], "mount path")
    known_hosts_path = _absolute_path(value["known_hosts_path"], "known-hosts path")
    password_file = _absolute_path(value["password_file"], "password file")
    poll_interval = value["poll_interval_seconds"]
    if (
        isinstance(poll_interval, bool)
        or not isinstance(poll_interval, (int, float))
        or not 1 <= float(poll_interval) <= 300
    ):
        raise SourceConfigError("poll interval must be between 1 and 300 seconds")
    port = _positive_int(value["port"], "port")
    if port > 65_535:
        raise SourceConfigError("source port is outside the supported range")
    scan_limit = _positive_int(value["scan_limit"], "scan limit")
    delivery_limit = _positive_int(value["delivery_limit"], "delivery limit")
    if scan_limit > 100:
        raise SourceConfigError("scan limit exceeds 100")
    if delivery_limit > 500:
        raise SourceConfigError("delivery limit exceeds 500")
    return IncomingSourceConfig(
        host=host,
        username=username,
        port=port,
        remote_path=remote_path,
        mount_path=mount_path,
        known_hosts_path=known_hosts_path,
        password_file=password_file,
        poll_interval_seconds=float(poll_interval),
        scan_limit=scan_limit,
        delivery_limit=delivery_limit,
    )


class ReadOnlySSHFS:
    """Mount and unmount exactly one strictly verified read-only SFTP export."""

    def __init__(
        self,
        config: IncomingSourceConfig,
        *,
        run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        self.config = config
        self._run = run
        self._owned_mount = False
        self._created_directory = False

    @property
    def mounted(self) -> bool:
        return self._mount_verified()

    def ensure_mounted(self) -> Path:
        if self._mount_verified():
            return self.config.mount_path
        if self._find_mount() is not None:
            raise SourceMountError("source_mount_unverified")
        self._validate_support_files()
        mount_path = self.config.mount_path
        if mount_path.is_symlink():
            raise SourceMountError("source_mount_path_invalid")
        if not mount_path.exists():
            try:
                mount_path.mkdir(parents=True, mode=0o700)
                os.chmod(mount_path, 0o700)
            except OSError as exc:
                raise SourceMountError("source_mount_path_unavailable") from exc
            self._created_directory = True
        if not mount_path.is_dir():
            raise SourceMountError("source_mount_path_invalid")
        try:
            if any(mount_path.iterdir()):
                raise SourceMountError("source_mount_path_not_empty")
        except OSError as exc:
            raise SourceMountError("source_mount_path_unavailable") from exc

        password = _read_password(self.config.password_file)
        command = (
            "sshfs",
            "-p",
            str(self.config.port),
            "-o",
            "ro,password_stdin,BatchMode=no,StrictHostKeyChecking=yes,"
            "UpdateHostKeys=no,ConnectTimeout=5,ServerAliveInterval=15,"
            "ServerAliveCountMax=2,ClearAllForwardings=yes,"
            f"UserKnownHostsFile={self.config.known_hosts_path}",
            f"{self.config.username}@{self.config.host}:{self.config.remote_path}",
            str(mount_path),
        )
        try:
            completed = self._run(
                command,
                input=password + b"\n",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceMountError("source_mount_failed") from exc
        finally:
            del password
        if completed.returncode != 0:
            raise SourceMountError("source_mount_failed")
        self._owned_mount = True
        if not self._mount_verified():
            self.close()
            raise SourceMountError("source_mount_unverified")
        return mount_path

    def close(self) -> None:
        if self._owned_mount and self._mount_verified():
            try:
                self._run(
                    ("fusermount3", "-u", str(self.config.mount_path)),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        self._owned_mount = False
        if self._created_directory:
            try:
                self.config.mount_path.rmdir()
            except OSError:
                pass
            self._created_directory = False

    def _validate_support_files(self) -> None:
        known_hosts = self.config.known_hosts_path
        if known_hosts.is_symlink() or not known_hosts.is_file():
            raise SourceMountError("known_hosts_unavailable")
        _read_password(self.config.password_file)

    def _mount_verified(self) -> bool:
        info = self._find_mount()
        if info is None:
            return False
        source, filesystem, options = info
        expected_source = (
            f"{self.config.username}@{self.config.host}:{self.config.remote_path}"
        )
        return (
            source == expected_source
            and filesystem.startswith("fuse")
            and "ro" in options.split(",")
        )

    def _find_mount(self) -> tuple[str, str, str] | None:
        try:
            completed = self._run(
                (
                    "findmnt",
                    "-rn",
                    "-M",
                    str(self.config.mount_path),
                    "-o",
                    "SOURCE,FSTYPE,OPTIONS",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        try:
            fields = completed.stdout.decode("utf-8").strip().split(None, 2)
        except UnicodeError:
            return None
        if len(fields) != 3:
            return None
        return fields[0], fields[1], fields[2]


def _read_password(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SourceMountError("source_password_unavailable")
    try:
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SourceMountError("source_password_permissions_invalid")
        raw = path.read_bytes()
    except SourceMountError:
        raise
    except OSError as exc:
        raise SourceMountError("source_password_unavailable") from exc
    password = raw[:-1] if raw.endswith(b"\n") else raw
    if not password or b"\n" in password or b"\r" in password or b"\x00" in password:
        raise SourceMountError("source_password_invalid")
    return password


def _valid_host(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return _SAFE_HOSTNAME.fullmatch(value) is not None
    return True


def _absolute_path(value: object, label: str) -> Path:
    text = _string(value, label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise SourceConfigError(f"{label} must be absolute")
    return path.resolve(strict=False)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceConfigError("source configuration has duplicate fields")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    del value
    raise SourceConfigError("source configuration contains a non-finite number")


def _exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise SourceConfigError("source configuration fields are invalid")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SourceConfigError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SourceConfigError(f"{label} must be a positive integer")
    return value


__all__ = [
    "IncomingSourceConfig",
    "ReadOnlySSHFS",
    "SourceConfigError",
    "SourceMountError",
    "load_source_config",
]
