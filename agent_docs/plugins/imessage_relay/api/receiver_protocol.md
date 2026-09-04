# iMessage Relay Receiver Protocol

owner: `bmo.features.imessage_relay.receiver.protocol`,
  `bmo.features.imessage_relay.receiver.auth`, and the HTTP contract

Current stage/status is intentionally omitted; see `../progress.md`.

## Status and Boundary

This document records the Stage 4 kiosk receiver protocol as extended by Stage
6 reconciliation and Stage 7 attachment transfer on 2026-09-01. The receiver is a standalone,
standard-library Python package. It is not registered with application startup,
does not read Apple Messages data, and does not contact an iPhone.

The protocol accepts normalized message and reaction events from the Stage 2
contract. It deliberately excludes Apple source ROWIDs and filesystem paths.
Attachment bytes use a separate bounded binary endpoint and never enter event
JSON.

## Transport Decision

Stage 4 uses HTTPS request/response rather than a persistent WebSocket.

HTTPS maps one event transaction to one explicit response, works with the
standard libraries on Python and Raspberry Pi OS, has straightforward timeout
and reconnect behavior, and does not require maintaining connection state while
the phone or kiosk is offline. A WebSocket would still require application ACKs,
reconnect logic, replay protection, and durable duplicate handling while adding
a framing implementation or another dependency. Nothing in the current event
rate justifies that added surface.

Production/private-LAN operation requires native TLS. Plain HTTP is accepted
only when configuration explicitly opts in and the receiver binds to a loopback
address. TLS authenticates the kiosk to a client that validates or pins its
certificate; the per-request HMAC authenticates the client to the kiosk. TLS
also provides response authenticity and confidentiality.

## HTTP Interface

All endpoints require valid request authentication, including health and
status. Responses use `application/json`, disable caching, and contain no
message content.

| Method and path | Purpose | Success |
| --- | --- | --- |
| `POST /v1/events` | Validate and durably ingest one event | `201` accepted or `200` duplicate ACK |
| `POST /v1/reconciliation` | Classify bounded sender receipt candidates | `200` ordered receipt statuses |
| `POST /v1/attachment-sessions` | Create/resume one manifest-bound blob upload | `201` created or `200` resumed |
| `PUT /v1/attachment-chunks/{upload_id}/{offset}/{request_id}` | Commit one bounded binary chunk | `200` partial/complete offset |
| `GET /v1/health` | Confirm the authenticated service is responsive | `200` health document |
| `GET /v1/status` | Return content-free durable counts and uptime | `200` status document |

An event request is UTF-8 JSON with exactly these top-level fields:

```json
{
  "protocol_version": 1,
  "request_id": "invented-request-1",
  "event": {
    "schema_version": 1,
    "event_kind": "message",
    "event_id": "INVENTED-EVENT-ID",
    "message_id": "INVENTED-EVENT-ID",
    "chat_id": "INVENTED-CHAT-ID",
    "participant_ids": ["INVENTED-PARTICIPANT-ID"],
    "sender": {
      "kind": "remote_handle",
      "identifier": "INVENTED-PARTICIPANT-ID"
    },
    "direction": "incoming",
    "timestamp_raw_ns": 1000000000,
    "timestamp_utc": "2001-01-01T00:00:01+00:00",
    "text": "invented content",
    "attachments": []
  }
}
```

The message and reaction event fields otherwise follow the immutable Stage 2
contracts. Validation is strict: unknown or missing fields, duplicate JSON
keys, non-finite numbers, invalid enum values, invalid identifiers, malformed
UTC timestamps, inconsistent message/attachment parents, and unsupported
versions receive a NACK. Booleans are not accepted where integers are required.

The successful response is an explicit ACK:

```json
{
  "event_id": "INVENTED-EVENT-ID",
  "protocol_version": 1,
  "request_id": "invented-request-1",
  "result": "ack",
  "status": "accepted"
}
```

An identical event retransmitted under a new authenticated request receives the
same event ID with status `duplicate`. A NACK has this shape:

```json
{
  "error": {"code": "invalid_schema"},
  "protocol_version": 1,
  "request_id": null,
  "result": "nack"
}
```

When the envelope has already been decoded, its request ID is included in a
storage or conflict NACK. Diagnostics remain bounded error codes; rejected
message content is never copied into the response or default logs.

