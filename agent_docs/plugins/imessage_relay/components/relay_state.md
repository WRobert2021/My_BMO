# Relay State and Durable Queue

## Status and boundary

Stage 3 implements a local, relay-owned SQLite state manager. Stage 5 uses its
public claim/failure/ACK transitions from `sender.py`, and Stage 6 uses bounded
lookback commits, keyset pages, and selective acknowledged-event requeue.
Stage 7 keeps relay schema version 1 and uses the same attempt lifecycle, but
sender ACK now requires a kiosk attachment-complete event response. The store
itself remains independent of the kiosk application runtime and contains
no network client, receiver, authentication, live-iPhone access, launch daemon,
or UI integration. Current stage authority lives only in `../progress.md`.

The store must never point at Apple's Messages files. `RelayStateStore`
explicitly rejects the Apple `sms.db` and `chat.db` filenames and their WAL/SHM
companions. A new state file is created with mode `0600`; existing state files
with group or world permissions fail closed. The containing directory should
be created privately by the operator, for example with mode `0700`.

## Ownership and persisted data

`bmo.features.imessage_relay.relay.state` solely owns the SQLite schema and
state transitions. `bmo.features.imessage_relay.relay.state_codec` solely owns
the canonical version-one JSON payload stored inside the database.
`bmo.features.imessage_relay.relay.state_config` parses only the
relay-owned state/retry configuration and acquires no runtime resources.

The store persists each normalized event payload at discovery time. This is
intentional: the controlled corpus proves that reaction-add rows can later be
deleted, and ordinary source rows or content may also become unavailable
before a retry. Persisting the bounded normalized payload allows metadata and
text retries without depending on the continued existence of the Apple row.

Attachment bytes are not copied into SQLite. Payloads retain their normalized
attachment metadata, availability, and contained source paths. Stage 7 reads
available source files in bounded chunks while the attempt is in flight;
missing, unsafe, size-changed, or metadata-changed sources fail into the normal
retry/dead-letter policy. Durable partial bytes and offsets belong to the kiosk
receiver rather than this sender database.

Acknowledged events remain stored for stable-ID deduplication and
reconciliation. Stage 6 does not add pruning: sender absence is not deletion
authority, and retention/storage-growth policy remains a later explicit
decision.

## Database schema

The owned database uses SQLite `application_id = 0x494D524C` (`IMRL`) and
`user_version = 1`. An empty version-zero file is initialized; populated
unrecognized, incomplete, corrupt, or future-version databases fail closed and
are not overwritten.

- `source_cursors`: observation cursor per named source.
- `relay_events`: canonical payload, digest, source ordering, queue state,
  attempt counts, retry eligibility, ACK, and dead-letter metadata.
- `delivery_attempts`: immutable attempt identity/number plus its final
  outcome and bounded diagnostic code.
- `parse_issues`: bounded privacy-safe parser issues, deduplicated with an
  occurrence count.
- `scan_commits`: non-content audit of each atomic discovery commit or replay.

The state database uses WAL mode, foreign keys, full synchronous durability,
and explicit `BEGIN IMMEDIATE` transactions. This WAL belongs only to the relay
state store; it is unrelated to and never checkpoints Apple's WAL.

## Atomic discovery and checkpoint rule

```python
cursor = store.source_cursor()
batch = reader.scan(after_rowid=cursor, limit=100)
store.commit_scan(batch, expected_after_rowid=cursor)
```

One transaction validates and persists the event payloads, parser issues, scan
audit, and new source cursor. A database error, conflicting GUID payload, stale
cursor, invalid issue, or invalid event rolls back every part of the batch.
The cursor therefore never commits ahead of a normalized event or its visible
parse issue.

Replaying a fully observed batch is idempotent when each GUID, source ROWID,
event kind, and payload digest matches. A stable GUID with different content
fails closed. A stale batch that includes any row beyond the current cursor is
rejected instead of merging a discontinuous checkpoint.

Parser-invalid rows are retained as visible `parse_issues` before their source
cursor advances. They do not permanently block later rows, and repeated
lookback/reconciliation scans increase their occurrence count without copying
private source values into diagnostics.

