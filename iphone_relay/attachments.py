"""Contained attachment resolution and media classification."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from iphone_relay.contracts import (
    Attachment,
    AttachmentAvailability,
    AttachmentComponent,
    AttachmentComponentRole,
    MediaCategory,
)
from iphone_relay.errors import SourceRecordError, UnsafeAttachmentPathError


APPLE_ATTACHMENT_PREFIX = "~/Library/SMS/Attachments/"


def normalize_attachment(
    row: object,
    *,
    parent_message_id: str,
    messages_root: Path,
) -> Attachment:
    """Normalize one sqlite row without reading attachment contents."""

    attachment_id = _required_string(row["guid"], "attachment guid")
    filename = row["filename"]
    transfer_name = _safe_transfer_name(row["transfer_name"])
    uti = _optional_string(row["uti"], "attachment uti")
    mime_type = _optional_string(row["mime_type"], "attachment mime type")
    declared_bytes = row["total_bytes"]
    if (
        isinstance(declared_bytes, bool)
        or not isinstance(declared_bytes, int)
        or declared_bytes < 0
    ):
        raise SourceRecordError("attachment total_bytes must be non-negative")
    try:
        source = resolve_attachment_path(filename, messages_root)
    except UnsafeAttachmentPathError:
        return Attachment(
            attachment_id=attachment_id,
            parent_message_id=parent_message_id,
            transfer_name=transfer_name,
            uti=uti,
            mime_type=mime_type,
            media_category=_media_category(uti, mime_type, None),
            source_path=None,
            declared_bytes=declared_bytes,
            actual_bytes=None,
            availability=AttachmentAvailability.UNSAFE,
        )

    if not source.is_file():
        return Attachment(
            attachment_id=attachment_id,
            parent_message_id=parent_message_id,
            transfer_name=transfer_name,
            uti=uti,
            mime_type=mime_type,
            media_category=_media_category(uti, mime_type, source),
            source_path=str(source),
            declared_bytes=declared_bytes,
            actual_bytes=None,
            availability=AttachmentAvailability.MISSING,
        )

    motion = _live_photo_motion_path(source)
    if motion is not None:
        components = (
            AttachmentComponent(
                component_id=f"{attachment_id}:still",
                role=AttachmentComponentRole.STILL,
                source_path=str(source),
                actual_bytes=source.stat().st_size,
            ),
            AttachmentComponent(
                component_id=f"{attachment_id}:motion",
                role=AttachmentComponentRole.MOTION,
                source_path=str(motion),
                actual_bytes=motion.stat().st_size,
            ),
        )
        media_category = MediaCategory.LIVE_PHOTO
    else:
        components = ()
        media_category = _media_category(uti, mime_type, source)
    return Attachment(
        attachment_id=attachment_id,
        parent_message_id=parent_message_id,
        transfer_name=transfer_name,
        uti=uti,
        mime_type=mime_type,
        media_category=media_category,
        source_path=str(source),
        declared_bytes=declared_bytes,
        actual_bytes=source.stat().st_size,
        availability=AttachmentAvailability.AVAILABLE,
        components=components,
    )


def resolve_attachment_path(filename: object, messages_root: Path) -> Path:
    """Resolve Apple's tilde path and reject traversal/symlink escapes."""

    if not isinstance(filename, str) or not filename.startswith(
        APPLE_ATTACHMENT_PREFIX
    ):
        raise UnsafeAttachmentPathError("attachment filename has an unsafe prefix")
    relative_text = filename.removeprefix("~/Library/SMS/")
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise UnsafeAttachmentPathError("attachment filename contains traversal")
    root = (Path(messages_root).resolve() / "Attachments").resolve()
    candidate = (Path(messages_root).resolve() / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(root):
        raise UnsafeAttachmentPathError("attachment filename escapes its root")
    return candidate


def _live_photo_motion_path(still: Path) -> Path | None:
    if still.suffix.lower() not in {".jpg", ".jpeg", ".heic"}:
        return None
    parent = still.parent.resolve()
    try:
        entries = tuple(parent.iterdir())
    except OSError:
        return None
    motions = [
        item.resolve()
        for item in entries
        if item.is_file()
        and item.stem == still.stem
        and item.suffix.lower() == ".mov"
        and item.resolve().is_relative_to(parent)
    ]
    private_bundle = parent / f"{parent.name}.pvt"
    metadata = private_bundle / "metadata.plist"
    if len(motions) != 1 or not metadata.is_file():
        return None
    private_root = private_bundle.resolve()
    if not private_root.is_relative_to(parent):
        return None
    if not metadata.resolve().is_relative_to(private_root):
        return None
    return motions[0]


def _media_category(
    uti: str | None,
    mime_type: str | None,
    source: Path | None,
) -> MediaCategory:
    lowered_uti = (uti or "").lower()
    lowered_mime = (mime_type or "").lower()
    suffix = source.suffix.lower() if source else ""
    if lowered_mime.startswith("image/") or lowered_uti in {
        "public.jpeg",
        "public.heic",
        "public.png",
    } or suffix in {".jpg", ".jpeg", ".heic", ".png"}:
        return MediaCategory.PHOTO
    if lowered_mime.startswith("video/") or "movie" in lowered_uti or suffix in {
        ".mov",
        ".mp4",
        ".m4v",
    }:
        return MediaCategory.VIDEO
    return MediaCategory.UNKNOWN


def _safe_transfer_name(value: object) -> str | None:
    text = _optional_string(value, "attachment transfer name")
    if text is None:
        return None
    posix = PurePosixPath(text)
    if posix.name != text or text in {".", ".."}:
        raise SourceRecordError("attachment transfer name must be a leaf name")
    return text


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceRecordError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceRecordError(f"{label} must be a string or null")
    return value.strip() or None
