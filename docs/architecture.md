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
- `bmo.features.get_weather` — weather voice/menu registration, provider
  ownership, place cleanup, optional-alert isolation, and view lifecycle.
- `bmo.features.weather_config` — private weather-file validation and safe
  legacy fallback without merging location data into global settings.
- `bmo.features.weather_narration` — deterministic condition mapping,
  hemisphere-aware seasons, and child-friendly BMO tap narration.
- `bmo.features.weather_alerts` — optional cached National Weather Service
  point-alert adapter.
- `bmo.features.search_web` — web-search action, formatting, and archive details.
- `bmo.features.capture_image` — configured camera routing, Raspberry Pi still
  capture, rotation, interaction archival, optional persistent copies, event
  recording, and vision follow-up results.
- `bmo.features.album` — menu-only photo discovery, root-containment checks,
  FreeDesktop Wastebasket moves, and album-view registration.
- `bmo.features.learning` — menu-only Pre-K curriculum registration, private
  configuration, deterministic lesson engine, and local learner-data ownership.
- `bmo.features.learning.curriculum` — validated, prerequisite-aware literacy,
  math, vocabulary, and general-readiness lesson catalog.
- `bmo.features.learning.store` — versioned profiles, plans, attempts, and
  atomic progress persistence contained under the learning data root.
- `bmo.features.set_timer` — natural durations and a single condition-driven
  priority-queue scheduler for all active timers.
- `bmo.features.calendar` — read-only calendar voice routing, touch-view
  registration, local-date attention refresh, and menu persistence actions.
- `bmo.features.calendar_store` — versioned event and acknowledgment JSON,
  recurrence expansion, occurrence exceptions, and built-in US holidays.
- `bmo.features.calendar_config` — private calendar-file validation without
  merging calendar paths or narration choices into global settings.
- `bmo.modes` — typed lifecycle contracts and exclusive input ownership for
  long-lived interactions.
- `bmo.modes.loader` — standard-library module loading from `modes` config.
- `bmo.modes.matching_game` — Pup Pairs lifecycle and registration adapter.
- `bmo.modes.twenty_questions` — Twenty Questions lifecycle and registration
  adapter over the indexed dataset engine in `bmo.twenty_questions`.
- `bmo.twenty_questions_ui` — embedded touch canvas for menu-launched Twenty
  Questions games.
- `bmo.modes.games` — compatibility imports for the two built-in adapters.
- `bmo.memory` — conversation-history loading and atomic persistence.
- `bmo.archive` — append-only, per-interaction artifacts and event metadata.
- `bmo.config` — defaults, paths, Ollama options, and JSON loading.
- `bmo.prompts` — system-prompt construction.
- `bmo.state` — shared UI/application states.
- `bmo.kiosk_access` — global quiet-hours calculation and one-period parent-PIN
  unlock policy.
- `bmo.ui.gestures` — UI-independent tap and horizontal-swipe recognition.
- `bmo.ui.compact_face` — validated contained face-frame configuration, the
  canonical 108×65 top-right layout, distortion-free normalization, and the
  stack-aware Tk lifecycle shared by menus, features, and modes.
- `bmo.ui.scrolling` — bounded vertical finger scrolling shared by touch views.
- `bmo.ui.menu` — ordered menu-page navigation and the touch menu overlay.
- `bmo.ui.timer` — live countdown rendering, touch deletion, and vertical
  drag-scrolling for the menu-launched timer view.
- `bmo.ui.calendar` — current-day-first day/month/year navigation, bounded
  event-dot layout, scrollable day rows, color/category editor, and recurring
  occurrence/series choices.
- `bmo.ui.quiet_hours` — fullscreen sleeping-BMO cover and four-digit parent
  keypad for the global kiosk lock.
- `bmo.ui.album` — paginated photo thumbnails, horizontal swipe navigation,
  fullscreen image actions, and BMO vision-state presentation.
- `bmo.ui.learning` — 800x480 learner sessions, replayable BMO instruction,
  touch exercises, teacher-plan controls, and progress presentation.
- `bmo.ui.weather` — asynchronous location carousel, stale-response guards,
  secure loopback bridge, owned Chromium lifecycle, and SVG forecast state.

