---
id: plugin.imessage_relay
type: plugin
plugin_type: feature/service
entrypoint: bmo.features.imessage_relay (opt-in)
status: experimental
progress: progress.md
tests: [tests/test_imessage_parser.py, tests/test_imessage_state.py, tests/test_imessage_receiver.py, tests/test_imessage_relay_e2e.py, tests/test_imessage_reconciliation.py, tests/test_imessage_attachments.py, tests/test_imessage_live_validation.py, tests/test_imessage_live_delivery.py, tests/test_imessage_runtime.py]
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
| normalized contracts/read-only parser | `bmo/features/imessage_relay/relay/{contracts,reader,attachments,attributed_body,timestamps}.py` |
| sender-side discovery/queue state | `bmo/features/imessage_relay/relay/{state,state_codec,state_config}.py` |
| sender and reconciliation | `bmo/features/imessage_relay/relay/{sender,reconciliation}.py` |
| stable live source snapshots | `bmo/features/imessage_relay/relay/live_source.py` |
| kiosk authentication/wire schema | `bmo/features/imessage_relay/receiver/{auth,protocol,config}.py` |
| kiosk receipt store/listener | `bmo/features/imessage_relay/receiver/{store,server}.py` |
| manual schema/live acceptance tools | `bmo/features/imessage_relay/tools/` |
| configuration examples | `config/example.imessage_relay.json`, `config/example.imessage_receiver.json`, disabled entry in `config/example.features.json` |
| BMO lifecycle/status/reconciliation adapter | `bmo/features/imessage_relay/feature.py` |
| Qt status view | `bmo/qt/views/imessage_relay.py`, `bmo/qt/qml/IMessageRelayView.qml` |

Stage 11 consolidates the reusable backend and manual tools under the BMO
plugin package. The adapter remains absent from feature defaults and starts
only when an explicit enabled feature entry names it. No root compatibility
package preserves the retired import identities.

## Implemented flow

1. `MessagesReader.scan()` opens an Apple Messages database read-only and
   returns immutable normalized events/issues plus a source boundary.
2. `RelayStateStore.commit_scan()` atomically persists payloads/issues and the
   cursor, then owns leases, retries, ACKs, dead letters, and restart recovery.
3. The standalone authenticated kiosk receiver strictly validates one event,
   reserves its nonce, commits canonical event JSON exactly once, and ACKs only
   after commit.
4. `RelaySender` claims Stage 3 entries and delivers them through a bounded
   HTTP(S) transport with fresh request authentication, strict ACK identity,
   durable retry/dead-letter outcomes, and content-free status. The complete
   path is verified only against invented local simulation data.
5. `RelayReconciler` re-scans an explicit recent/month window without moving
   the live cursor, compares bounded canonical event digests with kiosk
   receipts, and selectively requeues acknowledged events reported missing.
   Conflicts and kiosk-only history are never overwritten or deleted.
6. For an event with available attachment data, the receiver first persists a
   pending manifest. `RelaySender` hashes and sends each ordinary file or Live
   Photo component in authenticated 64-KiB chunks, resumes from kiosk-owned
   durable offsets, and acknowledges sender state only after a repeated event
   receives an attachment-complete ACK.
7. Stage 8 exposes an authorized Messages root through a read-only mount,
   copies the live DB/WAL/SHM trio to disposable local storage, and runs only
   privacy-safe schema, query-plan, parser, and attachment-read diagnostics.
8. The Stage 9 manual runner composes stable disposable source snapshots, the
   durable queue, attachment sender, and real loopback receiver. It injects
   bounded auth, outage, lost-ACK, and restart faults and emits only aggregate
   acceptance status. It creates no daemon or BMO integration.
9. The Stage 10 adapter owns an opt-in BMO receiver listener and content-free
   Qt status view. Explicit recent/month controls start at most one worker,
   use a disposable source snapshot, and reuse Stage 6 reconciliation against
   the in-process authenticated receiver application. It has no sender loop.

Stage 8 live read-only acceptance completed on 2026-09-02. Stage 9 has passed
its macOS rehearsal but remains incomplete until the same matrix passes on the
physical Raspberry Pi kiosk.

## Safety and failure boundaries

Apple's Messages database, WAL/SHM, attachments, metadata, and state are
strictly read-only: no insert/update/delete, read-state/reaction change, send,
checkpoint, attachment modification, or live-device deployment outside an
authorized stage. Relay and receiver state are separate private SQLite files;
receiver-owned partial and complete attachment files use a private sibling
directory.
Logs omit content/handles/paths by default. Network receipt never means
delivery without a validated kiosk ACK.

The receiver can run either as its explicit standalone process or inside the
enabled BMO feature lifecycle. BMO registration failure is content-free and
isolated; invalid private receiver configuration registers a visibly degraded
menu surface without a listener. Registry cleanup closes the view, joins a
reconciliation job, shuts the listener, closes the store, and releases its
port. No launch daemon or default enablement is authorized.

## Detailed routing

Read `progress.md` for the sole current stage. Read `architecture.md` for
lifecycle/safety ownership, `roadmap.md` for future stage gates, a component
doc for implementation, and `api/receiver_protocol.md` for the wire contract.
Schema evidence and completed-stage archives are opt-in.
