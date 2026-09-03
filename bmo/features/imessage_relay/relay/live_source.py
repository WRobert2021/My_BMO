"""Stable disposable copies of an authorized live Messages source."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterator


TRIO_NAMES = ("sms.db", "sms.db-wal", "sms.db-shm")


class LiveSourceError(RuntimeError):
    """A bounded, content-free live-source failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class LiveMessagesSnapshot:
    database_path: Path
    messages_root: Path


@contextmanager
def disposable_messages_snapshot(
    messages_root: Path | str,
) -> Iterator[LiveMessagesSnapshot]:
    """Yield a stable local DB/WAL/SHM copy without opening live SQLite."""

    root = Path(messages_root).expanduser().resolve(strict=False)
    source_paths = _source_paths(root)
    before = _fingerprint(source_paths)
    with tempfile.TemporaryDirectory(prefix="imessage-live-source-") as temporary:
        destination = Path(temporary) / "SMS"
        database_path = _copy_trio(source_paths, destination)
        if before != _fingerprint(source_paths):
            raise LiveSourceError("source_changed_during_copy")
        try:
            yield LiveMessagesSnapshot(database_path, root)
        except BaseException:
            if before != _fingerprint(source_paths):
                raise LiveSourceError("source_changed_during_use") from None
            raise
        else:
            if before != _fingerprint(source_paths):
                raise LiveSourceError("source_changed_during_use")


def _source_paths(messages_root: Path) -> tuple[Path, ...]:
    paths = tuple(messages_root / name for name in TRIO_NAMES)
    if not all(path.is_file() for path in paths):
        raise LiveSourceError("messages_trio_unreadable")
    return paths


def _copy_trio(source_paths: tuple[Path, ...], destination: Path) -> Path:
    destination.mkdir(mode=0o700)
    for source, name in zip(source_paths, TRIO_NAMES, strict=True):
        shutil.copyfile(source, destination / name)
    return destination / "sms.db"


def _fingerprint(
    paths: tuple[Path, ...],
) -> tuple[tuple[int, int, int, int, int, int, str], ...]:
    observations = []
    for path in paths:
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise LiveSourceError("messages_trio_unreadable")
            observations.append((*_metadata(info), _sha256(path)))
        except LiveSourceError:
            raise
        except OSError as exc:
            raise LiveSourceError("messages_trio_unreadable") from exc
    return tuple(observations)


def _metadata(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise LiveSourceError("messages_trio_unreadable") from exc
    return digest.hexdigest()