## Runtime flow

1. `agent.py` creates Tkinter and `BotGUI`.
2. `BotGUI` creates services using defaults overlaid by
   `config/settings.json`, then loads feature and mode wiring from
   `config/features.json`. Missing config files are not created; defaults remain
   in memory only. Weather and calendar separately read their private feature
   files, and the application reads the global quiet-hours file. None of those
   private contents are merged into the shared settings mapping.
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
conversation, feature-tool, or interaction-mode registries. Every compact BMO
presentation uses `bmo.ui.compact_face.CompactFace`: one fixed 108×65 viewport
at the canonical upper-right bounds. Its artwork is normalized into the
largest exact integer 5:3 area inside that viewport, so state changes never
stretch or shift the face. Tapping the menu face returns immediately to the
full-screen face.

`config/compact_face.json` is an optional private UI configuration with the
tracked `config/example.compact_face.json` as its template. It maps state names
to deterministic PNG sequences contained under `faces/` and supplies frame and
refresh timing. Missing, malformed, empty, or escaping paths fall back safely.
The application animation loop remains the sole runtime state/frame owner;
compact Tk views receive only its narrow current-frame provider. The shared
component owns placement, normalization, fallback art, image references,
scheduling, and cleanup.

Menu pages satisfy the small `bmo.ui.menu.MenuPage` rendering contract and are
supplied to `MenuApp` in display order. Left swipes advance through that tuple.
Right swipes decrement the current page index, so every visited page is
retraced in reverse order; a right swipe from the first page closes the menu.
Enabled modes and feature tools may optionally contribute typed menu metadata.
Their registries expose those contributions in configuration order, and
`BotGUI` maps them to generic three-column, two-row icon-grid pages without
checking concrete extension names. Each page holds up to six actions;
additional actions are placed on later swipeable pages. Grid cells render only
their alpha-preserving icons, without tile backgrounds, borders, or labels;
each invisible cell remains the full touch target. A mode tap queues the
selected mode for the normal interaction worker, interrupting wake-word waiting
without starting mode lifecycle work on Tk's event thread. A feature tap opens
its view on Tk's event thread with a narrow `FeatureMenuContext`; voice and
model routing remain unchanged because opening a view is a separate hook. When
no enabled extension contributes an item, the menu retains its intentionally
blank fallback page.

Selecting a menu item does not destroy or navigate away from `MenuApp`. The
originating grid page remains placed below the launched mode's newer embedded
canvas. Compact faces on the same Tk root form a visibility stack: mounting a
newer face suspends the covered menu renderer, and destroying the newer view
resumes the menu face. A feature such as Album may temporarily unmount its face
while retaining stack ownership, preventing the covered menu from doing
duplicate refresh work. Closing a game destroys only its game canvas and shared
face, revealing the same live menu instance with its original page index.
Voice-launched modes still return to the full-screen face because no menu
instance owns their launch path.

The timer tool contributes `graphics/icons/timer.png` by reference and opens a
full-screen list only when that icon is selected. The list polls immutable
snapshots of the same scheduler used by voice commands, refreshes countdowns
four times per second, and cancels through the scheduler when a delete button is
tapped. It mounts the same canonical compact face as every other menu-launched
view. Vertical finger drags move a bounded list viewport when the active timer
rows exceed the display. Closing the view destroys only its canvases and reveals
the originating menu page. Timer cancellation removes the timer from both the
active index and priority queue immediately, so a deleted row cannot later
expire or retain scheduler state.

The calendar tool contributes `graphics/icons/calendar.png` by reference and
opens only from its touch-menu item. It starts on the local current day, with
explicit Day, Month, Year, Today, and Menu controls. Day navigation uses only
previous/next arrows; more than four event rows remain inside a clipped,
vertically draggable viewport. Month cells place colored event dots beside the
day number and then in bounded rows, displaying an overflow count only after
the cell's safe capacity is full. The year view uses month-specific birthstone
colors and opens a selected month. A live upper-right BMO face animates while
calendar-owned announcements play.

