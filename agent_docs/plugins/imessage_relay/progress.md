# iMessage Relay Progress

current_stage: 5
current_chapter: Stage 5 acceptance gate
state: complete
next_action: Stop and wait for explicit authorization before Stage 6 reconciliation.
last_verified: 2026-08-28

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0 — audit/snapshot validation | complete | private inputs and read-only boundary established |
| 1 — schema investigation | complete | evidence and explicit gaps preserved |
| 2 — read-only parser | complete | immutable normalized events and sanitized tests |
| 3 — relay state/durable queue | complete | atomic cursors, retries, ACK/dead-letter state |
| 4 — kiosk receiver prototype | complete | authenticated durable idempotent local receiver |
| 5 — simulated end-to-end relay | complete | local fault matrix and cleanup accepted |
| 6 — reconciliation | not started | requires explicit authorization |
| 7 — attachment transfer | not started | metadata only is currently delivered |
| 8 — live iPhone read-only integration | not started | separately authorized live-device gate |
| 9 — live relay | not started | blocked by Stage 8 acceptance |
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Connect the parser, durable queue, authenticated sender, and durable receiver
in a local-only simulation and stop after the Stage 5 fault matrix.

### Completed

- Added the standard-library `iphone_relay.sender` bridge over Stage 3 claims,
  failures, ACKs, bounded backoff, and dead letters without changing the state
  schema or tracked configuration.
- Added fresh request ID/nonce authentication, exact path-free event retries,
  strict bounded ACK/NACK validation, distinct `stale_request`, content-free
  status, explicit loopback-only plaintext policy, Ctrl-C, and idempotent
  transport cleanup.
- Verified invented parser input through the real queue, loopback HTTP server,
  HMAC receiver, and durable receipt while preserving the source hash.
- Passed the Stage 5 matrix for offline before/during send, lost ACK/duplicate
  receipt, fresh retry authentication, sender/receiver restart, ordered
  backlog, NACK/malformed/mismatched response, poison bypass/dead letter,
  explicit requeue recovery, Ctrl-C, status privacy, and resource cleanup.
- Ran the complete parser/state/receiver/end-to-end relay suite with local
  loopback permission: **70 passed, 14 subtests passed in 2.34s**.

### Remaining

No Stage 5 implementation work is identified. Stage 6 reconciliation is not
started and requires explicit authorization. No live iPhone contact,
deployment, daemon, private sender configuration, or runtime plugin
registration is authorized by completed Stage 5.

### Decisions constraining next work

- Stage gates remain authorization gates; completion does not authorize the
  next stage.
- HTTPS request/response plus per-request HMAC is the Stage 4 transport.
- Plain HTTP is accepted only for explicit literal-loopback simulation.
- Sender state acknowledges only an exact `201 accepted` or `200 duplicate`
  ACK with matching protocol, request ID, and stable event ID.
- Attachment bytes remain outside the protocol until Stage 7.
- Current standalone packages are plugin-owned but not yet runtime-integrated.

### Blockers and known risks

There is no Stage 5 blocker. Stage 6 is gated by user authorization. Known
future risks: production endpoint trust and sender configuration are undefined;
source attachment bytes are not durable queue payloads;
acknowledged-event retention has no pruning policy; live schema/environment,
emoji reactions, retractions, edits, real groups/email handles, TLS/key
provisioning, and iPhone clock skew remain unverified in their later stages.
