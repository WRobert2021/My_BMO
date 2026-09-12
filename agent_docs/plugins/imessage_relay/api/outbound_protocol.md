# Outbound Command Protocol

## Transport and authentication

Stage 13 reserves two authenticated phone endpoints:

- `POST /v1/outbound/commands` submits one canonical command.
- `POST /v1/outbound/status` queries one stable command ID.

Requests use the receiver protocol's `IMESSAGE-RELAY-HMAC-V1` canonical
signature headers and production TLS. Request bodies are strict UTF-8 JSON,
reject duplicate fields and non-finite numbers, and are limited to 64 KiB.
The command and status paths are signed exactly; a signature for a control path
cannot be replayed here.

## Common command fields

Every command has:

- `schema_version`: integer `1`;
- `command_id`: stable safe token, unique for the intended operation;
- `created_at_utc`: canonical second-resolution UTC timestamp with `+00:00`;
- `kind`: `text`, `media`, or `reaction`; and
- `destination`: an object containing `recipient_ids`, `chat_id`, and
  `reply_to_message_id`.

`recipient_ids` contains 1–32 unique canonical E.164 numbers or email
addresses. The two context fields are explicitly `null` when unused. A reply
target is invalid without a chat ID.

Protocol version 1 is fixed to the iMessage service. SMS/MMS fallback is not
allowed implicitly and is not represented by this command model.

## Kind-specific fields

Text commands contain nonblank `text`, limited to 32 KiB UTF-8.

Media commands contain optional nonblank `text` and 1–10 unique media
references. Each reference contains:

- `blob_id` and a leaf-only `transfer_name`;
- `media_category`, currently `photo` or `video`;
- a matching `image/*` or `video/*` MIME type;
- `expected_bytes`, from 1 byte through 2 GiB; and
- a lowercase SHA-256 digest.

The metadata does not authorize a filesystem path. A separate authenticated
upload contract will map the blob ID to phone-owned private staging.

Reaction commands contain `target_message_id`, `target_part` from 0 through
10,000, `reaction_kind`, and `operation`. Supported kinds are `heart`,
`thumbs_up`, `thumbs_down`, `haha`, `emphasize`, and `question`; operations are
`add` and `remove`.

## Submission and status bodies

A submission object contains exactly `protocol_version`, `request_id`, and
`command`. A status request contains exactly `protocol_version`, `request_id`,
`action: "status"`, and `command_id`.

An ACK contains exactly:

- `protocol_version: 1`;
- the exact `request_id` and `command_id`;
- `result: "ack"`;
- `status`: `accepted`, `duplicate`, or `status`; and
- `command_state`: `queued`, `executing`, `sent`, `failed`, or `uncertain`.

`failed` and `uncertain` also require a bounded non-content `error_code`. Other
states forbid it. HTTP success alone is never a command success.

## Idempotency and states

Both sides compare the stable command ID and SHA-256 digest of canonical
command JSON. Same ID and same digest is idempotent. Same ID with a different
digest is a conflict and must not execute.

`queued` means durably recorded, `executing` brackets the one Apple-service
invocation, `sent` means that interface accepted it, `failed` is terminal, and
`uncertain` means the call may have happened but its outcome is not proven.
Terminal commands do not retry automatically. Status resolution precedes any
operator decision about an uncertain command.

## Current availability

The canonical model, kiosk outbox, and authenticated kiosk client are
implemented and tested with invented data. No client is wired into the UI, the
matching phone endpoint is not yet implemented, and no physical outbound send
has occurred.
