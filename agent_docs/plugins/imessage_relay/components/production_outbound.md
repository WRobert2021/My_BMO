# Production Outbound Relay

## Stage and scope

Stage 13 adds kiosk-originated iMessage text, photo/video, and standard tapback
commands after Stage 12 incoming delivery. It uses the existing dedicated
`pi-bmo` phone service and private TLS/HMAC relationship. Outbound is a separate
command plane: an incoming failure must not stop BMO, and an outbound failure
must not damage or rewrite the incoming receipt history.

No physical outbound message is authorized merely by beginning Stage 13. The
implementation must first pass invented-data simulation. A first physical send
requires separate confirmation naming the recipient and test content.

## Verified phone interface

Read-only runtime introspection established that the phone's dyld shared cache
can resolve Foundation, IMCore, IMFoundation, IMSharedUtilities, ChatKit, IDS,
and libobjc. `IMAutomationMessageSend` exposes high-level text and file-path
send selectors plus message-construction helpers; `IMChat` exposes message and
message-acknowledgment operations needed for reactions.

A no-send initialization ran after dropping to the deployed service identity,
UID 1002/GID 1001. It reported iMessage enabled, service availability, text and
photo/video/audio capability, and successful `IMAutomationMessageSend`
construction. MMS was disabled. No recipient, message, attachment, or reaction
was submitted.

The first implementation is iMessage-only and must explicitly select the
iMessage service. It does not silently fall back to SMS/MMS; the disabled MMS
capability therefore does not block the verified iMessage photo/video path.

Physical preflights proved the standalone Python 3.9 `ctypes` boundary
insufficient: it could connect to IMDaemon but could not obtain a usable active
iMessage account. That path is retired. The selected adapter is a rootless
Theos helper injected only into SpringBoard, with a narrow Python 3.9
Unix-socket client remaining under `pi-bmo`. Theos and `ldid` are build-only Mac
dependencies and add nothing to the phone relay's Python or kiosk runtime.

## Command lifecycle

1. The kiosk constructs a command with a stable command ID, canonical UTC
   timestamp, explicit destination, and bounded kind-specific data.
2. Before network activity, the kiosk commits the canonical command and digest
   to a private `0600` SQLite outbox.
3. The kiosk signs an exact request with the existing HMAC scheme and sends it
   over production TLS.
4. Before touching Apple services, the phone durably reserves the command ID
   and canonical digest in relay-owned private state.
5. A repeated ID with the same digest returns the stored state. A repeated ID
   with different content is rejected and never executed.
6. The phone moves the command to `executing`, invokes the narrow adapter once,
   and records `sent`, `failed`, or `uncertain` before answering when possible.
7. The kiosk accepts only an exact request ID, command ID, protocol version,
   and state. A missing or malformed result becomes `uncertain`, not success.
8. Terminal `sent` and `failed` records never retry automatically. An
   `uncertain` record is resolved by status before any operator-approved retry.

This is at-most-once execution around the Apple call, not a promise of carrier
delivery. `sent` means the verified Apple sending interface accepted the
operation. Delivery/read receipts are a separate future concern.

## Recipient and reply safety

Every command names one or more canonical E.164 phone numbers or email
addresses. No command may infer the recipient from whichever conversation is
currently open. A reply additionally carries the selected incoming chat ID and
message ID. The phone adapter must verify that this context still resolves to
the explicit recipients before sending.

The kiosk UI must show the resolved contact or explicit address, content kind,
and attachment count before queuing. Sending is never triggered by merely
opening a message, attachment, or notification.

The kiosk confirmation gate holds at most one prepared command in memory for a
bounded time. It displays exact recipients plus text, media names, or reaction
operation as applicable. Only the exact, unexpired opaque confirmation token
can release the command once; mismatch, expiry, cancellation, reuse, or view
cleanup fails closed. Preparing or confirming at this boundary does not itself
open durable state or contact the phone. The later Qt controller is responsible
for passing the released command to the authenticated client.

