---
id: plugin.capture_image
type: plugin
plugin_type: feature
entrypoint: bmo.features.capture_image
status: stable
tests: [tests/test_camera.py, tests/test_tool_presentation.py]
---

# Plugin: Capture Image

## Purpose

Capture a still image with Raspberry Pi camera tooling, archive it, optionally
copy it to a configured photo directory, and request a generic vision
follow-up.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration/camera command/validation | `bmo/features/capture_image.py` |
| archive allocation/status/vision result | shared feature contracts |
| configuration | feature settings plus shared `camera_rotation` |
| persistence | interaction image and optional atomic persistent copy |
| UI | global camera overlay/status; no plugin view |
| resources | bounded camera subprocess per execution |

`CaptureImageTool.execute(request, context)` uses only approved artifact,
event, and status methods from `ToolContext`. It selects supported Raspberry Pi
camera commands, enforces timeout and result existence, applies configured
rotation, and returns a typed image attachment with generic vision follow-up.
Persistent filenames are unique UTC values; copy failure is recorded but does
not discard the interaction image or its follow-up.

## Configuration and failure boundary

`save_directory` selects persistent copies; omission uses the documented local
Pictures default and `null` disables the copy. Disabling the feature prevents
module import and therefore contributes no subprocess route or prompt metadata.
Missing hardware, command failure, timeout, invalid image, rotation, and copy
errors remain typed feature outcomes and do not break other plugins.

## Tests and interfaces

Primary: `tests/test_camera.py`. Shared: `tests/test_tool_presentation.py`,
`tests/test_archive.py`, and routing tests. Consumes the generic vision
follow-up API documented under `agent_docs/shared/vision_follow_up.md`; exposes
no cross-plugin API.

For continuation/status, read `progress.md`.
