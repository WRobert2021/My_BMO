# iMessage Relay Architecture and Safety

## Production direction

The production boundary is event-driven phone-to-kiosk push. The phone owns
read-only Apple observation, incremental discovery, a private identifier
backlog, retry control, normalization, and transmission. The kiosk owns
authenticated durable receipt, attachment storage, presentation, resume
control, and the reconciliation schedule.

The kiosk never mounts or copies Apple's live database in production. SSHFS and
full-tree snapshots were useful for authorized Stage 8/9 validation but are not
a runtime transport.

## Runtime split

`be-more-agent` remains Python 3.13.5 on Raspberry Pi OS. The sibling
`phone_relay` project targets Python 3.9 (CPython 3.9.6 in local compatibility
tests and CPython 3.9.9 on the physical phone) and must remain standalone
because the BMO package uses newer Python syntax and runtime assumptions.

The two runtimes share a documented wire contract rather than importing one
another. Compatibility is verified with common canonical JSON/signature/ACK
vectors and real loopback tests.

The phone launchd job runs as dedicated non-login `pi-bmo`; `mobile` remains the
administrator account used for provisioning and recovery only. Because Apple's
SMS tree is mode-private to `mobile`, setup grants `pi-bmo` only inherited
read/traverse ACL rights on that tree. The relay account receives no Messages
write authority, and Apple ownership and POSIX mode bits remain unchanged. The
phone lacks Apple BSD `/bin/chmod`, so the standalone project owns a
dependency-free Darwin ACL helper rather than depending on a shell ACL tool.
The helper replaces/removes only the dedicated UID's allow entry and verifies
that existing ownership/modes remain stable.

## Incoming state model

The phone keeps two distinct durable positions:

- an observation cursor proving which Apple source interval was examined; and
- an identifier-only backlog proving which supported events have not received
  a validated kiosk ACK.

Filesystem activity is only a wake hint. Every wake queries the complete
bounded interval after the cursor, so coalesced notifications and bursts do not
map incorrectly to a single message. Content and attachment bytes are read only
when an identified event is ready for delivery.

Delivery is at least once. The kiosk's stable event ID and canonical digest
make retries idempotent. A network send is never success; only an exact ACK
after kiosk commit removes a phone backlog entry.

## Offline circuit

One failure episode gets an immediate delivery attempt and five one-minute
retries. Exhaustion latches the phone delivery circuit dormant. New events are
still discovered and queued but cannot reset or bypass the latch. Only a valid
authenticated kiosk resume request resets it.

This separation prevents a long kiosk outage plus frequent incoming messages
from keeping the phone in a permanent network-poll loop.

## Deletion behavior

Deletion and related Messages mutations also wake observation. Queued
identifiers are revalidated before send. An event may be pruned only when the
live schema conclusively identifies it as deleted and it has never been ACKed.
Ambiguous edit, unsend, deletion, or reaction-removal evidence fails closed
until a controlled live corpus establishes the exact mapping.

Identifier-only backlog storage means content deleted before delivery is not
archived by the relay. This is an explicit best-effort product tradeoff.

## Reconciliation

The kiosk schedules a bounded recent-window check once or twice weekly and asks
the phone to perform it. The phone reads Apple data locally, presents stable
event ID/digest candidates to the existing kiosk receipt endpoint, and resends
only missing entries. Conflict never overwrites either side, and absence never
authorizes deletion of kiosk history.

## Non-negotiable source safety

- Apple's Messages database, WAL/SHM, attachment tree, metadata, reactions,
  read state, chats, permissions, and process state are read-only.
- Never issue INSERT/UPDATE/DELETE, DDL, checkpoint, journal-mode mutation,
  VACUUM, message sending, reaction changes, or attachment modifications.
- Use SQLite URI `mode=ro`, `PRAGMA query_only=ON`, and one read transaction.
  Do not use `immutable=1` for a changing WAL database.
- Phone writable state is limited to private configuration, cursor/backlog,
  retry metadata, and bounded non-content diagnostics.
- Kiosk state is separate private receipt/nonce/attachment storage.
- The public notification count boundary opens only that kiosk receiver state
  in read-only/query-only mode; its caller owns any last-seen checkpoint or
  runtime attention.
- Message content, handles, paths, credentials, keys, and private fixtures do
  not enter tracked files or default logs.

## Kiosk lifecycle

Import and menu metadata remain resource-free. Enabled registration validates
private receiver configuration, opens the kiosk receipt store, binds the
receiver, and starts its listener. It does not start a source mount, local
sender queue, Apple parser, or polling worker.

The failure-isolated phone control client sends resume at receiver startup,
uses content-free health probes to detect a later network return, and schedules
bounded recent reconciliation weekly. Missing or invalid control configuration
does not affect the receiver or local feed. Cleanup closes the view, joins the
control and receiver threads, closes both transports and the store, and
releases ports exactly once.

The installed phone maintenance command is invoked from a `mobile` SSH session
and controls the launchd unit rather than the Python process directly. Stop
boots the job out so KeepAlive cannot restart it. Start validates fixed
installed paths and bootstraps/kickstarts the unit. Confirmed uninstall revokes
the exact relay ACL, deletes the `pi-bmo` service identity, removes only
relay-owned paths, and retains Apple Messages data plus the `mobile`
administrator account.

## Deferred outbound direction

Stage 13 may extend the same authenticated bridge with kiosk-originated text,
photo/video, and reaction commands only after incoming acceptance. It must
define replay-safe request IDs, recipient selection, delivery states, user
confirmation, and an evidence-backed Messages sending interface. Direct Apple
database writes remain prohibited.
