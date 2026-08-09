# Architecture

The application keeps `agent.py` as the stable startup command while implementation lives in the `bmo` package.

## Module boundaries

- `bmo.app` — Tkinter UI and top-level interaction workflow.
- `bmo.audio` — audio-device discovery, microphone recording, sound effects, and Piper playback.
- `bmo.speech` — OpenWakeWord detection, Whisper transcription, and action-JSON extraction.
- `bmo.tools` — stable compatibility router over the enabled feature registry.
- `bmo.features` — typed contracts, lazy loading, and registry-backed dispatch.
- `bmo.features.camera` — Raspberry Pi still capture and configured rotation.
- `bmo.features.loader` — standard-library module loading from `features` config.
- `bmo.features.get_time` — current-time action, alias, and direct phrases.
- `bmo.features.get_location` — configured-location action and failure handling.
- `bmo.features.get_weather` — weather action, place cleanup, and failures.
- `bmo.features.search_web` — web-search action, formatting, and archive details.
- `bmo.features.capture_image` — camera request metadata and UI capture signal.
- `bmo.features.set_timer` — natural durations and a single condition-driven
  priority-queue scheduler for all active timers.
- `bmo.modes` — typed lifecycle contracts and exclusive input ownership for
  long-lived interactions.
- `bmo.modes.games` — adapters for Twenty Questions and the Pup Pairs UI.
- `bmo.memory` — conversation-history loading and atomic persistence.
- `bmo.archive` — append-only, per-interaction artifacts and event metadata.
- `bmo.config` — defaults, paths, Ollama options, and JSON loading.
- `bmo.prompts` — system-prompt construction.
- `bmo.state` — shared UI/application states.

## Runtime flow

1. `agent.py` creates Tkinter and `BotGUI`.
2. `BotGUI` loads enabled feature modules, constructs the two built-in modes,
   and creates services using defaults overlaid by `config.json`. A missing
   config file is not created; defaults remain in memory only.
3. The wake-word service waits for wake word or push-to-talk.
4. A unique dated interaction archive is created.
5. The recorder captures a WAV directly into that archive.
6. Whisper transcribes the WAV and retains its raw stdout/stderr.
7. Ollama produces either normal text or an allowlisted tool request; requests and typed tool results are logged and processed through the same presentation path as direct actions.
8. Tool calls, full web results, and camera images are stored under the same interaction.
9. Piper streams speech through `sounddevice` while also writing archival WAVs.
10. Shutdown stops audio, saves recent memory atomically, unloads the text model, and closes Tkinter.

## Platform behavior

The same Python entry point is used on macOS and Raspberry Pi.

- Piper uses `./piper/piper` when the bundled Pi binary exists.
- Otherwise Piper runs through the active environment with `python -m piper`.
- Whisper paths can be overridden with `whisper_binary` and `whisper_model` in `config.json`.
- Raspberry Pi camera execution and rotation live in `bmo.features.camera`.
  `BotGUI.capture_image()` retains UI-state and interaction-archive coordination,
  while action aliases, matching, and prompt metadata live in
  `bmo.features.capture_image`.

## Extension contracts

Features and modes solve different routing problems:

| Extension | Lifetime | Selection | Input ownership |
| --- | --- | --- | --- |
| Feature tool | One action request | Enabled module list, direct matcher, or model-produced action JSON | Does not retain it |
| Interaction mode | Multiple turns or a dedicated UI | First registered mode whose start matcher succeeds | Exclusive until `is_active()` is false |

### Feature module contract

`features` is an ordered list. Omitting the key loads the six modules in
`DEFAULT_FEATURE_MODULES`; providing the key replaces that default list. Each
entry supports:

- `module`: a non-empty importable Python module name.
- `enabled`: a JSON boolean, defaulting to `true`. A false entry is skipped
  before `module` or `settings` validation and before import.
- `settings`: an object, defaulting to `{}`. During application loading, these
  values override shared top-level configuration before the module hook runs.

Every enabled module must expose a callable `register(registry, settings)`.
That hook registers one or more objects satisfying the structural `Tool`
contract in `bmo.features.contracts`:

- `action` is the unique canonical identifier; `aliases` contains unique
  alternate identifiers. The registry normalizes both to stripped lowercase.
- `description`, `schemas`, `prompt_guidance`, and `prompt_examples` describe
  the capability to the routing and system prompts.
- `execute(request)` returns a `ToolResult`, never a bare string. Its kind tells
  the application whether it contains content, is empty, failed, falls back to
  chat, or requests camera capture.
- `match_direct_action(user_text)` returns action data only for deterministic,
  unambiguous phrases. `normalize_request(request)`,
  `prepare_model_request(request)`, and `close()` are optional hooks for
  request cleanup, model-route validation, and resource ownership. Returning
  `None` from `prepare_model_request` rejects that model-produced request.
