"""QML adapter for local Music selection, browsing, and playback."""

from __future__ import annotations

import base64
from collections import defaultdict
import json
from typing import Any

from PySide6.QtCore import QTimer, QUrl

from bmo.features.music import MusicSession, MusicTrack
from bmo.qt.views.base import QtHostedView


_GROUP_LABELS = {
    "albums": ("album", "Albums", "Unknown Album"),
    "artists": ("artist", "Artists", "Unknown Artist"),
    "series_groups": ("series", "Series", "Unknown Series"),
}
_BROWSE_ACTIONS = {
    "albums": "albums",
    "artists": "artists",
    "series": "series_groups",
    "songs": "songs",
    "recent": "recent",
    "most": "most",
    "favorites": "favorites",
    "playlists": "playlists",
}


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, remaining = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining:02d}"
    return f"{minutes}:{remaining:02d}"


class QtMusicView(QtHostedView):
    kind = "music"
    title = "Music"

    def __init__(
        self,
        host: Any,
        *,
        session: MusicSession,
        on_close: Any,
        face_provider: Any = None,
    ) -> None:
        del face_provider
        self.session = session
        self.browse_mode = "albums"
        self.group_value = ""
        self.active_playlist = ""
        self._browser_cache_revision = ""
        self._browser_cache: tuple[str, str, list[dict[str, object]]] | None = None
        self._last_signature = session.signature
        super().__init__(host, on_close=on_close)
        self._poll_timer = QTimer(host)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    @staticmethod
    def _artwork_source(track: MusicTrack | None) -> QUrl:
        if track is None or not track.artwork or not track.artwork_mime:
            return QUrl()
        encoded = base64.b64encode(track.artwork).decode("ascii")
        return QUrl(f"data:{track.artwork_mime};base64,{encoded}")

    def _track_item(self, index: int) -> dict[str, object]:
        track = self.session.tracks[index]
        return {
            "kind": "track",
            "trackIndex": index,
            "title": track.title,
            "album": track.album or "Unknown Album",
            "artist": track.artist,
            "series": track.series,
        }

    def _group_items(self, mode: str) -> list[dict[str, object]]:
        field, _label, unknown = _GROUP_LABELS[mode]
        grouped: dict[str, list[int]] = defaultdict(list)
        display_names: dict[str, str] = {}
        for index, track in enumerate(self.session.tracks):
            value = str(getattr(track, field) or unknown).strip() or unknown
            key = value.casefold()
            grouped[key].append(index)
            display_names.setdefault(key, value)
        return [
            {
                "kind": "group",
                "groupKind": field,
                "key": display_names[key],
                "title": display_names[key],
                "subtitle": f"{len(grouped[key])} song"
                + ("" if len(grouped[key]) == 1 else "s"),
            }
            for key in sorted(
                grouped,
                key=lambda item: display_names[item].casefold(),
            )
        ]

    def _indices_for_mode(self) -> list[int]:
        tracks = self.session.tracks
        if self.browse_mode in {"album", "artist", "series"}:
            unknown = {
                "album": "Unknown Album",
                "artist": "Unknown Artist",
                "series": "Unknown Series",
            }[self.browse_mode]
            indices = [
                index
                for index, track in enumerate(tracks)
                if (
                    str(getattr(track, self.browse_mode) or unknown).strip()
                    or unknown
                )
                == self.group_value
            ]
            return sorted(
                indices,
                key=lambda index: (
                    tracks[index].album.casefold(),
                    tracks[index].title.casefold(),
                ),
            )
        if self.browse_mode == "recent":
            return self.session.track_indices_for_ids(self.session.store.recent)
        if self.browse_mode == "most":
            return sorted(
                (
                    index
                    for index, track in enumerate(tracks)
                    if self.session.store.play_counts.get(track.track_id, 0) > 0
                ),
                key=lambda index: (
                    -self.session.store.play_counts.get(
                        tracks[index].track_id,
                        0,
                    ),
                    tracks[index].title.casefold(),
                ),
            )
        if self.browse_mode == "favorites":
            return sorted(
                self.session.track_indices_for_ids(
                    sorted(self.session.store.favorites)
                ),
                key=lambda index: (
                    tracks[index].album.casefold(),
                    tracks[index].title.casefold(),
                ),
            )
        if self.browse_mode == "playlist":
            return self.session.track_indices_for_ids(
                self.session.store.playlists.get(self.active_playlist, [])
            )
        return sorted(
            range(len(tracks)),
            key=lambda index: tracks[index].title.casefold(),
        )

    def _browser(self) -> tuple[str, str, list[dict[str, object]]]:
        if self.browse_mode in _GROUP_LABELS:
            _field, label, _unknown = _GROUP_LABELS[self.browse_mode]
            return "groups", label.upper(), self._group_items(self.browse_mode)
        if self.browse_mode == "playlists":
            items = [
                {
                    "kind": "playlist",
                    "key": name,
                    "title": name,
                    "subtitle": f"{len(track_ids)} song"
                    + ("" if len(track_ids) == 1 else "s"),
                }
                for name, track_ids in self.session.store.playlists.items()
            ]
            return "playlists", "PLAYLISTS", items
        title = {
            "album": self.group_value,
            "artist": self.group_value,
            "series": self.group_value,
            "recent": "RECENTLY PLAYED",
            "most": "MOST PLAYED",
            "favorites": "FAVORITES",
            "playlist": self.active_playlist,
            "songs": "ALL SONGS",
        }.get(self.browse_mode, "SONGS")
        return (
            "tracks",
            title,
            [self._track_item(index) for index in self._indices_for_mode()],
        )

    def _browser_revision(self) -> str:
        store_revision = (
            self.session.store.revision
            if self.browse_mode
            in {"recent", "most", "favorites", "playlists", "playlist"}
            else 0
        )
        return ":".join(
            (
                self.browse_mode,
                self.group_value,
                self.active_playlist,
                str(store_revision),
            )
        )

    def _cached_browser(
        self,
        revision: str,
    ) -> tuple[str, str, list[dict[str, object]]]:
        if (
            getattr(self, "_browser_cache_revision", "") != revision
            or getattr(self, "_browser_cache", None) is None
        ):
            self._browser_cache_revision = revision
            self._browser_cache = self._browser()
        return self._browser_cache

    def payload(self) -> dict[str, object]:
        display_track = self.session.display_track
        selected_index = self.session.selected_index
        playing_index = self.session.playing_index
        browser_revision = self._browser_revision()
        browser_kind, browser_title, browser_items = self._cached_browser(
            browser_revision
        )
        if self.session.error:
            status = self.session.error
        elif not self.session.tracks:
            status = "No songs tagged for this music player were found."
        elif self.session.state == "playing":
            status = "NOW PLAYING"
        elif self.session.state == "paused":
            status = "PAUSED"
        else:
            status = "Pick a song, then tap PLAY!"
        position = self.session.position_seconds
        duration = self.session.duration_seconds
        display_id = display_track.track_id if display_track is not None else ""
        playlist_tracks = self.session.store.playlists.get(
            self.active_playlist,
            [],
        )
        active_chip = {
            "album": "albums",
            "artist": "artists",
            "series": "series",
            "series_groups": "series",
            "playlist": "playlists",
        }.get(self.browse_mode, self.browse_mode)
        return {
            "browserKind": browser_kind,
            "browserTitle": browser_title,
            "browserItems": browser_items,
            "browserRevision": browser_revision,
            "activeChip": active_chip,
            "trackCount": len(self.session.tracks),
            "selectedIndex": selected_index if selected_index is not None else -1,
            "playingIndex": playing_index if playing_index is not None else -1,
            "title": (
                display_track.title if display_track is not None else "Music Time!"
            ),
            "album": display_track.album if display_track is not None else "",
            "artist": display_track.artist if display_track is not None else "",
            "series": display_track.series if display_track is not None else "",
            "artworkSource": self._artwork_source(display_track),
            "status": status,
            "state": self.session.state,
            "canPlay": selected_index is not None,
            "canPause": self.session.state in {"playing", "paused"},
            "canSeek": duration > 0.0,
            "position": position,
            "duration": duration,
            "positionLabel": _format_time(position),
            "durationLabel": _format_time(duration),
            "repeat": self.session.repeat,
            "shuffle": self.session.shuffle_active,
            "favorite": display_id in self.session.store.favorites,
            "activePlaylist": self.active_playlist,
            "viewingPlaylist": self.browse_mode == "playlist",
            "playlistContainsCurrent": bool(display_id)
            and display_id in playlist_tracks,
            "libraryReadOnly": self.session.store.read_only,
        }

    def handle_action(self, action: str, value: str) -> None:
        if action == "music_select":
            try:
                index = int(value)
            except (TypeError, ValueError):
                self.session.error = "That song is no longer available."
            else:
                self.session.select(index)
        elif action == "music_play":
            self.session.play_selected()
        elif action == "music_pause":
            self.session.pause_or_resume()
        elif action == "music_stop":
            self.session.stop()
        elif action == "music_repeat":
            self.session.toggle_repeat()
        elif action == "music_shuffle":
            self.session.shuffle_all()
        elif action == "music_seek":
            try:
                self.session.seek(float(value))
            except ValueError:
                self.session.error = "That song position is not valid."
        elif action == "music_favorite":
            self.session.toggle_favorite()
        elif action == "music_browse":
            browse_mode = _BROWSE_ACTIONS.get(value)
            if browse_mode is not None:
                self.browse_mode = browse_mode
                self.group_value = ""
        elif action == "music_open_group":
            try:
                request = json.loads(value)
                group_kind = str(request["kind"])
                group_value = str(request["value"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.session.error = "That music group is no longer available."
            else:
                if group_kind in {"album", "artist", "series"} and group_value:
                    self.browse_mode = group_kind
                    self.group_value = group_value
        elif action == "music_open_playlist":
            if value in self.session.store.playlists:
                self.browse_mode = "playlist"
                self.active_playlist = value
        elif action == "music_create_playlist":
            created = self.session.create_playlist(value)
            if created is not None:
                self.browse_mode = "playlist"
                self.active_playlist = created
        elif action == "music_delete_playlist":
            if (
                self.active_playlist
                and self.session.delete_playlist(self.active_playlist)
            ):
                self.active_playlist = ""
                self.browse_mode = "playlists"
        elif action == "music_playlist_track":
            if self.active_playlist:
                self.session.toggle_current_in_playlist(self.active_playlist)
        else:
            super().handle_action(action, value)
            return
        self._last_signature = self.session.signature
        self.refresh()

    def _poll(self) -> None:
        self.session.poll()
        signature = self.session.signature
        if signature != self._last_signature:
            self._last_signature = signature
            self.refresh()

    def close(self) -> None:
        timer = getattr(self, "_poll_timer", None)
        if timer is not None:
            timer.stop()
        self.session.close()
        super().close()


__all__ = ["QtMusicView"]
