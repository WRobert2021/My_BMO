"""Menu-only local music library with Ogg metadata and ffplay playback."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import random
import re
import shutil
import signal
import struct
import subprocess
import time
from typing import Any, Protocol

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
)
from bmo.features.music_config import MusicConfig, load_music_config
from bmo.features.music_store import MusicStore
from bmo.view_factory import NOT_HOSTED, create_hosted_view


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MUSIC_MENU_ITEM = FeatureMenuItem(
    name="music",
    label="Music",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "music.png",
)
MUSIC_EXTENSIONS = frozenset({".ogg", ".oga", ".opus"})
MAX_COMMENT_PACKET_BYTES = 12 * 1024 * 1024
MAX_ARTWORK_BYTES = 10 * 1024 * 1024
_FILENAME_TRACK_PREFIX = re.compile(r"^\s*\d+\s*[-._]\s*")

MusicAppFactory = Callable[..., Any]
FaceAnimationHook = Callable[[str], None]


class MusicPlaybackBackend(Protocol):
    """Small playback surface shared by the Qt and legacy views."""

    def play(self, path: Path, start_seconds: float = 0.0) -> None: ...

    def is_running(self) -> bool: ...

    def pause(self) -> bool: ...

    def resume(self) -> bool: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MusicTrack:
    """One playable track derived from Ogg comments, without track numbering."""

    path: Path
    track_id: str
    title: str
    album: str
    artist: str
    series: str
    genre: str
    duration_seconds: float = 0.0
    artwork_mime: str = ""
    artwork: bytes = b""


def _create_music_app(*args: Any, **kwargs: Any) -> Any:
    """Construct the legacy Tk view only outside the production Qt host."""
    hosted = create_hosted_view("music", args, kwargs)
    if hosted is not NOT_HOSTED:
        return hosted
    from bmo.ui.music import MusicApp

    return MusicApp(*args, **kwargs)


def _ogg_packets(path: Path) -> Iterator[bytes]:
    """Yield bounded packets from each logical stream in an Ogg container."""
    partial: dict[int, bytearray] = {}
    with path.open("rb") as handle:
        while True:
            header = handle.read(27)
            if not header:
                return
            if len(header) != 27 or header[:4] != b"OggS" or header[4] != 0:
                raise ValueError("invalid Ogg page")
            page_flags = header[5]
            serial = struct.unpack_from("<I", header, 14)[0]
            segment_count = header[26]
            lacing = handle.read(segment_count)
            if len(lacing) != segment_count:
                raise ValueError("truncated Ogg segment table")
            body_length = sum(lacing)
            body = handle.read(body_length)
            if len(body) != body_length:
                raise ValueError("truncated Ogg page")

            packet = partial.setdefault(serial, bytearray())
            if not (page_flags & 0x01) and packet:
                packet.clear()
            offset = 0
            for segment_length in lacing:
                packet.extend(body[offset : offset + segment_length])
                offset += segment_length
                if len(packet) > MAX_COMMENT_PACKET_BYTES:
                    raise ValueError("Ogg metadata packet is too large")
                if segment_length < 255:
                    yield bytes(packet)
                    packet.clear()


def _parse_comment_packet(packet: bytes) -> dict[str, tuple[str, ...]] | None:
    if packet.startswith(b"OpusTags"):
        payload = memoryview(packet)[8:]
    elif packet.startswith(b"\x03vorbis"):
        payload = memoryview(packet)[7:]
    else:
        return None

    offset = 0

    def read_u32() -> int:
        nonlocal offset
        if offset + 4 > len(payload):
            raise ValueError("truncated Ogg comments")
        value = struct.unpack_from("<I", payload, offset)[0]
        offset += 4
        return value

    vendor_length = read_u32()
    if vendor_length > len(payload) - offset:
        raise ValueError("truncated Ogg vendor string")
    offset += vendor_length
    count = read_u32()
    if count > 4096:
        raise ValueError("too many Ogg comments")

    comments: dict[str, list[str]] = {}
    for _index in range(count):
        length = read_u32()
        if length > len(payload) - offset:
            raise ValueError("truncated Ogg comment")
        raw = bytes(payload[offset : offset + length])
        offset += length
        text = raw.decode("utf-8", errors="replace")
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        normalized = key.strip().casefold()
        if normalized:
            comments.setdefault(normalized, []).append(value.strip())
    return {key: tuple(values) for key, values in comments.items()}


def read_ogg_comments(path: str | Path) -> dict[str, tuple[str, ...]]:
    """Return normalized Vorbis/Opus comments without decoding audio."""
    supplied = Path(path)
    for index, packet in enumerate(_ogg_packets(supplied)):
        comments = _parse_comment_packet(packet)
        if comments is not None:
            return comments
        if index >= 31:
            break
    return {}


def _ogg_codec_timing(data: bytes) -> tuple[int, int, int] | None:
    """Return the codec stream serial, sample rate, and Opus pre-skip."""
    partial: dict[int, bytearray] = {}
    offset = 0
    while offset + 27 <= len(data):
        page = data.find(b"OggS", offset)
        if page < 0 or page + 27 > len(data):
            return None
        if data[page + 4] != 0:
            offset = page + 4
            continue
        page_flags = data[page + 5]
        serial = struct.unpack_from("<I", data, page + 14)[0]
        segment_count = data[page + 26]
        table_end = page + 27 + segment_count
        if table_end > len(data):
            return None
        lacing = data[page + 27 : table_end]
        body_end = table_end + sum(lacing)
        if body_end > len(data):
            return None
        packet = partial.setdefault(serial, bytearray())
        if not (page_flags & 0x01) and packet:
            packet.clear()
        body_offset = table_end
        for segment_length in lacing:
            packet.extend(data[body_offset : body_offset + segment_length])
            body_offset += segment_length
            if segment_length >= 255:
                continue
            if packet.startswith(b"OpusHead") and len(packet) >= 12:
                return serial, 48_000, struct.unpack_from("<H", packet, 10)[0]
            if packet.startswith(b"\x01vorbis") and len(packet) >= 16:
                sample_rate = struct.unpack_from("<I", packet, 12)[0]
                return serial, sample_rate, 0
            packet.clear()
        offset = body_end
    return None


def read_ogg_duration(path: str | Path) -> float:
    """Read Opus/Vorbis duration from its stream's final Ogg granule."""
    supplied = Path(path)
    with supplied.open("rb") as handle:
        head = handle.read(64 * 1024)
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        tail_size = min(size, 256 * 1024)
        handle.seek(size - tail_size)
        tail = handle.read(tail_size)

    timing = _ogg_codec_timing(head)
    if timing is None:
        return 0.0
    codec_serial, sample_rate, pre_skip = timing
    if sample_rate <= 0:
        return 0.0

    granule = -1
    offset = 0
    while True:
        page = tail.find(b"OggS", offset)
        if page < 0:
            break
        if (
            page + 18 <= len(tail)
            and tail[page + 4] == 0
            and struct.unpack_from("<I", tail, page + 14)[0] == codec_serial
        ):
            candidate = struct.unpack_from("<Q", tail, page + 6)[0]
            if candidate != 0xFFFFFFFFFFFFFFFF:
                granule = max(granule, candidate)
        offset = page + 4
    if granule < 0:
        return 0.0
    return max(0.0, (granule - pre_skip) / sample_rate)


