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

## Later safety gates

Stage 6 must keep memory bounded and reuse idempotent receipt. Stage 7 requires
all transferable attachment blobs before event ACK and represents partial state
explicitly. Stage 8 requires separate live access authorization and
evidence of no Apple-state mutation. Stage 9 requires a written live acceptance
checklist. Stage 10 must use the normal plugin lifecycle: disabled means no
port/listener/worker/store, failure cannot block startup, and cleanup releases
every resource.
