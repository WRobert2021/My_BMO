---
id: plugin.imessage_relay
type: plugin
plugin_type: feature/service
entrypoint: future registry adapter; current packages iphone_relay and kiosk_receiver
status: experimental
progress: progress.md
tests: [tests/test_imessage_parser.py, tests/test_imessage_state.py, tests/test_imessage_receiver.py]
---

# Plugin: iMessage Relay

## Purpose

Incrementally relay incoming iMessage text, photos, videos, and standard
tapbacks from a jailbreak/rootless iPhone to the kiosk with at-least-once
delivery, explicit durable kiosk ACKs, and stable-ID idempotency. Content flows
iPhone-to-kiosk only; control traffic may be bidirectional. SMS/MMS and sending
through Messages are out of scope.

## Current versus intended ownership

| Area | Current owner/path |
| --- | --- |
| normalized contracts/read-only parser | `iphone_relay/contracts.py`, `reader.py`, `attachments.py`, `attributed_body.py`, `timestamps.py` |
| sender-side discovery/queue state | `iphone_relay/state.py`, `state_codec.py`, `state_config.py` |
| kiosk authentication/wire schema | `kiosk_receiver/auth.py`, `protocol.py`, `config.py` |
| kiosk receipt store/listener | `kiosk_receiver/store.py`, `server.py` |
| configuration examples | `config/example.imessage_relay.json`, `config/example.imessage_receiver.json` |
| UI/registry adapter | not implemented |

The current source is intentionally standalone and is not imported, enabled,
or started by the BMO runtime. Architectural ownership is nevertheless the
iMessage Relay plugin. Future integration must use normal plugin lifecycle and
failure isolation; do not move packages merely to make paths look integrated.

## Implemented flow

1. `MessagesReader.scan()` opens an Apple Messages database read-only and
   returns immutable normalized events/issues plus a source boundary.
2. `RelayStateStore.commit_scan()` atomically persists payloads/issues and the
   cursor, then owns leases, retries, ACKs, dead letters, and restart recovery.
3. The standalone authenticated kiosk receiver strictly validates one event,
   reserves its nonce, commits canonical event JSON exactly once, and ACKs only
   after commit. It does not yet consume Stage 3 queue entries; that is Stage 5.

## Safety and failure boundaries

Apple's Messages database, WAL/SHM, attachments, metadata, and state are
strictly read-only: no insert/update/delete, read-state/reaction change, send,
checkpoint, attachment modification, or live-device deployment outside an
authorized stage. Relay and receiver state are separate private SQLite files.
Logs omit content/handles/paths by default. Network receipt never means
delivery without a validated kiosk ACK.

The receiver currently runs only as an explicitly started standalone process.
No launch daemon is authorized. Current stores/listeners close explicitly.
Future plugin startup failure must mark only Relay unavailable/degraded while
the application and unrelated plugins continue.

## Detailed routing

Read `progress.md` for the sole current stage. Read `architecture.md` for
lifecycle/safety ownership, `roadmap.md` for future stage gates, a component
doc for implementation, and `api/receiver_protocol.md` for the wire contract.
Schema evidence and completed-stage archives are opt-in.
