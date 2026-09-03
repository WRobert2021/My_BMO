# iMessage Relay Stage Roadmap

This file owns future stage definitions and authorization gates, not current
status. Read `progress.md` for current state. Every stage stops at its gate;
completion never authorizes the next stage.

| Stage | Objective | Gate / excluded work |
| --- | --- | --- |
| 0 | audit repository, private snapshots, tooling, safety | no schema implementation or live access |
| 1 | establish evidence-based Messages schema behavior | no parser/network/deployment |
| 2 | implement stateless read-only parser and immutable events | no queue/network/live device |
| 3 | implement relay-owned cursor, durable queue, retry/ACK/dead-letter state | no network service |
| 4 | implement local authenticated durable idempotent kiosk receiver | no sender integration or iPhone contact |
| 5 | connect parser/queue/sender/receiver in local simulation with fault injection | no live device; stop after fault matrix |
| 6 | add bounded recent/month reconciliation and selective resend | never delete kiosk-only history |
| 7 | add authenticated bounded streaming, digest/size checks, partial state, attachment-aware ACK | no whole-file memory loading |
| 8 | manually validate read-only discovery on authorized live iPhone | no live delivery or daemon |
| 9 | manually validate real iPhone-to-kiosk at-least-once delivery | no automatic startup |
| 10 | add optional failure-isolated runtime service/UI status and reconciliation controls | sending/daemon proposals remain separate scope |
| 11 | consolidate plugin implementation under `bmo.features.imessage_relay` | layout/import changes only; full tests required before completion |

## Stage 5 acceptance shape

Only after explicit authorization, build a simulated sender against the fixed
Stage 4 protocol. Use Stage 3 queue claims, fresh nonce/request ID per attempt,
the same canonical stable event, strict ACK validation, bounded backoff, and
content-free status. Test offline before/during send, dropped/lost ACK,
duplicate request, NACK/malformed response, sender/receiver restart, ordered
backlog, poison event, recovery, SIGINT, and resource cleanup. Stop when the
simulated acceptance matrix passes.

## Stage 6 acceptance shape

Only after explicit authorization, support exact recent and UTC calendar-month
windows with bounded source and state paging. Compare only sender-provided
stable IDs plus canonical wire digests, selectively requeue acknowledged
missing receipts, preserve conflicts, reuse normal idempotent delivery, and
never enumerate or delete kiosk-only history. Test repeated runs, malformed or
mismatched responses, maximum wire bounds, restart-safe durable receipts, and
both transport-neutral and real loopback paths. Stop when this matrix passes.

## Stage 7 acceptance shape

Only after explicit authorization, persist attachment-bearing events as pending
until every available ordinary file or Live Photo component passes declared
size and whole-file SHA-256 validation. Transfer with authenticated requests no
larger than 64 KiB, persist receiver-owned offsets/files for restart resume,
reject unavailable/changed sources and metadata-only ACKs, migrate existing
receiver receipts without loss, and never load a whole file into memory. Test
interruption/lost response, duplicate chunks, digest/offset mismatch, both
sender and receiver restart, source immutability, transport-neutral calls, and
real loopback HTTP. Stop before any live-iPhone access.

## Stage 8 acceptance shape

Only after explicit authorization, collect non-content environment and file
permission facts, mount only `/var/mobile/Library/SMS` read-only, and copy the
DB/WAL/SHM trio to disposable local storage before SQLite inspection. Validate
the live schema, WAL mode, expected ROWID-range plan, bounded iMessage
discovery, contained attachment access, restart/SIGINT behavior, and unchanged
source fingerprints. Natural concurrent Messages changes make a run
inconclusive. Do not change permissions, stop Messages, write to the phone,
contact the kiosk, install a daemon, or begin Stage 9 delivery.

## Stage 9 acceptance shape

Only after explicit authorization and a written checklist, run the standalone
relay and receiver manually in the Raspberry Pi kiosk's existing `.venv`.
Mount only the authorized phone SMS root read-only, open SQLite only on stable
disposable DB/WAL/SHM copies, keep relay/receiver state private and separate,
and send over authenticated literal kiosk loopback. Validate bounded supported
backlog, real attachments, offline recovery, authentication failure, lost ACK,
duplicate prevention, receiver/relay restart, one new live event, source
immutability, and complete cleanup. A macOS rehearsal cannot satisfy the Pi
gate. Stop before BMO registration, deployment, daemon, or automatic startup.

## Later safety gates

Stage 6 must keep memory bounded and reuse idempotent receipt. Stage 7 requires
all transferable attachment blobs before event ACK and represents partial state
explicitly. Stage 8 requires separate live access authorization and
evidence of no Apple-state mutation. Stage 9 requires a written live acceptance
checklist. Stage 10 must use the normal plugin lifecycle: disabled means no
port/listener/worker/store, failure cannot block startup, and cleanup releases
every resource.

## Stage 10 acceptance shape

After explicit authorization, add an opt-in BMO feature/service adapter without
changing the default feature list. Imports and menu metadata remain
resource-free; enabled registration starts the owned receiver listener only
after private config validation. Startup failure leaves a content-free degraded
status UI and cannot block BMO or later plugins. Provide aggregate status plus
explicit recent/month reconciliation controls that use stable disposable source
copies and the existing bounded idempotent protocol. Reject concurrent jobs and
fail closed when config, source, authentication, or storage is unavailable.
Close the view, reconciliation worker, listener, store, socket, and port exactly
once on registry shutdown. Validate with invented local data and offscreen Qt,
then stop before default enablement, private provisioning, deployment, daemon
installation, phone contact, or outbound Messages actions. Physical kiosk
touch/VNC, binding, restart, and stability evidence remains a final gate.

## Stage 11 acceptance shape

After explicit authorization, move the root relay and receiver packages, the
BMO feature adapter, and plugin-specific manual tools into one
`bmo.features.imessage_relay` package. Preserve the established Qt, test,
example-config, and documentation locations. Update every active import and CLI
reference without leaving compatibility shims or duplicate package identities.
Do not change behavior, schemas, dependencies, private configuration, runtime
enablement, or deployment. Structural/static checks must pass immediately; the
complete relay, shared extension/Qt, setup, and repository test suites must pass
before Stage 11 can be accepted.
