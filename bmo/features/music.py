"""Menu-only local music library with Ogg metadata and ffplay playback."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
from typing import Any, Protocol

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
)
from bmo.features.music_config import MusicConfig, load_music_config
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

    def play(self, path: Path) -> None: ...

    def is_running(self) -> bool: ...

    def pause(self) -> bool: ...

    def resume(self) -> bool: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MusicTrack:
    """One playable track derived from Ogg comments, without track numbering."""

    path: Path
    title: str
    album: str
    artist: str
    genre: str
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
                    discovered.append(
                        MusicTrack(
                            path=resolved,
                            title=_first_comment(comments, "title", fallback_title),
                            album=_first_comment(
                                comments,
                                "album",
                                resolved.parent.name,
                            ),
                            artist=_first_comment(comments, "artist"),
                            genre=genres[0],
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

    def play(self, path: Path) -> None:
        resolved = Path(path).resolve(strict=True)
        if self.current_path == resolved and self.is_running():
            if self.paused:
                self.resume()
            return
        self.stop()
        self._process = self._popen(
            [
                self._executable(),
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                str(resolved),
            ],
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
    """Toolkit-neutral song selection, controls, repeat, and face hook."""

    def __init__(
        self,
        tracks: tuple[MusicTrack, ...],
        backend: MusicPlaybackBackend,
        *,
        face_animation_hook: FaceAnimationHook | None = None,
    ) -> None:
        self.tracks = tracks
        self.backend = backend
        self.selected_index: int | None = 0 if tracks else None
        self.playing_index: int | None = None
        self.state = "stopped"
        self.repeat = False
        self.error = ""
        self._face_animation_hook = face_animation_hook

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
    def signature(self) -> tuple[object, ...]:
        return (
            self.selected_index,
            self.playing_index,
            self.state,
            self.repeat,
            self.error,
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
        self.error = ""
        return True

    def play_selected(self) -> bool:
        track = self.selected_track
        if track is None:
            self.error = "No songs with the configured genre were found."
            return False
        try:
            self.backend.play(track.path)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.error = str(exc) or "BMO could not play that song."
            self._set_state("stopped")
            return False
        self.playing_index = self.selected_index
        self.error = ""
        self._set_state("playing")
        return True

    def pause_or_resume(self) -> bool:
        try:
            if self.state == "paused":
                changed = self.backend.resume()
                if changed:
                    self._set_state("playing")
            else:
                changed = self.backend.pause()
                if changed:
                    self._set_state("paused")
        except OSError as exc:
            self.error = str(exc) or "BMO could not pause that song."
            return False
        return changed

    def stop(self) -> None:
        self.backend.stop()
        self._set_state("stopped")

    def toggle_repeat(self) -> None:
        self.repeat = not self.repeat

    def poll(self) -> None:
        if self.state not in {"playing", "paused"} or self.backend.is_running():
            return
        if self.repeat and self.playing_index is not None:
            self.selected_index = self.playing_index
            self.play_selected()
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
    "MusicTool",
    "MusicTrack",
    "read_ogg_comments",
]
