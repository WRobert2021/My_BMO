# iMessage Relay Progress

current_stage: 6
current_chapter: Stage 6 acceptance gate
state: complete
next_action: Stop and wait for explicit authorization before Stage 7 attachment transfer.
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
| 6 — reconciliation | complete | bounded recent/month selective repair accepted |
| 7 — attachment transfer | not started | requires explicit authorization; metadata only is delivered |
| 8 — live iPhone read-only integration | not started | separately authorized live-device gate |
| 9 — live relay | not started | blocked by Stage 8 acceptance |
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Add bounded recent/month reconciliation and selective resend without granting
the sender deletion authority over kiosk-only history.

### Completed

- Added exact recent and UTC calendar-month window constructors plus bounded,
  half-open, read-only source scans that never advance the live cursor.
- Added atomic reconciliation commits, 20-entry keyset state pages, canonical
  wire digests, and authenticated ordered receipt membership.
- Added `present`, `missing`, and `conflict` handling. Only acknowledged missing
  events are requeued; pending/dead/conflicting events retain their state, and
  kiosk-only history is neither enumerated nor deleted.
- Verified idempotent reruns, rediscovery of a deliberately missed source row,
  selective duplicate-safe resend, source hash/cursor preservation, maximum
  escaped-ID wire bounds, mismatched-response failure, HMAC application routing,
  and real loopback HTTP.
- Ran the complete parser/state/receiver/sender/reconciliation suite with local
  loopback permission: **79 passed, 14 subtests passed in 2.89s**.

### Remaining

No Stage 6 implementation work is identified. Stage 7 attachment transfer is
not started and requires explicit authorization. No live iPhone contact,
deployment, daemon, private sender configuration, or runtime plugin
registration is authorized by completed Stage 6.

### Decisions constraining next work

- Stage gates remain authorization gates; completion does not authorize the
  next stage.
- HTTPS request/response plus per-request HMAC is the Stage 4 transport.
- Plain HTTP is accepted only for explicit literal-loopback simulation.
- Sender state acknowledges only an exact `201 accepted` or `200 duplicate`
  ACK with matching protocol, request ID, and stable event ID.
- Reconciliation pages contain at most 20 candidates and never authorize kiosk
  deletion; receiver absence can only selectively requeue sender-owned state.
- Attachment bytes remain outside the protocol until Stage 7.
- Current standalone packages are plugin-owned but not yet runtime-integrated.

### Blockers and known risks

There is no Stage 6 blocker. Stage 7 is gated by user authorization. Known
future risks: production endpoint trust and sender/reconciliation scheduling
are undefined; source attachment bytes are not durable queue payloads;
acknowledged-event retention has no pruning policy; live schema/environment,
emoji reactions, retractions, edits, real groups/email handles, TLS/key
provisioning, and iPhone clock skew remain unverified in their later stages.
