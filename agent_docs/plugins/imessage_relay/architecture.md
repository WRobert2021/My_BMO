# iMessage Relay Architecture and Safety

## Ownership model

iMessage Relay is a first-class feature/service plugin. Its Stage 2–9 backend
remains in standalone `iphone_relay/` and `kiosk_receiver/` packages; Stage 10
adds the opt-in adapter at `bmo.features.imessage_relay` without moving either
backend. The reusable separation is not an exemption from plugin contracts.

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
6. Cleanup invalidates late callbacks, closes the view, joins the optional
   reconciliation worker, stops accepting traffic, closes its per-job relay
   store and long-lived receiver store, closes the socket, and releases the
   port exactly once.

`python -m kiosk_receiver.server` remains an explicit standalone alternative.
The Stage 5 sender still has no unattended process entrypoint, and Stage 10
does not add a discovery/delivery loop, launch daemon, default feature entry,
private provisioning, or outbound Messages action.

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
