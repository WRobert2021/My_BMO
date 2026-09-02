# Bounded Attachment Transfer

## Status and boundary

Stage 7 is complete. Attachment transfer extends the standalone simulated
sender and kiosk receiver; it does not add a CLI, daemon, deployment, BMO
runtime registration, live-iPhone access, or automatic scheduling. Imports and
construction remain resource-free. The caller continues to own sender,
transport, listener, relay store, and receiver store lifecycle.

The sender reads only parser-contained source paths already persisted in its
private relay state. It never modifies, renames, copies over, or deletes Apple
source files. Tests use invented files in temporary directories.

## Completion-aware event flow

An event without attachments retains the Stage 5 ACK behavior. An event with
available attachment data follows this sequence:

1. `POST /v1/events` durably stores the canonical event as a pending manifest
   and returns `202 attachments_pending`; this is not a sender ACK.
2. For each ordinary attachment or Live Photo component, the sender opens one
   regular non-symlink source file, verifies its persisted size, and computes a
   SHA-256 digest in 64-KiB reads.
3. `POST /v1/attachment-sessions` binds the signed event ID, blob ID, byte
   count, and whole-blob digest to a receiver-owned upload ID and durable next
   offset.
4. Authenticated `PUT /v1/attachment-chunks/{upload_id}/{offset}/{request_id}`
   requests carry at most 64 KiB. The exact path, nonce, and chunk bytes are
   HMAC-bound. Each response identifies the upload and next durable offset.
5. After every required blob is digest-verified, the sender repeats the
   identical canonical event with fresh authentication. The receiver promotes
   the pending manifest and returns an ACK containing
   `attachment_status: complete`. Only that response acknowledges relay state.

The maximum accepted size of one attachment blob is 2 GiB. Whole attachment
bytes are never placed in JSON, base64 encoded, loaded into memory, or stored
inside either SQLite database.

## Durable partial state and storage

Receiver schema version 2 adds `pending_events` and `attachment_uploads` while
preserving and migrating version-1 event receipts and nonces. Each upload row
records its event/blob binding, declared size, SHA-256, upload ID, committed
offset, completion state, private storage filename, and update time.

Partial and complete bytes live in a receiver-owned sibling directory named
`<database>.attachments`, created as `0700`; files are `0600`. A chunk is
written and flushed before its new offset commits. If a process stops after
the file write but before the database commit, reopening truncates the file to
the last durable offset. Lost-response replays must match already committed
bytes. A final digest mismatch resets the partial file to offset zero and never
promotes or ACKs the event.

Completed attachment records remain bound to their event/blob IDs. Ordinary
attachments use the attachment ID as the blob ID. Live Photos transfer only
their deterministic still and motion component IDs, avoiding a duplicate copy
of the still image.

## Failure behavior

Missing/unsafe source metadata, a non-regular or symlink source, size or file
metadata change, invalid session identity, offset mismatch, digest mismatch,
malformed/mismatched response, timeout, and storage failure all fail closed
through the existing bounded retry/dead-letter policy. A legacy metadata-only
event ACK is rejected for events that require bytes.

Pending manifests are not returned as present by reconciliation because they
are not complete kiosk receipts. They are never deleted by reconciliation.
Orphan/abandoned partial retention is intentionally unresolved for a later
operational policy; Stage 7 adds no automatic deletion authority.

## Stage 7 verification

`tests/test_imessage_attachments.py` covers strict session/chunk contracts,
hard size and chunk bounds, version-1 receiver migration, private file modes,
partial restart/resume on both sides, duplicate chunks, final digest mismatch,
ordinary and Live Photo transfer, source hash preservation, unavailable source
handling, legacy ACK rejection, transport-neutral integration, and real
loopback HTTP. The complete parser/state/receiver/sender/reconciliation/
attachment suite remains the primary acceptance command.
