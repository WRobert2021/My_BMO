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
- System-wide `sshfs` and `fusermount3` commands on the Pi. The repository's
  `setup.sh` detects existing commands, idempotently verifies/installs the
  Raspberry Pi OS `sshfs` package, and checks both commands after installation;
  neither command belongs in `.venv` or `venv/`.
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

- `bmo/features/imessage_relay/relay/live_source.py` fingerprints and copies the DB/WAL/SHM trio
  into a disposable directory and rejects source changes around each use.
- `bmo.features.imessage_relay.tools.run_live_delivery` owns the bounded manual matrix,
  private-directory enforcement, ephemeral authentication, and aggregate-only
  result.
- `tests/test_imessage_live_delivery.py` owns invented WAL-backed orchestration,
  faults, restarts, immutability, redaction, source failure, and CLI coverage.

The 2026-09-02 macOS rehearsal passed supported backlog, attachment completion,
authentication failure, lost ACK, receiver outage, relay/receiver restart,
duplicate prevention, stable-source checks, and fail-closed missing-source
behavior. A second pass discovered and durably acknowledged exactly one
post-baseline text event, then the read-only mount and SSH control connection
closed cleanly. The operator explicitly chose cleanup, and the private macOS
receiver/relay state directory was deleted and verified absent. This is
evidence for runner readiness only and does not satisfy the physical-Pi
acceptance gate.

On 2026-09-05 the physical Pi preflight confirmed Debian SSHFS package
`3.7.3-1.2~deb13u1`, SSHFS 3.7.3, FUSE 3.17.2, and `fusermount3` 3.17.2. The
target setup-contract suite passed with 12 tests. The first read-only mount
attempt ended with `Connection reset by peer` before a mount appeared. A
subsequent no-operation verbose SFTP probe established TCP and SSH key exchange
but stopped at strict host-key verification because the Pi had no trusted key
for the phone; user authentication and the SFTP subsystem were never reached.
`sms.db`, `sms.db-wal`, and `sms.db-shm` were therefore unreadable and no phone
file was opened or changed. The phone's ED25519 fingerprint must be verified
through an independent trusted path before its public host key is added to the
Pi. This is a failed-closed endpoint-trust result, not Stage 9 acceptance.
The operator subsequently compared the Pi-observed ED25519 fingerprint with
the existing trusted Mac `known_hosts` entry and obtained an exact match.
Independent identity verification is therefore complete; adding only that
verified public host key to the Pi's local `known_hosts` is the next authorized
step and does not write to the phone.

After provisioning that verified key, the repeated empty-batch probe passed:
strict host-key verification matched, the `agent` account authenticated using
the intentionally configured passwordless method, the SFTP v3 subsystem was
accepted, its visible root resolved to `/`, and the client exited with status
zero. No Apple data path or file was opened. OpenSSH also learned the server's
RSA and ECDSA host keys through its signed host-key update; their fingerprints
matched the Mac's independently trusted entries supplied by the operator.
Known SMS-path metadata and read permission remain to be checked before the
read-only mount is retried.

The subsequent metadata-only SFTP probe could enter
`/var/mobile/Library/SMS`, which canonicalized to
`/private/var/mobile/Library/SMS`, but an exact metadata lookup for `sms.db`
returned not found. The batch therefore stopped before the optional WAL/SHM
lookups, and no database bytes were read. This proves path traversal but not
that the `agent` SFTP namespace exposes the live database. The next safe step
is a read-only existence/metadata comparison through the already authorized
`mobile` shell; phone permissions or SFTP configuration must not be changed as
part of diagnosis.

The authorized `mobile` shell confirmed both SMS directory aliases exist with
mode `0700` and `mobile:mobile` ownership. It also confirmed `sms.db`,
`sms.db-wal`, and `sms.db-shm` exist as fixed-path regular files with mode
`0644`. The separate `agent` UID is therefore blocked by the parent directory's
traversal permissions before file modes matter; the SFTP not-found response is
an access-boundary result, not a missing database. No permission change is
authorized. Continuing with `agent` requires a separately reviewed
server-enforced read-only access design; the existing `mobile` account could
instead be used with client-enforced SSHFS `ro`, but that weaker boundary
requires an explicit operator choice.

The operator selected a redesigned password-protected `agent` account with
server-enforced read-only access and path confinement. Its authorized export is
exactly `sms.db`, `sms.db-wal`, `sms.db-shm`, and the `Attachments` tree; the
attachment scope is required by the Stage 9 photo/video matrix. Shell access,
command execution, forwarding, all other SMS paths, and the rest of the phone
remain excluded. Before configuration changes, a read-only capability audit
must identify the installed OpenSSH controls and whether the phone can place
the live sources inside a root-owned chroot without changing Apple-owned
permissions. If it cannot, a bounded private snapshot export must be designed
and separately validated; no daemon is authorized.

