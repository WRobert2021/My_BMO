# iMessage Relay Progress

current_stage: 13
current_chapter: Text composer complete; corrected physical validation gate
state: awaiting_confirmation
next_action: Preserve the original test command as consumed and obtain separate user confirmation naming the recipient and exact harmless text before a second physical call through the corrected adapter. Do not attach the production phone executor or kiosk coordinator until that corrected physical call is accepted.
last_verified: 2026-09-12

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0–7 | complete | schema, parser, queue, receiver, simulation, reconciliation, and attachment protocol accepted |
| 8 | complete | authorized read-only live discovery accepted |
| 9 | complete | manual physical iPhone-to-kiosk delivery matrix accepted |
| 10 | complete | opt-in kiosk receiver/UI lifecycle accepted |
| 11 | complete | plugin package consolidation and full physical suite accepted |
| 12 | complete | event-driven incoming phone push, kiosk presentation, maintenance, and physical acceptance passed |
| 13 | in progress | kiosk and phone command planes plus cross-runtime invented simulation passed; physical send requires separate confirmation |
| 14 | planned | post-main-stage media controls, speech, relay address book, and kiosk-only deletion/retrieval polish |

## Current Stage 13 decisions

- Stage 13 was explicitly authorized on 2026-09-12. Discovery and local
  simulation may begin; no physical message send is implied by that planning
  authorization.
- Direct writes to Apple's Messages database remain prohibited. The first gate
  is a bounded, read-only inventory of the phone's installed messaging tools,
  private-framework surface, Objective-C/Python bridge availability, compiler,
  and code-signing tools.
- The first physical inventory found no compiler, Mach-O inspection or signing
  tools, existing messaging CLI, Cycript/Frida bridge, or Python `objc` and
  `Foundation` modules. `/Applications/MobileSMS.app/MobileSMS` is present.
  Direct filesystem checks for messaging frameworks were negative, which is
  inconclusive on modern iOS because system images may exist only in the dyld
  shared cache. A subsequent no-load `dlopen_preflight` confirmed that IMCore,
  IMFoundation, IMSharedUtilities, ChatKit, IDS, Foundation, and libobjc are all
  resolvable from the phone's shared cache. A disposable process then loaded
  the non-UI IMCore dependency chain and found the relevant
  `IMAutomationMessageSend`, `IMChat`, `IMChatRegistry`, `IMMessage`,
  `IMFileTransfer`, and associated-message classes without opening Apple data
  or sending anything.
- The development Mac has Apple Clang 17 and `codesign`, but only Command Line
  Tools: no iPhoneOS SDK was found and `ldid` is absent. The phone also has no
  compiler or `ldid`, so a native helper would require an explicitly approved
  toolchain addition. Selector-level discovery comes first because a
  dependency-free `ctypes` adapter may avoid that new dependency surface.
- Targeted selector inspection found a high-level
  `IMAutomationMessageSend` surface accepting message text, destination ID,
  file paths, group ID, service, timeout, thread identifier, and an `NSError`
  result. It also exposes message construction and attachment staging helpers.
  `IMChat` exposes `sendMessage:` plus message-acknowledgment methods suitable
  for reactions. These signatures make a narrow Python `ctypes` adapter the
  preferred candidate. The no-send initialization check passed under the
  actual `pi-bmo` service identity (UID 1002/GID 1001): iMessage and the send
  service were available, text/photo/video/audio capability was reported, and
  `IMAutomationMessageSend` constructed successfully. MMS reported disabled.
  No send was performed. Stage 13 version 1 is iMessage-only and will not
  silently fall back to SMS/MMS, so that MMS result is not a blocker.
- The outbound architecture is now frozen on a dependency-free Python 3.9
  `ctypes` adapter; no native helper, compiler, signing tool, or PyObjC package
  is required for the first implementation.
- The kiosk foundation now defines strict canonical text, photo/video, and
  reaction commands; explicit canonical recipients and reply context;
  path-free media references; exact request/response identity; and a private
  durable SQLite outbox. Enqueue is idempotent by command ID and digest,
  attempts enter `executing`, ambiguous transport outcomes become `uncertain`,
  and `sent`/`failed` states cannot silently regress or retry.
- The authenticated kiosk client signs the exact command/status path, records
  the command and attempt before transport use, accepts only exact JSON ACKs,
  and requires status resolution after an ambiguous outcome. A local invented
  phone simulation accepted text, media, and reaction commands only after the
  durable boundary, then proved a lost ACK resolves to `sent` without a second
  execution.
- Photo/video staging uses separate signed session and chunk paths. The kiosk
  validates a regular non-symlink source against the path-free command digest,
  sends at most 64 KiB per chunk, accepts only the exact durable offset, and
  resumes after a lost chunk ACK without starting the Apple send early.
- The kiosk now has a resource-free confirmation gate that holds at most one
  command in memory, exposes exact recipients and kind-specific content for a
  visible prompt, expires after a bounded interval, and releases the command
  only once for the exact opaque token. Preparing, inspecting, cancelling, or
  closing this gate cannot open durable state, contact the phone, or send.
