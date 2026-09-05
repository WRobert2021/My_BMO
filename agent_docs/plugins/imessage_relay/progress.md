# iMessage Relay Progress

current_stage: 9
current_chapter: Physical Raspberry Pi live relay acceptance
state: in_progress
next_action: Diagnose the failed-closed read-only SSHFS/SFTP session on the physical Pi, then run the Stage 9 live relay matrix and complete the Stage 10 physical UI/lifecycle gate.
last_verified: 2026-09-05

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
| 11 — package cleanup | complete | nested layout accepted after Pi relay/shared/full suites passed |
| 12 — outbound Messages bridge | planned | deferred until incoming Stages 9/10 are accepted; not authorized |

## Current chapter

### Objective

Complete the physical Raspberry Pi incoming-relay matrix using a read-only
iPhone Messages mount, private Pi-owned state, and authenticated kiosk
loopback, without deployment or writes to the phone.

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
- Received explicit Stage 11 cleanup authorization and recorded the approved
  nested package layout in `components/package_cleanup.md`. The operator asked
  to defer all pytest execution until the kiosk is online.
- Consolidated the feature adapter, relay, receiver, and plugin-owned manual
  tools under `bmo.features.imessage_relay`; rewrote source/test imports and
  module-mode CLI references; and removed the three legacy root directories
  without compatibility shims.
- Updated active ownership, architecture, API, component, evidence, roadmap,
  and index documentation for the nested package. Historical archives remain
  unchanged.
- Passed offline static acceptance: Python compilation for the nested package
  and iMessage Relay tests, resource-free imports for the package and all tool
  modules, active-reference and legacy-directory inspection, example feature
  JSON validation, and `git diff --check`.
- The first physical Raspberry Pi relay-suite run reached 108 passed, 2
  skipped, and 17 subtests passed, with one failure. The failure exposed a
  platform-specific false source-change result because validation fingerprints
  included access time even though hashing may update it on the Pi.
- Removed access time from source and attachment stability metadata, retaining
  mode, owner, size, modification/change time, and SHA-256 checks. Added an
  access-time-only regression. Local verification passed: the focused module
  reported 7 tests and 3 subtests passed, and the complete relay suite reported
  112 tests and 17 subtests passed.
- The physical Raspberry Pi rerun passed with 110 tests, 2 expected
  missing-snapshot skips, and 17 subtests in 7.32 seconds. This clears the
  Stage 11 plugin-specific suite gate.
- The physical Raspberry Pi shared extension/runtime-menu/Qt/setup suite passed
  with 71 tests and 40 subtests in 11.64 seconds.
- The complete physical Raspberry Pi repository suite passed with 825 tests,
  2 expected missing-snapshot skips, and 10,002 subtests in 23.86 seconds with
  exit status zero. Stage 11 is accepted.
- Physical Stage 9 preflight passed on Raspberry Pi 5 Model B Rev 1.1,
  `aarch64`, Python 3.13.5, SQLite 3.46.1, and an NTP-synchronized clock.
- Physical setup also confirmed SSHFS 3.7.3, FUSE 3.17.2, and `fusermount3`
  3.17.2. `setup.sh` now detects the existing system commands, idempotently
  verifies/installs the Raspberry Pi OS `sshfs` package, and requires both
  commands after installation; setup tests and platform/operator docs own this
  contract.
- The first Pi `ro` SSHFS attempt as the read-only phone account failed with
  `Connection reset by peer` before a mount was established. The mount/work
  directories retained mode `0700`, and the DB/WAL/SHM trio remained
  unreadable, so the attempt failed closed without reading or changing phone
  data. Stage 9 is still pending transport/SFTP-session diagnosis.
- The operator confirmed outbound text replies, photo/video sends, and
  reactions remain final product requirements. A separately authorized Stage
  12 will plan a phone-side bridge and Python 3.9.9 environment only after the
  incoming Stage 9/10 gates; no phone environment or outbound behavior is
  authorized now.

### Remaining and boundary

Stage 11 is complete. Its relocation/static checks, physical-Pi relay suite,
shared extension/runtime-menu/Qt/setup suite, and complete repository suite all
pass after the access-time portability correction.

Offline Stage 10 implementation acceptance is complete. Stage 10 remains absent
from defaults and reads private config or starts resources only when explicitly
enabled. Physical touch/VNC, listener binding, shutdown/restart, and long-run
stability remain unverified while the kiosk is offline. No phone/kiosk contact,
private provisioning, deployment, daemon, sender loop, or outbound Messages
action was performed.

Stage 9 still requires its physical Raspberry Pi 5/aarch64/Python 3.13.5 matrix.
Stage 10 additionally requires physical kiosk touch/VNC, listener binding,
shutdown/restart, and stability evidence on the now-online kiosk.

Stage 12 outbound planning remains queued behind incoming Stage 9 and Stage 10.
The proposed iPhone Python 3.9.9 environment and any additional phone-side
dependency, service, credential, or daemon must be evaluated and explicitly
authorized in that stage; no direct Apple database write is permitted.

Known later-stage risks remain: production endpoint trust, TLS/key provisioning,
iPhone clock skew, scheduling, retention/pruning, and unverified edits,
retractions, emoji reactions, real group mutations, and real email handles.
