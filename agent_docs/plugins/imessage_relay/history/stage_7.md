# Stage 7 — Attachment Transfer

Completed on 2026-09-01. This archive preserves the former current-chapter
detail; `../progress.md` remains the current status authority.

- Added pending event manifests, per-blob upload sessions, HMAC-bound 64-KiB
  chunk paths, whole-blob SHA-256/size checks, and a 2-GiB per-blob cap.
- Added receiver schema version 2 with lossless version-1 migration, private
  `0700` attachment storage, `0600` files, crash-tail truncation, durable
  offsets, duplicate-chunk validation, and completion promotion.
- Extended `RelaySender` to stream ordinary files and Live Photo components
  without whole-file buffering, resume after sender/receiver restart, reject
  changed/unavailable sources and legacy metadata-only ACKs, and acknowledge
  only an attachment-complete final event response.
- Verified protocol bounds, interrupted/lost responses, duplicate chunks,
  digest failure/reset, source hash preservation, Live Photo non-duplication,
  migration, cleanup, transport-neutral calls, and real loopback HTTP using
  invented temporary data.
- Final Stage 7 suite: **88 passed, 14 subtests passed in 3.01s**.
