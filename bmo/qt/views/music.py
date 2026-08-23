"""QML adapter for local Music selection and playback."""

from __future__ import annotations

import base64
from typing import Any

from PySide6.QtCore import QTimer, QUrl

from bmo.features.music import MusicSession, MusicTrack
from bmo.qt.views.base import QtHostedView


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

    def payload(self) -> dict[str, object]:
        display_track = self.session.display_track
        selected_index = self.session.selected_index
        playing_index = self.session.playing_index
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
        return {
            "tracks": [
                {
                    "index": index,
                    "title": track.title,
                    "album": track.album,
                    "artist": track.artist,
                    "selected": index == selected_index,
                    "playing": index == playing_index
                    and self.session.state in {"playing", "paused"},
                }
                for index, track in enumerate(self.session.tracks)
            ],
            "trackCount": len(self.session.tracks),
            "selectedIndex": selected_index if selected_index is not None else -1,
            "playingIndex": playing_index if playing_index is not None else -1,
            "title": display_track.title if display_track is not None else "Music Time!",
            "album": display_track.album if display_track is not None else "",
            "artist": display_track.artist if display_track is not None else "",
            "artworkSource": self._artwork_source(display_track),
            "status": status,
            "state": self.session.state,
            "canPlay": selected_index is not None,
            "canPause": self.session.state in {"playing", "paused"},
            "repeat": self.session.repeat,
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