def _decode_picture_block(value: str) -> tuple[str, bytes]:
    try:
        block = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return "", b""
    if len(block) < 32 or len(block) > MAX_ARTWORK_BYTES + 1024:
        return "", b""
    view = memoryview(block)
    offset = 4  # FLAC picture type; front cover is preferred by convention.

    def read_u32() -> int:
        nonlocal offset
        if offset + 4 > len(view):
            raise ValueError
        parsed = struct.unpack_from(">I", view, offset)[0]
        offset += 4
        return parsed

    try:
        mime_length = read_u32()
        if mime_length > 128 or mime_length > len(view) - offset:
            return "", b""
        mime = bytes(view[offset : offset + mime_length]).decode(
            "ascii", errors="ignore"
        ).strip().lower()
        offset += mime_length
        description_length = read_u32()
        if description_length > len(view) - offset:
            return "", b""
        offset += description_length
        for _field in range(4):
            read_u32()  # Width, height, depth, indexed-color count.
        data_length = read_u32()
        if data_length > MAX_ARTWORK_BYTES or data_length > len(view) - offset:
            return "", b""
        data = bytes(view[offset : offset + data_length])
    except (ValueError, struct.error):
        return "", b""
    if not mime.startswith("image/") or not data:
        return "", b""
    return mime, data


