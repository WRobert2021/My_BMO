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

The selected adapter is dependency-free Python 3.9 `ctypes` over libobjc. A
native helper remains a fallback only if later simulation proves the Python
boundary insufficient. The current phone and Mac tool inventories do not
justify adding a compiler, signing tool, or PyObjC dependency.

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
owns verified bounded upload. A local invented phone simulation proves
durable-before-network ordering, all three command kinds, resumable chunk
transfer, and lost-ACK recovery without duplicate execution. The matching
Python 3.9 phone handler, durable phone execution ledger and staging store,
user confirmation UI, and cross-runtime simulation are the next chapter and
are not yet deployed.
