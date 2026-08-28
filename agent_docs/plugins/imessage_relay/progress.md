# iMessage Relay Progress

current_stage: 4
current_chapter: Stage 4 acceptance gate
state: complete
next_action: Stop and wait for explicit authorization before Stage 5 simulated sender integration.
last_verified: 2026-08-28

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0 — audit/snapshot validation | complete | private inputs and read-only boundary established |
| 1 — schema investigation | complete | evidence and explicit gaps preserved |
| 2 — read-only parser | complete | immutable normalized events and sanitized tests |
| 3 — relay state/durable queue | complete | atomic cursors, retries, ACK/dead-letter state |
| 4 — kiosk receiver prototype | complete | authenticated durable idempotent local receiver |
| 5 — simulated end-to-end relay | not started | requires explicit authorization |
| 6 — reconciliation | not started | blocked by Stage 5 acceptance |
| 7 — attachment transfer | not started | metadata only is currently delivered |
| 8 — live iPhone read-only integration | not started | separately authorized live-device gate |
| 9 — live relay | not started | blocked by Stage 8 acceptance |
| 10 — runtime/UI integration | not started | blocked by stable backend contracts |

## Current chapter

### Objective

Reconcile the interrupted Stage 4 documentation against code and tests without
starting Stage 5.

### Completed

- Verified the standard-library `kiosk_receiver` package implements strict
  configuration, HMAC authentication/replay protection, versioned path-free
  JSON validation, private SQLite receipt/nonce state, authenticated
  health/status, HTTP(S) serving, and explicit ACK/NACK behavior.
- Verified ACK is emitted only after durable ingest; identical stable-ID replay
  is a duplicate ACK and conflicting content is rejected.
- Verified TLS is required except explicit loopback development, and build/
  shutdown paths close the listener and store.
- Ran `.venv/bin/python -m pytest -q tests/test_imessage_receiver.py
  --tb=short` with loopback permission: **20 passed, 9 subtests passed in
  2.10s**. An initial sandboxed run had 18 pass and two setup errors solely
  because loopback bind was denied; the permitted rerun passed both HTTP tests.
- Ran the combined parser/state/receiver boundary suite after documentation
  reconciliation: **63 passed, 12 subtests passed in 1.84s**.

### Remaining

No Stage 4 implementation work is identified. Stage 5 sender/queue integration,
fault simulation, and status loop are intentionally absent. Do not implement
them without explicit authorization. No live iPhone contact, deployment,
daemon, or runtime plugin registration is authorized by completed Stage 4.

### Decisions constraining next work

- Stage gates remain authorization gates; completion does not authorize the
  next stage.
- HTTPS request/response plus per-request HMAC is the Stage 4 transport.
- Attachment bytes remain outside the protocol until Stage 7.
- Current standalone packages are plugin-owned but not yet runtime-integrated.

### Blockers and known risks

There is no Stage 4 blocker. Stage 5 is gated by user authorization. Known
future risks: source attachment bytes are not durable queue payloads;
acknowledged-event retention has no pruning policy; live schema/environment,
emoji reactions, retractions, edits, real groups/email handles, TLS/key
provisioning, and iPhone clock skew remain unverified in their later stages.
