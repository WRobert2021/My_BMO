# iMessage Relay Progress

current_stage: 13
current_chapter: first SpringBoard physical text gate
state: production_phone_path_ready_kiosk_gate_pending
next_action: Enable the kiosk gate with the private-safe configurator, restart BMO, then consume the one authorized text through the UI exactly once and record its physical result.
last_verified: 2026-10-01

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

- Standalone Python processes are retired as the Apple execution boundary.
  Repeated physical preflights connected to IMDaemon but could not expose a
  usable active iMessage account under `pi-bmo`, root-to-mobile setuid, or a
  direct `mobile` login. Further capability-number variants are not a useful
  next step.
- The selected boundary is a rootless Theos helper injected only into
  SpringBoard. It hooks the modern `processCapabilities` contract, retains the
  observed legacy `_capabilities` fallback, and exposes a fixed Unix-domain
  socket rather than a network listener or shell.
- The socket directory is owned by `mobile:pi-bmo` with mode `2710`; the socket
  is mode `0660`. A trusted installer-created, mode-`0000` identity marker
  carries the Procursus-only service UID/GID into SpringBoard, and the helper
  verifies `LOCAL_PEERCRED` against that exact numeric identity.
- Version 1 accepts only content-free preflight and new single-recipient text.
  Group, reply, media, and reaction commands are rejected before Apple
  execution. The authenticated phone service still owns durable command
  reservation and duplicate prevention.
- SpringBoard returns a generated GUID after one `sendMessage:` invocation.
  The `pi-bmo` relay reports `sent` only after a bounded, read-only SQLite query
  finds that exact GUID with `is_from_me = 1`. Transport loss, malformed
  results, missing evidence, and exceptions after entering the send call are
  terminal `uncertain` and never automatically retry.
- Theos and `ldid` are installed only on the development Mac. A rootless
  `arm64`/`arm64e` package builds successfully from the standalone phone
  project. No kiosk or phone runtime dependency changed.
- The Python socket executor is integrated behind the exact
  `--enable-springboard-outbound` launcher tuple. Construction and content-free
  preflight happen only after the launcher permanently drops to `pi-bmo`;
  failure selects the disabled executor so incoming delivery still starts.
- The maintenance command exposes only `springboard-preflight`, which runs the
  exact helper readiness check as `pi-bmo` and emits bounded content-free JSON.
  Retired standalone-process preflight commands are no longer exposed.
- The tracked launchd and sudoers definitions now select the exact
  `--enable-springboard-outbound` tuple. Kiosk `outbound_enabled` and the
  one-shot UI confirmation remain independent gates.
- Native package `0.1.5` and the production launchd/sudoers definitions are
  installed. Its strengthened content-free physical preflight returned
  `{"error_code":null,"state":"ready"}`, and the production phone relay was
  verified running. No recipient or message was constructed or sent during
  this gate. Version `0.1.5` adds selector-level readiness, constructs IMCore
  text as attributed text, and treats the validated E.164/email destination as
  canonical.
- Initial physical deployment exposed and fixed two native integration defects:
  Apple's user database could not resolve the Procursus-only account, and the
  fully resolved rootless bootstrap path exceeded Darwin's Unix-socket path
  limit. The installed helper now uses the trusted numeric marker and the short
  `/var/jb/...` socket address. The content-free `bridge.status` marker reached
  `listening`.
- Production activation and one exact physical text have now received a
  single explicit authorization. The recipient and content are intentionally
  not recorded in repository documentation. That authorization permits no
  automatic retry or additional message.

## Stage 13 investigation history (superseded)

- Repeated `apple_imessage_account_unavailable` results now identify a process
  identity boundary: IMDaemon and account-monitor setup succeeded, but iOS did
  not expose a sendable iMessage account to restricted `pi-bmo`.
- The approved launcher hook keeps the main relay as `pi-bmo` and can opt into
  one anonymous-socket broker permanently dropped to verified built-in UID/GID
  501 (`mobile`). The broker has no listener or shell and accepts only an
  authenticated, durably reserved, new single-recipient text command. Group,
  reply, media, and reaction shapes fail before Apple execution.
- Broker creation failure selects the disabled executor and preserves incoming
  startup. Ambiguity after an entered send remains terminal `uncertain` and is
  never automatically retried.
