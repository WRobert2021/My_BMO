# Be More Agent script map

This is a high-level map of the repository's executable and supporting code.
`AGENTS.md` is the sole source of repository workflow rules, while
`docs/AGENT_ARCHITECTURE.md` contains the detailed extension contracts and design
rationale.

## Runtime at a glance

`agent.py` starts the Qt Quick application. `bmo.runtime.AssistantRuntime`
composes configuration, audio, speech recognition, local Ollama models,
archives, memory, feature tools, and interaction modes. `bmo.qt` owns the
fullscreen presentation and marshals worker updates onto the Qt event thread.

For each transcript, an active mode receives input first. Otherwise, the tool
registry checks deterministic phrases and then exposes enabled capabilities to
the local intent model. Requests not handled by a mode or tool continue as
ordinary local-model conversation. Touch-menu items come from the feature and
mode registries.

```text
agent.py
  -> bmo.qt.app -> QML presentation
       -> bmo.runtime -> core services: config, audio, speech, memory, archive
            -> feature loader -> tool registry -> bmo.features.*
            -> mode loader    -> mode registry -> bmo.modes.*
            -> bmo.qt.view_host -> QML feature and mode adapters
```

## Launch, installation, and package files

| File | Role |
| --- | --- |
| `agent.py` | Production launcher; starts the Qt/QML application and neutral assistant runtime. |
| `typed_agent.py` | Qt debug launcher that adds an on-screen text field while retaining normal routing and presentation. |
| `qt_agent.py` | Explicit alias for the production Qt/QML launcher. |
| `tk_agent.py` | Explicit legacy Tk fallback retained for one validation cycle. |
| `start_agent.sh` | Runs `agent.py` with the repository virtual environment. |
| `setup.sh` | Raspberry Pi/aarch64 installer for system packages, Whisper.cpp, Piper, voices, Python packages, Ollama models, and the wake-word model. |
| `be-more-agent.desktop` | Linux desktop shortcut for `start_agent.sh`. |
| `requirements.txt` | Runtime Python dependency list. |
| `requirements-dev.txt` | Runtime dependencies plus pytest. |
| `bmo/__init__.py` | Root Python package marker. |

## Core runtime modules

| File | Role |
| --- | --- |
| `bmo/runtime.py` | Toolkit-neutral production composition root: workers, tool/mode routing, speech queue, attentions, recovery, persistence, and shutdown. |
| `bmo/app.py` | Legacy Tk adapter retained only for the explicit fallback launcher. |
| `bmo/conversation.py` | UI-neutral model-call logging and typed tool-result presentation used by the application coordinator. |
| `bmo/config.py` | Global defaults, shared paths, Ollama options, and split settings/extension configuration loading. |
| `bmo/extensions.py` | Shared configuration-driven import, registration transaction, rollback, and failure-isolation mechanism for features and modes. |
| `bmo/tools.py` | Compatibility facade over the enabled `ToolRegistry`, including resource-free metadata access. |
| `bmo/intent.py` | Local-model tool classification, game-answer interpretation, and constrained fallback guessing. |
| `bmo/prompts.py` | Builds system and routing prompts from registered feature capabilities. |
| `bmo/audio.py` | Audio-device discovery, recording, WAV effects, and Piper playback. |
| `bmo/speech.py` | OpenWakeWord streaming, Whisper.cpp transcription, and model-action JSON extraction. |
| `bmo/archive.py` | Per-interaction directories, artifacts, JSONL events, and manifests. |
| `bmo/memory.py` | Conversation-history validation, loading, bounding, and atomic saving. |
| `bmo/jsonio.py` | Strict JSON decoding, embedded-object extraction, and atomic JSON/JSONL replacement. |
| `bmo/state.py` | Shared application and face-state names. |
| `bmo/face_config.py` | UI-toolkit-neutral face layout, animation-frame discovery, timing, and private configuration validation. |
| `bmo/gestures.py` | UI-toolkit-neutral tap and horizontal-swipe recognition shared by Tk and Qt. |
| `bmo/menu_model.py` | UI-toolkit-neutral menu items, 5x3 pagination, hit geometry, and swipe history shared by Tk and Qt. |
| `bmo/menu_catalog.py` | Namespaced registry-to-menu composition and typed mode/feature selection requests shared by Tk and Qt. |
| `bmo/menu_loader.py` | Resource-free loading of configured feature/mode menu metadata with per-extension failure isolation. |
| `bmo/runtime_menu.py` | UI-neutral live menu snapshots, stale-selection validation, and typed mode/feature launch dispatch. |
| `bmo/runtime_extensions.py` | UI-neutral feature/mode registry lifetime, worker wake event, and queued mode/vision menu requests. |
| `bmo/runtime_loop.py` | UI-neutral resilient assistant worker and voice-turn arbitration across menus, modes, wake/PTT, interrupts, and shutdown. |
| `bmo/runtime_voice.py` | UI-neutral voice capture selection, transcription, transcript archival, retry presentation, and successful turn completion. |
| `bmo/text.py` | Shared spoken-command normalization. |
| `bmo/network.py` | Shared bounded timeout parsing for online features. |
| `bmo/location.py` | Location validation, home resolution, and Nominatim geocoding. |
| `bmo/weather.py` | Open-Meteo client, typed forecast records, unit handling, and spoken report formatting. |
| `bmo/kiosk_access.py` | Quiet-hours configuration, active-period calculation, and current-period unlock state. |

