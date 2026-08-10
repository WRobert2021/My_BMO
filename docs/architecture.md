# Architecture

The application keeps `agent.py` as the stable startup command while implementation lives in the `bmo` package.

## Module boundaries

- `bmo.app` — Tkinter UI and top-level interaction workflow.
- `bmo.audio` — audio-device discovery, microphone recording, sound effects, and Piper playback.
- `bmo.speech` — OpenWakeWord detection, Whisper transcription, and action-JSON extraction.
- `bmo.tools` — stable compatibility router over the enabled feature registry.
- `bmo.features` — typed contracts, lazy loading, and registry-backed dispatch.
- `bmo.features.loader` — standard-library module loading from `features` config.
- `bmo.features.get_time` — current-time action, alias, and direct phrases.
- `bmo.features.get_location` — configured-location action and failure handling.
- `bmo.features.get_weather` — weather action, place cleanup, and failures.
- `bmo.features.search_web` — web-search action, formatting, and archive details.
- `bmo.features.capture_image` — configured camera routing, Raspberry Pi still
  capture, rotation, event recording, and vision follow-up results.
- `bmo.features.set_timer` — natural durations and a single condition-driven
  priority-queue scheduler for all active timers.
- `bmo.modes` — typed lifecycle contracts and exclusive input ownership for
  long-lived interactions.
- `bmo.modes.loader` — standard-library module loading from `modes` config.
- `bmo.modes.matching_game` — Pup Pairs lifecycle and registration adapter.
- `bmo.modes.twenty_questions` — Twenty Questions lifecycle and registration
  adapter over the existing Bayesian engine.
- `bmo.modes.games` — compatibility imports for the two built-in adapters.
- `bmo.memory` — conversation-history loading and atomic persistence.
- `bmo.archive` — append-only, per-interaction artifacts and event metadata.
- `bmo.config` — defaults, paths, Ollama options, and JSON loading.
- `bmo.prompts` — system-prompt construction.
- `bmo.state` — shared UI/application states.

## Runtime flow

1. `agent.py` creates Tkinter and `BotGUI`.
2. `BotGUI` creates services using defaults overlaid by
   `config/settings.json`, then loads feature and mode wiring from
   `config/features.json`. Missing config files are not created; defaults remain
   in memory only.
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
- Whisper paths can be overridden with `whisper_binary` and `whisper_model` in
  `config/settings.json`.
- Raspberry Pi camera matching, execution, timeout, configured rotation, and
  result ownership all live in the optional `bmo.features.capture_image`
  module. When disabled, that module is never imported and contributes no
  prompt metadata, direct matcher, or subprocess path.
- The application supplies a fresh `ToolContext` for each execution. It exposes
  only approved artifact allocation, structured interaction events, and generic
  UI status requests; features never receive `BotGUI` or an archive object.
- Mode registration receives one frozen `ModeRuntimeContext` exposing only the
  Tk master, text model and chat callback, speech and memory callbacks, state
  updates, announcements, and the current-face provider. Modes never receive
  `BotGUI` itself.

## Extension contracts

Features and modes solve different routing problems:

| Extension | Lifetime | Selection | Input ownership |
| --- | --- | --- | --- |
| Feature tool | One action request | Enabled module list, direct matcher, or model-produced action JSON | Does not retain it |
| Interaction mode | Multiple turns or a dedicated UI | Enabled module list, then first registered start matcher | Exclusive until `is_active()` is false |

### Feature module contract

The `features` list lives in `config/features.json`. Omitting the key loads the
six modules in `DEFAULT_FEATURE_MODULES`; providing the key replaces that
default list. Each entry supports:

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
- `execute(request)` returns a `ToolResult`, never a bare string. Its kind
  records the semantic outcome: content, an expected empty/error result, chat
  fallback, invalid action, a typed attachment, or a generic follow-up.
- Tools that need runtime services opt in with `uses_context = True` and receive
  `execute(request, context)`. The registry leaves ordinary one-argument tools
  unchanged. Image attachments and vision follow-ups are core contracts, so
  presentation and vision routing never inspect the producing feature's action.