The Qt relay surface now provides a new-message composer and a per-message
reply action. Reply context is looked up again from the current feed by stable
message ID rather than accepted from QML. The review surface shows exact
recipients and text before its separate send action becomes available. A
resource-owning coordinator submits on a worker only after the exact one-shot
confirmation. Normal plugin registration constructs that coordinator only
when `outbound_enabled` is explicitly true; otherwise this UI path cannot
contact the phone.

Incoming feed items retain their stable message ID, chat ID, and participant
IDs so a reply or reaction can bind to the selected receipt rather than the
foreground conversation. These identifiers are kiosk receipt metadata and do
not grant send authority by themselves.

## Media staging

The command JSON contains blob ID, leaf transfer name, category, MIME type,
byte count, and SHA-256 digest. It never contains a kiosk or phone path. Media
bytes use a separate bounded authenticated session/chunk flow into a private
relay-owned staging directory. The kiosk verifies a regular non-symlink source
against the command metadata and streams at most 64 KiB per request. Sessions
resume at the phone's exact durable offset after interruption. The phone must
verify the final length and digest, reject links and non-regular files, supply
only its own validated staging path to Apple, and clean staging after a
terminal result.

Stage 13 covers photo and video sends. Incoming audio remains supported, but
outbound audio is not claimed unless a later verified product decision adds it.

## Reaction behavior

Reaction commands carry the exact source-message identity, chat context, part
index, standard reaction kind, and add/remove operation. The adapter must
resolve that target and fail closed if it is absent or ambiguous. It must not
fall back to sending reaction prose or to the current foreground chat.

## Failure isolation and cleanup

Outbound imports open no database, listener, socket, or Apple framework.
Lifecycle construction is opt-in. Private framework loading occurs only in the
phone executor process after configuration, identity, and command validation.
Errors exposed to the kiosk are bounded codes without recipient, message,
attachment, path, or framework content.

The existing phone maintenance stop must also stop outbound acceptance and any
in-progress staging. Confirmed uninstall removes outbound state and staged
media with the rest of relay-owned data while retaining Apple Messages data.

## Current implementation boundary

`bmo.features.imessage_relay.outbound.protocol` owns the canonical path-free
command model. `bmo.features.imessage_relay.outbound.state` owns the private
kiosk outbox, `bmo.features.imessage_relay.outbound.client` owns signed
submission and status resolution, and `bmo.features.imessage_relay.outbound.media`
owns verified bounded upload. `bmo.features.imessage_relay.outbound.confirmation`
owns the resource-free one-shot user gate, and
`bmo.features.imessage_relay.outbound.coordinator` owns confirmed background
text submission. The standalone Python 3.9 phone
runtime now mirrors the strict contract, routes the authenticated endpoints on
its existing TLS listener, durably reserves commands, converts an interrupted
execution to terminal `uncertain`, and owns private resumable media staging.
Its default production invocation deliberately constructs the disabled
executor and returns `apple_send_not_enabled`.

The local `phone_relay.springboard_outbound` executor accepts only a new
single-recipient text command, exchanges strict length-framed canonical JSON at
the fixed rootless socket, and rejects group, reply, media, and reaction shapes
before connecting. The SpringBoard-only native package verifies the caller with
`LOCAL_PEERCRED`, loads the non-UI messaging frameworks, applies the modern and
legacy IMDaemon capability hooks, validates account/chat/message readiness, and
invokes `sendMessage:` at most once. The relay then queries Apple's database
read-only for the exact returned GUID and `is_from_me = 1`. Any ambiguous
post-invocation outcome remains terminal `uncertain`.

The package builds locally for `arm64` and `arm64e`. It is not connected to the
production launcher, deployed, injected, or physically exercised. Those are
separate gates; incoming service behavior remains unchanged.

### Retired standalone-process investigation