The touch editor owns event name, all-day or start/end times, category,
unrestricted color selection, notes, weekly/monthly/yearly recurrence, weekly
day selection, repeat end date/count, and monthly short-month behavior. Irrelevant
controls are hidden or disabled. Editing or deleting one repeated occurrence
asks whether the change applies to that occurrence or the series. Occurrence
overrides atomically store both the series exception and replacement. Built-in
US holidays are read-only calendar rows. Calendar voice routing can summarize
today, tomorrow, this/next week, weekends, months, dates, and named weekdays,
but exposes no voice mutation path.

At startup and each local date change, the feature publishes one typed
attention for every unacknowledged current-day occurrence. `BotGUI` owns the
badge and draws it only over the full-screen idle face, never over menu or
feature PIP faces. Tapping the badge persistently acknowledges the occurrence
and speaks it. Optional `faces/calendar` PNG art is composited over the normal
idle face; missing art falls back to lightweight edge decoration and never
replaces listening, thinking, speaking, error, or warmup faces.

Quiet hours are a global kiosk policy rather than a calendar feature. When the
configured local schedule is active, a full-screen sleeping-BMO cover blocks
menu, push-to-talk, voice interaction, scoped announcements, and attention
presentation. A four-digit parent PIN unlocks only the current quiet period;
normal operation resumes automatically at its end. Missing sleeping art uses a
drawn fallback, and a disabled or malformed private quiet-hours file leaves the
kiosk unlocked.

The album feature contributes `graphics/icons/album.png` by reference and has
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

The Learning feature contributes `graphics/icons/learning.png` by reference
and likewise has no voice, model, prompt, alias, direct-matching, or executable
tool surface. It opens only from the touch menu. Its 800x480 Tk canvas presents
data-driven Pre-K literacy, early-math, vocabulary, and general-readiness
lessons, while a PIN-gated teacher area owns learner profiles, ordered plans,
prerequisite warnings, and progress reports. Spoken instructions and feedback
use only the view-scoped `FeatureMenuContext` announcement service, so they use
the configured BMO Piper voice without giving the feature direct access to
audio services. If scoped speech is unavailable, replay controls are visibly
disabled and every visual exercise remains usable. Closing the view cancels its
speech and reveals the unchanged originating menu page.

Learning question generation is deterministic when supplied a seeded random
source and remains independent of Tk. The catalog validates unique lesson IDs,
prerequisite existence and acyclicity, supported interaction types, and usable
answer banks before a session begins. Teacher plans retain an ordered lesson
sequence, bounded varied repetitions, session length, and an optional mastery
gate. Attempt records distinguish first-try accuracy from eventual correctness;
plan completion is reported separately from accuracy, and mastery requires
multiple recent observations. Learner data never enters conversation memory or
interaction archives.

The weather tool contributes `graphics/Icons/weather.png` by reference while
retaining its existing voice/model action. Opening its icon starts a separate
800×480 Chromium kiosk surface over the same originating Tk menu. Horizontal
swipes wrap
through the weather-owned ordered location tuple instead of navigating the
underlying menu. Each location is loaded on a bounded daemon worker; the Tk
thread polls a result queue, caches successful pages for the view lifetime, and
accepts a result only when its per-location request token is current. A late
worker can therefore finish safely after navigation or close without touching
destroyed widgets or replacing newer data.

Because Chromium cannot instantiate the Tk component, `WeatherWebBridge`
builds a narrow JSON adapter from the same validated `CompactFaceConfig`. The
adapter injects canonical bounds, timing, and a current-frame endpoint into the
local HTML before it is served. The host selects the runtime frame; the bridge
normalizes and publishes that one raster, so CSS and JavaScript contain no
independent face coordinates, state choice, or frame list. Weather therefore
matches the 108×65 Tk viewport while remaining failure-isolated behind its
tokenized loopback bridge.

