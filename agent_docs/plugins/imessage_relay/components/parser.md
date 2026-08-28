# Read-Only iMessage Parser

## Status and boundary

Stage 2 is complete. The `iphone_relay` package is a stateless, local parser
for the conclusively supported Stage 1 schema. It is not a relay daemon, does
not contain a queue or networking code, and has not been deployed to or run
against the live iPhone.

The parser has no third-party runtime dependency. It uses Python's standard
library and remains independent of the kiosk application's feature registry
and runtime lifecycle. A later UI integration must remain optional and
failure-isolated under `../../../core/extensions.md`.

## Public contract

```python
from iphone_relay import MessagesReader

reader = MessagesReader(
    "iphone_snapshot/SMS/sms.db",
    messages_root="iphone_snapshot/SMS",
)
batch = reader.scan(after_rowid=0, limit=100)
```

When `messages_root` is omitted, it defaults to the database's parent
directory. The configured root is the directory that contains `Attachments/`.
Production's eventual value is expected to be `/var/mobile/Library/SMS`, but
live use is prohibited until Stage 8.

`scan()` returns an immutable `ScanBatch` containing:

- versioned `MessageEvent` and `ReactionEvent` records in source ROWID order;
- privacy-safe `ParseIssue` records for contained row/text/attachment failures;
- the number of allowlisted iMessage rows examined; and
- the last examined source ROWID.

The parser is deliberately stateless. Repeating the same scan returns the same
stable GUID-based event IDs. Stage 3 must durably store normalized events and
issues before it persists any source cursor; `scanned_through_rowid` is an
observation boundary, not proof that an event was queued or acknowledged.

## Supported normalization

- Positive `message.service = 'iMessage'` and `chat.service_name = 'iMessage'`
  allowlists exclude other services.
- Ordinary outgoing messages are recognized but omitted because the initial
  relay content scope is incoming. Outgoing standard reactions remain because
  the local actor is required for accurate reaction state.
- Incoming senders resolve through the service-scoped `handle` row. Outgoing
  reaction senders normalize to local `self`.
- Chat identity uses `chat.guid`; participant identifiers use ordered,
  service-scoped `chat_handle_join` rows. These values are private and must not
  appear in default logs.
- Message times retain the raw integer nanoseconds since the 2001 UTC Apple
  epoch and expose a derived UTC `datetime` without float rounding.
- Non-empty `message.text` is preferred. Attachment-only U+FFFC normalizes to
  null text. Empty/null text uses a bounded decoder for the exact observed
  Apple typedstream root-string variant. Unsupported archives fail closed and
  produce a diagnostic without exposing the blob or message content.
- Attachment metadata comes from `message_attachment_join` and
  `attachment.guid`. Paths must have the exact Apple attachment prefix and
  remain contained after traversal and symlink resolution. Missing and unsafe
  paths become explicit availability states rather than scanner failures.
- JPEG/HEIC/PNG and common movie metadata/suffixes normalize to photo/video.
  The demonstrated Live Photo structure normalizes as one attachment with
  deterministic `:still` and `:motion` components; byte-identical `.pvt`
  copies are not duplicated.
- Standard reaction additions map observed values 2000 through 2005. The
  observed 3001 removal maps to Thumbs Up; unproven reaction-range values are
  retained as `unknown`. Targets use the validated `p:<part>/<GUID>` shape.

## Failure and privacy behavior

Source databases are opened with a SQLite `mode=ro` URI and
`PRAGMA query_only = ON`. A scan uses one explicit read transaction so its
message, chat, sender, and attachment queries see a consistent WAL snapshot.
The code issues no checkpoint, journal-mode change, DDL, or DML statement.

Malformed source records become issues and do not prevent later rows in the
same batch from being returned. Attachment errors are isolated per attachment.
Issue strings describe only the violated contract; they never include GUIDs,
handles, chat IDs, text, blob bytes, filenames, or paths.

Normalized events necessarily contain private source values and resolved
attachment paths. Callers must treat the records as sensitive and must not log
or serialize them without the later protocol's explicit privacy policy.

## Explicitly unsupported or unverified

- Emoji reactions have no reliable semantic marker in the controlled corpus;
  the observed row remains an ordinary incoming message.
- Undo Send/retraction and edits have no demonstrated semantic event and are
  not synthesized from ambiguous deletion state.
- A sanitized two-participant join verifies generic participant extraction,
  but a real group-chat fixture and group membership mutations remain
  unverified.
- A sanitized opaque email-shaped handle verifies that the parser does not
  assume phone-number syntax; a real Apple-ID/email sender fixture remains
  unverified.
- SMS is excluded by positive allowlisting, but exact device-specific SMS/MMS
  downgrade values remain unverified because the snapshot has no such corpus.
- The typedstream fallback is verified with a sanitized archive shaped from
  the exact observed prefix. The supplied device snapshot has no natural row
  with null/empty `text` and usable attributed-body text.
- Live schema/version compatibility, permissions, Python/SQLite behavior, and
  WAL shared-memory effects remain Stage 8 acceptance work.

## Stage 2 verification

`tests/test_imessage_parser.py` builds invented SQLite fixtures in temporary
directories and optionally validates the ignored controlled snapshot. It
covers read-only rejection and source hashing, filtering, sender/chat/group
shape, timestamps, repeat scans and cursor gaps, all six reaction additions,
the demonstrated removal, unknown reactions, bounded typedstream extraction,
ordinary photo/video/Live Photo discovery, declared versus actual sizes,
missing files, traversal/symlink containment, schema errors, and per-record
failure isolation.

No snapshot data, attachment bytes, handles, message text, or credentials were
added to tracked fixtures.
