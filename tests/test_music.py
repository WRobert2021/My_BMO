"""Music metadata, filtering, playback lifecycle, and UI boundary tests."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
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
    read_ogg_duration,
)
from bmo.features.music_config import MusicConfig, load_music_config
from bmo.features.music_store import MusicStore
from bmo.qt.views.music import QtMusicView


def _ogg_page(
    packet: bytes,
    *,
    serial: int,
    sequence: int,
    bos: bool,
    granule: int = 0,
) -> bytes:
    segments = [255] * (len(packet) // 255)
    remainder = len(packet) % 255
    if remainder or not segments:
        segments.append(remainder)
    elif segments:
        segments.append(0)
    header = (
        b"OggS"
        + bytes((0, 0x02 if bos else 0))
        + struct.pack("<Q", granule)
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


def make_ogg(
    path: Path,
    *,
    title: str,
    genre: str,
    album: str = "Fun",
    artist: str = "A Friend",
    series: str = "Adventure Tunes",
    duration: float = 120.0,
) -> bytes:
    picture, image = _picture_tag()
    comments = (
        f"TITLE={title}",
        f"ALBUM={album}",
        f"ARTIST={artist}",
        f"SERIES={series}",
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
        + _ogg_page(
            b"audio",
            serial=4,
            sequence=2,
            bos=False,
            granule=int(duration * 48_000),
        )
    )
    return image


class MusicMetadataTests(unittest.TestCase):
    def test_reads_opus_comments_and_embedded_picture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "album" / "07 - Hidden Number.ogg"
            expected_art = make_ogg(path, title="Hidden Number", genre="song")

            comments = read_ogg_comments(path)
            duration = read_ogg_duration(path)
            tracks = MusicLibrary(directory, ("song",)).tracks()

        self.assertEqual(comments["title"], ("Hidden Number",))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Hidden Number")
        self.assertEqual(tracks[0].artist, "A Friend")
        self.assertEqual(tracks[0].series, "Adventure Tunes")
        self.assertAlmostEqual(tracks[0].duration_seconds, 120.0)
        self.assertAlmostEqual(duration, 120.0)
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

    def test_duration_ignores_granules_from_other_logical_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "song.ogg"
            make_ogg(path, title="Song", genre="song", duration=90.0)
            path.write_bytes(
                path.read_bytes()
                + _ogg_page(
                    b"other stream",
                    serial=99,
                    sequence=0,
                    bos=True,
                    granule=999_999_999,
                )
            )

            duration = read_ogg_duration(path)

        self.assertAlmostEqual(duration, 90.0)


class FakeBackend:
    def __init__(self) -> None:
        self.running = False
        self.paused = False
        self.play_calls: list[tuple[Path, float]] = []
        self.stop_count = 0

    def play(self, path: Path, start_seconds: float = 0.0) -> None:
        self.play_calls.append((path, start_seconds))
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


def sample_track(
    name: str = "Play Me",
    *,
    album: str = "BMO Jams",
    artist: str = "A Friend",
    series: str = "Adventure Tunes",
) -> MusicTrack:
    return MusicTrack(
        path=Path(f"/{name}.ogg"),
        track_id=f"{name}.ogg",
        title=name,
        album=album,
        artist=artist,
        series=series,
        genre="song",
        duration_seconds=120.0,
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

    def test_progress_pause_and_seek_track_elapsed_time(self) -> None:
        now = [10.0]
        backend = FakeBackend()
        session = MusicSession(
            (sample_track(),),
            backend,
            clock=lambda: now[0],
        )

        session.play_selected()
        now[0] = 22.5
        self.assertAlmostEqual(session.position_seconds, 12.5)
        session.pause_or_resume()
        now[0] = 40.0
        self.assertAlmostEqual(session.position_seconds, 12.5)
        session.seek(77.25)

        self.assertEqual(backend.play_calls[-1], (Path("/Play Me.ogg"), 77.25))
        self.assertTrue(backend.paused)
        self.assertAlmostEqual(session.position_seconds, 77.25)

    def test_repeat_restarts_finished_song_and_close_stops_it(self) -> None:
        backend = FakeBackend()
        session = MusicSession((sample_track(),), backend)
        session.play_selected()
        session.toggle_repeat()
        backend.running = False

        session.poll()
        session.close()

        self.assertEqual(len(backend.play_calls), 2)
        self.assertEqual(session.store.play_counts["Play Me.ogg"], 2)
        self.assertEqual(session.state, "stopped")

    def test_finished_song_advances_and_wraps_without_shuffle(self) -> None:
        backend = FakeBackend()
        tracks = tuple(sample_track(name) for name in ("One", "Two", "Three"))
        session = MusicSession(tracks, backend)

        session.play_selected()
        for expected_index in (1, 2, 0):
            backend.running = False
            session.poll()
            self.assertEqual(session.playing_index, expected_index)
            self.assertEqual(backend.play_calls[-1][0], tracks[expected_index].path)

        self.assertEqual(len(backend.play_calls), 4)
        self.assertEqual(session.state, "playing")

    def test_shuffle_plays_full_library_then_makes_a_fresh_queue(self) -> None:
        class RotatingShuffle:
            def __init__(self) -> None:
                self.calls = 0

            def shuffle(self, values: list[int]) -> None:
                self.calls += 1
                shift = self.calls % len(values)
                values[:] = values[shift:] + values[:shift]

        backend = FakeBackend()
        random_source = RotatingShuffle()
        tracks = tuple(sample_track(name) for name in ("One", "Two", "Three"))
        session = MusicSession(tracks, backend, random_source=random_source)

        self.assertTrue(session.shuffle_all())
        first_cycle = [session.playing_index]
        for _index in range(2):
            backend.running = False
            session.poll()
            first_cycle.append(session.playing_index)
        backend.running = False
        session.poll()

        self.assertCountEqual(first_cycle, (0, 1, 2))
        self.assertEqual(random_source.calls, 2)
        self.assertNotEqual(session.playing_index, first_cycle[-1])
        self.assertEqual(session.state, "playing")

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

    def test_seek_launches_ffplay_at_requested_position(self) -> None:
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

            backend.play(path, 42.75)

        arguments = popen.call_args.args[0]
        self.assertEqual(arguments[arguments.index("-ss") + 1], "42.750")

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
        self.assertEqual(config.state_path, MusicConfig().state_path)

    def test_private_config_can_relocate_music_state(self) -> None:
        config = load_music_config(
            {
                "config_path": "missing.json",
                "state_path": "somewhere/music-state.json",
            }
        )

        self.assertEqual(config.state_path, Path("somewhere/music-state.json"))

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
        view.browse_mode = "albums"
        view.group_value = ""
        view.active_playlist = ""

        payload = view.payload()

        self.assertEqual(payload["browserItems"][0]["title"], "BMO Jams")
        self.assertNotIn("track", payload["browserItems"][0])
        self.assertTrue(payload["artworkSource"].toString().startswith("data:image/png"))
        self.assertEqual(payload["durationLabel"], "2:00")

    def test_qt_browses_album_artist_series_and_saved_collections(self) -> None:
        tracks = (
            sample_track("One", album="Alpha", artist="Finn", series="Show A"),
            sample_track("Two", album="Alpha", artist="Jake", series="Show A"),
            sample_track("Three", album="Beta", artist="Finn", series="Show B"),
        )
        store = MusicStore(None)
        store.record_play("Two.ogg")
        store.record_play("One.ogg")
        store.record_play("One.ogg")
        store.toggle_favorite("Three.ogg")
        store.create_playlist("Road Songs")
        store.toggle_playlist_track("Road Songs", "Two.ogg")
        session = MusicSession(tracks, FakeBackend(), store=store)
        view = QtMusicView.__new__(QtMusicView)
        view.session = session
        view.group_value = ""
        view.active_playlist = ""

        expected = {
            "albums": ["Alpha", "Beta"],
            "artists": ["Finn", "Jake"],
            "series_groups": ["Show A", "Show B"],
        }
        for mode, titles in expected.items():
            view.browse_mode = mode
            self.assertEqual(
                [item["title"] for item in view.payload()["browserItems"]],
                titles,
            )

        view.browse_mode = "recent"
        self.assertEqual(
            [item["title"] for item in view.payload()["browserItems"]],
            ["One", "Two"],
        )
        view.browse_mode = "most"
        self.assertEqual(
            [item["title"] for item in view.payload()["browserItems"]],
            ["One", "Two"],
        )
        view.browse_mode = "favorites"
        self.assertEqual(
            [item["title"] for item in view.payload()["browserItems"]],
            ["Three"],
        )
        view.browse_mode = "playlist"
        view.active_playlist = "Road Songs"
        self.assertEqual(
            [item["title"] for item in view.payload()["browserItems"]],
            ["Two"],
        )

    def test_series_tab_opens_a_series_track_list(self) -> None:
        tracks = (
            sample_track("One", series="Show A"),
            sample_track("Two", series="Show A"),
            sample_track("Three", series="Show B"),
        )
        session = MusicSession(tracks, FakeBackend())
        view = QtMusicView.__new__(QtMusicView)
        view.session = session
        view.browse_mode = "albums"
        view.group_value = ""
        view.active_playlist = ""
        view.refresh = Mock()

        view.handle_action("music_browse", "series")
        groups = view.payload()["browserItems"]
        view.handle_action(
            "music_open_group",
            json.dumps({"kind": "series", "value": groups[0]["key"]}),
        )

        self.assertEqual(view.browse_mode, "series")
        self.assertEqual(
            [item["title"] for item in view.payload()["browserItems"]],
            ["One", "Two"],
        )

    def test_filtered_track_items_keep_full_library_indices(self) -> None:
        tracks = (
            sample_track("Bluey", artist="Bingo"),
            sample_track("Unrelated", artist="Other"),
            sample_track("Friend Like Me", artist="Disney"),
        )
        session = MusicSession(tracks, FakeBackend())
        view = QtMusicView.__new__(QtMusicView)
        view.session = session
        view.browse_mode = "artist"
        view.group_value = "Disney"
        view.active_playlist = ""

        items = view.payload()["browserItems"]

        self.assertEqual(items[0]["title"], "Friend Like Me")
        self.assertEqual(items[0]["trackIndex"], 2)
        self.assertNotIn("index", items[0])

    def test_track_selection_does_not_change_browser_revision(self) -> None:
        session = MusicSession(
            tuple(sample_track(f"Song {index}") for index in range(30)),
            FakeBackend(),
        )
        view = QtMusicView.__new__(QtMusicView)
        view.session = session
        view.browse_mode = "songs"
        view.group_value = ""
        view.active_playlist = ""
        view.refresh = Mock()
        initial_revision = view.payload()["browserRevision"]

        view.handle_action("music_select", "24")

        self.assertEqual(view.payload()["browserRevision"], initial_revision)

    def test_playlist_target_stays_active_while_browsing_for_more_songs(self) -> None:
        tracks = (sample_track("One"), sample_track("Two"))
        store = MusicStore(None)
        store.create_playlist("My Mix")
        session = MusicSession(tracks, FakeBackend(), store=store)
        view = QtMusicView.__new__(QtMusicView)
        view.session = session
        view.browse_mode = "playlist"
        view.group_value = ""
        view.active_playlist = "My Mix"
        view.refresh = Mock()

        view.handle_action("music_browse", "songs")
        view.handle_action("music_select", "1")
        view.handle_action("music_playlist_track", "")

        self.assertEqual(view.active_playlist, "My Mix")
        self.assertEqual(store.playlists["My Mix"], ["Two.ogg"])
        self.assertFalse(view.payload()["viewingPlaylist"])

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
            "music_shuffle",
            "music_seek",
            "music_favorite",
        ):
            self.assertIn(f'"{action}"', music_qml)
        self.assertIn("ListModel { id: browserModel }", music_qml)
        self.assertIn("Image.PreserveAspectFit", music_qml)
        self.assertIn('component MarqueeText', music_qml)
        self.assertIn('text: "ALBUMS"', music_qml)
        self.assertIn('text: "ARTISTS"', music_qml)
        self.assertIn('text: "SERIES"', music_qml)
        self.assertNotIn("currentIndex:", music_qml)
        self.assertNotIn('TEXT: "BACK', music_qml.upper())
        self.assertIn('objectName: "hostedCompactFace"', hosted_qml)
        self.assertIn("x: 684", hosted_qml)
        self.assertIn("y: 5", hosted_qml)
        self.assertIn("width: 108", hosted_qml)
        self.assertIn("height: 65", hosted_qml)

    def test_music_qml_loads_and_fits_800_by_420_host(self) -> None:
        script = r'''
import json
import base64
from io import BytesIO
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from bmo.qt.app import QML_PATH
from bmo.qt.controller import QtFaceController

app = QGuiApplication(["music-qml-geometry"])
controller = QtFaceController(start_timer=False)
actions = []
controller.viewActionRequested.connect(
    lambda action, value: actions.append([action, value])
)
art_buffer = BytesIO()
Image.new("RGB", (100, 200), "purple").save(art_buffer, format="PNG")
art_source = QUrl(
    "data:image/png;base64," + base64.b64encode(art_buffer.getvalue()).decode("ascii")
)
payload = {
    "browserKind": "tracks",
    "browserTitle": "ALL SONGS",
    "browserItems": [
        {"kind": "track", "trackIndex": 100 + index, "title": f"Song {index}",
         "album": "BMO Jams", "artist": "A Friend", "series": "A Series"}
        for index in range(20)
    ],
    "browserRevision": "songs:::0",
    "activeChip": "songs",
    "trackCount": 3,
    "selectedIndex": 100,
    "playingIndex": 100,
    "title": "A Very Long Song Title That Needs To Move Across The Screen",
    "album": "BMO Jams",
    "artist": "A Friend",
    "series": "Adventure Tunes",
    "artworkSource": art_source,
    "status": "NOW PLAYING",
    "state": "playing",
    "canPlay": True,
    "canPause": True,
    "canSeek": True,
    "position": 42.0,
    "duration": 120.0,
    "positionLabel": "0:42",
    "durationLabel": "2:00",
    "repeat": False,
    "shuffle": False,
    "favorite": False,
    "activePlaylist": "",
    "viewingPlaylist": False,
    "playlistContainsCurrent": False,
    "libraryReadOnly": False,
}
controller.show_view("music", "Music", payload)
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("bmoUi", controller)
engine.load(QUrl.fromLocalFile(str(QML_PATH.resolve())))
window = engine.rootObjects()[0]
window.showNormal()
window.resize(800, 480)
for _index in range(5):
    app.processEvents()

def find(name):
    item = window.findChild(QQuickItem, name)
    if item is None:
        raise AssertionError(name)
    return item

def geometry(name):
    item = find(name)
    point = item.mapToItem(None, QPointF(0, 0))
    return [point.x(), point.y(), item.width(), item.height()]

song_list = find("musicSongList")
first_row = song_list.mapToItem(None, song_list.width() / 2, 25)
QTest.mouseClick(
    window,
    Qt.MouseButton.LeftButton,
    pos=QPoint(int(first_row.x()), int(first_row.y())),
)
for _index in range(2):
    app.processEvents()
song_list.setProperty("contentY", 150.0)
updated = dict(payload)
updated["selectedIndex"] = 114
controller.update_view(updated)
for _index in range(4):
    app.processEvents()

result = {name: geometry(name) for name in (
    "hostedCompactFace", "musicSongPanel", "musicSongList",
    "musicNowPlayingCard", "musicProgressSlider", "musicAlbumArtFrame",
    "musicAlbumArt"
)}
result["scrollY"] = song_list.property("contentY")
result["selectionAction"] = actions[-1]
print(json.dumps(result))
window.close()
controller.stop()
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ReferenceError", result.stderr)
        geometry = json.loads(result.stdout.strip())
        self.assertEqual(geometry["hostedCompactFace"], [684.0, 5.0, 108.0, 65.0])
        self.assertEqual(
            geometry["selectionAction"],
            ["music_select", "100"],
        )
        self.assertAlmostEqual(geometry["scrollY"], 150.0)
        for name in (
            "musicSongPanel",
            "musicSongList",
            "musicNowPlayingCard",
            "musicProgressSlider",
        ):
            x, y, width, height = geometry[name]
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 62)
            self.assertLessEqual(x + width, 800)
            self.assertLessEqual(y + height, 480)
        frame_x, frame_y, frame_width, frame_height = geometry[
            "musicAlbumArtFrame"
        ]
        art_x, art_y, art_width, art_height = geometry["musicAlbumArt"]
        self.assertGreaterEqual(art_x, frame_x)
        self.assertGreaterEqual(art_y, frame_y)
        self.assertLessEqual(art_x + art_width, frame_x + frame_width)
        self.assertLessEqual(art_y + art_height, frame_y + frame_height)
        self.assertAlmostEqual(art_width / art_height, 0.5, places=2)


class MusicStoreTests(unittest.TestCase):
    def test_history_favorites_and_playlists_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "music-state.json"
            store = MusicStore(path)

            store.record_play("album/one.ogg")
            store.record_play("album/two.ogg")
            store.record_play("album/one.ogg")
            store.toggle_favorite("album/one.ogg")
            store.create_playlist("Dance Time")
            store.toggle_playlist_track("Dance Time", "album/two.ogg")

            loaded = MusicStore(path)

        self.assertEqual(loaded.recent, ["album/one.ogg", "album/two.ogg"])
        self.assertEqual(loaded.play_counts["album/one.ogg"], 2)
        self.assertEqual(loaded.favorites, {"album/one.ogg"})
        self.assertEqual(loaded.playlists, {"Dance Time": ["album/two.ogg"]})

    def test_malformed_state_becomes_read_only_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "music-state.json"
            original = '{"version":1,"version":1}'
            path.write_text(original, encoding="utf-8")

            store = MusicStore(path)
            store.toggle_favorite("album/one.ogg")

            self.assertTrue(store.read_only)
            self.assertIn("read-only", store.error)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_store_file_contains_only_portable_track_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "music-state.json"
            store = MusicStore(path)
            store.record_play("series/song.ogg")

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["recent"], ["series/song.ogg"])


if __name__ == "__main__":
    unittest.main()