## Feature framework

Features are short-lived tools or menu-only views loaded from the `features`
configuration list.

| File | Role |
| --- | --- |
| `bmo/features/__init__.py` | Feature package with lazy compatibility exports. |
| `bmo/features/contracts.py` | Typed tool, result, presentation, archive, attachment, follow-up, notification, attention, execution-context, and menu-context records. |
| `bmo/features/registry.py` | Tool registration, aliases, prompt metadata, direct matching, execution, menu contribution, notifications, attentions, and cleanup. |
| `bmo/features/loader.py` | Built-in feature list and configuration-driven module loading. |

## Built-in feature modules

| File | Role |
| --- | --- |
| `bmo/features/get_time.py` | Local-time action and direct phrases. |
| `bmo/features/get_location.py` | Configured-home-location action and error response. |
| `bmo/features/get_weather.py` | Spoken weather action and lifecycle owner for the Weather menu view. |
| `bmo/features/weather_config.py` | Weather-owned private configuration and ordered location carousel. |
| `bmo/features/weather_alerts.py` | Optional cached National Weather Service alert provider. |
| `bmo/features/weather_narration.py` | Child-friendly condition, temperature, season, rain, hourly, and alert narration. |
| `bmo/features/search_web.py` | DuckDuckGo news/text search, result formatting, and search archive details. |
| `bmo/features/capture_image.py` | Raspberry Pi still capture, rotation, persistent copy, and vision follow-up. |
| `bmo/features/set_timer.py` | Duration parsing, multi-timer scheduler, voice operations, menu callbacks, and alarm attentions. |
| `bmo/features/timer_view.py` | Toolkit-neutral active-timer snapshots shared with presentation adapters. |
| `bmo/features/calendar.py` | Read-only spoken calendar, editable menu view, midnight refresh worker, and current-day attentions. |
| `bmo/features/calendar_config.py` | Calendar-owned private configuration. |
| `bmo/features/calendar_store.py` | Event/acknowledgement storage, recurrence expansion, occurrence overrides, and US holidays. |
| `bmo/features/calendar_view.py` | Toolkit-neutral calendar occurrence and editor records shared with presentation adapters. |
| `bmo/features/weather_view.py` | Toolkit-neutral weather-page records and condition/season/time/moon/hourly scene contract shared with presentation adapters. |
| `bmo/features/album.py` | Menu-only contained photo library, Wastebasket moves, and Album view registration. |
| `bmo/features/galaxy_rvr.py` | Menu-only Bluetooth gamepad remote, GalaxyRVR LAN protocol, camera snapshots, and safe-stop lifecycle. |
| `bmo/features/galaxy_rvr_config.py` | GalaxyRVR-owned private network, photo, controller mapping, motion, camera, and timeout configuration. |

## Learning feature modules

| File | Role |
| --- | --- |
| `bmo/features/learning/__init__.py` | Menu-only Learning registration and service/view lifecycle. |
| `bmo/features/learning/config.py` | Learning-owned private settings and contained data/art paths. |
| `bmo/features/learning/models.py` | Immutable lessons, questions, attempts, profiles, plans, sessions, mastery, and report records. |
| `bmo/features/learning/curriculum.py` | Data-driven Pre-K lesson catalog, content banks, prerequisites, and catalog validation. |
| `bmo/features/learning/engine.py` | Deterministic question generation, grading, retries, reveals, and session transitions. |
| `bmo/features/learning/analytics.py` | Pure accuracy, grade, trend, mastery, and plan-completion calculations. |
| `bmo/features/learning/codec.py` | Strict version-one private persistence schema. |
| `bmo/features/learning/store.py` | Profiles, plans, attempts, sessions, atomic persistence, reports, and read-only recovery. |
| `bmo/features/learning/errors.py` | Learning persistence and confirmation exception types. |