The read-only capability audit confirmed OpenSSH 9.7p1 and an existing
`agent` match block with password authentication, empty passwords permitted,
public-key and keyboard-interactive authentication disabled, forced
`internal-sftp -R -d /`, forwarding disabled, and no TTY. It has no chroot, so
its path scope is not confined. The phone's APFS environment provides `cp` but
not `mount_nullfs`, `bindfs`, `rsync`, or `ditto`; approximately 107 GiB was
available on `/private/var`. Authorized root execution through `sudo` was also
confirmed without exposing a password.

Because no installed read-only bind/null mount can project the live Apple tree
into a root-owned chroot, the bounded Stage 9 design is a manually refreshed,
private chroot snapshot containing only the trio plus `Attachments`. The
snapshot is phone-owned relay data, not an Apple path, and must be created from
read-only source operations, mode-sanitized, served by `internal-sftp -R`, and
removed or retained only by explicit operator choice. This manual snapshot can
support the Stage 9 matrix but does not authorize or provide automatic incoming
refresh; any future scheduler or daemon requires a later explicit gate.

The operator subsequently replaced the planned `agent` redesign with a new
dedicated phone account named `pi-bmo` and explicitly requested deletion of
`agent`. Migration must first prove that `pi-bmo` alone has the password,
SFTP-only, read-only, forwarding-disabled, chroot-confined behavior; only then
may the exact old account and its SSH match block be removed. This ordering
preserves rollback access without retaining the temporary account after
acceptance.

The migration audit confirmed that `pi-bmo` is unused and the temporary
account is exactly UID/GID 1002. Procursus provides `adduser`, `pw`, `passwd`,
and GNU coreutils `cp` 9.5; standalone `useradd`, `userdel`, and `deluser` are
absent. GNU `cp` supports copy-on-write reflinks with ordinary-copy fallback.
`/private` and `/private/var` are root-owned mode `0755`, satisfying the
candidate chroot-parent ownership boundary. The authorized attachment source
is currently bounded to five files and 13,596 KiB, with ample private-volume
space. The OpenSSH launch service is socket-activated and was not persistently
running at audit time. Exact `adduser`/`pw` syntax and launch arguments must be
read before account creation or deletion; no destructive command may be
guessed.

The root-owned `/private/var/imessage-relay-chroot` boundary was then created
at mode `0755`. A root-only staging snapshot took private SHA-256 baselines,
copied the trio and attachment tree with copy-on-write fallback, proved the
source remained stable, and proved every copied file matched before deleting
the temporary manifests. The snapshot was atomically published as `/SMS` with
root ownership, group `pi-bmo`, directory mode `0550`, and file mode `0440`.
It contains eight regular files; aggregate verification reported zero wrong
directory modes, file modes, or owners. The new login still does not exist and
the live SSH configuration remains unchanged.

An offline copy of the phone's SSH configuration was extended with the
`pi-bmo` match policy and validated by both `sshd -t` and `sshd -T`. This phone
build rejected `PermitUserEnvironment` inside a match block, so that redundant
line was removed; the effective global policy remains `no`. The accepted
candidate requires password authentication, rejects empty/public-key/
keyboard-interactive authentication, chroots to the private relay boundary,
forces `internal-sftp -R -d /SMS`, and disables TCP, agent, stream-local, X11,
tunnel, TTY, and user-RC paths. The active configuration is still unchanged;
installation requires a protected backup and retention of the current
authorized `mobile` session until the replacement login passes.

The active SSH configuration was protected by a root-only rollback copy, then
replaced with the already validated candidate and rechecked successfully. A
locked `pi-bmo` account was created as UID/GID 1003 with no supplementary
groups or home creation, after which the operator assigned a unique password
locally without exposing it. The platform's generic login-keychain warning is
not applicable to this headless SFTP-only account and must not trigger keychain
creation. The existing authorized `mobile` session remains open for rollback;
new-account authentication, confinement, read access, and denied-write probes
are still required before removing `agent`.

A separate Mac SFTP session then authenticated `pi-bmo` by password and proved
the account starts at `/SMS`, can stat the DB/WAL/SHM trio, can traverse into
`Attachments`, sees the chroot boundary as `/`, cannot resolve `/private`, and
receives permission denied for a test `mkdir`. No source content was printed or
modified. This accepts the phone account policy, but because the probe ran from
the Mac rather than the kiosk, one double-read-only kiosk SSHFS mount must pass
before the temporary `agent` account and block are deleted.

