"""Publish completed receiver blobs into user-facing kiosk media folders."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping
from uuid import uuid4

from .receiver import ReceiverStateStore, ReceiverStoreError


_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
_PHOTO_SUFFIXES = {".gif", ".heic", ".jpeg", ".jpg", ".png", ".webp"}
_AUDIO_SUFFIXES = {".aac", ".aiff", ".caf", ".m4a", ".mp3", ".ogg", ".wav"}
_VIDEO_SUFFIXES = {".m4v", ".mov", ".mp4", ".webm"}


@dataclass(frozen=True, slots=True)
class PublishedAttachment:
    label: str
    media_category: str
    path: str | None
    available: bool


class ReceivedMediaLibrary:
    """Create stable links/copies for complete private receiver attachments."""

    def __init__(
        self,
        *,
        photo_directory: Path,
        audio_directory: Path,
        video_directory: Path,
    ) -> None:
        self._directories = {
            "photo": _absolute_directory(photo_directory, "photo"),
            "audio": _absolute_directory(audio_directory, "audio"),
            "video": _absolute_directory(video_directory, "video"),
        }

    def attachments_for_event(
        self,
        store: ReceiverStateStore,
        event: Mapping[str, Any],
    ) -> tuple[PublishedAttachment, ...]:
        event_id = event.get("event_id")
        raw_attachments = event.get("attachments")
        if not isinstance(event_id, str) or not isinstance(raw_attachments, list):
            return ()
        published: list[PublishedAttachment] = []
        for attachment in raw_attachments:
            if not isinstance(attachment, dict):
                continue
            published.extend(self._publish_attachment(store, event_id, attachment))
        return tuple(published)

    def _publish_attachment(
        self,
        store: ReceiverStateStore,
        event_id: str,
        attachment: Mapping[str, Any],
    ) -> tuple[PublishedAttachment, ...]:
        transfer_name = attachment.get("transfer_name")
        mime_type = attachment.get("mime_type")
        media_category = attachment.get("media_category")
        raw_components = attachment.get("components")
        blobs: list[tuple[str, str | None]] = []
        if isinstance(raw_components, list) and raw_components:
            for component in raw_components:
                if not isinstance(component, dict):
                    continue
                component_id = component.get("component_id")
                role = component.get("role")
                if isinstance(component_id, str) and isinstance(role, str):
                    blobs.append((component_id, role))
        else:
            attachment_id = attachment.get("attachment_id")
            if isinstance(attachment_id, str):
                blobs.append((attachment_id, None))

        results: list[PublishedAttachment] = []
        for blob_id, role in blobs:
            category = _destination_category(media_category, mime_type, transfer_name, role)
            label = _attachment_label(transfer_name, category, role)
            try:
                stored = store.get_attachment(event_id, blob_id)
            except ReceiverStoreError:
                stored = None
            if (
                stored is None
                or not stored.complete
                or stored.storage_path is None
                or not stored.content_sha256
            ):
                results.append(PublishedAttachment(label, category, None, False))
                continue
            try:
                destination = self._publish_file(
                    source=stored.storage_path,
                    digest=stored.content_sha256,
                    transfer_name=transfer_name,
                    category=category,
                    role=role,
                )
            except OSError:
                results.append(PublishedAttachment(label, category, None, False))
            else:
                results.append(
                    PublishedAttachment(label, category, str(destination), True)
                )
        return tuple(results)

    def _publish_file(
        self,
        *,
        source: Path,
        digest: str,
        transfer_name: object,
        category: str,
        role: str | None,
    ) -> Path:
        if source.is_symlink() or not source.is_file():
            raise OSError("received attachment source is unavailable")
        directory = self._directories[category]
        _ensure_directory(directory)
        filename = _published_filename(transfer_name, digest, category, role)
        destination = directory / filename
        if destination.exists() or destination.is_symlink():
            if (
                destination.is_symlink()
                or not destination.is_file()
                or _sha256_file(destination) != digest
            ):
                raise OSError("received attachment destination conflicts")
            return destination
        try:
            os.link(source, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _atomic_copy(source, destination, digest)
        return destination


def _absolute_directory(value: Path, label: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ValueError(f"{label} attachment directory must be absolute")
    return value.resolve(strict=False)


def _destination_category(
    media_category: object,
    mime_type: object,
    transfer_name: object,
    role: str | None,
) -> str:
    if role == "still":
        return "photo"
    if role == "motion":
        return "video"
    if media_category in {"photo", "video"}:
        return str(media_category)
    lowered_mime = str(mime_type or "").lower()
    if lowered_mime.startswith("audio/"):
        return "audio"
    extension = Path(str(transfer_name or "")).suffix.lower()
    if extension in _AUDIO_SUFFIXES:
        return "audio"
    if lowered_mime.startswith("video/") or extension in _VIDEO_SUFFIXES:
        return "video"
    return "photo"


def _attachment_label(transfer_name: object, category: str, role: str | None) -> str:
    raw_name = Path(str(transfer_name or "")).name
    name = raw_name if raw_name not in {"", ".", ".."} else category.title()
    if role in {"still", "motion"}:
        return f"{name} ({category})"
    return name


def _published_filename(
    transfer_name: object,
    digest: str,
    category: str,
    role: str | None,
) -> str:
    raw_name = Path(str(transfer_name or "")).name
    raw_suffix = Path(raw_name).suffix.lower()
    allowed_suffixes = {
        "photo": _PHOTO_SUFFIXES,
        "audio": _AUDIO_SUFFIXES,
        "video": _VIDEO_SUFFIXES,
    }[category]
    suffix = raw_suffix if raw_suffix in allowed_suffixes else {
        "photo": ".jpg",
        "audio": ".m4a",
        "video": ".mov",
    }[category]
    stem = Path(raw_name).stem if raw_name else category
    stem = _UNSAFE_FILENAME.sub("_", stem).strip(" ._")[:80] or category
    role_suffix = f"-{role}" if role else ""
    return f"{stem}{role_suffix}-{digest[:12]}{suffix}"


def _ensure_directory(directory: Path) -> None:
    if directory.is_symlink():
        raise OSError("received attachment directory cannot be a symbolic link")
    created = not directory.exists()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise OSError("received attachment directory is unavailable")
    if created:
        directory.chmod(0o700)


def _atomic_copy(source: Path, destination: Path, digest: str) -> None:
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as target, source.open("rb") as stream:
            descriptor = None
            shutil.copyfileobj(stream, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if _sha256_file(temporary) != digest:
            raise OSError("received attachment copy failed verification")
        os.replace(temporary, destination)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["PublishedAttachment", "ReceivedMediaLibrary"]
