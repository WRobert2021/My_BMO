# Production Incoming Activation

## Stage and goal

Stage 12 turns the accepted manual incoming relay into an opt-in service owned
by the normal BMO plugin lifecycle. It makes new incoming messages available on
the kiosk without an SSH password prompt on each start. Stage 13 outbound
Messages work is not authorized by this stage.

## Configuration and credentials

The feature entry names a private source configuration file. That file stores
the restricted phone host, `pi-bmo` username, port, `/SMS` remote path, local
mount path, pinned known-hosts path, polling bounds, and the path of a private
password file. The password file must be a regular non-symlink file readable
only by its kiosk owner (`0600`) and contain exactly one password line.

Passwords are never accepted in tracked example JSON, process arguments,
status payloads, exceptions, or logs. SSHFS receives the password through its
standard input. The tracked example contains placeholders only; the operator
creates private ignored configuration and the password file directly on the
kiosk once.

## Source and phone boundary

The existing `pi-bmo` account remains chrooted, SFTP-only, password-protected,
server-read-only, and confined to `/SMS`. The kiosk additionally requests a
read-only SSHFS mount, requires strict host-key verification, disables host-key
updates, requests no forwarding, and treats an unverified or writable mount as
unavailable. The validated phone-side account policy disables all forwarding.
`ClearAllForwardings` is not passed as a mount option because SSHFS 3.7.3
rejects it before starting SSH.

The `/SMS` export is a snapshot rather than the live Apple directory. A
root-owned phone publisher may periodically build `.SMS.next` from read-only
DB/WAL/SHM and attachment inputs, verify the source trio did not change during
copy, restrict the copy to `root:pi-bmo` with directories `0550` and files
`0440`, and atomically rotate it into `/SMS`. It never changes Apple ownership,
permissions, database state, or attachments. An inconclusive copy is discarded
and retried later.

## Kiosk lifecycle

Enabled registration validates private configs, starts the receiver, mounts or
adopts the verified read-only source, and starts one plugin-owned worker. Each
bounded cycle copies the DB trio to disposable local storage, scans from the
durable cursor, stores normalized events, and drains eligible delivery attempts
through the in-process authenticated receiver while attachment source paths
remain under the read-only mounted snapshot. Source, mount, parse, or delivery
failure becomes bounded status and a later retry; it cannot block BMO.

The receiver store supplies a bounded newest-first local feed for the relay
view. The view may show incoming sender identifiers, message text, timestamp,
reaction summaries, and attachment categories because this is the explicit
private message surface. None of that content may cross logs, generic tool
results, status/error payloads, docs, or fixtures.

Plugin close stops and joins the worker, closes sender/relay/receiver state,
unmounts only a mount it created, removes its empty runtime mount directory,
and remains idempotent. It does not remove durable message state or the phone's
restricted account/export.

## Acceptance

Invented tests must cover strict configuration and password-file permissions,
argument/diagnostic redaction, read-only mount verification, startup failure
isolation, source outage and recovery, bounded polling and pagination,
idempotent restart, attachment delivery, feed decoding, UI actions, and full
cleanup. Physical acceptance then requires one newly published incoming event
to appear in the kiosk view without a manual password or reconciliation action,
followed by one restart/offline recovery observation. Stop before Stage 13.

## Operator activation

The repository setup script installs/verifies SSHFS on the kiosk but never
contacts or modifies the phone. After the code is synchronized, the operator
runs the one-time kiosk configurator with the restricted phone host and
username. It prompts once without echo, writes ignored owner-only source and
receiver secrets, updates the existing private feature entry, and requires no
password input on later BMO starts:

```text
venv/bin/python -m bmo.features.imessage_relay.tools.configure_incoming \
  --host PHONE_IP_ADDRESS --username pi-bmo
```

The configurator validates the existing private feature file before prompting.
If an earlier version stored the protected password but failed while enabling
the feature, `--reuse-existing-password` resumes without reading a password
from the terminal. Failures identify the configuration boundary without
printing secret contents. A missing private `features.json` is initialized from
the tracked feature template; an existing symlink or malformed file still
fails closed rather than being overwritten.

The phone publisher is likewise explicit. Copy only the project-owned
`refresh_snapshot.sh` and plist template to a temporary phone path through the
normal `mobile` maintenance login. As `mobile`, install the script as
`/var/jb/usr/local/libexec/imessage-relay-refresh` with root ownership and mode
`0700`, install the plist as
`/var/jb/Library/LaunchDaemons/com.bmo.imessage-relay-snapshot.plist` with root
ownership and mode `0600`, syntax-check it, run the script once, then bootstrap
that exact system launchd path. This does not deploy Python or modify the
Messages application/database.