- Kiosk registration now creates its durable outbound client and confirmation
  coordinator only when `outbound_enabled` is explicitly true. Its private
  outbox defaults to `config/private/imessage_outbound.db`; failure degrades to
  incoming-only.
- The tracked phone launchd and sudoers examples still omit the opt-in broker
  flag. No phone deployment or physical send occurred in this implementation
  pass. The content-free `outbound-mobile-preflight` is the next physical gate.
- The first `outbound-mobile-preflight` still returned
  `apple_imessage_account_unavailable`. It was not a genuine mobile-context
  test: the maintenance command started Python through `sudo` and only later
  changed its UID/GID to 501. The result proves that setuid alone does not
  recreate the iOS process context used for messaging account visibility.
- The maintenance action now launches a content-free preflight directly from
  the authenticated `mobile` shell without sudo. It verifies real/effective
  UID/GID 501 before importing the Apple runtime. Installed package source must
  be readable, but private configuration, keys, secrets, and state remain
  inaccessible to `mobile` through that path.
- The first direct invocation failed before importing code because the service
  application root was mode `0751`; Python must enumerate its import root to
  discover the package. The corrected root mode is `0755`, while package source
  stays read-only and private configuration/state retain `0700`/`0600`.
- The genuine direct-mobile run then reached IMCore but still returned
  `apple_imessage_account_unavailable`. Review against the modern IMCore
  capability contract found the implementation still supplied legacy `17159`.
  The disposable helper now installs iOS 16+ `processCapabilities` value
  `4485895` before daemon connection, while retaining the legacy method only as
  compatibility fallback. The next content-free preflight tests this correction.
- The standalone phone suite passes 93 tests; the focused kiosk
  outbound/runtime suite passes 45 tests and 13 subtests. The complete BMO
  suite passes 875 tests with 2 skipped and 10,019 subtests.

- Stage 13 was explicitly authorized on 2026-09-12. Discovery and local
  simulation may begin; no physical message send is implied by that planning
  authorization.
- A second exact single-message physical test was separately authorized and
  executed once on 2026-09-12 after the corrected adapter's no-send preflight.
  It returned terminal `uncertain` with
  `apple_acceptance_unverified`; no outgoing phone message appeared and the
  recipient received nothing. Its fixed command ID is consumed. It did not
  authorize a persistent production enable switch or any additional message.
- The refined adapter was deployed on 2026-09-13. Its no-send preflight passed
  under the phone service identity after initializing the shared sending
  utilities and constructing the automation sender. No send was performed, and
  the normal phone relay was restarted and verified running.
- A third exact single-message physical test was separately authorized on
  2026-09-13. It permits one call through a new fixed command ID only; it does
  not permit reuse of either consumed command, an automatic retry, persistent
  production enablement, or any additional message.
- The first manual invocation for that authorization failed while constructing
  the command because its generated timestamp included fractional seconds. The
  strict protocol rejected it before command reservation, nonce consumption,
  or Apple-adapter entry, so no send was attempted and the authorization
  remains unused. The abandoned invocation ID will not be reused; the corrected
  invocation formats canonical UTC seconds and uses a new fixed ID.
- The corrected third invocation entered the refined Apple adapter exactly once
  and ended `uncertain` with `apple_sent_evidence_empty`. No outgoing phone
  message appeared and the recipient received nothing. Its durable command ID
  is consumed and must not be retried. The normal incoming phone relay was
  restarted and verified running.
- A no-send live selector inspection verified both daemon singleton selectors;
  `connectToDaemon`, its launch variants, `isConnected`, and the older
  `_capabilities` method with exact 32-bit ABI. `processCapabilities` is absent.
  The phone also exposes the required chat registry, account, handle, message,
  `canSendMessage:`, and `sendMessage:` selectors with their exact encodings.
  No daemon connection or send was performed. The next probe will test the
  unmodified service identity's daemon connection before any capability
  override is considered.
- The disposable baseline daemon probe reported native capabilities `512`;
  `connectToDaemon` returned true and `isConnected` became true under the
  deployed `pi-bmo` service identity. No Apple data was accessed and no send
  was performed. Native `512` was sufficient for the automation-sender probe,
  so no override was justified for that path. The local guarded adapter now
  validates this exact live ABI, establishes and boundedly verifies the native
  daemon connection before constructing the sender, and maps pre-send
  connection failure to a bounded definite error. Its full 58-test Python 3.9
  suite passed before deployment.