- A background feature sends `RuntimeNotification` values through
  `registry.notify_runtime`; it must stop its workers in `close()`.

Registration order controls prompt order and the first matching direct action.
Only successfully registered tools appear in prompts or dispatch. The
compatibility router rejects unregistered actions, so disabling a feature also
removes its aliases, direct phrases, prompt metadata, and execution path.

### Mode contract

An `InteractionMode` has a unique normalized `name` and implements
`matches_start_request`, `start`, `handle_input`, `is_active`, `input_policy`,
and `close`. With no active mode, the registry checks start matchers in
registration order. After a mode starts, every subsequent transcript goes to
that mode until `is_active()` becomes false; another mode cannot start in the
meantime.

The mode's `InputPolicy` selects one of three main-loop behaviors:

- `WAKE_WORD`: normal one-shot wake-word or push-to-talk input.
- `CONTINUOUS`: record another turn without requiring a wake word, using the
  mode's timeout, status messages, and archive trigger source.
- `SUSPENDED`: pause speech capture while a separate UI owns interaction.

The two game modes are constructed directly in `BotGUI`. They are always
registered and are active only after their start matcher succeeds. There is no
configuration-driven mode loader, so a `modes` key in `config.json` or
`example.config.json` would currently have no effect.

### Enable, disable, and failure isolation

Feature isolation is intentionally strongest during startup. A malformed
`features` value produces an empty registry and a reported configuration
failure. For individual enabled entries, configuration, import, missing-hook,
and hook exceptions are reported and skipped while later entries continue.
Registration is transactional: if a hook registers a tool and then fails (for
example, on a duplicate action), all registrations from that hook are rolled
back without disturbing earlier modules. Disabled entries produce no failure
because they are not validated or imported.

Execution is a separate boundary. The registry validates that handlers return
`ToolResult`, but it does not swallow handler or mode lifecycle exceptions.
Feature execution failures propagate to `BotGUI`, which records the failed
tool call when interaction logging is enabled before its normal interaction
error handling runs. If a mode's `start` raises, the registry releases input
ownership and re-raises; exceptions from other mode methods also propagate to
the caller. On application shutdown, feature and mode `close()` methods run in
reverse registration order, and one close failure is reported without
preventing the remaining resources from closing.

### Add a feature

1. Create a module under `bmo/features/` with a tool and
   `register(registry, settings)` hook. Keep imports free of side effects;
   allocate threads, devices, or clients during registration or first use.
2. Give every action and alias a globally unique name. Return a typed
   `ToolResult` for every normal outcome, and reserve exceptions for unexpected
   failures that should reach the application error boundary.
3. Add the module to the `features` list in local configuration. Add it to
   `DEFAULT_FEATURE_MODULES` only if it should load when `features` is omitted,
   and keep `example.config.json` synchronized for a new built-in default.
4. Add focused tests for registration, settings, routing metadata, direct
   matching, result kinds, failure behavior, and cleanup as applicable. Run
   the focused tests and then the full suite with `.venv/bin/python -m pytest -q`.

This minimal feature has no resources to close. Save it as
`bmo/features/say_hello.py`:

```python
from collections.abc import Mapping
from typing import Any

from bmo.features import (
    ToolContract,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    greeting = str(settings.get("greeting", "Hello!"))

    def execute(request: ToolRequest) -> ToolResult:
        del request
        return ToolResult.success(greeting)

    def match_direct(user_text: str):
        if normalize_direct_text(user_text) == "say hello":
            return {"action": "say_hello"}
        return None

    registry.register(
        ToolContract(
            action="say_hello",
            aliases=("hello",),
            description="Say a configured greeting.",
            schemas=('{"action":"say_hello"}',),
            prompt_examples=(("Say hello.", '{"action":"say_hello"}'),),
            handler=execute,
            direct_matcher=match_direct,
        )
    )
```

The disabled `bmo.features.say_hello` entry in `example.config.json` is safe to
leave in place because disabled modules are never imported. After creating the
module, copy the example to `config.json` if needed and set that entry's
`enabled` value to `true`.

## Next extraction

The current `BotGUI` still combines presentation and conversation orchestration. The next safe step is to move widget/animation behavior into `bmo.ui` and move Ollama streaming/tool-response handling into `bmo.conversation`, after this extraction has been verified on both macOS and Raspberry Pi.

## Shutdown ownership

Audio streams are closed cooperatively by the thread that created them. The UI shutdown path sets a shared event, wakes any push-to-talk wait, joins the interaction and TTS threads, and then exits Tkinter. It deliberately does not call process-wide `sounddevice.stop()` while another thread owns an input stream; doing so can crash Core Audio on macOS.
