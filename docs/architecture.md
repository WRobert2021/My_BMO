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
  capture, rotation, interaction archival, optional persistent copies, event
  recording, and vision follow-up results.
- `bmo.features.album` — menu-only photo discovery, root-containment checks,
  FreeDesktop Wastebasket moves, and album-view registration.
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
- `bmo.ui.gestures` — UI-independent tap and horizontal-swipe recognition.
- `bmo.ui.menu` — ordered menu-page navigation and the touch menu overlay.
- `bmo.ui.timer` — live countdown rendering, touch deletion, and vertical
  drag-scrolling for the menu-launched timer view.
- `bmo.ui.album` — paginated photo thumbnails, horizontal swipe navigation,
  fullscreen image actions, and BMO vision-state presentation.

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
8. Tool calls, full web results, and camera images are stored under the same
   interaction; camera captures are also copied to the feature's configured
   persistent directory.
9. Piper streams speech through `sounddevice` while also writing archival WAVs.
10. Shutdown stops audio, saves recent memory atomically, unloads the text model, and closes Tkinter.

## Display navigation

The full-screen face recognizes taps separately from horizontal swipes. A
right-to-left swipe opens the menu without coupling menu behavior to the
conversation, feature-tool, or interaction-mode registries. The menu keeps a
live 140×84 BMO face in the same upper-right position used by Pup Pairs. Tapping
that face returns immediately to the full-screen face.

Menu pages satisfy the small `bmo.ui.menu.MenuPage` rendering contract and are
supplied to `MenuApp` in display order. Left swipes advance through that tuple.
Right swipes decrement the current page index, so every visited page is
retraced in reverse order; a right swipe from the first page closes the menu.
Enabled modes and feature tools may optionally contribute typed menu metadata.
Their registries expose those contributions in configuration order, and
`BotGUI` maps them to generic three-column, two-row icon-grid pages without
checking concrete extension names. Each page holds up to six actions;
additional actions are placed on later swipeable pages. A mode tap queues the
selected mode for the normal interaction worker, interrupting wake-word waiting
without starting mode lifecycle work on Tk's event thread. A feature tap opens
its view on Tk's event thread with a narrow `FeatureMenuContext`; voice and
model routing remain unchanged because opening a view is a separate hook. When
no enabled extension contributes an item, the menu retains its intentionally
blank fallback page.

Selecting a menu item does not destroy or navigate away from `MenuApp`. The
originating grid page remains placed below the launched mode's newer embedded
canvas, and its upper-right face continues its 150 ms refresh schedule during
launch and while covered. Closing the game destroys only the game canvas, which
reveals the same live menu instance with its original page index. Voice-launched
modes still return to the full-screen face because no menu instance owns their
launch path.

The timer tool contributes `graphics/Icons/timer.png` by reference and opens a
full-screen list only when that icon is selected. The list polls immutable
snapshots of the same scheduler used by voice commands, refreshes countdowns
four times per second, and cancels through the scheduler when a delete button is
tapped. Vertical finger drags move a bounded list viewport when the active timer
rows exceed the display. Closing the view destroys only its canvases and reveals
the originating menu page. Timer cancellation removes the timer from both the
active index and priority queue immediately, so a deleted row cannot later
expire or retain scheduler state.

The album feature contributes `graphics/Icons/album.png` by reference and has
no voice, model, prompt, alias, or executable-tool surface. Its full-screen
view recursively lists only resolved regular image files contained by the
configured `photo_root`. The grid shows multiple images per page, retraces its
pages with horizontal swipes, and retains the live BMO face in the upper-right
corner. Selecting a thumbnail hides BMO and shows the image full screen; a
second tap opens Back, Wastebasket, and BMO-analysis actions. Back restores the
album, and Wastebasket uses the recoverable FreeDesktop `Trash/files` plus
`Trash/info` layout. The analysis action validates containment again, restores
the full-screen image with BMO in the upper-right corner, and queues a generic
vision turn on the normal interaction worker. The feature never receives
`BotGUI`, model objects, or an interaction archive.