- The daemon-connected adapter was deployed and passed its no-send readiness
  preflight under `pi-bmo`: shared sending utilities initialized, the native
  IMDaemon connection succeeded, and the automation sender constructed without
  a recipient or send invocation. The normal phone relay was restarted and
  verified running. A new physical call requires separate exact authorization.
- A fourth exact single-message physical test was separately authorized on
  2026-09-13 for the daemon-connected adapter. It permits one execution through
  a fresh fixed command ID only and does not authorize retries, capability
  overrides, persistent production enablement, or any additional message.
- The fourth call established the native IMDaemon connection and entered
  `IMAutomationMessageSend` exactly once, but ended `uncertain` with
  `apple_sent_evidence_empty`. No outgoing phone message appeared and the
  recipient received nothing. Its durable command ID is consumed. This rules
  out the automation sender as the Stage 13 execution path. The normal incoming
  phone relay was restarted and verified running.
- The direct IMCore no-send readiness probe connected to IMDaemon and
  constructed an in-memory message, but native capability `512` exposed no
  active iMessage account or existing test chat, so `canSendMessage:` could not
  authorize the object. `sendMessage:` was not invoked. This confirms that
  daemon connectivity alone is insufficient and that any elevated capability
  must be isolated to a disposable, already-authenticated command process; the
  long-running network relay must retain its native capability set.
- The first direct-helper design proposed temporarily replacing the private
  `_capabilities` method to report IMDaemon capability `17159`. That unsupported
  process boundary received a separate implementation-only approval; the
  approval did not authorize deployment or a physical message.
- The user gave that exact implementation-only approval on 2026-09-13 while
  explicitly withholding phone deployment, phone execution, production
  enablement, and any physical message. The standalone phone project now has a
  disposable direct-IMCore helper and an injected local test suite. No phone
  was contacted.
- The long-running service still constructs `DisabledOutboundExecutor` and does
  not import or select the helper. The parent adapter also defaults disabled
  and checks that gate before inspecting a command or starting a child. The
  child accepts one canonical new single-recipient text command over standard
  input; group, reply, media, and reaction shapes fail before framework use.
- The current child does not replace Objective-C methods. It requests capability
  `17159` directly through the verified
  `connectToDaemonWithLaunch:capabilities:blockUntilConnected:` selector for
  its own daemon connection. Preflight verifies only daemon/account readiness
  and never constructs a recipient, chat, or message. Execution remains
  unapproved and disconnected from production.
- A child timeout or malformed/mismatched result is never success. Once the
  send boundary may have been entered it becomes terminal `uncertain`. A direct
  send can become `sent` only if a bounded read-only query finds the exact
  generated message GUID with `is_from_me = 1`; the helper never writes or
  copies Apple's database.
- Nineteen focused direct-helper tests and the complete 80-test standalone phone
  suite passed locally on Python 3.9.6. The pre-existing loopback HTTP tests
  required local socket permission and passed when run with it. The relevant
  kiosk outbound/runtime/end-to-end set also passed with 49 tests and 15
  subtests. No Apple framework was loaded and no phone was contacted.
- A dedicated `outbound-preflight` maintenance action is ready for the
  authorized deployment. It uses the existing root-to-`pi-bmo` privilege-drop
  launcher, accepts only the exact installed configuration path, emits the
  helper's content-free result, and does not stop, restart, or reconfigure the
  incoming relay. It has no execution mode and cannot submit a message.
- The first authorized phone preflight failed safely with
  `apple_capability_override_failed` before account lookup. A more precise
  runtime-class probe then showed `apple_daemon_identity_changed`: initializing
  Apple's sending utilities replaces the shared daemon-controller singleton.
  Neither attempt accepted a recipient, constructed a message, or entered the
  send path.
- Two revised method-replacement preflights progressed through capability
  observation and daemon connection but ended safely at
  `apple_imessage_account_unavailable`. Neither accepted a recipient,
  constructed a message, or entered the send path.
