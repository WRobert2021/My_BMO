# Repository Ownership Map

This is the sole active project-wide `source path -> responsibility -> owner`
map. Plugin overviews contain only their local subset.

## Launch, platform, and core

| Path | Responsibility | Owner |
| --- | --- | --- |
| `agent.py`, `qt_agent.py` | production Qt launch | core runtime/UI |
| `typed_agent.py` | production Qt typed-debug launch; lazy legacy export | core UI |
| `tk_agent.py` | explicit temporary Tk fallback | compatibility |
| `start_agent.sh`, `be-more-agent.desktop` | operator launch | platform/operator |
| `setup.sh`, `requirements*.txt` | Pi installation and Python dependencies | platform |
| `bmo/runtime.py` | service composition, conversation, speech, persistence, shutdown | core runtime |
| `bmo/runtime_loop.py`, `runtime_voice.py` | worker arbitration and voice-turn execution | core runtime |
| `bmo/runtime_extensions.py`, `runtime_menu.py` | registry lifetime and queued menu work | core extensions |
| `bmo/config.py` | split settings/extension config and global defaults | core configuration |
| `bmo/extensions.py` | configured import, transaction, rollback, isolation | core extensions |
| `bmo/features/contracts.py`, `registry.py`, `loader.py` | feature API, lifecycle, defaults | feature framework |
| `bmo/modes/contracts.py`, `registry.py`, `loader.py` | mode API, input ownership, defaults | mode framework |
| `bmo/conversation.py`, `intent.py`, `prompts.py`, `tools.py` | generic model/tool routing and presentation | core conversation |
| `bmo/audio.py`, `speech.py` | device audio, wake word, transcription, Piper | core speech/audio |
| `bmo/archive.py`, `memory.py`, `jsonio.py` | archives, conversation memory, strict JSON/atomic writes | shared persistence |
| `bmo/text.py`, `network.py`, `state.py` | narrow shared normalization/timeout/state values | shared core |
| `bmo/kiosk_access.py` | Quiet Hours schedule and unlock state | core kiosk policy |

## UI and compatibility

| Path | Responsibility | Owner |
| --- | --- | --- |
| `bmo/qt/app.py`, `presentation.py`, `controller.py` | Qt engine, queued presentation, global UI state | core UI |
| `bmo/qt/view_host.py`, `bmo/qt/views/base.py` | one active hosted view and base adapter | core UI |
| `bmo/qt/views/<plugin>.py` | plugin-to-QML adapters | named plugin |
| `bmo/qt/qml/Main.qml`, `HostedView.qml` | root face/menu/overlay/view shell | core UI |
| `bmo/qt/qml/*View.qml`, weather scene helpers | plugin screens | named plugin |
| `bmo/menu_model.py`, `menu_catalog.py`, `menu_loader.py` | neutral menu geometry, routing, metadata | core UI/extensions |
| `bmo/face_config.py`, `gestures.py`, `view_factory.py` | neutral face/gesture/view discovery | shared UI |
| `bmo/app.py`, `bmo/ui/`, `bmo/typed_tk.py` | explicit legacy Tk presentation | compatibility |
| `bmo/matching_game_core.py`, `matching_game_text.py` | toolkit-neutral Pup Pairs support | Pup Pairs |
| `bmo/twenty_questions*.py` | dataset engine, text/contracts, legacy UI | Twenty Questions |

## Plugin inventory

