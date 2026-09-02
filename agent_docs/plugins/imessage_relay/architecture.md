# iMessage Relay Architecture and Safety

## Ownership model

iMessage Relay is a first-class feature/service plugin even though its current
Stage 2–7 code remains in standalone `iphone_relay/` and `kiosk_receiver/`
packages. That separation was a development safety boundary, not a permanent
exemption from plugin contracts. No source package move or runtime adapter is
part of the documentation refactor.

Current boundaries are: Apple read-only parsing; relay-owned discovery/delivery
state and reconciliation; a simulated sender and bounded HTTP(S) event/chunk
transport; kiosk-owned authenticated receipt lookup, pending manifests, and
attachment storage; and a future plugin lifecycle adapter. Discovery cursor,
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

## Intended runtime lifecycle

When a future authorized stage adds the registry adapter:

1. Import and menu metadata remain resource-free.
2. If enabled, plugin runtime registration validates private config and starts
   the owned service/listener.
3. The listener remains active, authenticates iPhone traffic, commits through
   relay-owned stores, and publishes content-free status/future UI state.
4. If disabled, no port, listener, worker, or unnecessary store opens.
5. Startup failure marks Relay unavailable/degraded and is isolated from app
   startup and unrelated plugins.
6. Cleanup stops accepting traffic, stops/joins workers, closes both owned
   stores, closes the server socket, and releases the port exactly once.

The current implementation differs: `python -m kiosk_receiver.server` starts a
standalone receiver explicitly, the Stage 5 sender has no standalone process
entrypoint, and BMO's feature loader knows nothing about Relay. Document and
preserve that distinction until the roadmap stage that authorizes integration.

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
