from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from bmo.features.imessage_relay.media_library import ReceivedMediaLibrary
from bmo.features.imessage_relay.receiver import StoredAttachment


class ReceivedMediaLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.library = ReceivedMediaLibrary(
            photo_directory=self.root / "Pictures",
            audio_directory=self.root / "Music",
            video_directory=self.root / "Videos",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_completed_photo_is_published_with_a_stable_safe_name(self) -> None:
        source, digest = self._blob(b"invented-photo")
        store = Mock()
        store.get_attachment.return_value = StoredAttachment(
            event_id="EVENT-1",
            blob_id="PHOTO-1",
            expected_bytes=14,
            received_bytes=14,
            content_sha256=digest,
            complete=True,
            storage_path=source,
        )
        event = self._event(
            {
                "attachment_id": "PHOTO-1",
                "transfer_name": "../../My Photo.JPG",
                "mime_type": "image/jpeg",
                "media_category": "photo",
                "components": [],
            }
        )

        first = self.library.attachments_for_event(store, event)
        second = self.library.attachments_for_event(store, event)

        self.assertEqual(first, second)
        self.assertTrue(first[0].available)
        published = Path(first[0].path or "")
        self.assertEqual(published.parent, (self.root / "Pictures").resolve())
        self.assertEqual(published.read_bytes(), b"invented-photo")
        self.assertEqual(published.name, f"My Photo-{digest[:12]}.jpg")
        self.assertEqual(published.stat().st_ino, source.stat().st_ino)

    def test_audio_video_and_live_photo_components_use_their_own_directories(self) -> None:
        audio_source, audio_digest = self._blob(b"audio", "audio.blob")
        still_source, still_digest = self._blob(b"still", "still.blob")
        motion_source, motion_digest = self._blob(b"motion", "motion.blob")
        store = Mock()
        store.get_attachment.side_effect = (
            self._stored("AUDIO-1", audio_source, audio_digest),
            self._stored("STILL-1", still_source, still_digest),
            self._stored("MOTION-1", motion_source, motion_digest),
        )

        audio = self.library.attachments_for_event(
            store,
            self._event(
                {
                    "attachment_id": "AUDIO-1",
                    "transfer_name": "voice-note.m4a",
                    "mime_type": "audio/mp4",
                    "media_category": "unknown",
                    "components": [],
                }
            ),
        )
        live_photo = self.library.attachments_for_event(
            store,
            self._event(
                {
                    "attachment_id": "LIVE-1",
                    "transfer_name": "live-photo.heic",
                    "mime_type": "image/heic",
                    "media_category": "live_photo",
                    "components": [
                        {"component_id": "STILL-1", "role": "still"},
                        {"component_id": "MOTION-1", "role": "motion"},
                    ],
                }
            ),
        )

        self.assertEqual(
            Path(audio[0].path or "").parent,
            (self.root / "Music").resolve(),
        )
        self.assertEqual(
            Path(live_photo[0].path or "").parent,
            (self.root / "Pictures").resolve(),
        )
        self.assertEqual(
            Path(live_photo[1].path or "").parent,
            (self.root / "Videos").resolve(),
        )
        self.assertTrue(all(item.available for item in audio + live_photo))

    def test_incomplete_or_missing_blob_is_reported_without_a_path(self) -> None:
        store = Mock()
        store.get_attachment.return_value = None

        (attachment,) = self.library.attachments_for_event(
            store,
            self._event(
                {
                    "attachment_id": "MISSING-1",
                    "transfer_name": "missing.mov",
                    "mime_type": "video/quicktime",
                    "media_category": "video",
                    "components": [],
                }
            ),
        )

        self.assertFalse(attachment.available)
        self.assertIsNone(attachment.path)
        self.assertEqual(attachment.media_category, "video")

    def _blob(self, content: bytes, name: str = "source.blob") -> tuple[Path, str]:
        source = self.root / name
        source.write_bytes(content)
        return source, hashlib.sha256(content).hexdigest()

    @staticmethod
    def _event(attachment: dict[str, object]) -> dict[str, object]:
        return {"event_id": "EVENT-1", "attachments": [attachment]}

    @staticmethod
    def _stored(blob_id: str, path: Path, digest: str) -> StoredAttachment:
        size = path.stat().st_size
        return StoredAttachment(
            event_id="EVENT-1",
            blob_id=blob_id,
            expected_bytes=size,
            received_bytes=size,
            content_sha256=digest,
            complete=True,
            storage_path=path,
        )


if __name__ == "__main__":
    unittest.main()