`WeatherSnapshot` is the immutable neutral data boundary used by both the
historical short spoken report and the GUI. Open-Meteo supplies current values,
the daily high/low and precipitation total, sunrise/sunset, and upcoming hourly
values. The report calls `precipitation_probability_max` the “highest hourly
rain chance today”; it is not rainfall volume. The scene composes season,
day/night, primary WMO condition, and measured modifiers such as heat, cold,
humidity, and high gusts. Seasons affect only scenery—winter never implies
snow. The 800×480 presentation uses weather-owned HTML, CSS, and inline SVG:
layered seasonal ground, animated condition particles, childlike current and
hourly icons, and locally calculated eight-phase moon art. Forecast cards use
real alpha transparency. The close control samples the current frame selected
by the application animation loop through the feature's narrow face provider.
The loopback bridge normalizes that frame with the shared compact-face adapter
and exposes only the resulting 108×65 raster; the browser owns neither face
state nor animation sequencing and falls back to a simple inline face whenever
the current host frame is unavailable. The hourly strip drops
past local forecast points as the view remains open, and each cached location
is refreshed on a bounded fifteen-minute interval so its remaining hours and
day period advance without reopening the menu. All tap speech uses
deterministic templates rather than a model.

Browser actions cross a feature-owned HTTP bridge bound only to a random
`127.0.0.1` port. A per-view path token, strict origin and action validation,
bounded request bodies, a restrictive content-security policy, and a dedicated
temporary Chromium profile isolate the surface from the LAN and from the
user's browser data. The credential store is explicitly set to the temporary
profile's basic store so Chromium cannot block the kiosk with a desktop keyring
dialog. Closing Weather stops the Chromium process group, server thread,
timers, and scoped speech. A browser-ready signal and periodic heartbeat close
an unresponsive or blank kiosk and return to the menu. If Chromium cannot
start, the feature reports the failure without affecting voice weather or
another feature.

Setting private weather configuration `debug` to true exposes a collapsible
browser-only preview panel for every visual condition, season, day period, and
moon phase. Preview selection never mutates provider data or the Python cache;
Live Weather clears the override. Debug controls remain absent when disabled.

Optional National Weather Service alerts are fetched by forecast coordinates
and cached independently. An alert-provider error is reported generically and
never removes an otherwise valid Open-Meteo page. Alert banners and narration
use direct safety language; configured automatic warning announcements speak
only warnings or severe/extreme alerts. No weather or location component uses
IP geolocation.

## Platform behavior

The primary deployment baseline is a Raspberry Pi 5 with 16 GB RAM running
64-bit Raspberry Pi OS (`aarch64`) and Python 3.13.5. macOS is a supported
development and test environment, but a successful macOS install is not proof
that a native or Python dependency works on the deployment target. New
dependencies must satisfy the compatibility and justification policy in
`AGENTS.md` before they are added.

The weather view requires the Raspberry Pi OS `chromium` system package. The
setup script installs and verifies its executable; no Python webview package is
added. Chromium runs only while the weather view is open.

Calendar persistence, recurrence, color selection, and quiet-hours enforcement
use only Python's standard library and existing Tk/Pillow packages. The system
local date and time are authoritative; there is no feature-level timezone.
Private event data lives under `data/calendar`, optional calendar overlay art
lives under `faces/calendar`, and calendar/quiet-hours settings live in
`config/calendar.json` and `config/quiet_hours.json`. These paths are local and
Git-ignored; the tracked `config/example.calendar.json` and
`config/example.quiet_hours.json` files document their schemas.

Learning also uses only the standard library plus the existing Tk/Pillow
surface. Private profiles, plans, sessions, and bounded attempt history live
under `data/learning` and are written with atomic replacement. Learning
settings live in `config/learning.json`; the tracked
`config/example.learning.json` documents the schema without exposing local
learner data or the teacher PIN. Optional artwork lookups are contained under
`graphics/learning`, but the current repository policy keeps `graphics/`
read-only, so the feature has complete original Canvas-drawn fallbacks.

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
nine modules in `DEFAULT_FEATURE_MODULES`; providing the key replaces that
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
- A feature that needs persistent full-screen acknowledgment sends typed
  `RuntimeAttention` and `RuntimeAttentionDismissal` values through the
  registry. The application owns generic badge presentation and invokes the
  supplied acknowledgment callback; PIP views never receive attention widgets.
