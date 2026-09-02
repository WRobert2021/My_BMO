# iMessage Relay Progress

current_stage: 10
current_chapter: Physical kiosk runtime/UI acceptance
state: in_progress
next_action: When the kiosk returns online, run the documented Stage 9 Pi matrix, then Stage 10 touch/VNC, listener binding, shutdown/restart, and stability acceptance without default enablement or deployment.
last_verified: 2026-09-02

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0 — audit/snapshot validation | complete | private inputs and read-only boundary established |
| 1 — schema investigation | complete | evidence and explicit gaps preserved |
| 2 — read-only parser | complete | immutable normalized events and sanitized tests |
| 3 — relay state/durable queue | complete | atomic cursors, retries, ACK/dead-letter state |
| 4 — kiosk receiver prototype | complete | authenticated durable idempotent local receiver |
| 5 — simulated end-to-end relay | complete | local fault matrix and cleanup accepted |
| 6 — reconciliation | complete | bounded recent/month selective repair accepted |
| 7 — attachment transfer | complete | bounded resumable digest-verified transfer accepted |
| 8 — live iPhone read-only integration | complete | live disposable-copy discovery and source immutability accepted |
| 9 — live relay | in progress | authorized; checklist written; Pi acceptance pending |
| 10 — runtime/UI integration | in progress | offline implementation/tests complete; physical kiosk acceptance pending |

## Current chapter

### Objective

Integrate the stable backend contracts into BMO's opt-in feature lifecycle with
content-free status and explicit reconciliation controls. The kiosk is offline,
so implementation and tests use invented local data only.

### Completed

- Received explicit Stage 9 authorization and wrote the required live
  acceptance matrix in `components/live_delivery_validation.md` before live
  delivery work.
- Chose a manual kiosk-side pull topology: SSHFS `ro` plus disposable source
  copies on the Pi, private Pi-owned queue/receiver state, and authenticated
  literal-loopback HTTP. No code or secret is deployed to the phone.
- Confirmed the phone's Python 3.9.9 cannot host the repository's Python
  3.13-oriented relay package; changing or upgrading phone Python is not in
  scope. The pull topology avoids that unsupported deployment constraint.
- Implemented stable disposable source snapshots and a bounded manual
  acceptance runner with no import-time resources, tracked private data, or
  persistent secret.
- Passed the macOS live rehearsal for supported backlog, real attachments,
  authentication failure, lost ACK, receiver outage, duplicate prevention,
  relay/receiver restart, stable source evidence, and missing-source failure.
- A second macOS pass discovered and durably acknowledged exactly one new
  post-baseline text event with no issue or pending entry. The read-only mount
  and authenticated control session then closed cleanly. The operator chose
  cleanup, and the private macOS acceptance-state directory was deleted and
  verified absent.
- Passed the complete isolated plugin suite: 99 tests and 17 subtests.
- Received explicit Stage 10 authorization while the kiosk is offline and wrote
  `components/runtime_integration.md` before implementation. Stage 9 remains
  incomplete rather than being implicitly waived.
- Implemented the non-default `bmo.features.imessage_relay` adapter. Enabled
  registration owns one receiver listener/store; missing private config yields
  a content-free degraded status surface, while disabled/metadata loading opens
  no resources.
- Added the Qt status view with aggregate receiver counts and explicit recent/
  UTC-month reconciliation controls. Reconciliation is single-job, uses stable
  disposable source copies and the existing authenticated Stage 6 protocol,
  and opens relay state only inside its worker.
- Added invented Stage 10 tests for lifecycle, isolation, real loopback receipt,
  recent/month repair, source/config failure, redaction, Qt actions, cleanup,
  worker join, store close, and port release. Focused result: 12 passed. Shared
  extension/runtime-menu/Qt result: 114 passed and 51 subtests passed.
- Passed the complete iMessage Relay suite: 111 tests and 17 subtests. Passed
  the complete repository suite: 820 tests and 10,002 subtests.

### Remaining and boundary

Offline Stage 10 implementation acceptance is complete. Stage 10 remains absent
from defaults and reads private config or starts resources only when explicitly
enabled. Physical touch/VNC, listener binding, shutdown/restart, and long-run
stability remain unverified while the kiosk is offline. No phone/kiosk contact,
private provisioning, deployment, daemon, sender loop, or outbound Messages
action was performed.

Stage 9 still requires its physical Raspberry Pi 5/aarch64/Python 3.13.5 matrix.
Stage 10 additionally requires physical kiosk touch/VNC, listener binding,
shutdown/restart, and stability evidence after the kiosk returns online.

Known later-stage risks remain: production endpoint trust, TLS/key provisioning,
iPhone clock skew, scheduling, retention/pruning, and unverified edits,
retractions, emoji reactions, real group mutations, and real email handles.