- Code review found the remaining flaw: sending-utility initialization could
  connect the daemon with native capability `512` before the local method was
  replaced, and observing the replacement afterward did not renegotiate that
  daemon session. The replacement design is retired.
- The first explicit-connection revision skipped sending-utility initialization,
  called the live capability-bearing daemon selector with `17159`, and still
  returned `apple_imessage_account_unavailable`. This proves explicit daemon
  negotiation alone does not initialize the account monitor. It reached no
  recipient, message, or send boundary.
- The current local revision explicitly connects with `17159` before account
  monitor initialization, initializes the shared sending utilities, then
  resolves the daemon controller again and reconnects it with `17159` if the
  initializer replaced the singleton. It waits at most five seconds for daemon
  connection and active-account readiness. It does not use `_capabilities`, the
  legacy zero-argument connection method, or Objective-C method replacement.
  The complete 80-test Python 3.9.6 suite passes.
- That revised physical preflight still returned
  `apple_imessage_account_unavailable`. It therefore proved that explicit
  capability negotiation plus account-monitor initialization does not make
  `activeIMessageAccount` visible to the dedicated `pi-bmo` process. The run
  reached no recipient, chat, message, or send boundary. The next diagnostic is
  a single content-free inventory of alternate account-controller presence and
  collection counts; it will distinguish an overly narrow selector from a
  service-identity or entitlement boundary before further implementation.
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
- The default production phone invocation remains deliberately wired to the
  disabled executor and returns `apple_send_not_enabled`. The exact approved
  launcher hook can instead inject the mobile broker. A separate guarded
  `ctypes` adapter now implements only a new, single-recipient text send after
  an explicit in-process enable flag. It verifies the narrow observed selector
  and Objective-C type encoding, initializes and checks the shared sending
  utilities, passes the explicit `iMessage` service, and pumps the Foundation
  run loop for at most five seconds while waiting for nonempty
  `sentMessageInfo` with no pending GUIDs. An entered call without that
  evidence maps to a precise terminal `uncertain` code. Reply, group, media,
  and reaction shapes are rejected before framework loading. No deployed
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
  command is treated as consumed and will not be retried. The first correction
  used the narrower verified text selector and required immediate
  sent-message/pending-state evidence. Its deployed no-send selector/ABI
  preflight passed, but the second separately authorized call returned
  `uncertain`; it likewise created no outgoing phone message and no recipient
  delivery, and its command is consumed. The local adapter now initializes the
  shared sending utilities and waits boundedly for asynchronous evidence. Its
  deployed no-send readiness preflight passed under the service identity; it
  was then physically exercised once and returned empty sent evidence without
  creating an outgoing message. Existing iOS IMCore implementation evidence
  indicates a separate authenticated `imagent` connection and process
  capability boundary is required before chat sends work. That boundary must
  be inspected and simulated before another exact physical authorization.
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

- Current local native checkpoint: 103 standalone phone tests passed; the
  rootless Theos package built successfully for both `arm64` and `arm64e` with
  `ldid`. Package inspection found only the SpringBoard-filtered dylib, filter
  plist, and bounded install/remove scripts. No phone was contacted and no
  message was sent.

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
- Current complete kiosk relay suite: 160 tests, 2 skipped, and 34 subtests
  passed. Current
  complete standalone phone suite: 103 tests passed.
- Contained-media implementation verification: the relay/hosted-QML/setup
  acceptance set passed 181 tests and 56 subtests; the Qt Multimedia QML
  component instantiated against its FFmpeg backend. Physical Pi photo, video,
  and audio interaction, touch selection, and playback cleanup passed.
- Stage 12 physical incoming acceptance is complete.
- Stage 13 outbound protocol/client/state/runtime/UI focus is included in the
  complete kiosk relay suite and passed on
  Python 3.13.12. Physical discovery under `pi-bmo` passed without sending.
  The local invented phone simulation passed. The Python 3.9 phone suite now
  passes 103 tests, including its durable command/media state, real HTTP route,
  guarded text-adapter boundary, and incoming failure isolation. A separate real
  loopback run passed the shared Python 3.13 kiosk-to-Python 3.9 phone contract
  for invented text, photo, and reaction commands. The first authorized send
  produced no outgoing message and is retained as consumed; a corrected second
  send remains separately gated.
