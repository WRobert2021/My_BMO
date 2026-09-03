# iMessage Relay Messages Schema Evidence

> Opt-in historical evidence from Stage 1. Current parser behavior is owned by
> `../components/parser.md`; current continuation state is owned only by
> `../progress.md`. This evidence does not override either document.

## Status and scope

**Stage:** Stage 1 — Messages Schema Investigation
**Primary evidence:** `iphone_snapshot/` controlled-test snapshot
**Baseline:** `iphone_snapshot_stage0/`
**Report date:** 2026-08-28

This report describes only the schema and behavior demonstrated by the two
supplied snapshots. It is the input contract for Stage 2; it is not a
production parser or a live-iPhone deployment guide.

The controlled snapshot conclusively covers ordinary iMessage text, incoming
and outgoing direction, one-to-one chats, normal JPEG attachments, one Live
Photo, one QuickTime video, the six legacy reaction additions, sent and
received thumbs-up removals, and WAL visibility. It does **not** conclusively
cover SMS/MMS rows, email handles, group chats, null/empty `text` fallback,
edited messages, a structurally identifiable emoji reaction, or a detectable
Undo Send event. Those limits are called out rather than filled with older
schema assumptions.

No production relay code was implemented. No live iPhone was contacted.

## Evidence method and privacy controls

All original DB/WAL/SHM files were SHA-256 fingerprinted. The complete trio
from each snapshot was copied byte-for-byte into `/private/tmp`, and SQLite was
opened only against those disposable copies with a `file:` URI using
`mode=ro` plus `PRAGMA query_only=ON`. A logical SQLite backup was used for
cross-snapshot comparisons. Original fingerprints were verified again after
inspection.

The repeatable evidence probe is:

```bash
.venv/bin/python -m bmo.features.imessage_relay.tools.inspect_schema \
  iphone_snapshot_stage0 iphone_snapshot \
  --assert-controlled-corpus
```

The probe deliberately omits message text, handles, GUID values, filenames,
and blob contents. Controlled message text was viewed only where needed to map
known test cases to rows; it is not reproduced here. Identifiers in examples
are local aliases such as `m25` (message ROWID 25) and `a3` (attachment ROWID
3), never real GUIDs or handles.

### Evidence strength labels

- **Observed:** directly demonstrated by these snapshots.
- **Derived:** deterministic conclusion from observed values or schema.
- **Inferred:** plausible generalization that needs another fixture/version.
- **Unresolved:** no reliable representation was demonstrated.

## Snapshot integrity and high-level differences

Both logical databases report:

- WAL journal mode;
- `PRAGMA quick_check = ok`;
- schema version 85;
- 16 tables, 44 indexes, and 16 triggers.

| Evidence | Stage 0 baseline | Controlled snapshot |
| --- | ---: | ---: |
| Logical `message` rows | 6 | 36 |
| Maximum `message.ROWID` | 6 | 38 |
| Missing allocated message ROWIDs | none | 13, 16 |
| `attachment` rows | 1 | 4 |
| `handle` rows | 2 | 2 |
| `chat` rows | 2 | 2 |
| `sync_deleted_messages` rows | 0 | 2 |
| Attachment files | 1 JPEG | 4 JPEG, 3 MOV, 1 XML plist |

The controlled interval allocated 32 new message ROWIDs (7–38), retained 30
new logical rows, and deleted two rows. Three attachment rows and their message
joins were added. No handle, chat, chat-participant, existing attachment, or
existing message row was added/removed/modified except:

- chat 1's `last_read_message_timestamp` advanced; and
- chat 1's binary-plist `properties` updated operational values such as its
  last-message watermark and response count.

Every pre-existing message row was byte-for-byte equal at the SQLite column
level. The two missing message ROWIDs correspond to reaction-add rows removed
when their thumbs-up reactions were removed. Their GUIDs remain in
`sync_deleted_messages`, and each surviving removal row's `reply_to_guid`
points to the corresponding deleted add GUID.

This comparison proves that the test interval was not append-only even though
all surviving events were new rows.

## Relevant schema map

### Core relationships

```text
handle.ROWID
   ^
   | message.handle_id                 attachment.ROWID
   |                                        ^
message.ROWID                               | message_attachment_join.attachment_id
   ^                                        |
   | chat_message_join.message_id      message_attachment_join.message_id
   |
chat.ROWID <- chat_message_join.chat_id
   |
   +---- chat_handle_join.chat_id -> chat_handle_join.handle_id -> handle.ROWID
```

### Tables used by the relay investigation