def _extract_artwork(
    comments: Mapping[str, tuple[str, ...]],
) -> tuple[str, bytes]:
    for value in comments.get("metadata_block_picture", ()):
        mime, data = _decode_picture_block(value)
        if data:
            return mime, data
    cover_mime = next(
        (value for value in comments.get("coverartmime", ()) if value),
        "image/jpeg",
    )
    for value in comments.get("coverart", ()):
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            continue
        if 0 < len(data) <= MAX_ARTWORK_BYTES and cover_mime.startswith("image/"):
            return cover_mime.lower(), data
    return "", b""


def _first_comment(
    comments: Mapping[str, tuple[str, ...]],
    key: str,
    default: str = "",
) -> str:
    return next((value for value in comments.get(key, ()) if value), default)


class MusicLibrary:
    """Discover only genre-approved audio beneath one configured root."""

    def __init__(self, root: str | Path, allowed_genres: tuple[str, ...]) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.allowed_genres = frozenset(genre.casefold() for genre in allowed_genres)

    def tracks(self) -> tuple[MusicTrack, ...]:
        discovered: list[MusicTrack] = []
        try:
            candidates = self.root.rglob("*")
            for candidate in candidates:
                if candidate.is_symlink() or candidate.suffix.casefold() not in MUSIC_EXTENSIONS:
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(self.root)
                    if not resolved.is_file():
                        continue
                    comments = read_ogg_comments(resolved)
                    genres = tuple(
                        value.strip().casefold()
                        for value in comments.get("genre", ())
                        if value.strip()
                    )
                    if not self.allowed_genres.intersection(genres):
                        continue
                    fallback_title = _FILENAME_TRACK_PREFIX.sub("", resolved.stem)
                    artwork_mime, artwork = _extract_artwork(comments)
                    track_id = resolved.relative_to(self.root).as_posix()
                    discovered.append(
                        MusicTrack(
                            path=resolved,
                            track_id=track_id,
                            title=_first_comment(comments, "title", fallback_title),
                            album=_first_comment(
                                comments,
                                "album",
                                resolved.parent.name,
                            ),
                            artist=_first_comment(comments, "artist"),
                            series=_first_comment(comments, "series"),
                            genre=genres[0],
                            duration_seconds=read_ogg_duration(resolved),
                            artwork_mime=artwork_mime,
                            artwork=artwork,
                        )
                    )
                except (OSError, PermissionError, RuntimeError, ValueError):
                    continue
        except OSError:
            return ()
        return tuple(
            sorted(
                discovered,
                key=lambda track: (
                    track.album.casefold(),
                    track.path.parent.as_posix().casefold(),
                    track.path.name.casefold(),
                ),
            )
        )


class FFplayBackend:
    """Own one headless ffplay child process."""

    def __init__(
        self,
        command: str = "ffplay",
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        command_finder: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.command = command
        self._popen = popen
        self._command_finder = command_finder
        self._process: Any | None = None
        self.current_path: Path | None = None
        self.paused = False

    def _executable(self) -> str:
        located = self._command_finder(self.command)
        if located is None:
            raise RuntimeError(
                f"Music playback needs '{self.command}'. Run setup.sh first."
            )
        return located

    def play(self, path: Path, start_seconds: float = 0.0) -> None:
        resolved = Path(path).resolve(strict=True)
        start = max(0.0, float(start_seconds))
        if self.current_path == resolved and self.is_running() and start <= 0.0:
            if self.paused:
                self.resume()
            return
        self.stop()
        arguments = [
            self._executable(),
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
        ]
        if start > 0.0:
            arguments.extend(("-ss", f"{start:.3f}"))
        arguments.append(str(resolved))
        self._process = self._popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.current_path = resolved
        self.paused = False

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def pause(self) -> bool:
        if not self.is_running() or self.paused:
            return False
        os.kill(self._process.pid, signal.SIGSTOP)
        self.paused = True
        return True

    def resume(self) -> bool:
        if not self.is_running() or not self.paused:
            return False
        os.kill(self._process.pid, signal.SIGCONT)
        self.paused = False
        return True

    def stop(self) -> None:
        process = self._process
        self._process = None
        self.current_path = None
        self.paused = False
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            try:
                process.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.75)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            # A concurrently exiting child is already safely stopped. Cleanup
            # must never prevent the feature or the rest of BMO from closing.
            return