- A feature may expose a `FeatureMenuItem` whose normalized name matches its
  action and an `open_menu(context)` hook. The registry validates and exposes
  this pair transactionally. A tool marked `menu_only = True` must have a menu
  item and no aliases; the registry excludes it from actions, capabilities,
  prompts, direct matching, model preparation, and executable dispatch.
  `FeatureMenuContext` supplies only the Tk master, the callback that reveals
  the originating menu, a current-face provider, a queued generic vision
  request, and optional scoped announcements. It does not expose `BotGUI`,
  Piper, models, or interaction archives. A scoped announcement replaces only
  older speech from that open feature view; closing the view cancels that
  scope without clearing unrelated speech.

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
  application settings. The Twenty Questions adapter accepts `show_in_menu`,
  `answer_wait_seconds`, `debug`, `data_path`, `learned_path`, `history_path`,
  `informative_question_limit`, and `total_prompt_limit`, while retaining the
  historical top-level setting names as fallbacks for the timeout and debug
  flag.

An enabled mode module exposes `register(registry, context, settings)`. The
context must be `ModeRuntimeContext`; it deliberately exposes approved services
rather than the entire GUI coordinator. Registration order controls the first
matching start request. The built-in modules construct the existing adapters.
Twenty Questions owns a lazily loaded immutable base JSONL catalog, an
integer-bitset adaptive partition index, and its local learned JSONL overlay;
it does not use Bayesian seed entities or model-generated candidate expansion.

A mode can expose an optional `ModeMenuItem` with the same normalized name as
the mode, a label, icon path, and synthetic start request. Registration validates
and rolls back that metadata with the mode, so disabled, failed, and quarantined
modes cannot leave stale menu pages. The matching-game adapter contributes the
existing `graphics/icons/matching_game.png` asset by reference. The Twenty
Questions adapter contributes `graphics/icons/20_questions.png` by reference
and starts its embedded touch canvas when selected. Spoken launches remain
voice-driven. Both adapters' `show_in_menu` settings default to `true`; setting
the Twenty Questions value to `false` hides only its menu entry and leaves
voice launch enabled.

Twenty Questions reads `data/20_questions/data.jsonl` only when a game starts.
The strict loader keeps that base catalog immutable and builds an inverted
integer-bitset index over its effective rows. Dataset `Often` and learned
`Unknown` values are wildcards, while the player's only canonical responses
are `yes`, `no`, `sometimes`, and `unknown`. Confirmed guesses and revealed
objects are replayed into `data/20_questions/learned.jsonl` using an atomic
JSONL replacement; a malformed learned file disables learning for that
session without affecting the base game. A missing or corrupt base file ends
only this mode and returns input ownership to the normal application loop. The
menu-launched mode owns an embedded 800×480 canvas with BMO status, answer
buttons, guess controls, a reveal field, and the five most recently identified
game things. The canvas
is created before the introduction is spoken and suspends voice capture while
it is open, matching the existing game-mode UI lifecycle. The indexed game
continues through 20 numbered question prompts after wrong guesses. An empty
pool after question 19 triggers one local-model fallback guess, and the model
also makes the round-ending guess at question 20. If that guess is wrong, the
player gets the round win and four bonus questions followed by another model
guess at question 25. The touch canvas offers PLAY AGAIN after completion.
Completed targets are stored newest-first in the bounded `history_path` JSON
file using atomic replacement, so a revealed `strawberry` remains visible when
the next game reveals `computer`. The history path must not collide with the
base or learned catalog paths.

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
- `FeatureMenuContext.announce` queues speech under a unique view scope without
  exposing Piper or naming the requesting feature.
- `RuntimeAttention` selects generic full-screen acknowledgment and optional
  idle-face overlay presentation without naming its producing feature in core
  UI routing.
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

Audio streams are closed cooperatively by the thread that created them. The UI
shutdown path cancels the quiet-hours poll, closes feature-owned workers such as
the calendar date-change watcher, sets a shared event, wakes any push-to-talk
wait, joins the interaction and TTS threads, and then exits Tkinter. It
deliberately does not call process-wide `sounddevice.stop()` while another
thread owns an input stream; doing so can crash Core Audio on macOS.