The first Apple execution adapter is implemented behind a separate in-process
enable flag that the service does not set and private configuration cannot
select. It loads Foundation, IMCore, and
libobjc only after that gate; accepts only a new, single-recipient text
command; requires the narrow previously observed Objective-C selector and type
encoding; initializes and verifies Apple's shared message-sending utilities;
supplies an empty file list and the explicit `iMessage` service; and pumps the
Foundation run loop for at most five seconds while waiting for nonempty
`sentMessageInfo` with no pending GUIDs. A non-null Objective-C return is not
independently a success signal, and an entered call without the stronger
evidence becomes `uncertain` with a bounded evidence-specific code.
Group text, reply context, media, and reactions are rejected before framework
loading. Injected tests cover exact argument selection, ABI arity, evidence
classification, and failure mapping without loading an Apple framework.

Local invented simulations prove durable-before-network ordering, all three
command kinds, replay/conflict rejection, resumable chunk transfer, verified
crash recovery, lost-ACK recovery without duplicate execution, confirmation
expiry/reuse rejection, and real HTTP interoperability between the Python 3.13
kiosk client and Python 3.9 phone handler. Outbound state failure is isolated
from incoming phone delivery. The first authorized physical call returned an
object without `NSError`, but it created no outgoing phone message and produced
no recipient delivery. That exposed and removed the adapter's invalid non-null
success assumption. The original test command remains duplicate-protected in
the phone ledger and must not be retried. The first corrected adapter then
passed its deployed no-send selector/ABI preflight, but its separately
authorized second physical call returned `uncertain`, created no outgoing phone
message, and produced no recipient delivery. That second command is also
consumed and must not be retried. The bounded sending-utility initialization
and asynchronous evidence wait are implemented, deployed, and have passed a
no-send readiness preflight under the phone service identity. Its subsequent
separately authorized physical call returned `uncertain` with empty sent
evidence and created no outgoing message or delivery; that command is consumed.
The next investigation is the phone's separate IMDaemon connection and
process-capability boundary, without sending. Live no-send inspection verified
that this phone exposes the older 32-bit `_capabilities` ABI rather than
`processCapabilities`, along with the daemon connection, chat registry,
account/handle/message construction, and chat-send selectors. Whether the
unmodified service identity can establish the daemon connection was then tested
in a disposable process: it reported native capabilities `512`, the connection
call succeeded, and `isConnected` became true without accessing Apple data or
sending. No capability override was needed for that automation-sender path. The guarded adapter now
validates that exact ABI and establishes the native daemon connection before
constructing or invoking the sender; this passed local tests before deployment.
The deployed readiness preflight subsequently passed under `pi-bmo`, and the
normal phone relay was restarted and verified running. No send was performed.
Its separately authorized daemon-connected physical call still returned empty
sent evidence and created no outgoing phone message or delivery. That command
is consumed, and `IMAutomationMessageSend` is retired as an execution candidate.
The next no-send gate is direct IMCore readiness: resolve an existing chat,
construct an in-memory `IMMessage`, and call only `canSendMessage:` before any
new direct-chat adapter or physical authorization is considered.
That no-send probe connected and constructed the message object, but native
capability `512` exposed neither an active iMessage account nor the existing
test chat, leaving `canSendMessage:` false. No send method was invoked. Any
future capability elevation must therefore be confined to a disposable
command-scoped helper after authentication and durable reservation; the
long-running relay process must retain its native capabilities.
The first helper design would have replaced a private Objective-C method
temporarily and could invoke `sendMessage:`. Because that introduced
unsupported process-stability and unintended-send risk, it required separate
informed implementation approval. Approval to implement it did not authorize
deployment, execution, or a physical message.

That implementation-only approval was given on 2026-09-13. The standalone
phone project first contained the helper behind disconnected boundaries. That
design has since become the reviewed broker implementation while remaining
opt-in at the launcher boundary. It receives one canonical command over a
private framed socket, emits only bounded content-free JSON, and rejects
non-text, group, reply, media, and reaction commands before private-framework
use.