class MusicSession:
    """Toolkit-neutral playback, progress, shuffle, and library state."""

    def __init__(
        self,
        tracks: tuple[MusicTrack, ...],
        backend: MusicPlaybackBackend,
        *,
        store: MusicStore | None = None,
        face_animation_hook: FaceAnimationHook | None = None,
        clock: Callable[[], float] = time.monotonic,
        random_source: Any | None = None,
    ) -> None:
        self.tracks = tracks
        self.backend = backend
        self.store = store or MusicStore(None)
        self.selected_index: int | None = 0 if tracks else None
        self.playing_index: int | None = None
        self.state = "stopped"
        self.repeat = False
        self.error = self.store.error
        self._face_animation_hook = face_animation_hook
        self._clock = clock
        self._random = random_source or random.SystemRandom()
        self._position_base = 0.0
        self._position_started_at: float | None = None
        self._position_track_index: int | None = self.selected_index
        self._shuffle_queue: list[int] = []
        self._shuffle_cursor = -1
        self._index_by_id = {
            track.track_id: index for index, track in enumerate(tracks)
        }

    @property
    def selected_track(self) -> MusicTrack | None:
        if self.selected_index is None:
            return None
        return self.tracks[self.selected_index]

    @property
    def display_track(self) -> MusicTrack | None:
        if self.state in {"playing", "paused"} and self.playing_index is not None:
            return self.tracks[self.playing_index]
        return self.selected_track

    @property
    def display_index(self) -> int | None:
        if self.state in {"playing", "paused"} and self.playing_index is not None:
            return self.playing_index
        return self.selected_index

    @property
    def duration_seconds(self) -> float:
        track = self.display_track
        return track.duration_seconds if track is not None else 0.0

    @property
    def position_seconds(self) -> float:
        display_index = self.display_index
        if display_index is None or self._position_track_index != display_index:
            return 0.0
        position = self._position_base
        if self.state == "playing" and self._position_started_at is not None:
            position += max(0.0, self._clock() - self._position_started_at)
        duration = self.duration_seconds
        return min(position, duration) if duration > 0.0 else max(0.0, position)

    @property
    def shuffle_active(self) -> bool:
        return bool(self._shuffle_queue)

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            self.selected_index,
            self.playing_index,
            self.state,
            self.repeat,
            self.shuffle_active,
            self.error,
            self.store.revision,
            round(self.position_seconds, 1),
        )

    def _set_state(self, state: str) -> None:
        if self.state == state:
            return
        self.state = state
        if self._face_animation_hook is not None:
            try:
                hook_state = {
                    "playing": "music_playing",
                    "paused": "music_paused",
                    "stopped": "idle",
                }.get(state, "idle")
                self._face_animation_hook(hook_state)
            except Exception:
                pass

    def select(self, index: int) -> bool:
        if not 0 <= index < len(self.tracks):
            self.error = "That song is no longer available."
            return False
        self.selected_index = index
        if self.state == "stopped":
            self._position_track_index = index
            self._position_base = 0.0
            self._position_started_at = None
        self.error = self.store.error
        return True

    def _play_selected(
        self,
        *,
        preserve_shuffle: bool,
        record_play: bool,
        start_seconds: float | None = None,
    ) -> bool:
        track = self.selected_track
        if track is None:
            self.error = "No songs with the configured genre were found."
            return False
        if not preserve_shuffle:
            self._shuffle_queue.clear()
            self._shuffle_cursor = -1
        start = (
            self._position_base
            if start_seconds is None and self._position_track_index == self.selected_index
            else float(start_seconds or 0.0)
        )
        try:
            self.backend.play(track.path, start)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.error = str(exc) or "BMO could not play that song."
            self._set_state("stopped")
            return False
        self.playing_index = self.selected_index
        self._position_track_index = self.playing_index
        self._position_base = max(0.0, start)
        self._position_started_at = self._clock()
        self.error = self.store.error
        self._set_state("playing")
        if record_play:
            self.store.record_play(track.track_id)
            self.error = self.store.error
        return True

    def play_selected(self) -> bool:
        if self.state == "playing" and self.selected_index == self.playing_index:
            return True
        if self.state == "paused" and self.selected_index == self.playing_index:
            return self.pause_or_resume()
        return self._play_selected(preserve_shuffle=False, record_play=True)

    def pause_or_resume(self) -> bool:
        try:
            if self.state == "paused":
                changed = self.backend.resume()
                if changed:
                    self._position_started_at = self._clock()
                    self._set_state("playing")
            elif self.state == "playing":
                position = self.position_seconds
                changed = self.backend.pause()
                if changed:
                    self._position_base = position
                    self._position_started_at = None
                    self._set_state("paused")
            else:
                changed = False
        except OSError as exc:
            self.error = str(exc) or "BMO could not pause that song."
            return False
        return changed

    def seek(self, seconds: float) -> bool:
        track = self.display_track
        display_index = self.display_index
        if track is None or display_index is None or track.duration_seconds <= 0.0:
            return False
        target = min(max(0.0, float(seconds)), track.duration_seconds)
        if self.state in {"playing", "paused"} and self.playing_index is not None:
            was_paused = self.state == "paused"
            try:
                self.backend.play(track.path, target)
                if was_paused:
                    self.backend.pause()
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                self.error = str(exc) or "BMO could not move within that song."
                return False
            self._position_track_index = self.playing_index
            self._position_base = target
            self._position_started_at = None if was_paused else self._clock()
        else:
            self._position_track_index = display_index
            self._position_base = target
            self._position_started_at = None
        self.error = self.store.error
        return True

    def stop(self) -> None:
        self.backend.stop()
        self._position_track_index = self.selected_index
        self._position_base = 0.0
        self._position_started_at = None
        self._shuffle_queue.clear()
        self._shuffle_cursor = -1
        self._set_state("stopped")

    def toggle_repeat(self) -> None:
        self.repeat = not self.repeat

    def shuffle_all(self) -> bool:
        if not self.tracks:
            self.error = "There are no songs to shuffle."
            return False
        self._shuffle_queue = list(range(len(self.tracks)))
        self._random.shuffle(self._shuffle_queue)
        if (
            len(self._shuffle_queue) > 1
            and self.playing_index is not None
            and self._shuffle_queue[0] == self.playing_index
        ):
            self._shuffle_queue[0], self._shuffle_queue[1] = (
                self._shuffle_queue[1],
                self._shuffle_queue[0],
            )
        self._shuffle_cursor = 0
        self.selected_index = self._shuffle_queue[0]
        self._position_track_index = self.selected_index
        self._position_base = 0.0
        self._position_started_at = None
        return self._play_selected(preserve_shuffle=True, record_play=True)

    def toggle_favorite(self) -> bool:
        track = self.display_track
        if track is None:
            return False
        favorite = self.store.toggle_favorite(track.track_id)
        self.error = self.store.error
        return favorite

    def create_playlist(self, name: str) -> str | None:
        try:
            created = self.store.create_playlist(name)
        except (RuntimeError, ValueError) as exc:
            self.error = str(exc)
            return None
        self.error = self.store.error
        return created

    def delete_playlist(self, name: str) -> bool:
        deleted = self.store.delete_playlist(name)
        self.error = self.store.error
        return deleted

    def toggle_current_in_playlist(self, name: str) -> bool | None:
        track = self.display_track
        if track is None:
            return None
        try:
            included = self.store.toggle_playlist_track(name, track.track_id)
        except (RuntimeError, ValueError) as exc:
            self.error = str(exc)
            return None
        self.error = self.store.error
        return included

    def track_indices_for_ids(self, track_ids: list[str]) -> list[int]:
        return [
            self._index_by_id[track_id]
            for track_id in track_ids
            if track_id in self._index_by_id
        ]

    def poll(self) -> None:
        if self.state not in {"playing", "paused"} or self.backend.is_running():
            return
        finished_index = self.playing_index
        if finished_index is not None:
            self._position_track_index = finished_index
            self._position_base = self.tracks[finished_index].duration_seconds
            self._position_started_at = None
        if self.repeat and finished_index is not None:
            self.selected_index = finished_index
            self._position_base = 0.0
            self._play_selected(
                preserve_shuffle=self.shuffle_active,
                record_play=True,
                start_seconds=0.0,
            )
            return
        if self.shuffle_active and self._shuffle_cursor + 1 < len(self._shuffle_queue):
            self._shuffle_cursor += 1
            self.selected_index = self._shuffle_queue[self._shuffle_cursor]
            self._position_track_index = self.selected_index
            self._position_base = 0.0
            self._play_selected(
                preserve_shuffle=True,
                record_play=True,
                start_seconds=0.0,
            )
            return
        if self.shuffle_active and finished_index is not None:
            self._shuffle_queue = list(range(len(self.tracks)))
            self._random.shuffle(self._shuffle_queue)
            if len(self._shuffle_queue) > 1 and self._shuffle_queue[0] == finished_index:
                self._shuffle_queue[0], self._shuffle_queue[1] = (
                    self._shuffle_queue[1],
                    self._shuffle_queue[0],
                )
            self._shuffle_cursor = 0
            self.selected_index = self._shuffle_queue[0]
            self._position_track_index = self.selected_index
            self._position_base = 0.0
            self._play_selected(
                preserve_shuffle=True,
                record_play=True,
                start_seconds=0.0,
            )
            return
        if finished_index is not None and self.tracks:
            self.selected_index = (finished_index + 1) % len(self.tracks)
            self._position_track_index = self.selected_index
            self._position_base = 0.0
            self._play_selected(
                preserve_shuffle=False,
                record_play=True,
                start_seconds=0.0,
            )
            return
        self._set_state("stopped")

    def close(self) -> None:
        self.stop()