## Platform behavior

The primary deployment baseline is a Raspberry Pi 5 with 16 GB RAM running
64-bit Raspberry Pi OS (`aarch64`) and Python 3.13.5. macOS is a supported
development and test environment, but a successful macOS install is not proof
that a native or Python dependency works on the deployment target. New
dependencies must satisfy the compatibility and justification policy in
`AGENTS.md` before they are added.

The same Python entry point is used on macOS and Raspberry Pi. The Python
virtual environment owns Python packages only. Whisper.cpp, Piper and its voice
models, and the wake-word model are project-local native/model artifacts;
Ollama and its downloaded models are system-level services. Replacing a virtual
environment therefore requires reinstalling Python packages, but it does not
require rebuilding or downloading those separate artifacts when their expected
paths remain valid.

- Piper uses `./piper/piper` when the bundled Pi binary exists.
- Otherwise Piper runs through the active environment with `python -m piper`.
- Whisper paths can be overridden with `whisper_binary` and `whisper_model` in
  `config/settings.json`.
- On Linux with Python 3.13, BMO uses OpenWakeWord 0.6 in ONNX-only mode.
  `setup.sh` deliberately installs it without the unused TFLite dependency,
  whose compatible Python 3.13 wheel is unavailable, after installing the ONNX
  runtime dependencies. Installer verification must instantiate the configured
  wake-word model; checking that the package merely imports is not sufficient.
- Raspberry Pi camera matching, execution, timeout, configured rotation, and
  result ownership all live in the optional `bmo.features.capture_image`
  module. Its `save_directory` setting selects a persistent capture folder;
  omitting it defaults to `~/Pictures/bmo/what_do_you_see`, and setting it to
  `null` keeps only the interaction-archive image. Persistent copies use unique
  UTC filenames and are written atomically. A copy failure is recorded without
  discarding the captured image or preventing its vision follow-up. When the
  feature is disabled, its module is never imported and contributes no prompt
  metadata, direct matcher, or subprocess path.
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
| Menu-only feature | While its view is open | Enabled module list, then touch-menu item | UI only; queued vision uses the normal interaction worker |
| Interaction mode | Multiple turns or a dedicated UI | Enabled module list, then first registered start matcher | Exclusive until `is_active()` is false |

### Feature module contract

The `features` list lives in `config/features.json`. Omitting the key loads the
seven modules in `DEFAULT_FEATURE_MODULES`; providing the key replaces that
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
- A feature may expose a `FeatureMenuItem` whose normalized name matches its
  action and an `open_menu(context)` hook. The registry validates and exposes
  this pair transactionally. A tool marked `menu_only = True` must have a menu
  item and no aliases; the registry excludes it from actions, capabilities,
  prompts, direct matching, model preparation, and executable dispatch.
  `FeatureMenuContext` supplies only the Tk master, the callback that reveals
  the originating menu, a current-face provider, and a queued generic vision
  request. It does not expose `BotGUI`, models, or interaction archives.

Registration order controls prompt order and the first matching direct action.
Only successfully registered routable tools appear in prompts or dispatch;
successfully registered menu-only tools appear only in menu contributions. The
compatibility router rejects unregistered actions, so disabling a feature also
removes its aliases, direct phrases, prompt metadata, menu item, and execution
path.

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

A mode can expose an optional `ModeMenuItem` with the same normalized name as
the mode, a label, icon path, and synthetic start request. Registration validates
and rolls back that metadata with the mode, so disabled, failed, and quarantined
modes cannot leave stale menu pages. The matching-game adapter contributes the
existing `graphics/Icons/Matching_Game.png` asset by reference. Its
`show_in_menu` setting defaults to `true`; setting it to `false` hides only the
menu page and leaves voice matching enabled.

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
- `FeatureMenuContext.request_vision` queues any contained feature-owned image
  for the same core vision flow without naming the requesting feature.
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
