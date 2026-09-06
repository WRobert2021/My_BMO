---
id: plugin.imessage_relay
type: plugin
plugin_type: feature/service
entrypoint: bmo.features.imessage_relay (opt-in)
status: experimental
progress: progress.md
tests: [tests/test_imessage_parser.py, tests/test_imessage_state.py, tests/test_imessage_receiver.py, tests/test_imessage_relay_e2e.py, tests/test_imessage_reconciliation.py, tests/test_imessage_attachments.py, tests/test_imessage_live_validation.py, tests/test_imessage_live_delivery.py, tests/test_imessage_runtime.py, tests/test_imessage_phone_control.py]
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
| phone observer/backlog/sender/service | standalone sibling `phone_relay` project, Python 3.9.6 |

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

Implemented in the local Stage 12 runtime:

- Python 3.9.6 Darwin filesystem observation and bounded read-only incremental
  discovery;
- identifier-only backlog, deletion prune, and a resume-only exhausted retry
  latch integrated with the delivery service;
- just-in-time text, reaction, photo, and video materialization plus bounded
  attachment streaming;
- phone-to-kiosk TLS/HMAC delivery using the established event/attachment ACK
  contract;
- authenticated kiosk-to-phone health, resume, and reconciliation control; and
- kiosk-scheduled, phone-executed bounded receipt reconciliation.

Pending Stage 12 work is private TLS/HMAC provisioning, reviewed phone launchd
installation, physical `kqueue` and live schema verification, and the complete
physical incoming acceptance matrix without SSHFS or snapshots.

The abandoned Stage 12 SSHFS source manager, kiosk polling worker, persistent
phone-login configurator, and snapshot publisher are removed from active code.
Historical Stage 8/9 snapshot evidence remains opt-in and does not define the
production topology.

The kiosk now has strict private phone-control configuration, authenticated
health/resume/reconciliation requests, a startup resume, content-free network
probes, weekly in-process scheduling, and owned cleanup. The standalone phone
project has strict private configuration, durable identifier/cursor/retry/nonce
state, read-only source handling, sender, control listener, and explicit
service lifecycle. All phone modules import and test under CPython 3.9.6.

## Safety and lifecycle

Apple's database, WAL/SHM, attachments, permissions, metadata, and Messages
process state are read-only. The phone may write only its own private cursor,
identifier backlog, retry state, configuration, and logs containing bounded
non-content diagnostics. The kiosk owns a separate private receipt database and
attachment directory.

Import and metadata discovery remain resource-free. Enabled BMO registration
starts the configured kiosk receiver and independently starts phone control
when its private configuration is valid. Either side may degrade without
blocking BMO or any other plugin. Cleanup closes the view, control
worker/transport, receiver socket/thread, and store.

Read `progress.md` for current state, `architecture.md` for boundaries,
`roadmap.md` for stage gates, `components/production_incoming.md` for the
corrected Stage 12 design, and `api/receiver_protocol.md` for the implemented
wire contract.
