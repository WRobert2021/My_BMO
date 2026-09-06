---
id: plugin.imessage_relay
type: plugin
plugin_type: feature/service
entrypoint: bmo.features.imessage_relay (opt-in)
status: experimental
progress: progress.md
tests: [tests/test_imessage_parser.py, tests/test_imessage_state.py, tests/test_imessage_receiver.py, tests/test_imessage_relay_e2e.py, tests/test_imessage_reconciliation.py, tests/test_imessage_attachments.py, tests/test_imessage_live_validation.py, tests/test_imessage_live_delivery.py, tests/test_imessage_runtime.py, tests/test_imessage_phone_control.py, tests/test_imessage_notifications.py]
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
| read-only notification count API | `bmo/features/imessage_relay/notifications.py` |
| kiosk lifecycle and private feed | `bmo/features/imessage_relay/feature.py` |
| Qt relay view | `bmo/qt/views/imessage_relay.py`, `bmo/qt/qml/IMessageRelayView.qml` |
| Stage 8/9 manual validation tools | `bmo/features/imessage_relay/tools/` |
| phone observer/backlog/sender/service | standalone sibling `phone_relay` project, Python 3.9 compatible; physical CPython 3.9.9 |

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

- Python 3.9-compatible Darwin filesystem observation and bounded read-only incremental
  discovery;
- identifier-only backlog, deletion prune, and a resume-only exhausted retry
  latch integrated with the delivery service;
- just-in-time text, reaction, photo, and video materialization plus bounded
  attachment streaming;
- phone-to-kiosk TLS/HMAC delivery using the established event/attachment ACK
  contract;
- authenticated kiosk-to-phone health, resume, and reconciliation control;
- kiosk-scheduled, phone-executed bounded receipt reconciliation;
- a read-only kiosk message-count/delta API for a future notification badge;
  and
- a dedicated-account launchd definition plus bounded phone maintenance
  command for status, full stop, start, and confirmed uninstall.

The dedicated non-login `pi-bmo` service account is now provisioned on the
phone as UID 1002 and GID 1001. Pending Stage 12 work is private TLS/HMAC
provisioning, a verified inherited read-only ACL for Apple SMS input, reviewed
phone launchd installation, physical `kqueue` and live schema verification,
and the complete physical incoming acceptance matrix without SSHFS or
snapshots.

The abandoned Stage 12 SSHFS source manager, kiosk polling worker, persistent
phone-login configurator, and snapshot publisher are removed from active code.
Historical Stage 8/9 snapshot evidence remains opt-in and does not define the
production topology.

The kiosk now has strict private phone-control configuration, authenticated
health/resume/reconciliation requests, a startup resume, content-free network
probes, weekly in-process scheduling, and owned cleanup. The standalone phone
project has strict private configuration, durable identifier/cursor/retry/nonce
state, read-only source handling, sender, control listener, and explicit
service lifecycle. All phone modules import and test under local CPython 3.9.6;
the physical phone provides CPython 3.9.9 for deployment verification.

## Safety and lifecycle

Apple's database, WAL/SHM, attachments, metadata, and Messages process state are
read-only. The phone may write only its own private cursor, identifier backlog,
retry state, configuration, and logs containing bounded non-content
diagnostics. The phone daemon runs as a dedicated non-login `pi-bmo` identity;
`mobile` remains the administrator and is not the service identity. A narrowly scoped inherited
read/traverse ACL is required for `pi-bmo` to consume Apple SMS input without
write authority; Apple ownership and POSIX mode bits remain unchanged. The
kiosk owns a separate private receipt database and attachment directory.

Import and metadata discovery remain resource-free. Enabled BMO registration
starts the configured kiosk receiver and independently starts phone control
when its private configuration is valid. Either side may degrade without
blocking BMO or any other plugin. Cleanup closes the view, control
worker/transport, receiver socket/thread, and store.

Read `progress.md` for current state, `architecture.md` for boundaries,
`roadmap.md` for stage gates, `components/production_incoming.md` for the
corrected Stage 12 design, `api/receiver_protocol.md` for the implemented wire
contract, and `api/notifications.md` for the future badge-facing count API.