| Table | Relevant ownership |
| --- | --- |
| `message` | Ordinary messages, standard reaction add/remove events, direction, text/body, timestamps, attachment cache flag, source GUID, and target association. |
| `handle` | Remote phone/email-like address plus service; observed phone handles only. |
| `chat` | Stable chat GUID, service, identifier, optional group/display fields, and operational properties. |
| `chat_message_join` | Many-to-many schema mapping messages to chats; exactly one chat per message in this corpus. |
| `chat_handle_join` | Remote participants; exactly one participant per observed chat. |
| `attachment` | Stable attachment GUID, source filename, UTI/MIME, transfer name/state, sizes, and transfer metadata. |
| `message_attachment_join` | Message-to-attachment association. |
| `sync_deleted_messages` | GUIDs of two deleted reaction-add rows in this corpus. |
| `deleted_messages` | Delete-trigger destination, empty in both logical snapshots. |
| `message_processing_task` | Present but empty. |

No edit/revision table exists in this schema. The `message` table also lacks
columns named `edited`, `date_edited`, or `associated_message_emoji`.

## Incoming, outgoing, and iMessage filtering

### Direction

**Observed:** `message.is_from_me` is the reliable direction flag:

- `0`: incoming/remote-authored row;
- `1`: outgoing/local-authored row.

The current corpus has 32 incoming and 4 outgoing rows. Both standard reaction
adds and reaction removals use the same direction flag. `is_sent`,
`is_delivered`, and `is_read` are delivery/read state, not substitutes for
direction.

For incoming rows, `message.handle_id` joins to the remote sender's `handle`.
For outgoing rows, that same handle is the recipient, **not** the sender. The
local account is represented by `account_guid` (a 36-character opaque value),
with `account` and `destination_caller_id` carrying local account/address
strings. A normalized outgoing sender should be `self` (optionally tied to the
opaque `account_guid`); it must not mislabel the recipient handle as sender.

### Service allowlist

**Observed:** all 36 current rows have:

```sql
message.service = 'iMessage'
```

Both observed chats and handles also use `iMessage` in `chat.service_name` and
`handle.service`.

**Unresolved:** neither snapshot contains an SMS or MMS row, so exact SMS/MMS
values and downgrade behavior are not established here. Stage 2 must use a
positive iMessage allowlist rather than guess every non-iMessage service:

```sql
WHERE m.service = 'iMessage'
  AND c.service_name = 'iMessage'
```

`was_downgraded` is present but zero for every observed row. It may be a useful
defensive exclusion later, but this corpus does not prove its SMS semantics.

### Recommended source candidate query

Read all new iMessage rows first, then classify ordinary messages and typed
reaction events. Do not filter reaction directions out at the SQL boundary;
sent reactions are needed to maintain the kiosk's reaction state.

```sql
SELECT
    m.ROWID,
    m.guid,
    m.service,
    m.is_from_me,
    m.handle_id,
    m.account_guid,
    m.date,
    m.text,
    m.attributedBody,
    m.associated_message_guid,
    m.associated_message_type,
    m.associated_message_range_location,
    m.associated_message_range_length
FROM message AS m NOT INDEXED
WHERE m.ROWID > :after_rowid
  AND m.service = 'iMessage'
ORDER BY m.ROWID
LIMIT :batch_size;
```

`NOT INDEXED` is intentional for this schema: `EXPLAIN QUERY PLAN` otherwise
selected an unrelated secondary index and a temporary order B-tree on the
small supplied database. With `NOT INDEXED`, SQLite can use the INTEGER PRIMARY
KEY range directly. Stage 8 must re-check the plan against the live database.

If the product ultimately excludes outgoing ordinary messages, apply
`is_from_me = 0` only after retaining outgoing reaction/retraction events that
change the displayed conversation state.

## Sender and handle identity

The `handle` table is:

```sql
handle(
  ROWID INTEGER PRIMARY KEY,
  id TEXT NOT NULL,
  country TEXT,
  service TEXT NOT NULL,
  uncanonicalized_id TEXT,
  person_centric_id TEXT,
  UNIQUE(id, service)
)
```

**Observed:** both handles are canonical-looking international phone numbers,
use service `iMessage`, and have country values. One retains a different
`uncanonicalized_id`; the other has none. `person_centric_id` is null for both.

**Unresolved:** no email/Apple-ID remote handle is present. The schema stores
addresses as text and can represent them, but Stage 2 needs a sanitized email
fixture or another controlled snapshot before claiming normalization rules.
Treat the address as an opaque service-scoped identifier first; format it for
display separately.

### Contacts-card result

Creating the Contacts entry did not change either `handle` row, either
`chat_handle_join` row, either chat identifier, or any historical message row.
No new handle/chat appeared. Both `chat.display_name` values remain null, and
no person-centric handle ID appeared. The only changed chat fields are explained
by subsequent message/read activity.