class MusicTool:
    """Register Music as an isolated menu-only feature."""

    action = "music"
    aliases: tuple[str, ...] = ()
    menu_only = True
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def __init__(
        self,
        config: MusicConfig,
        *,
        app_factory: MusicAppFactory = _create_music_app,
        backend_factory: Callable[[str], MusicPlaybackBackend] = FFplayBackend,
        face_animation_hook: FaceAnimationHook | None = None,
    ) -> None:
        self.config = config
        self.menu_item = MUSIC_MENU_ITEM
        self._app_factory = app_factory
        self._backend_factory = backend_factory
        self._face_animation_hook = face_animation_hook
        self._menu_ui: Any | None = None
        self._session: MusicSession | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        return ToolResult.invalid_action()

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        del user_text
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        if self._menu_ui is not None:
            return
        library = MusicLibrary(
            self.config.music_root,
            self.config.allowed_genres,
        )
        session = MusicSession(
            library.tracks(),
            self._backend_factory(self.config.player_command),
            store=MusicStore(self.config.state_path),
            face_animation_hook=self._face_animation_hook,
        )
        self._session = session

        def handle_close() -> None:
            if self._session is session:
                session.close()
                self._session = None
            self._menu_ui = None
            context.on_close()

        try:
            self._menu_ui = self._app_factory(
                context.master,
                session=session,
                face_provider=context.current_face,
                on_close=handle_close,
            )
        except Exception:
            session.close()
            self._session = None
            self._menu_ui = None
            context.on_close()
            raise

    def close(self) -> None:
        menu_ui = self._menu_ui
        if menu_ui is not None:
            menu_ui.close()
        elif self._session is not None:
            self._session.close()
            self._session = None


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register the configured Music feature and its playback lifecycle."""
    config = load_music_config(settings)
    if config.show_in_menu:
        registry.register(MusicTool(config))


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Contribute only validated Music menu metadata."""
    config = load_music_config(settings)
    if config.show_in_menu:
        registry.register(MUSIC_MENU_ITEM)


__all__ = [
    "FFplayBackend",
    "MUSIC_MENU_ITEM",
    "MusicLibrary",
    "MusicSession",
    "MusicStore",
    "MusicTool",
    "MusicTrack",
    "read_ogg_comments",
    "read_ogg_duration",
]