## Authentication and Replay Control

Each request provides four headers:

- `X-Relay-Key-Id`
- `X-Relay-Timestamp` as canonical integer Unix seconds
- `X-Relay-Nonce` as a unique safe token
- `X-Relay-Signature` as lowercase hexadecimal HMAC-SHA256

The signature input is UTF-8 with newline separators and no trailing newline:

```text
IMESSAGE-RELAY-HMAC-V1
POST
/v1/events
2000000000
invented-nonce-1
SHA256_HEX_OF_EXACT_BODY_BYTES
```

The HMAC key is a minimum 32-byte shared secret loaded from the environment
variable named by private configuration. It is never stored in tracked JSON.
The method, exact request target, timestamp, nonce, and exact body bytes are all
bound by the signature. Comparison uses constant-time digest checks.

The default clock-skew window is 300 seconds and is configurable from 1 through
3600 seconds. After signature verification, the kiosk commits the client key
ID and nonce to its own SQLite database before it parses or processes the
request. A repeated nonce receives `409 replay_detected`, including after a
receiver restart. Nonces older than twice the configured acceptance window are
removed during later nonce transactions. A rejected payload consumes its nonce;
a legitimate retry must use a new nonce and request ID.

Clock synchronization remains an operational prerequisite. The sender exposes
the `stale_request` NACK as a distinct failure and never responds by silently
widening the replay window.

## Durable Ingestion and Idempotency

The receiver owns a separate private SQLite database with application ID
`IMKR`, schema version 2, `0600` file creation, WAL journaling, foreign keys,
and `synchronous=FULL`. Its tables contain:

- canonical event JSON and its SHA-256 digest, keyed by stable event ID;
- first request ID, event kind, and receipt time;
- authenticated nonces keyed by client key ID and nonce.
- pending canonical manifests and per-blob expected sizes, digests, upload IDs,
  committed offsets, completion states, and private storage names.

The server starts an immediate transaction and checks the event ID. Events with
no required blobs insert directly. Events with available attachment data first
commit a pending manifest and return `202 attachments_pending`, which is not an
ACK. After every required blob is complete, an identical repeated event promotes
the manifest and emits `201 accepted` with `attachment_status: complete`. If the
stable ID/digest already exists it emits `200 duplicate`; conflicting content
rolls back with `409 event_conflict`. Storage errors never ACK. These rules
persist across process restart and provide the kiosk half of at-least-once
delivery without treating network transmission as delivery.

The receiver serializes transactions around its shared SQLite connection while
the standard-library HTTP server may handle independent connections in worker
threads. Shutdown closes the listening socket and state store explicitly.

## Reconciliation Interface

`POST /v1/reconciliation` accepts exactly a protocol version, request ID, and
one through 20 unique candidates. Each candidate contains an event ID and the
lowercase SHA-256 digest of the canonical path-free event JSON. The 20-item cap
keeps maximum escaped identifiers within the sender's 64-KiB response bound.

The successful response repeats the request ID and every candidate event ID in
the same order with one status:

- `present`: the kiosk has the same stable ID and canonical digest;
- `missing`: the kiosk has no receipt for that stable ID; or
- `conflict`: the kiosk has that stable ID with a different digest.

The endpoint is authentication-first and consumes its nonce like every other
request. Receipt lookup is bounded and read-only. It does not expose kiosk-only
IDs, delete receipts, overwrite conflicts, accept event bodies, or itself queue
a resend. The sender validates HTTP status, media type, protocol/request
identity, exact candidate order, unique IDs, and every status before applying
selective local transitions.

## Attachment Boundary

Event JSON carries stable IDs, parent message ID, display/type metadata, media
category, declared/observed sizes, availability, and path-free Live Photo
component metadata. Local `source_path` values and Apple ROWIDs are rejected.

For an available ordinary attachment, the attachment ID is its blob ID. For a
Live Photo, the still and motion component IDs are separate required blobs and
the top-level still path is not transferred again. Missing or unsafe manifest
entries cannot receive an event ACK.

`POST /v1/attachment-sessions` accepts exact JSON fields for protocol/request
identity, event ID, blob ID, expected byte count, and lowercase whole-blob
SHA-256. The event must already exist as an identical pending manifest and the
blob ID/size must match its requirement. The response supplies a receiver-owned
upload ID, exact next durable offset, expected bytes, and `ready` or `complete`.

