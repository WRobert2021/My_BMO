# Live Delivery Validation

## Stage, topology, and boundary

Stage 9 manually validates real iPhone data entering durable receiver state in
the Raspberry Pi kiosk's existing `.venv`. It does not register with BMO,
install either side, create a daemon, enable automatic startup, or authorize
Stage 10.

The accepted manual topology is kiosk-side pull:

1. The Pi mounts only the authorized phone's `/var/mobile/Library/SMS`
   directory through SSHFS `ro`.
2. Each discovery pass fingerprints and copies `sms.db`, `sms.db-wal`, and
   `sms.db-shm` into disposable local storage before SQLite opens the copy.
3. The Pi-owned relay state and standalone receiver state remain separate from
   Apple data. The sender and receiver communicate over literal loopback using
   the protocol's explicit insecure-loopback allowance and an ephemeral
   in-memory HMAC secret.
4. Real attachment bytes are read from contained paths on the read-only mount
   and written only into receiver-owned private storage.

This preserves the Stage 8 no-live-SQLite-open boundary and avoids deploying
the Python 3.13 codebase onto the phone's verified Python 3.9.9 runtime. The
SSH source leg remains authenticated/encrypted, while HTTP never leaves kiosk
loopback. A macOS run is a rehearsal only; repository platform policy requires
the final physical Raspberry Pi 5/Python 3.13.5 run for acceptance.

## Required private inputs

- Explicit authorization for the live phone and Pi.
- User-authenticated SSH/SFTP access capable of reading the canonical SMS root.
- An existing private `0700` acceptance work directory outside the repository.
- No tracked or ignored private config, secret, state, snapshot, certificate,
  attachment, or log file.

The acceptance runner creates its HMAC secret only in memory and prints only
counts, fixed status names, durations, byte totals, and bounded error codes.
It must never print message text, handles, chat IDs, GUIDs, source ROWIDs,
filenames, paths, attachment bytes, hashes, credentials, or exception text.

## Written acceptance matrix

Stage 9 is complete only when the physical Pi run records every item below:

| Case | Required evidence |
| --- | --- |
| preflight | Pi/aarch64/Python versions, read-only mount, private work-directory modes, synchronized clocks |
| supported backlog | bounded live text, standard reaction, photo, and video counts are durably acknowledged; unsupported cases remain issues |
| attachment completion | real available blobs arrive through 64-KiB chunks, pass whole-file size/digest checks, and ACK only after completion |
| offline source | loss of the read-only phone mount fails closed without advancing discovery state; recovery resumes cleanly |
| receiver offline | sender records a bounded retry and no ACK; receiver startup permits later delivery |
| authentication failure | wrong HMAC material returns a bounded authentication NACK and never ACKs or exposes content |
| lost ACK | receiver commits once, sender retries the same stable event with fresh authentication, and receives a duplicate ACK |
| duplicate prevention | receiver receipt count remains one per stable event across retries and restarts |
| kiosk restart | receiver store and partial attachment offsets reopen and continue without loss |
| relay restart | cursor, queue, attempts, retries, ACKs, and dead letters reopen consistently |
| backlog completion | every supported queued event reaches acknowledged or an explicit serious blocker; poison entries do not block later work |
| new live event | one user-created non-sensitive text event is discovered and durably acknowledged after the baseline backlog |
| source immutability | DB/WAL/SHM and attachment bytes plus mode/owner/size/mtime/ctime remain unchanged during each quiet validation window; access time is not treated as write evidence |
| shutdown | Ctrl-C closes sender transport, receiver socket/thread/store, relay store, mount, and temporary resources |

Receiver state must demonstrate durable presence across a deliberate restart
before acceptance cleanup. The acceptance work directory contains private
message data; cleanup or retention requires an explicit operator decision.

## Stop and failure rules

- Stop on schema conflict, source change during copying, path escape, digest or
  size mismatch, unbounded backlog, clock skew, authentication uncertainty,
  receiver conflict, private output, or source write evidence.
- Never respond by changing Apple permissions, stopping Messages,
  checkpointing its database, widening authentication windows, disabling
  digest checks, sending through Messages, or making the mount writable.
- Do not treat a macOS rehearsal, local invented fixture, network receipt,
  pending attachment manifest, or metadata-only ACK as Stage 9 acceptance.
- Stop after the documented physical-Pi matrix passes. Automatic startup and
  BMO runtime/UI integration remain Stage 10 authorization work.

## Expected implementation and tests

A Stage 9 manual acceptance runner may compose existing reader, queue, sender,
receiver, and HTTP components, but must add no import-time resource and must
keep its private state outside the repository. Invented tests own orchestration,
fault injection, redaction, bounds, restart, and cleanup. Existing parser,
state, receiver, sender, reconciliation, attachment, and live-read-only suites
remain required.

Implemented ownership:

- `iphone_relay/live_source.py` fingerprints and copies the DB/WAL/SHM trio
  into a disposable directory and rejects source changes around each use.
- `scripts/run_imessage_live_delivery.py` owns the bounded manual matrix,
  private-directory enforcement, ephemeral authentication, and aggregate-only
  result.
- `tests/test_imessage_live_delivery.py` owns invented WAL-backed orchestration,
  faults, restarts, immutability, redaction, source failure, and CLI coverage.

The 2026-09-02 macOS rehearsal passed supported backlog, attachment completion,
authentication failure, lost ACK, receiver outage, relay/receiver restart,
duplicate prevention, stable-source checks, and fail-closed missing-source
behavior. A second pass discovered and durably acknowledged exactly one
post-baseline text event, then the read-only mount and SSH control connection
closed cleanly. Private receiver/relay state was retained pending an explicit
operator decision. This is evidence for runner readiness only and does not
satisfy the physical-Pi acceptance gate.