- Each result carries `ToolPresentation` metadata. A feature can mark content
  as user-ready or provide local-model summary prompts, including distinct
  direct-match and model-routed policies when compatibility requires them.
  Expected empty and error outcomes carry their own user-facing text, so an
  offline search and a failed local hardware sensor do not share an error
  message.
- Each result also carries `ToolArchive` metadata. The category, JSONL
  filename, and optional structured details determine archival without UI code
  knowing which action produced the result. Ordinary results default to
  `output/tools.jsonl`; web search selects `web/searches.jsonl` and attaches its
  query and raw result/error details.
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

The importable `tests.extension_modules.proof_feature` fixture is the
end-to-end contract proof. A single enabled config entry supplies its custom
settings and makes its action, alias, schema, direct matcher, string and numeric
model parameters, request normalization, direct presentation, expected error,
and cleanup hook available. Disabling that same entry removes every surface and
does not import the module. Nothing in `bmo.tools`, `bmo.intent`, `bmo.prompts`,
`bmo.app`, or either package export table names the fixture.

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

The `modes` list also lives in `config/features.json` and has the same allowlist
semantics as `features`. Omitting it loads `bmo.modes.matching_game` followed
by `bmo.modes.twenty_questions`, preserving the historical matching order.
Providing the key replaces those defaults; an empty list disables every mode.
Each entry supports:

- `module`: a non-empty importable Python module name.
- `enabled`: a JSON boolean, defaulting to `true`. A false entry is skipped
  before its module name or settings are validated and before import.
- `settings`: an object, defaulting to `{}`. Per-mode values override shared
  application settings. The Twenty Questions adapter accepts
  `answer_wait_seconds` and `debug`, while retaining the historical top-level
  setting names as fallbacks.

An enabled mode module exposes `register(registry, context, settings)`. The
context must be `ModeRuntimeContext`; it deliberately exposes approved services
rather than the entire GUI coordinator. Registration order controls the first
matching start request. The built-in modules construct the existing adapters,
and the matching UI and Bayesian Twenty Questions engine remain responsible for
their existing score, history, and learning behavior.

The importable `tests.extension_modules.proof_mode` fixture proves the same
configuration-only boundary for modes. Its enabled entry registers start
matching, active input ownership, configured input policy, and cleanup; its
disabled entry is ignored before validation or import.

### Enable, disable, and failure isolation

Feature and mode isolation is intentionally strongest during startup. A
malformed top-level list produces an empty corresponding registry and a reported
configuration failure. For individual enabled entries, configuration, import,
missing-hook, and hook exceptions are reported and skipped while later entries
continue. Registration is transactional: if a hook partially registers and
then fails on an exception or duplicate name, its additions are rolled back
without disturbing earlier modules. Rolled-back tools and modes are closed
immediately.
Disabled entries produce no failure because they are not validated or imported.
Consequently, malformed or disabled extension entries cannot prevent valid
built-in entries later in the same explicit list from registering. Supplying a
`features` or `modes` list still replaces the omitted-key defaults, so an
explicit list must include whichever built-ins should remain enabled.

Execution is a separate boundary. The registry validates the optional
`ToolContext`, passes it only to tools that opt in, and validates that handlers
return `ToolResult`, but it does not swallow handler or mode lifecycle
exceptions.
Feature execution failures propagate to `BotGUI`, which records the failed
tool call when interaction logging is enabled before its normal interaction
error handling runs. Once startup has completed, each voice or typed turn has
its own failure boundary: an unexpected tool or mode failure ends only that
interaction, presents a generic retry message, and leaves the main loop ready
for another request. A failing mode lifecycle callback releases input
ownership, closes and quarantines that mode for the rest of the process, then
re-raises the original exception. On application shutdown, feature and mode
`close()` methods run in reverse registration order, and one close failure is
reported without preventing the remaining resources from closing.

### Add a feature

The exact minimal workflow for an optional feature is:

