# iMessage Relay Progress

current_stage: 8
current_chapter: Live iPhone read-only integration
state: in_progress
next_action: Restore local reachability to the authorized iPhone, then run and record the Stage 8 live checklist.
last_verified: 2026-09-01

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
| 8 — live iPhone read-only integration | in progress | authorized; local validator ready; target unreachable |
| 9 — live relay | not started | blocked by Stage 8 acceptance |
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Validate bounded discovery and attachment resolution against the authorized
live Messages source while proving the validator does not mutate Apple-owned
database, WAL/SHM, attachment, message, or metadata state.

### Completed

- Received explicit Stage 8 authorization and an SSH target; the private target
  is not stored in tracked files.
- Added a privacy-safe validator that never opens the live SQLite database. It
  fingerprints and copies the DB/WAL/SHM trio into disposable local storage,
  validates stability, schema/WAL/query-plan/parser behavior on that copy, and
  emits only aggregate diagnostics.
- Added bounded attachment read verification and invented WAL-fixture tests for
  source and attachment immutability, output redaction, trio/source-change
  failures, and scan bounds.
- Attempted non-interactive SSH and ICMP reachability. Both stopped before
  authentication with `No route to host`; no command reached the phone.

### Remaining acceptance work

- Record iOS/kernel, remote Python/SQLite, and Messages trio permission facts.
- Run the validator through a read-only mount during a quiet source window and
  record a content-free passing report, including a real available attachment
  when present.
- Verify a clean second run/restart, bounded discovery of a user-created test
  row, graceful interruption/unmount, and fail-closed permission behavior.
- Confirm before/after Apple DB/WAL/SHM and attachment observations are stable.

### Blocker and boundary

The local host currently has a route assigned through `en0`, but the authorized
device does not answer and reports `No route to host`. Stage 8 acceptance is
therefore incomplete. No live database was opened, no remote file or setting
was changed, and no kiosk endpoint, sender delivery, deployment, daemon, or BMO
runtime integration was attempted. Stage 9 remains unauthorized.

Known later-stage risks remain: production endpoint trust, TLS/key provisioning,
iPhone clock skew, scheduling, retention/pruning, and unverified edits,
retractions, emoji reactions, real group mutations, and real email handles.