**Conclusion:** this snapshot contains no evidence that Contacts display-name
resolution is stored in `sms.db`. The relay must treat contact-name resolution
as an optional, separate provider. Message identity and deduplication must use
Messages handles/GUIDs, never a mutable contact name.

## Chat identity and participants

Messages map to chats through:

```sql
chat_message_join(chat_id, message_id, message_date)
```

All 36 messages have exactly one join and no message has multiple joins. The
join's `message_date` equals `message.date` for every row. The schema permits
more than one chat per message, so Stage 2 should still validate cardinality
instead of silently selecting an arbitrary join.

**Observed one-to-one chat shape:** both chats have:

- unique `chat.guid` values with an `iMessage`-prefixed form;
- `style = 45`, `state = 3`, and `service_name = 'iMessage'`;
- one `chat_handle_join` participant;
- phone-like `chat_identifier` values;
- null `room_name` and `display_name`;
- non-null group ID fields even though the chats are one-to-one.

Therefore non-null `group_id` alone does not mean group chat.

**Unresolved group shape:** no group chat is present. Stage 2 should obtain
participants generically through `chat_handle_join` and expose the stable
`chat.guid`, but it must not hard-code `style = 45` as the universal one-to-one
test until a controlled group sample establishes the contrast.

Recommended normalized IDs:

- `chat_id`: exact `chat.guid`, treated as an opaque private value;
- `participants`: service-scoped handle IDs from `chat_handle_join`;
- local self: implicit, not expected in `chat_handle_join`.

The observed chat GUID embeds address-like material. It must not appear in
default logs; a later protocol may HMAC it if a non-PII transport identifier is
preferred.

## Timestamps

### Message and chat-message timestamps

`message.date`, `date_read`, `date_delivered`, `date_played`, and
`chat.last_read_message_timestamp` are observed as **integer nanoseconds since
2001-01-01 00:00:00 UTC**. `chat_message_join.message_date` uses the same value
as `message.date` in all rows.

Exact integer conversion:

```python
APPLE_TO_UNIX_SECONDS = 978_307_200
unix_nanoseconds = apple_nanoseconds + APPLE_TO_UNIX_SECONDS * 1_000_000_000
seconds, nanoseconds = divmod(unix_nanoseconds, 1_000_000_000)
```

For a Python `datetime` (microsecond precision):

```python
from datetime import datetime, timedelta, timezone

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
seconds, nanoseconds = divmod(raw_value, 1_000_000_000)
value = APPLE_EPOCH + timedelta(
    seconds=seconds,
    microseconds=nanoseconds // 1_000,
)
```

Preserve the raw integer if sub-microsecond ordering matters. Zero/null state
timestamps mean absent/not recorded, not a real event at the Apple epoch.

The controlled rows convert to the expected test interval in UTC and align
with the local CDT test times. Store UTC instants; timezone conversion belongs
only in presentation.

### Attachment timestamps

`attachment.created_date` and `start_date` are observed as **integer seconds**
since the same Apple epoch, not nanoseconds:

```python
unix_seconds = apple_attachment_seconds + 978_307_200
```

Do not apply one unit assumption to both tables.