1. **Create module:** add an importable module with a tool and
   `register(registry, settings)` hook. Keep imports free of side effects;
   allocate threads, devices, or clients during registration or first use.
   Give each action and alias a globally unique name and return a typed
   `ToolResult` for every expected outcome.
2. **Add config entry:** add its module name, enabled boolean, and settings to
   the local `features` list. No edit to `tools.py`, `intent.py`, `prompts.py`,
   `app.py`, or `bmo.features.__init__` is required. Edit
   `DEFAULT_FEATURE_MODULES` only when deliberately adding a built-in that must
   load when the key is omitted; keep `config/example.features.json`
   synchronized then.
3. **Add tests:** cover registration, settings, model and direct routing,
   normalization, presentation/result kinds, expected failures, disablement,
   and cleanup as applicable. Run focused tests and
   `.venv/bin/python -m pytest -q`.
4. **Restart:** restart the agent so it reloads configuration and imports the
   newly enabled module.

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
        return ToolResult.direct(greeting)

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

The disabled `bmo.features.say_hello` entry in
`config/example.features.json` is safe to
leave in place because disabled modules are never imported. After creating the
module, copy the example to `config/features.json` if needed and set that
entry's `enabled` value to `true`.

### Add a mode

The exact minimal workflow for an optional mode is:

1. **Create module:** implement `InteractionMode` without import-time workers
   or UI creation, then expose `register(registry, context, settings)`. Construct
   it only from `ModeRuntimeContext` and settings; do not retain `BotGUI`.
2. **Add config entry:** add the importable module to the local `modes` list.
   No edit to `app.py`, the mode registry, or `bmo.modes.__init__` is required.
   Edit `DEFAULT_MODE_MODULES` only when deliberately adding an omitted-key
   built-in default.
3. **Add tests:** cover enable/disable import behavior, settings, registration
   rollback, start matching, active input routing, `InputPolicy`, and idempotent
   cleanup. Run focused tests and `.venv/bin/python -m pytest -q`.
4. **Restart:** restart the agent so it reloads configuration and imports the
   newly enabled module.

### Intentional runtime coupling

An identifier-literal audit covers `bmo.app`, `bmo.intent`, `bmo.prompts`, and
both registries. Those routing and presentation modules contain no built-in
action names or concrete mode names. Their remaining branches are on typed,
generic runtime concepts:

- `ToolPresentationKind` selects direct text or model summarization.
- `ToolAttachmentKind.IMAGE` and `ToolFollowUpKind.VISION` select application
  services for typed artifacts; they do not identify the feature that produced
  them.
- `InputPolicyKind` selects wake-word, continuous, or suspended input behavior;
  it does not identify the active mode.
- `ToolResultKind` validates semantic outcomes independently of action names.

Concrete built-in identifiers remain only at explicit compatibility and
default-loading boundaries. `DEFAULT_FEATURE_MODULES` and
`DEFAULT_MODE_MODULES` define behavior when their config keys are omitted.
`bmo.tools.ToolRouter` names time, location, weather, and search only in legacy
patch/property/wrapper APIs; its class-level `VALID_TOOLS` and `ALIASES` are now
derived from the actual default registry rather than duplicated constants.
`bmo.features.__init__` and `bmo.modes.games` retain lazy or concrete exports for
callers using the old import paths. `bmo.config.DEFAULT_CONFIG` retains
historical top-level built-in settings while module-level defaults and per-entry
settings support new configurations. These compatibility surfaces do not
participate in core matching, model routing, dispatch, presentation, or mode
selection.

## Next extraction

The current `BotGUI` still combines presentation and conversation orchestration. The next safe step is to move widget/animation behavior into `bmo.ui` and move Ollama streaming/tool-response handling into `bmo.conversation`, after this extraction has been verified on both macOS and Raspberry Pi.

## Shutdown ownership

Audio streams are closed cooperatively by the thread that created them. The UI shutdown path sets a shared event, wakes any push-to-talk wait, joins the interaction and TTS threads, and then exits Tkinter. It deliberately does not call process-wide `sounddevice.stop()` while another thread owns an input stream; doing so can crash Core Audio on macOS.