- The kiosk now also has a resource-owning text coordinator and a visible Qt
  compose/reply surface. New messages require an explicit recipient; replies
  resolve recipient, chat, and message IDs from the current received feed
  instead of trusting QML input. Review shows exact recipient and text, and
  only the matching one-shot confirmation can release background submission.
  Normal plugin registration does not construct the coordinator yet, so the
  deployed kiosk still cannot originate a message.
- Incoming feed entries retain stable message, chat, and participant IDs. This
  supplies explicit reply/reaction context without granting send authority or
  trusting mutable UI fields.
- The standalone Python 3.9 runtime mirrors the frozen command and media
  contract on the existing authenticated listener. A private phone ledger
  reserves the canonical command before execution, rejects conflicting IDs,
  converts restart-time `executing` state to `uncertain`, and never retries a
  terminal outcome automatically.
- Phone-owned media staging accepts only exact authenticated 64-KiB chunks,
  resumes at its durable offset, recovers a verified final rename, and requires
  the declared byte count and SHA-256 before command reservation. Unsafe or
  exposed staging files fail closed. Terminal sent/failed commands remove their
  staged media.
- The running production phone service remains deliberately wired to the
  disabled executor and returns `apple_send_not_enabled`. A separate guarded
  `ctypes` adapter now implements only a new, single-recipient text send after
  an explicit in-process enable flag. It verifies the narrow observed selector
  and Objective-C type encoding, passes the explicit `iMessage` service,
  requires nonempty `sentMessageInfo` with no pending GUIDs, maps an entered
  call without that evidence to `uncertain`, and rejects reply, group, media,
  and reaction shapes before framework loading. No deployed
  configuration can select this adapter yet. Outbound state failure still
  returns a bounded unavailable response without stopping incoming delivery or
  phone control.
- A real loopback interoperability run passed invented text, photo, and
  reaction commands from the Python 3.13 kiosk client through the Python 3.9
  phone handler. Exactly three invented executor calls occurred and no Apple
  framework send method or physical phone was contacted.
- The first separately authorized physical text call passed selector/ABI
  preflight and returned a non-null Objective-C object with no `NSError`, but
  no outgoing message appeared on the phone and nothing reached the recipient.
  The phone ledger recorded `sent` under the former invalid assumption. That
  command is treated as consumed and will not be retried. The adapter now uses
  the narrower verified text selector and requires sent-message/pending-state
  evidence; otherwise the durable result is `uncertain`. A second physical call
  requires a new exact authorization. The corrected adapter was deployed for a
  no-send preflight under the service identity; its exact selector and ABI
  check passed and no send was performed.
- Prefer extending the existing authenticated TLS phone-control boundary and
  dedicated `pi-bmo` service. Add a separate native helper only if the verified
  phone interface cannot be called safely and reliably from Python 3.9.9.
- Outbound commands require stable kiosk request IDs, durable phone-side
  duplicate prevention before execution, explicit recipient or reply-target
  selection, bounded media staging, exact result states, and content-free
  diagnostics.
- The initial implementation order is text reply, new text with an explicit
  recipient, photo/video, then reactions tied to stable source-message
  identities. Every kind must pass invented-data simulation before a separately
  confirmed physical send.
- Stage 14 remains queued and is not part of Stage 13 implementation.

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
- Generic attachment buttons are replaced by touch-sized feed previews: the
  actual photo for images, a play tile for video, and a labeled tile for audio.

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
- Deleted the ignored local `iphone_snapshot` and `iphone_snapshot_stage0`
  directories after confirming that the current push runtime does not reference
  them.

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
- Complete repository suite: 872 tests, 2 skipped, and 10,019 subtests passed
  in 20.89 seconds with exit status zero.
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
  newest-first ordering, and stable scrolling have also passed. Touching the
  compact photo and video previews opens their contained viewers, playback and
  navigation cleanup work, and video is no longer routed through QQuickImage.
  The embedded audio attachment path also passed. The connected header status
  dot is green; its unavailable/red state remains covered by automated UI
  tests.
- Current complete kiosk relay suite: 157 tests, 2 skipped, and 34 subtests
  passed. Current
  complete standalone phone suite: 55 tests passed.
- Contained-media implementation verification: the relay/hosted-QML/setup
  acceptance set passed 181 tests and 56 subtests; the Qt Multimedia QML
  component instantiated against its FFmpeg backend. Physical Pi photo, video,
  and audio interaction, touch selection, and playback cleanup passed.
- Stage 12 physical incoming acceptance is complete.
- Stage 13 outbound protocol/client/state/runtime/UI focus is included in the
  complete kiosk relay suite and passed on
  Python 3.13.12. Physical discovery under `pi-bmo` passed without sending.
  The local invented phone simulation passed. The Python 3.9 phone suite now
  passes 55 tests, including its durable command/media state, real HTTP route,
  guarded text-adapter boundary, and incoming failure isolation. A separate real
  loopback run passed the shared Python 3.13 kiosk-to-Python 3.9 phone contract
  for invented text, photo, and reaction commands. The first authorized send
  produced no outgoing message and is retained as consumed; a corrected second
  send remains separately gated.
