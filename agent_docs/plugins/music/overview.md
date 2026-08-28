---
id: plugin.music
type: plugin
plugin_type: feature
entrypoint: bmo.features.music
status: stable
tests: [tests/test_music.py, tests/test_qt_shell.py]
---

# Plugin: Music

## Purpose

Provide a menu-only contained Ogg/Opus music library, metadata browsing,
favorites/playlists/history, and continuous or shuffled `ffplay` playback.

## Ownership

| Area | Owner/path |
| --- | --- |
| discovery, metadata, player/session, registration | `bmo/features/music.py` |
| private config | `bmo/features/music_config.py` |
| state persistence | `bmo/features/music_store.py` |
| production adapter/QML | `bmo/qt/views/music.py`, `bmo/qt/qml/MusicView.qml` |
| legacy UI | `bmo/ui/music.py` |
| background resource | one owned `ffplay` subprocess while playing |

The menu-only tool has no voice/model action or aliases. Resource-free menu
metadata reads only visibility. Opening discovers resolved regular Ogg/Opus
files contained by `music_root`, admits only allowed normalized metadata
genres, and parses duration, title, album, artist, series, and embedded artwork
with project code. Track identity is library-relative so state survives moving
the root.

## Configuration, persistence, and lifecycle

`config/example.music.json` owns root, allowed genres, visibility, player
command, and state path. Atomic state stores recent/most-played counts,
favorites, and named playlists. Invalid state becomes visible read-only rather
than overwritten. Production QML owns grouped collections, stable scrolling,
artwork/marquees, seeking, repeat, and whole-library shuffle.

Playback starts one headless auto-exiting child. Stop, face close, view close,
feature cleanup, and application shutdown terminate it. Repeat and queue
advancement are session-owned. Missing player/media or parse errors remain
local and do not prevent the plugin or app from loading.

## Tests and interfaces

Primary: `tests/test_music.py`; shared Qt/menu:
`tests/test_qt_shell.py`. Consumes atomic JSON and hosted-view contracts.
Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
