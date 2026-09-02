# Live Read-Only Validation

## Stage and boundary

Stage 8 validates discovery against a specifically authorized jailbroken
iPhone. It does not send an event, contact a kiosk endpoint, create relay
state, install files on the phone, install a daemon, or register with the BMO
runtime. Stage 9 remains a separate authorization gate.

`scripts/validate_imessage_live_readonly.py` accepts a read-only mount of the
phone's `/var/mobile/Library/SMS` directory. It hashes and copies `sms.db`,
`sms.db-wal`, and `sms.db-shm` into a local `0700` temporary directory, confirms
the live trio did not change during that copy, and opens only the disposable
copy with SQLite. This avoids SQLite opening or coordinating against the live
WAL/SHM files. The temporary directory is removed automatically.

The copied database is checked with `quick_check`, its schema and WAL mode are
observed, the production parser validates all required fields, and the
incremental query plan must use the ROWID range. A bounded newest-iMessage scan
exercises filtering, normalization, and attachment containment against the
live read-only attachment tree. Up to four small available attachment files
are read twice to confirm stable content and metadata; no bytes or digests are
printed.

Output is limited to versions, booleans, counts, event/direction/media enum
values, and parser issue codes. It excludes text, attributed bodies, handles,
chat IDs, GUIDs, ROWIDs, filenames, paths, attachment bytes, and hashes.

## Authorized manual procedure

Use existing key-based SSH access. Do not put a password, key, device address,
or private path in tracked configuration or shell history. First collect only
non-content compatibility facts:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes <authorized-target> \
  'uname -sr; sysctl -n kern.osversion; python3 --version; python3 -c "import sqlite3; print(sqlite3.sqlite_version)"; stat -f "%Sp %Su %Sg" /var/mobile/Library/SMS/sms.db /var/mobile/Library/SMS/sms.db-wal /var/mobile/Library/SMS/sms.db-shm'
```

Expose only the Messages root through a local read-only SSHFS mount, then run
the validator from the repository virtual environment:

```sh
stage8_root="$(mktemp -d /private/tmp/imessage-stage8.XXXXXX)"
mkdir "$stage8_root/SMS"
sshfs -o ro,BatchMode=yes,StrictHostKeyChecking=yes,ConnectTimeout=5 \
  <authorized-target>:/var/mobile/Library/SMS "$stage8_root/SMS"
.venv/bin/python scripts/validate_imessage_live_readonly.py \
  "$stage8_root/SMS" --scan-limit 100
umount "$stage8_root/SMS"
rmdir "$stage8_root/SMS" "$stage8_root"
```

If mount, authentication, trio stability, schema compatibility, query plan,
or attachment access fails, stop and retain only the content-free error code.
Never retry by changing permissions, copying files onto the phone, stopping
Messages, checkpointing SQLite, or making the remote mount writable.

## Acceptance checklist

Stage 8 is complete only when one quiet live run records all of the following
without private values:

- the authorized target is reachable and the three source files are readable;
- iOS/kernel, remote Python, and remote SQLite versions are recorded;
- the validator reports `pass`, WAL mode, query-only operation on the local
  copy, the expected ROWID-range plan, and stable DB/WAL/SHM fingerprints;
- bounded source diagnostics observe incoming/outgoing row counts when the
  live sample contains them, while normalization omits ordinary outgoing
  messages and positively selects only iMessage rows;
- at least one real available attachment path is contained and its controlled
  read leaves its content and metadata unchanged, or the absence of a recent
  attachment is recorded for a later explicitly selected quiet sample;
- a second manual run/restart is clean and a user-created new test row is
  discovered without any relay transmission;
- an interrupted manual run exits without leaving a mount/process and source
  fingerprints remain unchanged; and
- permission/schema/source-change failures are content-free and fail closed.

A `pass` report is necessary but does not by itself assert every manual item.
Natural Messages activity can change DB/WAL/SHM during validation; such a run
is inconclusive rather than evidence of mutation and must be repeated during a
quiet window. Do not proceed to Stage 9 until the complete checklist is
recorded in `progress.md`.

## Tests

`tests/test_imessage_live_validation.py` uses invented temporary WAL fixtures.
It verifies disposable-copy parsing, ROWID-plan and aggregate diagnostics,
source/attachment hash preservation, output redaction, trio failure, bounded
scan input, and fail-closed handling of a source change during copying.