Each chunk uses `application/octet-stream` and a generated path:

```text
/v1/attachment-chunks/UPLOAD-ID/65536/chunk-request-id
```

The upload ID, canonical decimal offset, request ID, and exact chunk body are
bound by the normal HMAC because the signature covers the exact request target
and body digest. Chunk responses repeat request/upload identity and return the
next offset with `partial` or `complete`. Lost-response replays at an older
offset are accepted only when the bytes exactly match durable storage.

The receiver writes at most 64 KiB per request, flushes before committing the
offset, and hashes the completed private file in bounded reads. A mismatched
digest resets the partial offset to zero and never promotes the event. Valid
version-1 receiver databases migrate to schema version 2 without losing event
receipts or replay nonces.

## Limits, Timeouts, and Error Mapping

The default JSON request body limit is 2 MiB, configurable up to 8 MiB. Binary
chunks have an independent hard 64-KiB limit and one blob has a hard 2-GiB
limit. The default
read timeout is 10 seconds, configurable up to 120 seconds. Chunked transfer
encoding is not accepted. Rejected oversized, incomplete, timed-out, or
unsupported-media requests close the connection so unread body bytes cannot be
interpreted as a later request.

| HTTP status | Stable error/result |
| --- | --- |
| `200` | Duplicate/complete event ACK, reconciliation, upload resume/chunk, health, or status |
| `201` | Newly committed event ACK or attachment session |
| `202` | Pending attachment manifest; explicitly not an ACK |
| `400` | Malformed JSON/schema, incomplete body, or unsupported framing |
| `401` | Missing, unknown, stale, or invalid authentication |
| `404` | Authenticated route is unknown |
| `408` | Request body timeout |
| `409` | Replayed nonce, event/session/digest/offset conflict |
| `411` | Missing content length |
| `413` | JSON request or binary chunk exceeds its limit |
| `415` | Wrong JSON/binary media type |
| `422` | Event includes an unavailable attachment |
| `503` | Durable state is unavailable |

## Configuration and Operation

Tracked settings are documented in `config/example.imessage_receiver.json`.
Real settings belong in ignored `config/imessage_receiver.json`; runtime state
belongs in ignored `bmo/data/imessage_receiver/`. The secret itself is supplied
only through the configured environment variable.

The receiver fails before binding when configuration is invalid, the secret is
missing or too short, TLS is incomplete, or certificate/key loading fails. A
non-loopback bind without TLS is rejected. It remains independent from the main
kiosk application, so an unavailable or disabled receiver cannot prevent other
features from loading.

After provisioning a private configuration, secret, trusted certificate, and
key, the standalone process is:

```text
python -m bmo.features.imessage_relay.receiver.server --config config/imessage_receiver.json
```

It runs until interrupted and performs graceful local cleanup. Stage 4 does not
install a service or daemon.

## Stage 5 Sender Integration

The simulated local sender now uses these fixed behaviors:

1. Produce the exact path-free event envelope and a fresh request ID.
2. Sign the exact request bytes with a fresh nonce and current Unix timestamp.
3. Treat only an authenticated HTTPS ACK with the expected request/event IDs as
   delivery.
4. Retry timeouts and lost responses with a new nonce/request ID but the same
   stable event payload.
5. Classify NACKs without logging content and preserve the Stage 3 queue state.

It additionally requires JSON media type, a bounded strict response body, the
exact protocol version, the expected request/event IDs, and the defined HTTP
status/ACK-status pairing before acknowledging sender state. Loopback plaintext
is permitted only by explicit simulation opt-in. This integration does not
authorize live-device access, deployment, daemon installation, or application
runtime registration.

## Stage 7 Sender Integration

An attachment-bearing event is not acknowledged on `202`. The sender hashes
each required regular source file in 64-KiB reads, creates/resumes a session,
sends bounded chunks with a fresh nonce/request ID, validates every next offset,
and repeats the identical event after all blobs report complete. Sender state
acknowledges only an exact final ACK containing `attachment_status: complete`.
A legacy metadata-only ACK, missing/unsafe/changed source, timeout, mismatch,
or negative response follows the existing bounded retry/dead-letter policy.
