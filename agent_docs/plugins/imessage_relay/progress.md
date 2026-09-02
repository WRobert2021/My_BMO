# iMessage Relay Progress

current_stage: 7
current_chapter: Stage 7 acceptance gate
state: complete
next_action: Stop and wait for explicit authorization before Stage 8 live iPhone read-only integration.
last_verified: 2026-09-01

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0 — audit/snapshot validation | complete | private inputs and read-only boundary established |
| 1 — schema investigation | complete | evidence and explicit gaps preserved |
| 2 — read-only parser | complete | immutable normalized events and sanitized tests |
| 3 — relay state/durable queue | complete | atomic cursors, retries, ACK/dead-letter state |
| 4 — kiosk receiver prototype | complete | authenticated durable idempotent local receiver |
| 5 — simulated end-to-end relay | complete | local fault matrix and cleanup accepted |
| 6 — reconciliation | complete | bounded recent/month selective repair accepted |
| 7 — attachment transfer | complete | bounded resumable digest-verified transfer accepted |
| 8 — live iPhone read-only integration | not started | requires separate live-device authorization |
| 9 — live relay | not started | blocked by Stage 8 acceptance |
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Add authenticated bounded attachment streaming, durable partial state,
digest/size enforcement, and attachment-complete event ACK semantics.

### Completed

- Added pending event manifests, per-blob upload sessions, HMAC-bound 64-KiB
  chunk paths, whole-blob SHA-256/size checks, and a 2-GiB per-blob cap.
- Added receiver schema version 2 with lossless version-1 migration, private
  `0700` attachment storage, `0600` files, crash-tail truncation, durable
  offsets, exact duplicate-chunk validation, and completion promotion.
- Extended `RelaySender` to stream ordinary files and Live Photo components
  without whole-file buffering, resume after sender/receiver restart, reject
  changed/unavailable sources and legacy metadata-only ACKs, and acknowledge
  only an attachment-complete final event response.
- Verified protocol bounds, interrupted/lost responses, duplicate chunks,
  digest failure/reset, source hash preservation, Live Photo non-duplication,
  migration, cleanup, transport-neutral calls, and real loopback HTTP using
  invented temporary data.
- Ran the complete parser/state/receiver/sender/reconciliation/attachment suite
  with local loopback permission: **88 passed, 14 subtests passed in 3.01s**.

### Remaining

No Stage 7 implementation work is identified. Stage 8 live iPhone read-only
integration is not started and requires separate authorization. No live iPhone
contact, deployment, daemon, private sender configuration, or BMO runtime
registration is authorized by completed Stage 7.

### Decisions constraining next work

- Stage gates remain authorization gates; completion does not authorize the
  next stage.
- HTTPS request/response plus per-request HMAC is the Stage 4 transport.
- Plain HTTP is accepted only for explicit literal-loopback simulation.
- Sender state acknowledges only an exact `201 accepted` or `200 duplicate`
  ACK with matching protocol, request ID, and stable event ID.
- Reconciliation pages contain at most 20 candidates and never authorize kiosk
  deletion; receiver absence can only selectively requeue sender-owned state.
- Attachment events ACK only after all transferable blobs are complete; partial
  storage belongs to the receiver and has no automatic deletion policy.
- Attachment chunks are capped at 64 KiB, blobs at 2 GiB, and source paths stay
  private/read-only and absent from the wire.
- Current standalone packages are plugin-owned but not yet runtime-integrated.

### Blockers and known risks

There is no Stage 7 blocker. Stage 8 is gated by separate live-device
authorization. Known future risks: production endpoint trust and
sender/reconciliation scheduling are undefined; partial/completed attachment
retention and acknowledged-event pruning have no policy; long transfers do not
yet renew sender leases because there is no concurrent daemon; live schema/environment,
emoji reactions, retractions, edits, real groups/email handles, TLS/key
provisioning, and iPhone clock skew remain unverified in their later stages.