## Mode framework and games

Modes are longer interactions that temporarily own user input.

| File | Role |
| --- | --- |
| `bmo/modes/__init__.py` | Public mode package exports. |
| `bmo/modes/contracts.py` | Mode lifecycle, runtime context, menu item, and input-policy types. |
| `bmo/modes/registry.py` | Mode registration, exclusive input routing, menu launch, failure quarantine, and cleanup. |
| `bmo/modes/loader.py` | Built-in mode list and configuration-driven loading. |
| `bmo/modes/games.py` | Compatibility imports for the built-in game adapters. |
| `bmo/modes/matching_game.py` | Adapter connecting Pup Pairs to the mode registry and menu lifecycle. |
| `bmo/modes/twenty_questions.py` | Adapter connecting Twenty Questions to voice/menu input, model fallback guesses, learning, and history. |
| `bmo/matching_game_core.py` | Toolkit-neutral Pup Pairs cards, imperfect BMO memory player, score history, and board state. |
| `bmo/matching_game.py` | Legacy Tk Pup Pairs presentation over the shared game core. |
| `bmo/matching_game_text.py` | Dependency-light spoken start-request matching for Pup Pairs. |
| `bmo/twenty_questions.py` | Strict dataset loader, learned overlay, bitset candidate index, adaptive game engine, and recent-target history. |
| `bmo/twenty_questions_contracts.py` | Dataset and learning-persistence errors. |
| `bmo/twenty_questions_text.py` | Object-name and answer normalization. |
| `bmo/twenty_questions_ui.py` | Embedded touch board, answer/guess controls, reveal entry, status, and replay. |

## UI modules

| File | Role |
| --- | --- |
| `bmo/ui/__init__.py` | Re-exports neutral UI components. |
| `bmo/ui/gestures.py` | Compatibility exports for the neutral gesture recognizers. |
| `bmo/ui/scrolling.py` | Bounded vertical drag state independent of Tk. |
| `bmo/ui/compact_face.py` | Shared 108x65 face configuration, image normalization, rendering, and overlay stack lifecycle. |
| `bmo/ui/menu.py` | Tk rendering and lifecycle for the shared swipe-menu model and compact face. |
| `bmo/ui/timer.py` | Active-timer list, countdown refresh, touch deletion, scrolling, and duration editor. |
| `bmo/ui/calendar.py` | Day/month/year views, event editor, recurrence controls, event scrolling, and narration actions. |
| `bmo/ui/quiet_hours.py` | Fullscreen sleeping cover and four-digit touch keypad. |
| `bmo/ui/album.py` | Thumbnail pages, fullscreen photos, Back/Wastebasket/BMO actions, and vision presentation. |
| `bmo/ui/galaxy_rvr.py` | Legacy Tk GalaxyRVR remote status view over the feature-owned controller session. |
| `bmo/ui/learning.py` | Learner sessions, generic activity rendering, teacher controls, plan/profile management, reports, and scoped speech. |
| `bmo/ui/weather.py` | Legacy Tk fallback weather carousel, loopback bridge, Chromium process/profile, action validation, and cleanup. |
| `bmo/ui/weather_web/index.html` | Legacy weather kiosk HTML/CSS/JavaScript renderer, SVG scenes, hourly cards, bridge polling, touch/swipe actions, and debug preview. |
| `bmo/qt/controller.py` | Qt properties/signals for face frames, overlays, HUD, menus, hosted views, attentions, quiet hours, and kiosk gestures. |
| `bmo/qt/presentation.py` | Queued Qt implementation of the runtime presentation port. |
| `bmo/qt/view_host.py` | Feature/mode app-factory host and active QML view lifecycle. |
| `bmo/qt/views/` | QML adapters for Timer, Calendar, Weather, Album, Learning, Pup Pairs, and Twenty Questions; the Weather adapter owns async cache/refresh and scoped narration. |
| `bmo/qt/app.py` | Production Qt Quick engine, runtime wiring, shutdown, and isolated preview ownership. |
| `bmo/qt/qml/Main.qml` | Fullscreen 800x480 face, menu, global overlays, debug input, and hosted-view surface. |
| `bmo/qt/qml/HostedView.qml` | Touch presentation host for every built-in feature and interaction mode. |
| `bmo/qt/qml/CalendarView.qml` | Production day/month/year Calendar, bounded event dots, recurrence editor, touch color picker, and occurrence/series choice. |
| `bmo/qt/qml/WeatherView.qml` | Production 800x480 child-friendly Weather layout, interaction, live face, carousel, and debug panel. |
| `bmo/qt/qml/WeatherScene.qml` | Seasonal/day-period ground, particles, and animated weather effects. |
| `bmo/qt/qml/WeatherIcon.qml` | Dependency-free Canvas current/hourly condition and eight-phase moon art. |