Inside that child only, the current implementation requests capability `17159`
through the exact verified
`connectToDaemonWithLaunch:capabilities:blockUntilConnected:` selector. It does
not replace `_capabilities` or another Objective-C method. It establishes that
connection before initializing the shared sending utilities, then reconnects
the post-initialization daemon controller with `17159` if the initializer
replaced the singleton. The content-free preflight stops after validating
selectors, establishing the explicit daemon connection, initializing the
account monitor, and resolving the active iMessage account. It does not accept
a recipient or construct a message. The execution path is implemented but not
approved for deployment or use: it constructs a handle/chat/message, requires
`canSendMessage:`, invokes `sendMessage:` at most once, and reports `sent` only
after the generated GUID appears as outgoing in a bounded read-only Apple
Messages query. Missing evidence, timeout, or an ambiguous child boundary is
terminal `uncertain` and cannot automatically retry.

The phone maintenance command now has a separate `outbound-preflight` action.
It invokes only the exact installed launcher/configuration tuple, permanently
drops from the mobile launch context to `pi-bmo`, runs the content-free helper
preflight, and exits. It neither stops the incoming job nor exposes an
execution flag. Production launchd and configuration remain unchanged.

The first two deployed no-send helper iterations failed closed before account
lookup. The first could not confirm the capability replacement; the second
proved that sending-utility initialization changes the shared daemon-controller
identity. These failures did not accept a recipient, construct a message, or
call `sendMessage:`.

The next no-send runs reached the active-account gate after observing the local
replacement and connecting a controller, but returned
`apple_imessage_account_unavailable` without reaching a recipient or message.
Code review showed why: sending-utility initialization could establish a daemon
session with native capability `512` before the replacement, and observing the
replacement afterward did not renegotiate that session. The replacement design
is retired. The first explicit-connection preflight also returned
`apple_imessage_account_unavailable`, showing that capability negotiation alone
does not initialize `IMAccountController`'s account monitor. The current helper
connects with `17159` first, initializes the shared sending utilities, resolves
the possibly replaced controller, and explicitly reconnects that replacement
when needed. It polls daemon connection and account readiness for at most five
seconds each and has no dependency on `_capabilities` or the legacy
zero-argument connection method. Its revised content-free phone preflight is
now complete and still returned `apple_imessage_account_unavailable`. This
shows that the dedicated `pi-bmo` process cannot obtain an account through the
account-controller selectors even after explicit capability negotiation and
monitor initialization.

The approved replacement is a split-identity boundary. The launcher can fork a
single broker before permanently dropping the main process to `pi-bmo`; that
broker permanently drops to verified UID/GID 501 and communicates only through
an anonymous socket pair. It has no network listener or shell. It accepts only
a new single-recipient text command that the `pi-bmo` service has already
authenticated and durably reserved. Group, reply, media, and reaction shapes
remain blocked. Broker creation failure selects the disabled executor without
stopping incoming delivery.

The kiosk composer/confirmation coordinator is wired by normal plugin
registration only when `outbound_enabled` is explicitly true. Its durable state
defaults to `config/private/imessage_outbound.db`, and setup failure degrades to
incoming-only. The phone launchd/sudoers examples still omit the opt-in broker
argument; mobile-identity preflight, deployment activation, and a new
separately authorized physical message remain gates.

The first maintenance action named `outbound-mobile-preflight` was still
root-originated: it invoked Python through sudo and changed to UID/GID 501 only
inside the process. Its unchanged `apple_imessage_account_unavailable` result
proves that UID replacement is insufficient to recreate the iOS mobile process
context. The revised action runs the content-free preflight directly from the
authenticated `mobile` login, verifies real and effective UID/GID 501, and does
not use sudo. That targeted physical result now gates the production bootstrap
shape.
The service application root must be mode `0755` because Python enumerates its
configured import root while locating `phone_relay`; mode `0751` permits path
traversal but makes the package appear absent. This exposes only root-owned,
read-only source names. Private configuration and state directories remain
mode `0700`, and private files remain mode `0600`.
The genuine mobile-context result still failed at account lookup. The remaining
implementation defect was the capability generation: `17159` is the legacy
contract, while modern iOS uses `processCapabilities` value `4485895`. The
disposable process now installs that modern method before connecting and keeps
the legacy method only as a compatibility fallback. No recipient or send call
is part of this revised preflight.