## Delivery lifecycle

```text
queued -> in_flight -> acknowledged
             |
             +-> retry_wait -> in_flight
             |
             +-> dead_letter -> queued (explicit requeue)
```

- `claim_next()` leases the oldest currently eligible source event and records
  a unique, monotonic attempt.
- No response, a negative response, or another delivery failure calls
  `record_failure()` with a short allowlisted-style error code—not exception
  text, payload content, handles, or paths.
- Retry delay is exponential and capped by `RetryPolicy`. Later eligible rows
  may proceed while an older failure waits, so one poison event does not block
  the queue.
- An unfinished attempt becomes `lease_expired` after its durable lease and
  enters the same bounded retry/dead-letter policy after restart.
- Reaching the configured attempt limit makes the event visibly
  `dead_letter`. `requeue_dead_letter()` starts a fresh bounded retry cycle
  while preserving total attempt numbering and history.
- `acknowledge(event_id)` is accepted only after at least one attempt. Duplicate
  ACKs are idempotent. A late ACK may resolve retry-wait or dead-letter state
  because durable kiosk receipt is authoritative even if the sender timed out.

The delivery lease is not a claim that transmission succeeded. The Stage 5
sender calls `acknowledge()` only after a strict expected kiosk ACK that follows
durable, idempotent kiosk processing; every other result uses
`record_failure()`.

For an event with required attachment blobs, Stage 7 rejects a metadata-only
ACK. `acknowledge()` is reached only after every blob is receiver-complete and a
repeated canonical event returns `attachment_status: complete`. An interrupted
chunk therefore finishes the current delivery attempt as failed while keeping
its kiosk offset resumable for the next normal attempt.

## Reconciliation transitions

`commit_reconciliation_batch()` applies the normal canonical round-trip,
stable-ID conflict, atomic insert, and issue rules to one bounded time-window
page without reading or modifying the live source cursor. `list_entries_page()`
uses a `(source_rowid, event_id)` keyset and caps each decoded page at 20.

An authenticated receiver `missing` result calls
`requeue_acknowledged_for_reconciliation()`. It changes only an acknowledged
entry to queued, clears the old ACK timestamp, resets its retry-cycle count,
and preserves total attempts/history. Pending or dead-letter entries are not
implicitly reset. A `present` result may use the normal late-ACK path only when
the local event already has an attempt. Conflict never mutates delivery state.

## Configuration

The tracked `config/example.imessage_relay.json` documents:

- private state database path;
- initial retry delay;
- integer exponential multiplier;
- maximum delay;
- maximum attempts per retry cycle; and
- in-flight lease duration.

`load_state_config()` accepts an explicit base directory for relative state
paths. A missing private config returns defaults in memory and creates nothing.
Unknown, duplicate, non-finite, incorrectly typed, excessive, or inconsistent
values fail closed. Copy the example only when local customization is needed;
`config/imessage_relay.json` and `data/imessage_relay/` are ignored.

## Security and privacy

- The state file contains private normalized text, sender/chat identifiers,
  and attachment paths. Never commit, upload, or log it.
- Canonical payload SHA-256 detects accidental corruption and inconsistent
  duplicate discovery. It is not an authentication mechanism against an
  attacker who can rewrite the entire private database.
- Payload JSON is size-bounded, duplicate-key rejecting, non-finite rejecting,
  exact-field validated, and decoded back into immutable event records.
- Parse details are bounded. Delivery failures persist only validated short
  error codes.
- The state manager creates no parent directory and never weakens permissions
  on an existing file.

## Stage 3 verification scope

`tests/test_imessage_state.py` covers atomic rollback, cursor conflicts,
duplicate discovery, conflicting payloads, parser-issue durability, payload
round trips and tamper detection, private paths/permissions, schema creation
and rejection, clean close, restart at queued/in-flight/retry/ACK/dead-letter
states, lease expiry, bounded backoff, lost and duplicate ACKs, poison-event
bypass, late ACK, dead-letter requeue, strict configuration, and the full
Stage 2 parser-to-Stage 3 store flow using a disposable snapshot copy.

No network request, live iPhone database, kiosk service, or application feature
was used.
