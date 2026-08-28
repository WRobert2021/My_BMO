# Agent Documentation Index

Read only the rows relevant to the current task. Paths are relative to this
directory. Plugin `progress.md` is needed only for continuation, staged work,
or status changes. Evidence and history are opt-in.

## Core routing

| Task | Read first | Additional only if needed |
| --- | --- | --- |
| repository/module/test ownership | [core/repo_map.md](core/repo_map.md) | relevant plugin overview |
| startup, runtime loop, shutdown | [core/runtime.md](core/runtime.md) | relevant plugin overview |
| add/change/remove a plugin | [core/extensions.md](core/extensions.md) | plugin overview; progress when staged |
| Qt/QML, menus, navigation, hosted views | [core/ui.md](core/ui.md) | relevant plugin overview |
| Raspberry Pi, setup, dependencies | [core/platform.md](core/platform.md) | relevant operator section in root README |
| shared JSON/atomic persistence | [core/persistence.md](core/persistence.md) | domain plugin persistence doc |
| scoped feature speech | [shared/scoped_announcements.md](shared/scoped_announcements.md) | consuming plugin overview |
| generic image/vision follow-up | [shared/vision_follow_up.md](shared/vision_follow_up.md) | Album or Capture Image overview |
| persistent runtime notices | [shared/runtime_attentions.md](shared/runtime_attentions.md) | Timer, Alarm Clock, or Calendar overview |

## Plugin routing

| Plugin | Type | Search triggers | Overview | Progress |
| --- | --- | --- | --- | --- |
| Get Time | feature | time, clock, current time | [overview](plugins/get_time/overview.md) | [progress](plugins/get_time/progress.md) |
| Timer | feature | timer, countdown, scheduler | [overview](plugins/timer/overview.md) | [progress](plugins/timer/progress.md) |
| Alarm Clock | feature | alarm, snooze, wall clock | [overview](plugins/alarm_clock/overview.md) | [progress](plugins/alarm_clock/progress.md) |
| Calendar | feature | calendar, events, recurrence, holidays | [overview](plugins/calendar/overview.md) | [progress](plugins/calendar/progress.md) |
| Location | feature | location, home, where am I | [overview](plugins/location/overview.md) | [progress](plugins/location/progress.md) |
| Weather | feature | weather, forecast, Open-Meteo, NWS | [overview](plugins/weather/overview.md) | [progress](plugins/weather/progress.md) |
| Web Search | feature | search, web, DuckDuckGo, DDGS | [overview](plugins/search_web/overview.md) | [progress](plugins/search_web/progress.md) |
| Capture Image | feature | camera, image, vision, libcamera | [overview](plugins/capture_image/overview.md) | [progress](plugins/capture_image/progress.md) |
| Album | feature | album, photos, Wastebasket, image analysis | [overview](plugins/album/overview.md) | [progress](plugins/album/progress.md) |
| Music | feature | music, Ogg, Opus, ffplay, playlist | [overview](plugins/music/overview.md) | [progress](plugins/music/progress.md) |
| Learning | feature | learning, Pre-K, curriculum, mastery | [overview](plugins/learning/overview.md) | [progress](plugins/learning/progress.md) |
| GalaxyRVR | feature | rover, RC, joystick, WebSocket, camera | [overview](plugins/galaxy_rvr/overview.md) | [progress](plugins/galaxy_rvr/progress.md) |
| Pup Pairs | mode | matching game, Pup Pairs, cards | [overview](plugins/matching_game/overview.md) | [progress](plugins/matching_game/progress.md) |
| Twenty Questions | mode | twenty questions, 20 questions, dataset | [overview](plugins/twenty_questions/overview.md) | [progress](plugins/twenty_questions/progress.md) |
| iMessage Relay | feature/service (experimental) | iMessage, relay, parser, receiver, ACK, Stage | [overview](plugins/imessage_relay/overview.md) | [progress](plugins/imessage_relay/progress.md) |

## Specialized relay routing

| Relay task | Read |
| --- | --- |
| ownership and intended plugin integration | [architecture.md](plugins/imessage_relay/architecture.md) |
| stage definitions or authorization gate | [roadmap.md](plugins/imessage_relay/roadmap.md), then progress |
| Apple database parser | [components/parser.md](plugins/imessage_relay/components/parser.md) |
| relay queue, retries, ACK state | [components/relay_state.md](plugins/imessage_relay/components/relay_state.md) |
| receiver implementation/config/lifecycle | [components/receiver.md](plugins/imessage_relay/components/receiver.md) |
| simulated sender, delivery loop, fault handling | [components/sender.md](plugins/imessage_relay/components/sender.md) |
| HTTP/HMAC wire contract | [api/receiver_protocol.md](plugins/imessage_relay/api/receiver_protocol.md) |
| Apple Messages schema evidence only | [evidence/messages_schema.md](plugins/imessage_relay/evidence/messages_schema.md) |
| completed-stage detail or legacy contradictions | [history](plugins/imessage_relay/history/) |

Project-wide Qt migration history is [opt-in](history/gui_migration.md); it is
not part of normal UI routing.