## Configuration examples

| File | Settings represented |
| --- | --- |
| `config/example.settings.json` | Models, audio, camera, prompts, timeout, Weather/quiet-hours paths, and interaction logging. |
| `config/example.features.json` | Ordered enabled feature and mode modules with module settings. |
| `config/example.weather.json` | Units, locations, carousel default, visual flags, and optional alerts. |
| `config/example.calendar.json` | Calendar data/overlay paths, categories, holidays, and spoken notes. |
| `config/example.learning.json` | Learning data/art paths, teacher area, session/mastery limits, fonts, speech, and debug seed. |
| `config/example.galaxy_rvr.json` | GalaxyRVR LAN address, controller mapping, motion/servo limits, camera preview, photo storage, and timeouts. |
| `config/example.quiet_hours.json` | Schedule, weekdays, passcode, and sleeping-face path. |
| `config/example.compact_face.json` | Compact-face state directories and animation timing. |

## Test map

| Area | Test files |
| --- | --- |
| Extension framework | `tests/test_extension_architecture.py`, `tests/test_feature_loading.py`, `tests/test_mode_loading.py`, `tests/extension_modules/proof_feature.py`, `tests/extension_modules/proof_mode.py` |
| Tool routing and presentation | `tests/test_tool_registry.py`, `tests/test_tool_routing.py`, `tests/test_tool_routing_characterization.py`, `tests/test_tool_presentation.py`, `tests/test_intent.py` |
| Main interaction and menus | `tests/test_interaction_failure_recovery.py`, `tests/test_runtime_loop.py`, `tests/test_menu.py`, `tests/test_modes.py` |
| Neutral menu catalog | `tests/test_menu_catalog.py` |
| Runtime menu and extension dispatch | `tests/test_runtime_menu.py`, `tests/test_runtime_extensions.py` |
| Core persistence/config | `tests/test_archive.py`, `tests/test_jsonio.py`, `tests/test_config_and_memory.py` |
| Audio and speech | `tests/test_speech.py`, `tests/test_runtime_voice.py` |
| Installation | `tests/test_setup_script.py` |
| Time/location/weather | `tests/test_location_weather.py`, `tests/test_weather_feature.py` |
| Timer | `tests/test_set_timer.py`, `tests/test_timer_ui.py` |
| Calendar | `tests/test_calendar.py` |
| Camera | `tests/test_camera.py` |
| Album | `tests/test_album.py` |
| GalaxyRVR remote | `tests/test_galaxy_rvr.py` |
| Learning | `tests/test_learning_curriculum.py`, `tests/test_learning_feature.py`, `tests/test_learning_store.py`, `tests/test_learning_ui.py` |
| Matching game | `tests/test_matching_game.py` |
| Twenty Questions | `tests/test_twenty_questions.py` |
| Compact face and quiet hours | `tests/test_compact_face.py`, `tests/test_quiet_hours.py` |
| Qt/QML production presentation | `tests/test_qt_shell.py` |

`tests/extension_modules/__init__.py` marks the proof-fixture package, and
`tests/__init__.py` is not present because pytest discovers the suite directly.

## Other repository material

| Path | Role |
| --- | --- |
| `README.md` | Operator setup, configuration, feature, customization, archive, and troubleshooting guide. |
| `docs/AGENT_ARCHITECTURE.md` | Detailed module boundaries, runtime behavior, extension contracts, failure isolation, and shutdown ownership. |
| `docs/AGENT_LEARNING.md` | Learning setup, scoring, persistence, teacher controls, and lesson extension. |
| `docs/AGENT_LOCATION_WEATHER.md` | Location/Weather privacy, providers, configuration, supported requests, and licensing. |
| `docs/GUI_MIGRATION.md` | Validated Qt/QML gates, remaining work, acceptance checks, and completion definition. |
| `faces/` | Fullscreen face animation frames. |
| `sounds/` | Greeting, acknowledgement, and thinking WAV effects. |
| `graphics/` | Existing referenced menu/game artwork. |
| `wakeword.onnx` | Wake-word inference model. |
