# iMessage Relay Progress

current_stage: 8
current_chapter: Stage 8 acceptance gate
state: complete
next_action: Stop and wait for explicit authorization before Stage 9 live relay validation.
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
| 9 — live relay | not started | requires separate live-delivery authorization |
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Validate bounded discovery and attachment resolution against the authorized
live Messages source while proving the validator does not mutate Apple-owned
database, WAL/SHM, attachment, message, or metadata state.

### Completed

- Added and tested a privacy-safe validator that fingerprints and copies the
  live DB/WAL/SHM trio into disposable local storage, opens SQLite only on the
  copy, exercises bounded parser/attachment reads, and emits aggregate
  diagnostics without content or identifiers.
- Accepted the authorized live environment, schema 89/WAL/query plan,
  filtering, clean repeat/restart, real attachment containment and unchanged
  bytes/metadata, content-free permission failure, graceful SIGINT, source
  fingerprint stability, and cleanup.
- A user-created non-sensitive incoming message changed the bounded live
  observation from 36 to 37 source rows and from 24 to 25 normalized message
  events with no parser issue or relay transmission.
- Cleanly unmounted SSHFS, closed the temporary authenticated control
  connection, and removed every Stage 8 temporary directory. Detailed
  content-free evidence is archived in `history/stage_8.md`.

### Remaining and boundary

No Stage 8 acceptance work remains. SQLite never opened the live source, no
write-capability probe was attempted, no remote file or setting was changed,
and no kiosk endpoint, sender delivery, deployment, daemon, or BMO runtime
integration was attempted. Stage 9 remains unauthorized until a separate
explicit request.

Known later-stage risks remain: production endpoint trust, TLS/key provisioning,
iPhone clock skew, scheduling, retention/pruning, and unverified edits,
retractions, emoji reactions, real group mutations, and real email handles.
