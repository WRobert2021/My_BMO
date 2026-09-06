# iMessage Relay Architecture and Safety

## Ownership model

iMessage Relay is a first-class feature/service plugin. Stage 11 consolidates
its backend under `bmo.features.imessage_relay.relay` and
`bmo.features.imessage_relay.receiver`; the opt-in feature entrypoint remains
`bmo.features.imessage_relay`. Relay/receiver subpackages preserve distinct
state and protocol ownership without root-level package identities.

Current boundaries are: Apple read-only parsing; relay-owned discovery/delivery
state and reconciliation; a simulated sender and bounded HTTP(S) event/chunk
transport; kiosk-owned authenticated receipt lookup, pending manifests, and
attachment storage; and an optional BMO lifecycle/status adapter. Discovery cursor,
lookback observation, queued transmission, pending manifest, partial upload,
complete kiosk receipt, and sender ACK are distinct states. Stable event GUIDs
provide idempotency; source ROWIDs are local scan cursors only.

## Non-negotiable source safety

- Apple's Messages database, WAL/SHM, attachment tree, metadata, reactions,
  read state, and chats are external read-only input.
- Never issue INSERT/UPDATE/DELETE, DDL, checkpoint, journal-mode mutation,
  VACUUM, message sending, reaction changes, or attachment modifications.
- Use SQLite URI `mode=ro`, `PRAGMA query_only=ON`, and one read transaction.
  Do not use `immutable=1` for the changing live WAL database.
- Stage 8 validation mounts only the authorized Messages root read-only and
  opens SQLite solely against a disposable local copy of the DB/WAL/SHM trio.
  A source change makes the observation inconclusive; it never authorizes a
  checkpoint, Messages shutdown, permission change, or writable remount.
- The authorized Stage 9 phone-access redesign requires a password-protected,
  SFTP-only `pi-bmo` account with server-enforced read-only operations, no
  shell or forwarding, and filesystem confinement to the DB/WAL/SHM trio plus
  the `Attachments` tree. It must not expose the remainder of the SMS directory
  or phone. The replacement passed Mac and physical-kiosk access/confinement
  checks before the temporary `agent` user, group, and SSH policy were removed.
  Apple-owned permissions were not weakened to make either account work.
- Relay cursors, payloads, attempts, retries, ACKs, errors, dead letters,
  nonces, kiosk receipts, partial offsets, and received attachment bytes live
  only in separate relay/kiosk-owned stores and private files.
- Private content, handles, chat IDs, paths, attachment names/bytes, snapshots,
  credentials, and keys never enter tracked docs/fixtures or default logs.
- Initial iPhone operation stays manual with graceful Ctrl-C. No daemon,
  service installation, live-iPhone access, or deployment occurs outside its
  explicitly authorized stage.

## Runtime lifecycle

When an explicit feature entry enables the Stage 10 adapter:

1. Import and menu metadata remain resource-free.
2. Enabled registration validates the private receiver and relay config paths
   and starts the owned receiver listener. The module remains outside defaults.
3. The listener authenticates relay traffic, commits through the receiver-owned
   store, and publishes content-free aggregate status. Recent/month
   reconciliation starts only from an explicit UI action and opens its relay
   store inside the single owned worker thread.
4. If disabled, no port, listener, worker, or unnecessary store opens.
5. Invalid private receiver configuration leaves a visibly degraded registered
   surface; malformed feature settings are isolated by loader rollback. Neither
   case blocks app startup or unrelated plugins.
6. When Stage 12 source configuration is present, enabled registration also
   owns a strict read-only SSHFS mount and one bounded discovery/delivery
   worker. The private relay view polls a bounded receiver feed locally.
7. Cleanup invalidates late callbacks, closes the view, joins optional
   reconciliation and incoming workers, unmounts only an owned source, stops
   accepting traffic, closes stores and sockets, and releases the port exactly
   once.

`python -m bmo.features.imessage_relay.receiver.server` remains an explicit
standalone alternative.
The Stage 5 sender still has no independent unattended process entrypoint.
Stage 12 composes it into the opt-in BMO lifecycle and provides an explicit
private configurator plus phone snapshot-publisher assets. It adds no outbound
Messages action.

## Reliability model

Delivery is at least once. Network transmission is never success; only a
validated expected kiosk ACK after durable, idempotent ingest allows sender
state to acknowledge. Timeouts/lost ACKs retry the identical stable event with
fresh request authentication. Poison items become visible dead letters without
blocking later work. Reconciliation reuses normal idempotent ingestion and must
never delete kiosk-only history.

Stage 5 implements this delivery path in local simulation. Stage 6 adds bounded
sender-candidate receipt comparison: missing acknowledged entries may be
requeued, present attempted entries may be confirmed, conflicts remain
unchanged, and kiosk-only history is never enumerated or deleted. Status and
reports contain counts and bounded error codes only. These stages do not change
the later live-device, deployment, or runtime gates.

Stage 7 makes event ACK attachment-aware. Available ordinary files and Live
Photo components are hashed and transferred in bounded authenticated chunks;
the kiosk owns restart-safe offsets and promotes a pending event only after all
required blobs pass exact size and digest checks. Missing/unsafe/changed source
files and legacy metadata-only ACKs fail closed. Neither side loads a whole
attachment into memory, and no Stage 7 code contacts a live device.

## Deferred outbound direction

The product intent includes kiosk-originated text replies, photo/video sends,
and reactions after incoming relay acceptance. That work is not implemented or
authorized yet. Its stage must first evaluate a separate iPhone Python 3.9.9
environment versus a narrower native bridge, then define authenticated,
replay-safe, idempotent commands and delivery-state reporting. Outbound actions
must use an evidence-backed Messages sending interface; they must never write
Apple's Messages database or attachment tree directly.
