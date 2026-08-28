---
id: plugin.galaxy_rvr
type: plugin
plugin_type: feature
entrypoint: bmo.features.galaxy_rvr
status: stable
tests: [tests/test_galaxy_rvr.py, tests/test_qt_shell.py]
---

# Plugin: GalaxyRVR

## Purpose

Provide a menu-only Bluetooth-gamepad remote for GalaxyRVR firmware, including
motor/servo control, telemetry, RGB, bounded camera preview, and snapshots.

## Ownership

| Area | Owner/path |
| --- | --- |
| protocol, joystick, controller session, registration | `bmo/features/galaxy_rvr.py` |
| private config | `bmo/features/galaxy_rvr_config.py` |
| production adapter/QML | `bmo/qt/views/galaxy_rvr.py`, `bmo/qt/qml/GalaxyRVRView.qml` |
| legacy UI | `bmo/ui/galaxy_rvr.py` |
| persistence | atomic photo snapshots only |
| resources | joystick fd, WebSocket, control worker, optional photo worker |

The feature has no voice/model route. Menu metadata is resource-free. Opening
creates one owned controller session: Linux `/dev/input/js*` polling maps
sticks/triggers/button to the firmware's dependency-free masked WebSocket
binary protocol, while HTTP `/capture` supplies size-bounded JPEGs/preview.
Status snapshots cross to the hosted view; controller/network loss commands a
safe motor stop.

## Configuration and lifecycle

`config/example.galaxy_rvr.json` owns LAN host/ports, controller mapping,
motion limits, servo behavior, timing/reconnect, photo root, request bounds,
preview, and visibility. No connection or device opens at import/metadata time.
View close sends a final stop, invalidates late callbacks, stops/joins workers,
closes socket and joystick, and leaves other plugins untouched. Connection,
controller, snapshot, and telemetry failures degrade only this view and remain
retryable where appropriate.

## Tests and interfaces

Primary: `tests/test_galaxy_rvr.py`; shared Qt/menu:
`tests/test_qt_shell.py`. Tests inject fake devices/transports and cover safe
stop/cleanup; physical controller/rover validation is target-only. Consumes
hosted-view contracts; exposes no cross-plugin API.

For continuation/status, read `progress.md`.
