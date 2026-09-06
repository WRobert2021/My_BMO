# iMessage Relay Progress

current_stage: 12
current_chapter: Production incoming activation
state: in_progress
next_action: Provision the Stage 12 phone publisher and private kiosk configuration, then accept one automatic live arrival and restart/outage recovery; stop before Stage 13 outbound work.
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
| 9 — live relay | complete | physical Pi matrix, live event, SIGINT, and cleanup accepted |
| 10 — runtime/UI integration | complete | physical Pi lifecycle, UI, reconciliation, restart, shutdown, and stability accepted |
| 11 — package cleanup | complete | nested layout accepted after Pi relay/shared/full suites passed |
| 12 — production incoming activation | in progress | implementation and invented tests pass; physical activation remains |
| 13 — outbound Messages bridge | planned | not authorized |

## Current chapter

### Objective

Activate the already tested incoming relay as an opt-in persistent kiosk
service: automatically access the restricted read-only phone export, discover
and deliver new events, and present them locally without beginning outbound
Messages work.

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
  3.17.2. The installed Debian package is the patched
  `3.7.3-1.2~deb13u1` revision, and the physical target setup-contract suite
  passed with 12 tests in 0.07 seconds. `setup.sh` now detects the existing
  system commands, idempotently verifies/installs the Raspberry Pi OS `sshfs`
  package, and requires both commands after installation; setup tests and
  platform/operator docs own this contract.
- The first Pi `ro` SSHFS attempt as the read-only phone account failed with
  `Connection reset by peer` before a mount was established. The mount/work
  directories retained mode `0700`, and the DB/WAL/SHM trio remained
  unreadable, so the attempt failed closed without reading or changing phone
  data. A subsequent `sftp -vvv -b /dev/null` probe proved that TCP and SSH key
  exchange succeed, but strict verification rejects the phone because the Pi
  has no trusted host-key entry. Authentication and SFTP were never reached.
  At that point Stage 9 was pending independent ED25519 fingerprint
  verification and local Pi `known_hosts` provisioning; automatic host-key
  acceptance remained forbidden.
- The operator independently compared the Pi-observed ED25519 fingerprint with
  the Mac's existing trusted `known_hosts` entry and confirmed an exact match.
  Endpoint identity verification was complete. At that point Stage 9 required
  adding only that verified public key to the Pi's local `known_hosts`, followed
  by the no-operation SFTP probe; automatic acceptance remained forbidden.
- The verified ED25519 key was added to the Pi, and the repeated empty-batch
  probe passed strict verification, passwordless `agent` authentication, SFTP
  v3 subsystem startup, root resolution to `/`, clean shutdown, and exit status
  zero without opening an Apple data path. OpenSSH's signed host-key update also
  learned the server's RSA and ECDSA keys; both matched the independently
  trusted Mac fingerprints already supplied by the operator. The next gate is
  metadata/read-permission inspection of only the known SMS root and DB trio,
  followed by a read-only SSHFS retry.
- The metadata-only SFTP probe entered `/var/mobile/Library/SMS` and resolved
  its canonical path as `/private/var/mobile/Library/SMS`, but an exact lookup
  of `sms.db` returned not found. The batch stopped before WAL/SHM checks and no
  database bytes were read. The `agent` namespace therefore permits traversal
  but has not proved live-database visibility. Next compare only fixed-path
  existence and metadata through the authorized `mobile` shell; do not change
  phone permissions or SFTP configuration during diagnosis.
- The read-only `mobile` shell comparison confirmed the SMS directory is mode
  `0700`, owned by `mobile:mobile`, and that the DB/WAL/SHM files exist with
  mode `0644`. The parent directory prevents the separate `agent` UID from
  traversing to those files, explaining the SFTP not-found result. No phone
  permission or configuration change was made. Stage 9 now needs an explicit
  operator choice: use `mobile` with client-enforced SSHFS `ro`, or separately
  authorize and review a server-enforced read-only access design for `agent`.
- The operator chose the server-enforced redesign and authorized exactly the
  DB/WAL/SHM trio plus `Attachments`, preserving the Stage 9 photo/video scope.
  The target account must use a password, forced read-only SFTP, a root-owned
  path boundary, and no shell or forwarding. No Apple permission weakening,
  other phone visibility, daemon, or automatic startup is authorized. The next
  step is a read-only audit of the phone's OpenSSH and filesystem confinement
  capabilities before any configuration edit.
