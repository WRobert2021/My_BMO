# iMessage Relay Progress

current_stage: 12
current_chapter: Contained attachment viewing and final physical acceptance
state: in_progress
next_action: Install the version-matched Qt Addons requirement and sync the contained relay media viewer; verify photo/video playback, deferred audio playback, cleanup, and the header dot on the kiosk, then finish restart/reconciliation/cleanup acceptance. Do not begin Stage 13.
last_verified: 2026-09-09

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0–7 | complete | schema, parser, queue, receiver, simulation, reconciliation, and attachment protocol accepted |
| 8 | complete | authorized read-only live discovery accepted |
| 9 | complete | manual physical iPhone-to-kiosk delivery matrix accepted |
| 10 | complete | opt-in kiosk receiver/UI lifecycle accepted |
| 11 | complete | plugin package consolidation and full physical suite accepted |
| 12 | in progress | local event-driven phone push and kiosk control implementation accepted; physical activation remains |
| 13 | not started | outbound text, media, and reactions remain unauthorized |

## Current Stage 12 decisions

- Normal operation is phone-to-kiosk push. The kiosk never mounts, copies, or
  polls Apple's Messages database.
- The phone treats Messages filesystem activity as a wake hint, scans all rows
  after its cursor in a read-only transaction, and records only identifiers and
  retry state in its private backlog.
- The first outage episode gets one immediate attempt followed by five
  one-minute retries. After exhaustion, delivery remains latched dormant even
  when new messages arrive. Only an authenticated kiosk resume request resets
  the circuit.
- Deletion activity revalidates queued identifiers. Conclusively deleted,
  unacknowledged events may be pruned, but live deletion/unsend/edit schema
  behavior must be verified before coverage is claimed.
- The kiosk receiver database remains the independent message record. Weekly
  or twice-weekly bounded reconciliation is initiated by the kiosk but scanned
  on the phone; only missing events are resent.
- The sibling `phone_relay` PyCharm project is a standalone, dependency-free
  Python 3.9 runtime with no imports from the Python 3.13.5 BMO package. Its
  local compatibility environment is CPython 3.9.6 and the physical phone has
  CPython 3.9.9.
- The phone daemon runs as dedicated non-login `pi-bmo`; `mobile` remains the
  SSH administrator and supplies the iOS launch persona only. A narrowly scoped inherited read/traverse ACL lets `pi-bmo` read
  current and newly created Apple SMS inputs without write rights or POSIX mode
  changes. Because `/bin/chmod` is absent on the phone, a dependency-free
  Darwin ACL API helper owns exact grant/revoke behavior.
- A fresh phone state defaults to `new_only`, recording the current maximum
  Messages ROWID before observing new arrivals. Existing kiosk receipts remain
  intact and the explicit `all` option is reserved for controlled migrations.
- The kiosk exposes a query-only durable message-total and delta API for a
  future badge script. The caller owns its checkpoint and suppresses a badge
  when the delta is zero.
- The phone project provides a fixed-path `mobile`-administered maintenance
  command whose stop removes the launchd job completely and whose confirmed
  uninstall revokes the relay ACL, deletes the service identity, and removes
  relay-owned files. Its account deletion temporarily repairs the missing
  Procursus `wheel` entry from a private backup and rolls access back if
  deletion does not complete. The `mobile` account and Apple Messages data are
  retained.
- Physical launch testing established that system launchd cannot give a
  Procursus-only UID the iOS persona needed for the protected SMS path. The
  reviewed bridge starts in the built-in `mobile` context, permits exactly one
  immutable launcher command through passwordless sudo, then validates and
  permanently drops to UID 1002/GID 1001 before configuration or Apple data is
  accessed. The top-level service directory is traverse-only to other users;
  private files and state remain restricted.
- The kiosk selects and renders its bounded recent feed newest-first by Apple
  source timestamp. Receipt timestamps are not an ordering
  authority because a recovered backlog may be accepted within one second.
- One phone-to-kiosk HTTP/TLS connection is reused across the signed event,
  attachment session, bounded 64-KiB chunks, and completion ACK for a single
  delivery. It is closed when that delivery ends so idle server disconnects
  cannot poison the next event.
- Reaction receipts remain durable events but are folded out of the kiosk feed.
  The newest event in each target-part/sender slot determines its state: a new
  kind replaces the prior badge and a removal clears the slot. Plugin-owned SVG
  artwork avoids the kiosk's missing color-emoji glyphs.
- The Qt boundary converts reaction and attachment tuples into native variant
  lists. This prevents PySide from exposing opaque Python objects to nested QML
  models and is required for reaction badges to render on the physical kiosk.
- Completed receiver blobs remain private durable state and are lazily exposed
  through configured photo, audio, and video directories. Same-filesystem hard
  links avoid another byte copy; cross-filesystem publication is atomic and
  digest-verified. The compact view opens only current validated feed paths.
