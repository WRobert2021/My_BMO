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

Relay incoming iMessage text, photos, videos, and standard tapbacks from a
jailbroken iPhone to the kiosk with explicit durable kiosk ACKs and stable-ID
idempotency. Normal production flow is event-driven phone-to-kiosk push. The
kiosk must not mount, copy, or poll Apple's Messages database.

Stage 12 owns incoming delivery. Stage 13 will separately plan authenticated
outbound text replies, photo/video sends, and reactions. Direct Messages
database writes are prohibited in every stage.

## Current ownership

| Area | Owner/path |
| --- | --- |
| normalized contracts and read-only parser reference | `bmo/features/imessage_relay/relay/` |
| kiosk authentication and wire schema | `bmo/features/imessage_relay/receiver/` |
| kiosk receipt/attachment store and listener | `bmo/features/imessage_relay/receiver/` |
| kiosk lifecycle and private feed | `bmo/features/imessage_relay/feature.py` |
| Qt relay view | `bmo/qt/views/imessage_relay.py`, `bmo/qt/qml/IMessageRelayView.qml` |
| Stage 8/9 manual validation tools | `bmo/features/imessage_relay/tools/` |
| phone observer/backlog/sender | planned standalone sibling `phone_relay` project, Python 3.9.6 |

The completed sender, queue, reconciliation, and attachment work under
`bmo.features.imessage_relay.relay` remains the behavior reference and local
simulation harness. The production phone implementation must reproduce its
wire behavior in Python 3.9-compatible code without importing the Python
3.13-oriented BMO package.

## Implemented versus pending

Implemented and retained:

- read-only Apple schema parsing and normalized incoming event contracts;
- sender queue, retry, ACK, reconciliation, and attachment behavior in local
  simulation;
- authenticated kiosk HTTP(S) receiver with replay protection;
- durable idempotent kiosk receipts and resumable attachment storage;
- bounded recent/month receipt classification;
- opt-in BMO receiver lifecycle, private message feed, stable scrolling UI,
  aggregate status, and complete cleanup; and
- authorized manual live validation evidence through Stage 11.

Pending Stage 12 work:

- Python 3.9.6 phone filesystem observer and read-only incremental discovery;
- identifier-only phone backlog and deletion revalidation;
- exhausted retry latch reset only by an authenticated kiosk resume;
- phone-to-kiosk TLS delivery using the established event/attachment ACK
  contract;
- kiosk-to-phone resume control and infrequent phone-owned reconciliation; and
- physical deployment and acceptance without SSHFS or snapshots.

The abandoned Stage 12 SSHFS source manager, kiosk polling worker, persistent
phone-login configurator, and snapshot publisher are removed from active code.
Historical Stage 8/9 snapshot evidence remains opt-in and does not define the
production topology.

## Safety and lifecycle

Apple's database, WAL/SHM, attachments, permissions, metadata, and Messages
process state are read-only. The phone may write only its own private cursor,
identifier backlog, retry state, configuration, and logs containing bounded
non-content diagnostics. The kiosk owns a separate private receipt database and
attachment directory.

Import and metadata discovery remain resource-free. Enabled BMO registration
starts only the configured kiosk receiver. Until the phone control client is
implemented, the UI reports receiver readiness and disables reconciliation.
Disabled, invalid, or unavailable relay configuration cannot block BMO or any
other plugin. Cleanup closes the view, receiver socket/thread, and store.

Read `progress.md` for current state, `architecture.md` for boundaries,
`roadmap.md` for stage gates, `components/production_incoming.md` for the
corrected Stage 12 design, and `api/receiver_protocol.md` for the implemented
wire contract.