- The capability audit confirmed OpenSSH 9.7p1, authorized root execution via
  `sudo`, APFS with about 107 GiB free, and an existing `agent` block that
  forces `internal-sftp -R`, disables forwarding/TTY, permits password
  authentication and empty passwords, and has no chroot. No `mount_nullfs`,
  `bindfs`, `rsync`, or `ditto` is installed; only `cp` is available for the
  export. Therefore direct live-tree chroot projection is unavailable with the
  installed tools. The bounded design is a root-owned chroot with a manually
  refreshed private snapshot of only the trio plus `Attachments`, a real
  password, and empty-password login disabled. Copy/launch tooling and source
  aggregate size remain to be audited before configuration changes.
- The operator changed the dedicated phone account name to `pi-bmo` and
  explicitly requested deletion of `agent`. The migration will first resolve
  exact account-management tooling and confirm the new name is unused, then
  create/configure/test `pi-bmo` before deleting exact UID 1002 `agent` and its
  SSH match block. The accepted source scope and all read-only/chroot/no-shell/
  no-forwarding boundaries are unchanged.
- The migration audit confirmed `pi-bmo` is unused, `agent` is UID/GID 1002,
  Procursus supplies `adduser`, `pw`, and `passwd`, and standalone user-delete
  tools are absent. GNU coreutils `cp` 9.5 supports reflink copies with fallback;
  the attachment source is only five files and 13,596 KiB. `/private` and
  `/private/var` are root-owned mode `0755`, suitable chroot parents. The
  OpenSSH launch job is socket-activated and not persistently running between
  connections. Exact account-tool syntax and launch arguments remain the final
  read-only audit before creating the replacement or deleting UID 1002.
- Dedicated group `pi-bmo` was created as GID 1003 after `pw user next`
  confirmed UID/GID 1003 were free. The root-owned mode-`0755` chroot was
  created under `/private/var`; a root-only staging pass privately hashed,
  copied, source-stability-checked, and copy-verified the DB trio and five
  attachment files before removing its manifests. The published `/SMS` tree
  contains eight regular files, with all directories `0550`, files `0440`, and
  entries `root:pi-bmo`; aggregate checks found zero mode/owner errors. No
  Apple path or live SSH configuration was modified, `pi-bmo` is not yet a
  login, and `agent` remains available for rollback.
- The offline SSH candidate passed full syntax and effective-policy checks.
  Its `pi-bmo` policy is password-only with empty passwords rejected, a
  `/private/var/imessage-relay-chroot` boundary, forced read-only SFTP rooted at
  `/SMS`, and explicit forwarding/shell/TTY/tunnel/user-RC denial. This OpenSSH
  build does not allow `PermitUserEnvironment` in a match block; the candidate
  omits it while the effective global setting remains `no`. The active config
  remains untouched pending a protected backup; the current `mobile` session
  must remain open through replacement-account validation and rollback.
- The active SSH configuration was backed up to a root-only rollback file,
  replaced with the validated policy, and passed a second syntax check. The
  `pi-bmo` login now exists as isolated UID/GID 1003 with no supplementary
  groups or created home, and the operator assigned its unique password
  locally without disclosing it. The platform's login-keychain warning is
  irrelevant to the forced SFTP account and no keychain action is authorized.
  The `mobile` recovery session remains open; kiosk-side password,
  confinement/read, and rejected-write probes must pass before deleting
  `agent`.
- A separate Mac SFTP probe passed password authentication, `/SMS` start,
  metadata access to the trio, `Attachments` traversal, chroot concealment of
  `/private`, and denied `mkdir`. No source content or phone path was changed.
  The restricted phone account policy is accepted. Because this was a Mac
  probe, retain the recovery session and temporary `agent` account until the
  kiosk proves an SSHFS mount with both client `ro` and server `-R`; then delete
  UID/GID 1002 and its SSH block as requested.
- The physical kiosk mounted the replacement export through SSHFS with client
  `ro`, strict verified host identity, and host-key updates disabled. The mount
  reported read-only FUSE options; all three database files were readable,
  `Attachments` was accessible, the write probe was denied, and its target
  remained absent. This accepts the double-read-only replacement path from the
  actual Stage 9 client. The mount remains active; exact UID/GID 1002 `agent`
  and its SSH block can now be removed as explicitly requested.
- Exact UID 1002 `agent` was removed without deleting a home or Apple data. An
  initial group deletion targeted the wrong account database, so the retained
  Procursus entry was detected before acceptance, backed up, removed explicitly
  from `/var/jb/etc`, and verified absent. The obsolete `Match User agent`
  block was removed through an offline candidate; syntax and effective
  `pi-bmo` policy passed before installation. A group-name lookup failure made
  the first install attempt fail before copying, leaving the active file valid;
  the validated candidate was then installed with numeric root UID/GID.
