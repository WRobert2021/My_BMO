# iMessage Relay Progress

current_stage: 9
current_chapter: Physical Raspberry Pi live-delivery acceptance
state: in_progress
next_action: Run the documented matrix in the authorized Raspberry Pi kiosk `.venv`, including a post-baseline live event and shutdown/retention decision.
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
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Validate authenticated at-least-once delivery of real phone data into durable
Raspberry Pi kiosk receiver state without weakening Apple-source safety or
enabling automatic startup.

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
  and authenticated control session then closed cleanly; private acceptance
  state remains retained pending the operator's explicit cleanup decision.
- Passed the complete isolated plugin suite: 99 tests and 17 subtests.

### Remaining and boundary

The current host is macOS, so its successful live rehearsal cannot complete
Stage 9. Physical Raspberry Pi 5/aarch64/Python 3.13.5 evidence remains
required, including the mount-loss/recovery window, a post-baseline user-made
non-sensitive event, synchronized-clock evidence, deliberate shutdown, and an
explicit operator decision about private acceptance-state retention. The Mac
rehearsal covered its equivalents but cannot substitute for Pi evidence. No
deployment, daemon, automatic startup, BMO registration, or Stage 10 work is
authorized.

Known later-stage risks remain: production endpoint trust, TLS/key provisioning,
iPhone clock skew, scheduling, retention/pruning, and unverified edits,
retractions, emoji reactions, real group mutations, and real email handles.
