"""Private atomic persistence for Music history, favorites, and playlists."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bmo.jsonio import atomic_write_json, load_json


MUSIC_STORE_VERSION = 1
MAX_STORE_BYTES = 2 * 1024 * 1024
MAX_RECENT_TRACKS = 50
MAX_PLAYLISTS = 50
MAX_PLAYLIST_TRACKS = 5_000
MAX_TRACK_ID_LENGTH = 2_048
MAX_PLAYLIST_NAME_LENGTH = 32


class MusicStore:
    """Own Music usage data without exposing it to conversation history."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path).expanduser() if path is not None else None
        self.favorites: set[str] = set()
        self.play_counts: dict[str, int] = {}
        self.recent: list[str] = []
        self.playlists: dict[str, list[str]] = {}
        self.read_only = False
        self.error = ""
        self.revision = 0
        self._load()

    @staticmethod
    def _track_id(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("music track identifiers must be non-empty strings")
        normalized = value.strip()
        if len(normalized) > MAX_TRACK_ID_LENGTH or "\x00" in normalized:
            raise ValueError("music track identifier is invalid")
        return normalized

    @staticmethod
    def _playlist_name(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("playlist name cannot be empty")
        normalized = " ".join(value.strip().split())
        if len(normalized) > MAX_PLAYLIST_NAME_LENGTH or "\x00" in normalized:
            raise ValueError(
                f"playlist name must be at most {MAX_PLAYLIST_NAME_LENGTH} characters"
            )
        return normalized

    @classmethod
    def _track_list(cls, value: object, *, limit: int) -> list[str]:
        if not isinstance(value, list) or len(value) > limit:
            raise ValueError("music track list is invalid")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            track_id = cls._track_id(item)
            if track_id not in seen:
                result.append(track_id)
                seen.add(track_id)
        return result

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            if self.path.stat().st_size > MAX_STORE_BYTES:
                raise ValueError("music library state is too large")
            with self.path.open("r", encoding="utf-8") as handle:
                raw = load_json(handle)
            if not isinstance(raw, Mapping) or raw.get("version") != MUSIC_STORE_VERSION:
                raise ValueError("unsupported music library state version")
            unknown = set(raw).difference(
                {"version", "favorites", "play_counts", "recent", "playlists"}
            )
            if unknown:
                raise ValueError("music library state has unknown fields")
            favorites = set(
                self._track_list(
                    raw.get("favorites", []),
                    limit=MAX_PLAYLIST_TRACKS,
                )
            )
            recent = self._track_list(raw.get("recent", []), limit=MAX_RECENT_TRACKS)
            counts_raw = raw.get("play_counts", {})
            if (
                not isinstance(counts_raw, Mapping)
                or len(counts_raw) > MAX_PLAYLIST_TRACKS
            ):
                raise ValueError("music play counts are invalid")
            counts: dict[str, int] = {}
            for raw_id, raw_count in counts_raw.items():
                track_id = self._track_id(raw_id)
                if isinstance(raw_count, bool) or not isinstance(raw_count, int):
                    raise ValueError("music play count must be an integer")
                if not 0 <= raw_count <= 2_147_483_647:
                    raise ValueError("music play count is out of range")
                if raw_count:
                    counts[track_id] = raw_count
            playlists_raw = raw.get("playlists", {})
            if (
                not isinstance(playlists_raw, Mapping)
                or len(playlists_raw) > MAX_PLAYLISTS
            ):
                raise ValueError("music playlists are invalid")
            playlists: dict[str, list[str]] = {}
            normalized_names: set[str] = set()
            for raw_name, raw_tracks in playlists_raw.items():
                name = self._playlist_name(raw_name)
                if name.casefold() in normalized_names:
                    raise ValueError("music playlist names must be unique")
                normalized_names.add(name.casefold())
                playlists[name] = self._track_list(
                    raw_tracks,
                    limit=MAX_PLAYLIST_TRACKS,
                )
            self.favorites = favorites
            self.play_counts = counts
            self.recent = recent
            self.playlists = playlists
        except (OSError, TypeError, ValueError) as exc:
            self.read_only = True
            self.error = (
                "Music history is read-only because its saved data could not "
                f"be loaded ({type(exc).__name__})."
            )

    def _payload(self) -> dict[str, object]:
        return {
            "version": MUSIC_STORE_VERSION,
            "favorites": sorted(self.favorites),
            "play_counts": dict(sorted(self.play_counts.items())),
            "recent": list(self.recent),
            "playlists": {
                name: list(track_ids)
                for name, track_ids in self.playlists.items()
            },
        }

    def _save(self) -> bool:
        if self.path is None:
            self.revision += 1
            return True
        if self.read_only:
            return False
        try:
            atomic_write_json(self.path, self._payload())
        except OSError as exc:
            self.error = f"Music could not save library changes ({type(exc).__name__})."
            return False
        self.error = ""
        self.revision += 1
        return True

    def record_play(self, track_id: str) -> bool:
        if self.read_only:
            return False
        normalized = self._track_id(track_id)
        self.play_counts[normalized] = self.play_counts.get(normalized, 0) + 1
        self.recent = [item for item in self.recent if item != normalized]
        self.recent.insert(0, normalized)
        del self.recent[MAX_RECENT_TRACKS:]
        return self._save()

    def toggle_favorite(self, track_id: str) -> bool:
        normalized = self._track_id(track_id)
        if self.read_only:
            return normalized in self.favorites
        if normalized in self.favorites:
            self.favorites.remove(normalized)
        else:
            self.favorites.add(normalized)
        self._save()
        return normalized in self.favorites

    def create_playlist(self, name: str) -> str:
        if self.read_only:
            raise RuntimeError(self.error or "Music history is read-only.")
        normalized = self._playlist_name(name)
        if any(
            existing.casefold() == normalized.casefold()
            for existing in self.playlists
        ):
            raise ValueError("A playlist with that name already exists.")
        if len(self.playlists) >= MAX_PLAYLISTS:
            raise ValueError("The playlist limit has been reached.")
        self.playlists[normalized] = []
        self._save()
        return normalized

    def delete_playlist(self, name: str) -> bool:
        if self.read_only:
            return False
        if name not in self.playlists:
            return False
        del self.playlists[name]
        return self._save()

    def toggle_playlist_track(self, name: str, track_id: str) -> bool:
        if self.read_only:
            raise RuntimeError(self.error or "Music history is read-only.")
        if name not in self.playlists:
            raise ValueError("That playlist is no longer available.")
        normalized = self._track_id(track_id)
        tracks = self.playlists[name]
        if normalized in tracks:
            tracks.remove(normalized)
            included = False
        else:
            if len(tracks) >= MAX_PLAYLIST_TRACKS:
                raise ValueError("That playlist is full.")
            tracks.append(normalized)
            included = True
        self._save()
        return included


__all__ = ["MUSIC_STORE_VERSION", "MusicStore"]