| Plugin | Type | Entrypoint | Config | UI | Persistence | Background resources | Primary tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Get Time | feature | `bmo.features.get_time` | shared settings only | none | none | none | `test_tool_routing*`, `test_feature_loading.py` |
| Timer | feature | `bmo.features.set_timer` | feature settings | Timer Qt/Tk | in memory | scheduler thread after use | `test_set_timer.py`, `test_timer_ui.py` |
| Alarm Clock | feature | `bmo.features.alarm_clock` | `alarm_config.py` | Alarm Qt/Tk | `alarm_store.py` | wall-clock worker | `test_alarm_clock.py` |
| Calendar | feature | `bmo.features.calendar` | `calendar_config.py` | Calendar Qt/Tk | `calendar_store.py` | local-date worker | `test_calendar.py` |
| Location | feature | `bmo.features.get_location` | shared home settings | none | none | network per request if geocoding | `test_location_weather.py` |
| Weather | feature | `bmo.features.get_weather` | weather config/alerts | Weather Qt/Tk/web | view cache only | bounded view fetch workers | `test_weather_feature.py`, `test_location_weather.py` |
| Web Search | feature | `bmo.features.search_web` | shared timeout | none | archive output | network per request | `test_tool_routing*`, `test_tool_presentation.py` |
| Capture Image | feature | `bmo.features.capture_image` | feature/shared camera settings | global overlay | interaction/persistent image | bounded subprocess per request | `test_camera.py` |
| Album | feature | `bmo.features.album` | feature settings | Album Qt/Tk | filesystem/Trash | none | `test_album.py` |
| Music | feature | `bmo.features.music` | `music_config.py` | Music Qt/Tk | `music_store.py` | one `ffplay` child | `test_music.py` |
| Learning | feature | `bmo.features.learning` | learning `config.py` | Learning Qt/Tk | learning `store.py`/`codec.py` | scoped speech only | `test_learning_*.py` |
| GalaxyRVR | feature | `bmo.features.galaxy_rvr` | `galaxy_rvr_config.py` | GalaxyRVR Qt/Tk | snapshots only | joystick/network/photo workers while open | `test_galaxy_rvr.py` |
| Pup Pairs | mode | `bmo.modes.matching_game` | mode settings | Matching Qt/Tk | score history | mode/UI lifecycle | `test_matching_game.py`, `test_modes.py` |
| Twenty Questions | mode | `bmo.modes.twenty_questions` | mode settings | Twenty Questions Qt/legacy | learned JSONL/history JSON | model calls during mode | `test_twenty_questions.py`, `test_modes.py` |
| iMessage Relay | feature/service, experimental | opt-in `bmo.features.imessage_relay`; backends `iphone_relay`, `kiosk_receiver` | two domain examples plus disabled feature entry | Relay Qt status/reconciliation view | receiver SQLite plus per-job relay SQLite | enabled receiver listener; one on-demand reconciliation worker | `test_imessage_*.py` |

## Relay and tooling

| Path | Responsibility | Owner |
| --- | --- | --- |
| `iphone_relay/contracts.py`, `reader.py`, `attachments.py`, `attributed_body.py`, `timestamps.py` | immutable events and read-only Apple parsing | iMessage Relay parser |
| `iphone_relay/state.py`, `state_codec.py`, `state_config.py` | discovery cursor, durable queue/retry/ACK, strict payload/config | iMessage Relay state |
| `kiosk_receiver/auth.py`, `protocol.py`, `config.py` | HMAC, wire schema, private config | iMessage Relay receiver |
| `kiosk_receiver/store.py`, `server.py` | idempotent receipt store and standalone HTTP(S) listener | iMessage Relay receiver |
| `bmo/features/imessage_relay.py`, `bmo/qt/views/imessage_relay.py`, `bmo/qt/qml/IMessageRelayView.qml` | opt-in BMO lifecycle, status, reconciliation controls, and Qt view | iMessage Relay runtime integration |
| `scripts/inspect_imessage_schema.py` | redacted disposable-snapshot evidence probe | relay development tooling |
| `config/example.*.json` | tracked schemas without private values | core or named plugin |
| `tests/extension_modules/` | importable registration proof fixtures | extension framework tests |
| `tests/test_*` | focused core/plugin/platform/integration coverage | corresponding row above |

Root `README.md` is human/operator-facing. `faces/`, `sounds/`, and referenced
`graphics/` are runtime assets; `graphics/` is locally copyrighted and
read-only under repository policy.