- A new physical-kiosk SFTP connection after cleanup started at `/SMS`, exposed
  `/` only as the chroot root, concealed `/private`, showed the DB/WAL/SHM trio
  as mode `0440`, traversed `Attachments`, denied `mkdir`, and left its target
  absent. A separate strict, non-interactive kiosk probe rejected the deleted
  `agent` login. The phone-access account migration and confinement gate are
  accepted; the active SSHFS mount remains read-only for the relay matrix.
- The first physical Stage 9 relay pass completed on Linux/aarch64/Python
  3.13.5 with status `pass` and exit zero. It scanned a bounded 38-row source,
  durably acknowledged 37 supported events, completed four real attachments
  (three photos and one video; 13,457,154 aggregate bytes), and left zero
  pending events or partial attachments. Invalid authentication, lost ACK, and
  receiver outage each produced the expected bounded retry code; relay and
  receiver reopen checks passed, receipt counts matched, no parse issues were
  reported, SQLite opened only a disposable local copy, and the source trio
  remained stable.
- The deliberate source-offline case unmounted only the kiosk's SSHFS source,
  leaving kiosk networking and phone services untouched. The runner failed
  closed with `messages_trio_unreadable` and exit status one; private before/
  after digest comparisons proved both durable state databases were unchanged.
  The same restricted export then remounted successfully with read-only FUSE
  options. Recovery delivery will be completed by the post-baseline event run.
- After one non-sensitive incoming text arrived, a second root-only staging
  snapshot privately baselined, copied, source-stability-checked, and
  copy-verified the same authorized trio plus attachment tree. Its manifests
  were removed, all directories/files were restricted to `0550`/`0440` under
  numeric root UID and `pi-bmo` GID 1003, and aggregate verification again
  found eight files with zero mode or owner errors. The new snapshot was
  published by rename while retaining the previous snapshot for rollback.
- Reusing the original Pi relay/receiver state after remount discovered exactly
  one post-baseline message row, acknowledged it in one attempt, and raised
  matching relay/receiver durable totals from 37 to 38. There were no issues,
  pending events, or partial attachments; both stores reopened consistently,
  SQLite again used only a disposable copy, and the source trio remained
  stable. This completes both the new-live-event and source-recovery cases.
- A controlled physical SIGINT used a separate mode-`0700` Pi work directory
  and was sent only after receiver state appeared. The runner emitted the
  content-free `interrupted` status, exited 130, left no relay process, and
  restored the pre-run count of disposable source directories. This accepts
  the physical interrupt and owned-resource cleanup behavior. The isolated
  interrupt directory remains pending the operator's explicit cleanup choice.
- The operator explicitly chose deletion. The kiosk SSHFS source was unmounted;
  both private Stage 9 state directories and the empty local mount tree were
  deleted and verified absent. On the phone, the retained previous snapshot
  and five temporary SSH/group candidate or rollback files were deleted. The
  active SSH policy passed a final syntax check, while the current restricted
  mode-`0550` `/SMS` snapshot and `pi-bmo` account were intentionally retained
  for Stage 10. Stage 9 is accepted; no daemon, deployment, automatic startup,
  outbound action, or Apple-data write occurred.
- Stage 10 physical work began with fresh mode-`0700` kiosk configuration,
  state, and mount directories outside the repository. The retained phone
  export mounted with read-only FUSE options. A 64-byte ephemeral secret stayed
  only in the operator shell; temporary mode-`0600` receiver/relay configs
  named only its environment variable and bound the receiver to an ephemeral
  literal-loopback port.
- The first real `RelayRuntimeService` lifecycle pass reported available,
  listening, and reconciliation-capable with zero initial aggregate counts.
  Idempotent close stopped the listener, and an immediate bind probe proved its
  assigned port was released; the command exited zero.
- A physical recent-reconciliation worker pass exited zero after asserting
  start, completion, and `complete` state. Hidden before/after hashes proved the
  mounted DB/WAL/SHM trio unchanged, and receiver/relay state files were mode
  `0600`. The detailed content-free report line was not retained in the
  operator paste, so its counts remain pending the visible UI check rather
  than being inferred.
- The isolated real `typed_agent.py` Qt path loaded on the physical display
  with one configured relay menu item and no metadata failures. The hosted view
  rendered correctly, reported the receiver available/listening, showed only
  aggregate zero receipt counts, preserved the compact face, and exposed the
  expected refresh/recent/month controls without private data.
