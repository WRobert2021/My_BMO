"""Music metadata, filtering, playback lifecycle, and UI boundary tests."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image

from bmo.features import FeatureMenuContext, load_feature_registry
from bmo.features.music import (
    FFplayBackend,
    MUSIC_MENU_ITEM,
    MusicLibrary,
    MusicSession,
    MusicTool,
    MusicTrack,
    read_ogg_comments,
)
from bmo.features.music_config import MusicConfig, load_music_config
from bmo.qt.views.music import QtMusicView


def _ogg_page(packet: bytes, *, serial: int, sequence: int, bos: bool) -> bytes:
    segments = [255] * (len(packet) // 255)
    remainder = len(packet) % 255
    if remainder or not segments:
        segments.append(remainder)
    elif segments:
        segments.append(0)
    header = (
        b"OggS"
        + bytes((0, 0x02 if bos else 0))
        + b"\x00" * 8
        + struct.pack("<I", serial)
        + struct.pack("<I", sequence)
        + b"\x00" * 4
        + bytes((len(segments),))
        + bytes(segments)
    )
    return header + packet


def _picture_tag(color: str = "#f08aa6") -> tuple[str, bytes]:
    buffer = BytesIO()
    Image.new("RGB", (12, 8), color=color).save(buffer, format="PNG")
    image = buffer.getvalue()
    mime = b"image/png"
    block = (
        struct.pack(">I", 3)
        + struct.pack(">I", len(mime))
        + mime
        + struct.pack(">I", 0)
        + struct.pack(">IIIII", 12, 8, 24, 0, len(image))
        + image
    )
    return base64.b64encode(block).decode("ascii"), image


def make_ogg(path: Path, *, title: str, genre: str, album: str = "Fun") -> bytes:
    picture, image = _picture_tag()
    comments = (
        f"TITLE={title}",
        f"ALBUM={album}",
        f"GENRE={genre}",
        "TRACK=7/20",
        f"METADATA_BLOCK_PICTURE={picture}",
    )
    vendor = b"BMO tests"
    encoded = [comment.encode("utf-8") for comment in comments]
    tags = (
        b"OpusTags"
        + struct.pack("<I", len(vendor))
        + vendor
        + struct.pack("<I", len(encoded))
        + b"".join(struct.pack("<I", len(value)) + value for value in encoded)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        _ogg_page(b"OpusHead" + b"\x00" * 12, serial=4, sequence=0, bos=True)
        + _ogg_page(tags, serial=4, sequence=1, bos=False)
    )
    return image


class MusicMetadataTests(unittest.TestCase):
    def test_reads_opus_comments_and_embedded_picture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "album" / "07 - Hidden Number.ogg"
            expected_art = make_ogg(path, title="Hidden Number", genre="song")

            comments = read_ogg_comments(path)
            tracks = MusicLibrary(directory, ("song",)).tracks()

        self.assertEqual(comments["title"], ("Hidden Number",))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Hidden Number")
        self.assertNotIn("07", tracks[0].title)
        self.assertEqual(tracks[0].artwork_mime, "image/png")
        self.assertEqual(tracks[0].artwork, expected_art)

    def test_recursively_filters_on_genre_and_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            song = root / "Music" / "01 - Song.ogg"
            story = root / "Stories" / "02 - Story.ogg"
            make_ogg(song, title="A Song", genre="SoNg", album="Music")
            make_ogg(story, title="A Story", genre="story", album="Stories")
            (root / "Music" / "song-link.ogg").symlink_to(song)

            tracks = MusicLibrary(root, ("song",)).tracks()

        self.assertEqual(tuple(track.title for track in tracks), ("A Song",))

    def test_missing_metadata_uses_filename_without_track_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Album" / "12 - Friendly Tune.ogg"
            make_ogg(path, title="", genre="song", album="")

            track = MusicLibrary(directory, ("song",)).tracks()[0]

        self.assertEqual(track.title, "Friendly Tune")
        self.assertEqual(track.album, "Album")


class FakeBackend:
    def __init__(self) -> None:
        self.running = False
        self.paused = False
        self.play_calls: list[Path] = []
        self.stop_count = 0

    def play(self, path: Path) -> None:
        self.play_calls.append(path)
        self.running = True
        self.paused = False

    def is_running(self) -> bool:
        return self.running

    def pause(self) -> bool:
        if not self.running:
            return False
        self.paused = True
        return True

    def resume(self) -> bool:
        if not self.running or not self.paused:
            return False
        self.paused = False
        return True

    def stop(self) -> None:
        self.running = False
        self.paused = False
        self.stop_count += 1


def sample_track(name: str = "Play Me") -> MusicTrack:
    return MusicTrack(
        path=Path(f"/{name}.ogg"),
        title=name,
        album="BMO Jams",
        artist="A Friend",
        genre="song",
        artwork_mime="image/png",
        artwork=b"picture bytes",
    )


class MusicSessionTests(unittest.TestCase):
    def test_play_pause_resume_stop_and_face_animation_hook(self) -> None:
        backend = FakeBackend()
        face_states: list[str] = []
        session = MusicSession(
            (sample_track(),),
            backend,
            face_animation_hook=face_states.append,
        )

        self.assertTrue(session.play_selected())
        self.assertTrue(session.pause_or_resume())
        self.assertTrue(session.pause_or_resume())
        session.stop()

        self.assertEqual(
            face_states,
            ["music_playing", "music_paused", "music_playing", "idle"],
        )
        self.assertEqual(session.state, "stopped")
        self.assertGreaterEqual(backend.stop_count, 1)

    def test_repeat_restarts_finished_song_and_close_stops_it(self) -> None:
        backend = FakeBackend()
        session = MusicSession((sample_track(),), backend)
        session.play_selected()
        session.toggle_repeat()
        backend.running = False

        session.poll()
        session.close()

        self.assertEqual(len(backend.play_calls), 2)
        self.assertEqual(session.state, "stopped")

    def test_empty_library_reports_useful_play_error(self) -> None:
        session = MusicSession((), FakeBackend())

        self.assertFalse(session.play_selected())

        self.assertIn("configured genre", session.error)


class FFplayBackendTests(unittest.TestCase):
    def test_launches_headless_player_and_stops_process(self) -> None:
        process = Mock()
        process.poll.return_value = None
        popen = Mock(return_value=process)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "song.ogg"
            path.touch()
            backend = FFplayBackend(
                "ffplay",
                popen=popen,
                command_finder=lambda command: f"/usr/bin/{command}",
            )

            backend.play(path)
            backend.stop()

        arguments = popen.call_args.args[0]
        self.assertEqual(arguments[0], "/usr/bin/ffplay")
        self.assertIn("-nodisp", arguments)
        self.assertIn("-autoexit", arguments)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=0.75)

    def test_missing_command_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "song.ogg"
            path.touch()
            backend = FFplayBackend(
                "missing-player",
                command_finder=lambda _command: None,
            )

            with self.assertRaisesRegex(RuntimeError, "setup.sh"):
                backend.play(path)


class MusicConfigurationAndFeatureTests(unittest.TestCase):
    def test_private_config_selects_library_and_genre(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music_root = root / "songs"
            config_path = root / "music.json"
            config_path.write_text(
                '{"music_root":"songs","allowed_genres":["Song"],'
                '"show_in_menu":false,"player_command":"ffplay"}',
                encoding="utf-8",
            )

            config = load_music_config({"config_path": config_path})

        self.assertEqual(config.music_root, Path("songs"))
        self.assertEqual(config.allowed_genres, ("song",))
        self.assertFalse(config.show_in_menu)

    def test_menu_tool_has_no_voice_or_prompt_surface(self) -> None:
        result = load_feature_registry(
            {
                "features": [
                    {
                        "module": "bmo.features.music",
                        "settings": {"music_root": "completed"},
                    }
                ]
            }
        )

        self.assertEqual(result.registry.actions, set())
        self.assertEqual(result.registry.menu_items, (MUSIC_MENU_ITEM,))

    def test_face_close_callback_stops_music_and_returns_to_menu(self) -> None:
        session_holder: list[MusicSession] = []
        app = Mock()

        def factory(_master: object, *, session: MusicSession, **kwargs: object):
            session_holder.append(session)
            app.on_close = kwargs["on_close"]
            return app

        tool = MusicTool(
            MusicConfig(music_root=Path("missing")),
            app_factory=factory,
            backend_factory=lambda _command: FakeBackend(),
        )
        returned = Mock()
        tool.open_menu(FeatureMenuContext(master=object(), on_close=returned))

        app.on_close()

        self.assertEqual(session_holder[0].state, "stopped")
        returned.assert_called_once_with()

    def test_qt_payload_has_title_album_art_and_no_track_number(self) -> None:
        session = MusicSession(
            (sample_track("Visible Title"),),
            FakeBackend(),
        )
        view = QtMusicView.__new__(QtMusicView)
        view.session = session

        payload = view.payload()

        self.assertEqual(payload["tracks"][0]["title"], "Visible Title")
        self.assertNotIn("track", payload["tracks"][0])
        self.assertTrue(payload["artworkSource"].toString().startswith("data:image/png"))

    def test_qml_has_touch_scrolling_controls_and_face_only_exit(self) -> None:
        qml_root = Path(__file__).resolve().parents[1] / "bmo" / "qt" / "qml"
        music_qml = (qml_root / "MusicView.qml").read_text(encoding="utf-8")
        hosted_qml = (qml_root / "HostedView.qml").read_text(encoding="utf-8")

        self.assertIn('objectName: "musicSongList"', music_qml)
        self.assertIn("Flickable.StopAtBounds", music_qml)
        for action in (
            "music_play",
            "music_pause",
            "music_stop",
            "music_repeat",
        ):
            self.assertIn(f'"{action}"', music_qml)
        self.assertNotIn('TEXT: "BACK', music_qml.upper())
        self.assertIn('objectName: "hostedCompactFace"', hosted_qml)
        self.assertIn("x: 684", hosted_qml)
        self.assertIn("y: 5", hosted_qml)
        self.assertIn("width: 108", hosted_qml)
        self.assertIn("height: 65", hosted_qml)


if __name__ == "__main__":
    unittest.main()
