# Stage 8 — Live iPhone Read-Only Integration

Accepted on 2026-09-02. This content-free record contains no device address,
hostname, credential, handle, GUID, chat identifier, message text, filename,
attachment path, attachment bytes, or hash. `../progress.md` remains the
current status authority.

## Environment and access

- Authorized live target: reachable through a temporary user-authenticated SSH
  control connection; no credential was stored or printed.
- Environment: Darwin 21.1.0 ARM64, Python 3.9.9, SQLite 3.36.0.
- Canonical source: `/var/mobile/Library/SMS`; directory mode `0700`; DB, WAL,
  and SHM modes `0644`.
- A dedicated SFTP-only account authenticated but failed closed with
  content-free `Permission denied` at the protected mobile Library boundary.
- Only the canonical SMS root was mounted through SSHFS `ro`. SQLite never
  opened the live source: each run fingerprinted and copied DB/WAL/SHM into a
  local `0700` temporary directory and opened only that disposable copy.

## Accepted observations

- Multiple quiet runs reported `pass`, schema version 89, WAL,
  `quick_check=ok`, query-only operation, and the expected ROWID-range plan.
- The initial bounded sample examined 36 positive-iMessage source rows and
  normalized 35 events: 24 messages, nine reaction additions, and two reaction
  removals. It observed incoming/outgoing source directions while omitting
  ordinary outgoing message events as required. No parser issues occurred.
- Four contained live attachments were available: three photo and one video.
  The validator read 13,457,154 bounded source bytes and found no content or
  full-metadata change and no read error.
- A second run/restart repeated the same result. A controlled post-startup
  SIGINT emitted only `{"status":"interrupted"}`, exited 130, left no validator
  resource behind, and was followed by another passing stable-source run.
- After the user created one non-sensitive incoming iMessage, the next run
  examined 37 source rows and normalized 25 message events; incoming counts
  increased by one, with no issue or relay transmission.
- Every accepted run reported stable DB/WAL/SHM fingerprints during copying and
  across validation. The final SSHFS mount, SSH control connection, and all
  Stage 8 temporary directories were closed or removed.

## Gate boundary

No write-capability probe, remote file/settings change, live SQLite open,
checkpoint, journal mutation, message send by the relay, kiosk contact, sender
delivery, deployment, daemon installation, or BMO runtime integration occurred.
Stage 9 requires separate explicit authorization.