- The physical Recent action completed with `Checked 3; requeued 0`, but both
  reconciliation controls remained disabled until a manual Refresh. Inspection
  found a completion-callback race: `status()` derived availability from the
  worker thread's liveness while the callback necessarily ran just before that
  thread returned. Availability now derives from the locked reconciliation
  state (`running` versus complete/failed); duplicate job exclusion remains
  enforced independently by `_start_reconciliation()`.
- Added a regression requiring the completion callback itself to observe
  `complete` and reconciliation available. Local verification passed for the
  focused regression (1 test), complete runtime module (13 tests), and complete
  relay suite (113 tests and 17 subtests). The first sandboxed focused attempt
  could not bind loopback and failed before the new assertion; the normal
  loopback-enabled rerun passed. Physical kiosk sync/retest remains required.
- Updated the relay menu metadata to reference the operator-selected existing
  `graphics/icons/message.png` asset and added a resource-free metadata
  assertion. The protected graphic remains untouched and untracked. The
  focused metadata test passed, followed by all 13 runtime tests and all 113
  relay tests plus 17 subtests. After synchronization, the physical Pi
  confirmed the existing icon was readable and passed all 13 runtime tests in
  1.06 seconds.
- The updated physical UI completed both Recent and Check Month. After each
  action, both controls returned to enabled without pressing Refresh, clearing
  the physical completion-callback regression. The requested message icon was
  visibly present. Two manual production-Qt launches supplied restart evidence;
  the UI remained stable through consecutive bounded actions, and the final
  run closed normally with exit status zero. Stage 10 is accepted.
- The operator authorized production incoming activation as Stage 12 and moved
  outbound text replies, photo/video sends, and reactions to Stage 13. Phone
  host/user settings and a private password-file reference may persist so the
  kiosk does not prompt at startup; credentials must not enter tracked JSON,
  command arguments, or logs.
- Documented the Stage 12 gate before implementation. Added schema-1 private
  phone source configuration, password-file validation, strict host-key/read-
  only SSHFS mounting, bounded outage recovery, and owned unmount cleanup.
- Added a plugin-owned incoming worker that copies the DB trio before SQLite
  inspection, scans from the durable cursor, delivers through the existing
  authenticated in-process receiver, retries on later cycles, and starts only
  when an explicit source configuration is present.
- Added receiver schema 2 for a mode-`0600` shared-secret file, an interactive
  one-time private configurator that persists phone login without echoing it,
  and an ignored `config/private/` boundary. No password appears in JSON,
  process arguments, logs, or tracked data.
- Added a bounded receiver feed and local relay-view message list with a
  two-second UI refresh. Private sender/message content is available only in
  that dedicated view; generic status remains aggregate/content-free.
- Added a root-owned iPhone shell publisher and launchd template that build and
  verify a read-only `.SMS.next`, apply the existing restricted ownership and
  modes, and atomically rotate it into `/SMS`. It never invokes SQLite or
  changes Apple source ownership/permissions.
- Focused Stage 12/receiver/runtime verification passes: 43 tests and 9
  subtests. The complete relay suite passes: 120 tests and 17 subtests. Shared
  extension/runtime-menu/Qt/setup verification passes: 72 tests and 40
  subtests. The complete repository suite passes with 836 tests and 10,002
  subtests. Physical provisioning and one automatic live arrival remain.

### Remaining and boundary

Stage 11 is complete. Its relocation/static checks, physical-Pi relay suite,
shared extension/runtime-menu/Qt/setup suite, and complete repository suite all
pass after the access-time portability correction.

Stage 10 is complete. The physical kiosk passed listener binding, touch/VNC UI,
recent/month controls, restart, clean shutdown, and bounded stability. The
feature remains absent from defaults and reads private config or starts
resources only when explicitly enabled. No deployment, daemon, automatic
startup, or outbound Messages action occurred.

Stage 9 is complete. Its physical supported-backlog, real-attachment,
authentication, lost-ACK, receiver-outage, duplicate/durable receipt,
relay/receiver restart, stable-source, source-offline/recovery, post-baseline
live-event, SIGINT, and explicit cleanup cases all passed on the Raspberry Pi.

Stage 12 production incoming activation is authorized and in progress. Stage
13 outbound planning remains gated on separate explicit authorization.
The proposed iPhone Python 3.9.9 environment and any additional outbound
dependency, credential, or sending service must be evaluated and explicitly
authorized in Stage 13; no direct Apple database write is permitted.

Known later-stage risks remain: production endpoint trust, TLS/key provisioning,
iPhone clock skew, scheduling, retention/pruning, and unverified edits,
retractions, emoji reactions, real group mutations, and real email handles.