The physical kiosk then mounted `pi-bmo@192.168.0.42:/SMS` through SSHFS with
client `ro`, strict host-key checking, and host-key updates disabled. `findmnt`
reported a read-only FUSE mount; the DB/WAL/SHM trio was readable, the
`Attachments` directory was accessible, an attempted test-file creation was
denied, and the test path remained absent. This proves the double read-only
boundary from the actual Stage 9 client. The mount remains active for the next
acceptance step, and the replacement account is now sufficiently proven to
remove exact UID/GID 1002 `agent` and its SSH match block.

The exact UID 1002 user was removed without recursive home deletion. The first
group-deletion command did not target Procursus's `/var/jb/etc` database, and a
read-only verification caught the retained GID 1002 entry. After a protected
backup, explicit removal from that database was verified. The old SSH match
block was deleted only in an offline candidate; `sshd -t` and the complete
effective `pi-bmo` restriction set passed before installation. The first
install attempt rejected an unavailable `wheel` group name before replacing
the live file, whose syntax remained valid; installation with numeric root
UID/GID then succeeded and revalidated.

A fresh physical-kiosk session against the cleaned configuration authenticated
`pi-bmo`, started at `/SMS`, resolved `/` only to the chroot, could not resolve
`/private`, read metadata for the mode-`0440` DB/WAL/SHM trio, traversed the
attachment tree, and received permission denied for `mkdir`; the marker
remained absent. A strict batch probe for `agent` was rejected. The replacement
account, obsolete-account removal, chroot confinement, and double read-only
mount gate are accepted. The mounted source is still a manually refreshed
snapshot, so the remaining Stage 9 relay and new-live-event cases require
explicit quiet-window snapshot refreshes rather than an automatic phone job.

The first physical relay run on Linux/aarch64/Python 3.13.5 returned `pass`
with exit status zero. A bounded 38-row scan yielded 37 supported events: 26
messages, nine reaction additions, and two reaction removals, with no issues.
All 37 events were durably acknowledged exactly once. Four real attachments
completed with no partial state: three photos and one video totaling 13,457,154
bytes. The authentication, lost-ACK, and receiver-offline injections returned
`invalid_signature`, `ack_timeout`, and `transport_unavailable` respectively;
each remained a bounded retry. Relay and receiver restart comparisons passed,
receiver and acknowledgement counts matched, the original database was not
opened directly, and the source trio remained stable. Remaining Stage 9 work
is deliberate source loss and recovery, one post-baseline live event through a
fresh manually published snapshot, and Ctrl-C/final resource cleanup evidence.

For the source-offline case, only the kiosk's SSHFS source was unmounted; the
kiosk network and phone services remained online. A rerun returned the
content-free `messages_trio_unreadable` code with exit status one. Hidden
before/after digest comparisons proved `relay.db` and `receiver.db` remained
byte-for-byte unchanged. The same restricted source subsequently remounted
with read-only FUSE options. Successful post-baseline delivery after the next
manual snapshot refresh will complete the recovery half of this case.

After exactly one new non-sensitive incoming text arrived, a second private
snapshot pass baselined, copied, source-stability-checked, and copy-verified
the authorized trio and attachment tree. The private manifests were removed;
the replacement again contained eight files with zero ownership or mode
errors. It was published by rename while the prior snapshot remained available
for rollback. Reusing the original durable Pi state then returned `pass` and
exit zero: exactly one message row was discovered and acknowledged in one
attempt, raising matching relay and receiver totals from 37 to 38. No issues,
pending events, partial attachments, or new attachment bytes appeared; both
restart comparisons passed and the source trio remained stable. This completes
the post-baseline event and recovery half of the source-offline case. Only
physical SIGINT/resource cleanup and the explicit private-data cleanup decision
remain before Stage 9 acceptance.

The physical SIGINT case ran against a separate mode-`0700` Pi work directory.
A controlled interrupt was delivered only after receiver state existed. The
runner emitted only `{"status": "interrupted"}`, exited 130, left no running
process, and returned the disposable-source directory count to its pre-run
value. This accepts interrupt handling and cleanup of runner-owned transient
resources. The isolated interrupt directory, accepted durable state, external
SSHFS mount, retained previous phone snapshot, and phone-side rollback files
remain subject to the operator's explicit final cleanup or retention decision.

The operator chose deletion. The kiosk unmounted the SSHFS source, deleted both
private acceptance-state directories and the empty mount tree, and verified all
three paths absent. The phone deleted the retained previous snapshot and five
temporary SSH/group candidate or rollback files. A final `sshd -t` check passed.
The active password-only, SFTP-only, chrooted read-only `pi-bmo` policy and the
current mode-`0550` `/SMS` snapshot remain intentionally available for the
separately gated Stage 10 physical checks. With cleanup complete, the entire
Stage 9 matrix is accepted on 2026-09-05. Acceptance does not authorize BMO
automatic startup, deployment, a phone daemon, outbound messaging, or Stage 12.
