---
id: plugin.album
type: plugin
plugin_type: feature
entrypoint: bmo.features.album
status: stable
tests: [tests/test_album.py, tests/test_qt_shell.py]
---

# Plugin: Album

## Purpose

Provide a menu-only contained photo browser with recoverable Wastebasket moves
and an optional generic BMO vision-analysis action.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration, discovery, containment, Trash | `bmo/features/album.py` |
| production adapter/QML | `bmo/qt/views/album.py`, `bmo/qt/qml/AlbumView.qml` |
| legacy UI | `bmo/ui/album.py` |
| configuration | feature settings in `config/features.json` |
| persistence | source photo tree; FreeDesktop Trash files/info |
| workers | none; vision is queued through runtime |

The menu-only `AlbumTool` has no voice/model action, alias, prompt, or
executable dispatch. `register_menu_metadata` is resource-free. Opening the
view recursively discovers only resolved regular images contained under
`photo_root`, presents bounded pages, and keeps the shared compact face as the
return control. Wastebasket revalidates containment and moves files into the
configured recoverable Trash layout. Analysis revalidates the image and calls
`FeatureMenuContext.request_vision`.

## Failure boundaries

Invalid/unreadable roots, image failures, Trash collisions, and unavailable
vision produce local empty/error/disabled states. The feature never receives
models, archives, or the application coordinator. Closing invalidates view
work and reveals the retained menu. Disabling/removing Album does not affect
camera capture or generic vision.

## Tests and interfaces

Primary: `tests/test_album.py`; shared Qt/menu coverage:
`tests/test_qt_shell.py`, `tests/test_menu_catalog.py`. Consumes
`FeatureMenuContext` and generic vision follow-up. Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