The 2001 UTC reference is consistent with Apple's documented Foundation
reference date: [Apple `timeIntervalSinceReferenceDate`](https://developer.apple.com/documentation/foundation/date/timeintervalsincereferencedate-swift.property).

## Plain text, `attributedBody`, and summary blobs

### Observed representation

- All 36 logical messages have non-null, non-empty `text`.
- All 36 also have non-null `attributedBody`.
- Every `attributedBody` begins with bytes `04 0B` followed by ASCII
  `streamtyped`.
- The object graph names `NSAttributedString`, `NSString`, `NSDictionary`,
  `NSNumber`, and `NSValue`.
- The UTF-8 bytes of `message.text` occur inside every observed typedstream.
- Ordinary text has a `__kIMMessagePartAttributeName` attribute.
- Attachment-only messages use a single U+FFFC object-replacement character in
  `text`; their typedstream also contains
  `__kIMFileTransferGUIDAttributeName` and the joined attachment GUID.

This is an Apple typedstream/NSArchiver-style attributed-string serialization,
**not** a binary plist and not an NSKeyedArchiver `bplist00` object.

`message_summary_info` is separate. It **is** a `bplist00` dictionary. Normal
rows in this corpus have keys shaped like `amc = 0` and `ust = true`; standard
reaction rows have `amc = 1`, an `ams` string containing target text, and
`ust = true`. The `ams` text is private duplicate content and should not be
logged or used when `associated_message_guid` is available.

### Stage 2 extraction contract

1. Prefer non-empty `message.text`.
2. If attachments are joined and text is only U+FFFC, normalize text to null
   and retain attachment references.
3. When `text` is null/empty, use a bounded, allowlisted typedstream decoder
   that extracts the root attributed string's `NSString` value.
4. Do not use regex/`strings` over arbitrary blob bytes: class names, attribute
   names, GUIDs, and metadata strings coexist with the text.
5. Do not instantiate arbitrary archived classes. Reject excessive blob size,
   nesting, invalid lengths, invalid UTF-8, or unexpected root/class graphs.
6. Preserve a diagnostic such as `text_decode_status` without logging blob or
   message content.

**Unresolved fixture gap:** there is no row where `text` is null/empty while
the typedstream contains usable text. Before Stage 2 calls the fallback
complete, obtain or construct a sanitized typedstream fixture with that exact
shape and verify extraction against invented text. Dependency choice and
Python 3.13/aarch64 compatibility remain a Stage 2 decision; Stage 1 added no
dependency.

## Attachments

### Database relationship and path resolution

`message_attachment_join(message_id, attachment_id)` maps a message to an
attachment. Each of the four observed attachment rows has exactly one message
join. Attachment-only messages also set `message.cache_has_attachments = 1`.
The join table is authoritative; the cache flag alone is not.

All observed filenames use:

```text
~/Library/SMS/Attachments/<2>/<2>/<UUID>/<transfer-name>
```

On the phone, `~` is the actual iOS user's home, so the demonstrated production
resolution is:

```text
~/Library/SMS/... -> /var/mobile/Library/SMS/...
```

It must **not** resolve against the Dopamine jailbreak home
`/var/jb/var/mobile`. Stage 2 must strip only the exact
`~/Library/SMS/Attachments/` prefix, join it under the configured Messages
root, resolve it, and reject traversal/symlink escapes outside
`/var/mobile/Library/SMS/Attachments`.

Every observed database filename exists in the copied attachment tree, but a
live attachment can be pending or missing. Missing files should produce a
retryable attachment state, not crash the scanner or cause an event-complete
ACK.

### Normal photo

The controlled normal photo is message `m19` joined to attachment `a2`:

- `uti = public.jpeg`;
- `mime_type = image/jpeg`;
- `.jpeg` filename and transfer name;
- one JPEG file in the attachment directory;
- `transfer_state = 5`, `is_outgoing = 0`;
- `guid = original_guid`.

Its database `total_bytes` is 1,048,576 while the local file is 4,568,906
bytes. The same 1 MiB value appears in transfer `user_info`. Therefore
`total_bytes` is not a reliable current-file length for these incoming photos;
streaming code must `stat` the contained source file and optionally record both
declared and actual sizes.

### Live Photo

The controlled Live Photo is message `m21` joined to **one** attachment row,
`a3`. At the database level it looks like the normal photo:

- `uti = public.jpeg`;
- `mime_type = image/jpeg`;
- one `.jpeg` database filename;
- no second attachment row or message-attachment join for the motion component.

Its attachment directory proves the Live Photo relationship:

- same-stem outer `.jpeg` and `.MOV` files;
- a `<directory-UUID>.pvt/` child containing byte-identical copies of that JPEG
  and MOV;
- a small `metadata.plist` with
  `PFVideoComplementMetadataVersionKey`;
- the outer and inner JPEG hashes match, and the outer and inner MOV hashes
  match.

The database attachment's UTI/MIME and transfer-plist key shapes do not
distinguish it from the normal JPEG. Live Photo detection in this corpus
therefore requires contained filesystem inspection for the paired same-stem
MOV and `.pvt` structure. Do not create a duplicate attachment event for the
byte-identical `.pvt` copies.

Recommended model: one parent attachment keyed by `attachment.guid`, category
`live_photo`, with components:

- `attachment.guid + ':still'` -> outer JPEG;
- `attachment.guid + ':motion'` -> outer MOV.

These component suffix IDs are a proposed deterministic relay convention, not
Apple database identifiers.

### Video

The controlled five-second video is message `m23` joined to attachment `a4`:

- `uti = com.apple.quicktime-movie`;
- `mime_type = video/quicktime`;
- `.MOV` filename and transfer name;
- one MOV file in its directory;
- `total_bytes` equals the observed file size (1,547,356 bytes);
- `transfer_state = 5`, `is_outgoing = 0`.

### Attachment metadata and identity

All attachment GUIDs are unique 36-character values; all four
`original_guid` values equal `guid`. Use `attachment.guid` as the stable
attachment ID and ROWID only for joins/local diagnostics.

`attachment.user_info` is a binary plist containing MIME/UTI, size, MMCS URLs,
owners, signatures, and decryption keys. `attribution_info` is another plist
with generated-media/dimension metadata. These blobs include sensitive transfer
material and must never be logged or relayed wholesale. Stage 2 needs only the
explicit attachment columns and contained local files for this scope.

## Standard reactions and tapbacks

### Add mapping

Standard tapbacks are separate `message` rows with their own unique `guid`.
They are not updates to the target message. The target is encoded as:

```text
associated_message_guid = 'p:<part-index>/<target-message-guid>'
```

All 11 typed reaction/removal rows use `p:0/`, resolve to an existing target
message, have range location 0, and have range length equal to target text
length. Preserve the part index and range for future multi-part messages.

Observed addition mapping:

| `associated_message_type` | Normalized kind | Evidence |
| ---: | --- | --- |
| 2000 | `heart` | Controlled Heart addition |
| 2001 | `thumbs_up` | Multiple incoming and outgoing additions |
| 2002 | `thumbs_down` | Controlled addition |
| 2003 | `haha` | Controlled addition |
| 2004 | `emphasize` | Controlled `!!` addition |
| 2005 | `question` | Controlled `?` addition |

Direction and actor use `is_from_me` exactly as ordinary messages:

- incoming reaction (`0`): actor is `handle_id`;
- outgoing reaction (`1`): actor is local `self`; `handle_id` is the remote
  participant/recipient.

The reaction event's own `message.guid` is the stable event ID. The target
message GUID is parsed from `associated_message_guid`; do not use duplicated
localized `text` or `message_summary_info.ams` to find the target.

### Reaction removal

Both controlled thumbs-up removals behaved the same way across direction:

1. a `2001` add row existed;
2. removing the reaction deleted that add row (current gaps 13 and 16);
3. its GUID appeared in `sync_deleted_messages`;
4. a new row with its own GUID and `associated_message_type = 3001` was added;
5. the new row's `associated_message_guid` still points directly to the
   original target message; and
6. its `reply_to_guid` points to the deleted add-event GUID.

Therefore removal is its own normalized event and must not duplicate or delete
the target message:

```text
reaction_removed(
  event_id = removal_message.guid,
  target_message_id = target GUID from associated_message_guid,
  reaction_kind = thumbs_up,
  actor = remote handle or self,
  removed_event_id = reply_to_guid,
  timestamp = message.date,
)
```

**Observed:** `3001` means thumbs-up removal.

**Inferred, not observed:** the natural corresponding removal range is
`3000`–`3005` (addition value plus 1000). Stage 2 may encode the arithmetic
only as a guarded mapping with unknown values preserved until one removal
fixture for each kind verifies it.

## Emoji reaction

The controlled grinning-face operation produced row `m37`, but it does not use
the standard reaction representation:

- `service = iMessage`, incoming direction;
- `associated_message_type = 0`;
- `associated_message_guid = NULL`;
- no `associated_message_emoji` column exists;
- `message_summary_info` has the ordinary `amc = 0` shape;
- `text` and the root attributed string contain a localized reaction sentence,
  the emoji, and copied target text;
- `reply_to_guid` points to the intended target, but ordinary messages in this
  controlled conversation also form reply-to chains.

No non-content column distinguishes this row from an ordinary reply. Parsing a
localized sentence or regex-scanning an opaque typedstream would be fragile and
would misclassify an ordinary user message with the same wording.

**Conclusion: unresolved.** The normalized model must support arbitrary emoji,
but Stage 2 must not claim reliable extraction from this snapshot. Until a
semantic marker is found, treat this row as ordinary text rather than invent a
reaction event.

Required resolving test: create emoji reactions against non-adjacent and
non-reply target messages, capture both sender and receiver databases after
settling, repeat in a second device language if practical, and diff every
column/blob shape against an ordinary reply containing the same visible text.

## Undo Send / unsend and edits

The controlled unsend label corresponds to row `m38`. In the final logical
snapshot it remains an ordinary intact incoming message:

- `associated_message_type = 0`, `associated_message_guid = NULL`;
- `is_empty = 0`, `replace = 0`, `version = 10`;
- `text` and `attributedBody` remain populated;
- `message_summary_info` has the ordinary shape;
- no later event row references it;
- its GUID is absent from `deleted_messages` and `sync_deleted_messages`;
- no revision/edit table or explicit edit/tombstone column exists.

The two sync-deleted rows are conclusively the deleted thumbs-up additions,
because their GUIDs equal the two removal rows' `reply_to_guid` values. They do
not represent this unsend.

**Conclusion: unresolved.** The supplied snapshot does not provide enough
database evidence to emit `message_retracted`. It is possible the unsend had
not settled before capture, is represented outside this database/version, or
was presented as a test case without a persisted retraction on this device.
Stage 2 must not silently omit an already-delivered message based on this row,
and must not interpret every `sync_deleted_messages` record as an unsend because
ordinary/local deletion and reaction cleanup can also populate deletion state.

Required resolving test:

1. capture a pre-unsend trio after recording the target GUID;
2. perform Undo Send and wait until both UIs show the final state;
3. capture immediate and delayed post-unsend trios from sender and recipient;
4. compare the target row, all blobs, joins, deletion tables, and WAL-visible
   logical state; and
5. separately delete a message locally to establish a non-unsend control.

Edited-message support is also unresolved. This schema has generic `replace`,
`version`, `message_summary_info`, delete tables, and message triggers, but no
edit fixture and no revision table. All observed rows have `replace = 0` and
`version = 10`. Defer edit normalization until a controlled before/after edit
corpus exists.

## Stable identifiers and deduplication

| Entity/event | External stable ID | Local cursor/join aid | Rationale |
| --- | --- | --- | --- |
| Ordinary message | `message.guid` | `message.ROWID` | GUID is unique and 36 characters in both snapshots; ROWID is database-local. |
| Standard reaction add | reaction row's `message.guid` | reaction ROWID | A reaction is an independent event row. |
| Reaction remove | removal row's `message.guid` | removal ROWID | Removal is an independent event; `reply_to_guid` optionally identifies deleted add. |
| Target message | UUID portion of `associated_message_guid`, preserving part index separately | target lookup ROWID if present | Association uses `p:<part>/<GUID>`. |
| Chat | `chat.guid` | `chat.ROWID` | GUID is unique; ROWID is local. Treat value as private because it may embed an address. |
| Attachment | `attachment.guid` | `attachment.ROWID` | GUID is unique and equals `original_guid` in all samples. |
| Live Photo component | proposed `<attachment.guid>:still` / `:motion` | contained file path | No Apple DB GUID exists for the motion sibling. |
| Retraction | proposed retraction row GUID, if a future fixture exposes one | source ROWID | No reliable event exists in this corpus. |

Use the exact event GUID as the kiosk idempotency key. Never make ROWID the
sole network identity; a database rebuild/import can change local ROWIDs.
ROWID remains the best demonstrated efficient insertion cursor.

## Incremental discovery and mutation handling

### What ROWID catches

In this controlled interval:

- ordinary messages appended rows;
- attachment messages appended rows and joins;
- standard reaction additions appended rows;
- reaction removals appended new removal rows;
- the removed add rows were deleted, leaving gaps;
- no pre-existing message row was updated.

Thus `message.ROWID > cursor` catches every **surviving normalized event** in
this corpus, including removal events. It must tolerate gaps.

### What ROWID alone cannot guarantee

The schema has no general `updated_at` column. A future edit/unsend could update
an old row, delete it without a semantic replacement, or use a blob/auxiliary
table. A pure high-water mark would miss that. Date is also unsuitable as the
sole cursor because state dates may be null/equal, timestamps can be late, and
mutation time need not replace original send time. GUID is a dedupe key, not an
ordered scan cursor.

### Recommended Stage 2/3 discovery model

Maintain these independently in relay-owned state:

1. `message_rowid_cursor`: highest source row fully normalized and durably
   queued, never merely the maximum observed row;
2. `sync_deleted_rowid_cursor`: separate cursor over
   `sync_deleted_messages.ROWID`;
3. `source_fingerprint_by_guid`: hash of relevant source columns for a bounded
   recent lookback;
4. event/attachment queue records keyed by stable GUID-derived IDs;
5. transmission attempts; and
6. kiosk ACK state.

Per scan:

1. begin one read transaction for a consistent SQLite snapshot;
2. fetch a bounded ROWID batch in ascending order;
3. normalize and commit each source event plus cursor progress atomically in
   relay-owned SQLite;
4. scan new `sync_deleted_messages` rows, but classify deletion only when
   independent semantic evidence exists;
5. rescan a configurable recent ROWID/time window and compare relevant-column
   fingerprints to detect in-place changes; and
6. rely on later short/month reconciliation for bounded gaps.

No bounded lookback can guarantee detection of arbitrary mutations to very old
rows in this schema. The remaining guarantee must come from reconciliation and
future version-specific mutation evidence. Never advance a discovery cursor in
a way that discards a row that failed normalization/queue commit. Delivery ACK
state never controls or replaces discovery state.

## Reading the live WAL database safely

Use an absolute URI with explicit read-only mode:

```python
sqlite3.connect(
    "file:/var/mobile/Library/SMS/sms.db?mode=ro",
    uri=True,
    timeout=configured_timeout,
)
connection.execute("PRAGMA query_only=ON")
```

Open the existing WAL/SHM as one SQLite database and keep related queries in a
single read transaction. Do not execute `PRAGMA wal_checkpoint`, `VACUUM`, a
journal-mode assignment, or any DDL/DML. Relay state must use a completely
separate path/database.

`immutable=1` is **wrong for the live Messages store**. SQLite defines it as an
assertion that the file cannot change, disables locking/change detection, and
warns that incorrect use can return wrong/corrupt results
([SQLite URI parameters](https://www.sqlite.org/uri.html#uriimmutable)). The
controlled disposable copy proves the practical failure:

- `mode=ro` saw 36 logical messages through the WAL;
- `immutable=1` saw only 22 messages from the main database;
- 14 committed logical rows were missed.

SQLite supports read-only WAL databases when WAL/SHM are already readable
([SQLite WAL read-only guidance](https://www.sqlite.org/wal.html#readonly)),
but the Stage 0 audit observed that a read-only connection changed ephemeral
SHM lock/index bytes. It did not alter `sms.db`, `sms.db-wal`, message rows, or
attachment data. Whether that coordination write is acceptable under the live
safety policy must be explicitly validated in Stage 8. A frozen copied trio may
use immutable mode only after consistency is established; it is not a live
polling strategy.

## Proposed normalized event model

The following is supported by observed schema except where marked unresolved.
Names are proposed Stage 2 contracts, not protocol finalization.

### Ordinary message

```json
{
  "schema_version": 1,
  "event_kind": "message",
  "event_id": "<message.guid>",
  "message_id": "<message.guid>",
  "source_rowid": 0,
  "chat_id": "<chat.guid>",
  "sender": {"kind": "remote_handle|self", "id": "<opaque-or-null>"},
  "direction": "incoming|outgoing",
  "timestamp_raw_ns": 0,
  "timestamp_utc": "<derived UTC instant>",
  "text": "<string-or-null>",
  "attachment_ids": ["<attachment.guid>"]
}
```

`source_rowid` is relay-local diagnostic/cursor metadata, never the idempotency
key. Do not log `chat_id`, sender IDs, or text by default.

### Attachment

```json
{
  "attachment_id": "<attachment.guid>",
  "parent_message_id": "<message.guid>",
  "transfer_name": "<sanitized leaf name>",
  "uti": "public.jpeg|com.apple.quicktime-movie|...",
  "mime_type": "image/jpeg|video/quicktime|...",
  "media_category": "photo|video|live_photo",
  "source_path": "<contained resolved path>",
  "declared_bytes": 0,
  "actual_bytes": 0,
  "components": []
}
```

For Live Photos, `components` contains deterministic `:still` and `:motion`
IDs. Do not include MMCS/decryption metadata.

### Standard reaction added

```json
{
  "event_kind": "reaction_added",
  "event_id": "<reaction-row message.guid>",
  "target_message_id": "<parsed target GUID>",
  "target_part": 0,
  "sender": {"kind": "remote_handle|self", "id": "<opaque-or-null>"},
  "reaction_kind": "heart|thumbs_up|thumbs_down|haha|emphasize|question|unknown",
  "emoji": null,
  "timestamp_raw_ns": 0
}
```

### Standard reaction removed

```json
{
  "event_kind": "reaction_removed",
  "event_id": "<removal-row message.guid>",
  "target_message_id": "<parsed target GUID>",
  "removed_event_id": "<reply_to_guid-if-present>",
  "sender": {"kind": "remote_handle|self", "id": "<opaque-or-null>"},
  "reaction_kind": "thumbs_up|unknown",
  "emoji": null,
  "timestamp_raw_ns": 0
}
```

The model intentionally includes nullable `emoji` and `unknown` reaction kind
so it is not limited to the legacy six. Reliable emoji extraction is unresolved.

### Message retracted

```json
{
  "event_kind": "message_retracted",
  "event_id": "<future semantic-event-id>",
  "target_message_id": "<target GUID>",
  "sender": {"kind": "remote_handle|self|unknown", "id": null},
  "timestamp_raw_ns": 0
}
```

This is a required model capability but has **no demonstrated extractor** in
the current corpus. Stage 2 must keep it unimplemented/explicitly unsupported
rather than synthesize events from ambiguous deletions.

## Skip and duplicate hazards

1. Ignoring the WAL missed 14 of 36 logical rows in the controlled snapshot.
2. Assuming contiguous ROWIDs would fail at deleted reaction additions 13/16.
3. Treating ROWID as a network ID would make dedupe database-instance-specific.
4. Advancing directly to `MAX(ROWID)` before durable queue commit could lose
   failed rows permanently.
5. Filtering only `associated_message_type != 0` would miss the observed emoji
   reaction operation, although no reliable alternate classification exists.
6. Treating all `sync_deleted_messages` as unsends would confuse reaction
   cleanup/local deletion with retraction.
7. Treating `is_from_me = 0` as the only sender rule would label outgoing
   reaction recipient handles as senders.
8. Trusting `cache_has_attachments` without the join can create stale or
   incomplete attachment events.
9. Trusting `attachment.total_bytes` as disk length is wrong for both controlled
   incoming JPEGs.
10. Treating each Live Photo file as a database attachment would duplicate its
    byte-identical `.pvt` copies.
11. Parsing attributed-body bytes with regex can select metadata/class strings
    instead of root text and can fail on length encoding/localization.
12. Using timestamp as the sole cursor can skip equal, late, null, or mutated
    events.
13. Assuming contact names are in `sms.db` would make sender display brittle;
    the controlled contact creation changed no identity records.

At-least-once delivery plus GUID-keyed kiosk ingestion is required to make
retries harmless.

## Original 24-question checklist

1. **Incoming retrieval:** `service='iMessage'`, joined iMessage chat, and
   `is_from_me=0`; classify reaction rows separately.
2. **Outgoing difference:** `is_from_me=1`; handle is recipient, local actor is
   self/account.
3. **SMS/MMS exclusion:** strict positive iMessage allowlist; no SMS sample.
4. **Sender:** incoming `handle_id`; outgoing `self`/`account_guid`.
5. **Handles:** service-scoped text; canonical phone observed, email unresolved.
6. **Chat association:** `chat_message_join`.
7. **One-to-one/group:** observed one participant/style 45; group unresolved.
8. **Participants:** `chat_handle_join`; local self absent.
9. **Timestamps:** message nanoseconds and attachment seconds since 2001 UTC.
10. **Plain text:** `message.text`; U+FFFC for attachment-only rows.
11. **`attributedBody`:** Apple typedstream attributed-string serialization.
12. **Fallback text:** use safe typedstream root-string decoder; exact empty-text
    fixture unresolved.
13. **Attachment relation:** `message_attachment_join`.
14. **Paths:** `~/Library/SMS/Attachments/...`, resolve under `/var/mobile`.
15. **Photos:** `public.jpeg`/`image/jpeg`; Live Photo needs filesystem pairing.
16. **Videos:** `com.apple.quicktime-movie`/`video/quicktime`.
17. **Tapbacks:** independent message rows; add codes 2000–2005.
18. **Targets:** `p:<part>/<GUID>` in `associated_message_guid`.
19. **Deduplication:** event row GUID; attachment/chat GUIDs for their entities.
20. **GUID vs ROWID:** GUID external, ROWID local scan cursor.
21. **Incremental retrieval:** ascending ROWID batches plus mutation/deletion
    lookback and reconciliation.
22. **Safest cursor:** ROWID for inserts; never timestamp/GUID alone.
23. **Edits/changes:** removal appends then deletes add; edits/unsend unresolved.
24. **Skip/duplicate causes:** enumerated in the preceding section.

## Required follow-up evidence before/within Stage 2

These are unresolved schema behaviors, not Stage 2 implementation permission:

1. **Emoji semantic test:** non-adjacent target, sender/receiver snapshots,
   ordinary-reply control, and preferably a second locale.
2. **Unsend test:** pre/immediate/delayed snapshots on both devices plus local
   delete control.
3. **Edit test:** before/after edit snapshots with target GUID recorded.
4. **Empty-text typedstream test:** a real or sanitized row whose root text is
   only in `attributedBody`.
5. **Group chat test:** at least three participants, name change, participant
   add/remove, and one group reaction.
6. **Email handle test:** controlled Apple-ID/email sender.
7. **SMS/MMS exclusion test:** sanitized or controlled rows sufficient to prove
   exact service/downgrade values without adding SMS relay scope.

Stage 2 may implement only the conclusively supported contract, preserve unknown
reaction codes, and mark unresolved event types explicitly. It must not begin
until separately authorized.

## Stage 1 completion conclusion

The supplied snapshots are sufficient to design the reliable read-only parser
for ordinary iMessage text, direction, phone handles, one-to-one chat mapping,
timestamps, normal photos, the demonstrated Live Photo layout, QuickTime video,
legacy reaction additions, and thumbs-up removals. GUID is the external event
identity; ROWID is the insertion cursor. The WAL is mandatory and immutable
mode is unsafe for live polling.

Emoji reaction semantics, Undo Send/retraction, edits, group chats, email
handles, SMS field values, and the null-text typedstream fallback remain
explicit evidence gaps. No Stage 2 code should hide those gaps behind
heuristics.