- The kiosk relay view now dedicates its body to messages and attachments. The
  counters, receiver prose, headings, and reconciliation panel are removed;
  reconciliation remains in the service. A header dot is green only for a
  healthy receiver plus connected phone control and red otherwise.
- Attachments no longer launch a desktop handler or VLC window. A validated
  current-feed selection opens a contained photo detail or Qt Multimedia
  video/audio player in the relay view. Playback stops on back/navigation and
  decode failures remain isolated from receiver operation.

## Cleanup status

- Removed the Stage 12 SSHFS source manager, kiosk polling worker, source
  configurator/example, snapshot publisher/installer, and their focused tests.
- Reduced the BMO data plane to the durable receiver and local feed, then added
  only the separate authenticated phone-control coordinator; no retired source
  path or kiosk-side Apple reader was restored.
- Preserved the stable message model/scroll behavior, kiosk receipt store,
  authenticated event/attachment protocol, and receiver-secret file support.
- Removed SSHFS/FUSE from `setup.sh` and its setup contract with explicit
  operator approval; the corrected runtime has no mount dependency.
- Live kiosk cleanup removed the retired source/sender configuration, stored
  source password, sender state, mount directories, and obsolete feature
  settings. Receiver configuration, secret, receipt database, attachments, and
  UI data were retained.
- Raspberry Pi OS package `sshfs` `3.7.3-1.2~deb13u1` was removed without an
  autoremove operation.
- Live phone cleanup verified that no publisher or launch plist was installed,
  removed the restricted `pi-bmo` SSH policy and exact UID/GID 1003, deleted
  the retired chroot, and retained the `mobile` maintenance account. The active
  SSH policy was syntax-validated, and the original Procursus group database
  was restored after account deletion.

## Verification status

- Kiosk Stage 12 control/configuration and lifecycle focus: 19 tests passed.
- Standalone CPython 3.9.6 compatibility suite: 39 tests passed, including strict
  private configuration, cursor/backlog restart, the resume-only retry latch,
  read-only burst discovery, text/reaction/photo/video materialization,
  attachment streaming, bounded reconciliation, service orchestration, and a
  real loopback control-listener request plus a real macOS/Darwin SQLite-WAL
  filesystem wake. The Darwin ACL test verifies grant inheritance, exact
  revocation, preservation of unrelated ACL entries, and unchanged modes and
  owners. Deployment tests validate the exact sudoers command, mobile-persona
  launch shape, immediate privilege drop, and bounded
  stop/start/status/uninstall command structure.
- Shared phone/kiosk control canonical body and HMAC vectors match. An actual
  local phone sender-to-kiosk receiver loopback delivered one invented event,
  accepted its duplicate idempotently, and left one durable kiosk receipt.

- Complete relay suite: 123 tests and 21 subtests passed.
- Complete repository suite: 845 tests and 10,006 subtests passed in 23.35
  seconds with exit status zero.
- Python 3.9 AST/import checks, tracked example JSON parsing, and `git diff
  --check` passed. Physical kiosk and phone migration cleanup is complete. The
  phone preflight found CPython 3.9.9 and no Apple BSD `/bin/chmod`; user/group
  next values were `1002:1001`. The dedicated non-login `pi-bmo` identity is
  now provisioned as UID 1002 and GID 1001; its pre-change group-database
  backup remains private until activation succeeds. The runtime, private
  TLS/HMAC material, exact Apple SMS ACL, launchd job, and maintenance command
  are installed. Five foreground service cycles passed after dropping to UID
  1002/GID 1001. Direct system-launchd execution still failed at the protected
  SMS path, which isolated the missing iOS persona; the reviewed exact-command
  bridge is installed with a later-sorting exact NOPASSWD rule, the process
  remains running, and authenticated kiosk health succeeds. Live `kqueue`
  delivery passed for immediate text, back-to-back text, stable scrolling,
  photo, an 18–20-MiB video, reaction add/remove, and kiosk-offline recovery.
  The offline batch exposed unstable display ordering when receipts shared a
  timestamp, and the large video exposed per-chunk TLS handshake overhead;
  source-time/newest-first ordering and per-delivery TLS reuse were deployed
  and the corrected visible order passed. Target-message SVG reactions now
  replace and remove correctly in the physical UI.
- Reaction badge replacement/removal and SVG rendering passed physical kiosk
  verification. Photo, 18–20-MiB video, reaction add/remove, offline recovery,
  newest-first ordering, and stable scrolling have also passed. Contained
  attachment viewing and the compact status UI still require physical retest.
- Current complete kiosk relay suite: 130 tests and 21 subtests passed. Current
  complete standalone phone suite: 39 tests passed.
- Contained-media implementation verification: the relay/hosted-QML/setup
  acceptance set passed 181 tests and 56 subtests; the Qt Multimedia QML
  component instantiated against its FFmpeg backend. Physical Pi photo/video
  rendering, playback cleanup, and later audio output remain to be checked.
