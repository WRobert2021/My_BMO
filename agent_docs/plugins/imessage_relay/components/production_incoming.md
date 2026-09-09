# Production Incoming Relay

## Stage and corrected direction

Stage 12 implements the original phone-to-kiosk design. The iPhone observes
new incoming iMessage activity and pushes only new normalized events and their
referenced attachments to the kiosk. Normal production operation never mounts,
copies, or polls Apple's Messages database from the kiosk.

The earlier SSHFS/snapshot implementation is retired. Its repository runtime,
configuration, publisher, and focused tests have been removed. The established
kiosk receiver, durable receipts, attachment uploads, feed, and UI remain the
foundation of the corrected implementation.

## Runtime ownership

Two separately deployable Python runtimes are required:

- `be-more-agent` remains the Python 3.13.5 Raspberry Pi kiosk application. It
  owns the authenticated receiver, durable receipt database, attachment store,
  message view, phone-resume client, and infrequent reconciliation schedule.
- The sibling `phone_relay` project is the Python 3.9 phone runtime. Its local
  PyCharm virtual environment is CPython 3.9.6, while the physical phone has
  CPython 3.9.9. It contains no BMO imports and will be tested against the
  exact phone interpreter before deployment.

The phone's Messages database and attachment tree remain external read-only
inputs. The phone runtime may create only its own private configuration,
identifier backlog, cursor, and bounded operational state.

The sibling project includes a rootless launchd example that runs continuously
as the dedicated non-login `pi-bmo` account after one-time private provisioning.
`mobile` remains the SSH administrator and is not the service identity. Because the
Apple SMS directory is private to `mobile`, provisioning grants `pi-bmo`
an inherited read/traverse ACL scoped to that directory. The grant must not add
write authority or change Apple ownership/POSIX mode bits, and both existing
and newly created attachment access is verified. The account, access grant,
runtime, private material, launchd definition, maintenance command, and
corrected mobile-persona launch bridge are installed on the phone. The bridge
has passed authenticated kiosk health plus live delivery.

The phone does not provide the Apple BSD ACL-capable `/bin/chmod`. The
dependency-free `phone_relay.access` administrator helper therefore uses the
Darwin `acl_*` and membership APIs directly. It rejects symbolic links and
unsupported filesystem objects before mutation, preserves unrelated entries,
adds only read/search plus inheritance rights for the dedicated UID, verifies
unchanged POSIX modes/ownership, and can revoke only that UID's allow entries.

The deployment addresses for this installation are kiosk `192.168.0.36` and
phone `192.168.0.42`. Both data and control directions still require private
TLS and independent HMAC secrets.

## Normal event flow

1. A filesystem notification indicates activity in the Messages database or
   WAL. The notification is a wake-up hint, never a one-event claim.
2. After a short debounce, the phone opens one read-only transaction and finds
   every supported incoming source row after its durable observation cursor.
3. The phone commits only stable event identifiers, source ROWIDs, event kinds,
   and retry state to its private backlog before advancing the cursor.
4. If delivery is permitted, the phone opens an authenticated TLS connection
   to the kiosk and drains backlog entries in source order.
5. Message content is normalized only when an entry is being delivered.
   Attachments are read and streamed only when referenced by that entry.
6. The kiosk validates and durably commits each event, completes any required
   attachment uploads, and returns the existing strict event ACK.
7. Only the exact validated kiosk ACK removes the phone backlog entry.

One connection is retained across the requests for a single event, including
all bounded attachment chunks, and then closed. This avoids repeated TLS
handshakes during large media transfer without retaining an idle connection
that the receiver may have timed out.

Coalesced notifications and several senders or back-to-back messages are safe
because each wake scans the complete ROWID interval after the cursor. A later
wake also closes any observation gap caused by a missed filesystem signal.

## Offline circuit

The first delivery failure starts one bounded retry episode:

- try immediately;
- retry once per minute;
- stop after five failed retry attempts; and
- latch delivery dormant while continuing to record new event identifiers.

New messages never reset this exhausted retry circuit. They are added to the
backlog without starting another delivery attempt. Only a valid authenticated
kiosk resume request resets the circuit and permits backlog delivery again.

The phone's resume listener accepts control only; Stage 12 does not expose any
Messages write, send, reaction, or recipient-selection action. Exact request
bounds, HMAC authentication, durable replay protection, and mandatory
production TLS are implemented.

## Deletion and mutation handling

Messages activity caused by deletion or another supported mutation wakes the
same observer. Before delivery, the phone revalidates queued identifiers
against current read-only Apple state:

- a conclusively deleted, never-acknowledged event is removed from backlog;
- an attachment removed before transfer becomes unavailable and the event is
  handled according to the eventual content policy; and
- ambiguous or schema-unverified changes remain pending rather than being
  guessed.

The exact live schema behavior for message deletion, unsend, edit, and reaction
removal must be verified before implementation claims coverage. Identifier-only
backlog storage intentionally does not preserve content that Apple state no
longer contains.

## Kiosk recovery and reconciliation

The kiosk sends an authenticated resume request when its receiver starts or
when its network availability returns. A successful resume clears the phone's
exhausted retry latch; the phone then drains its backlog through normal ACKed
delivery.

Once or twice weekly, the kiosk requests a bounded recent-window
reconciliation. The phone reads that window locally, sends stable event IDs and
canonical digests through the existing bounded receipt-classification
protocol, and resends only entries the kiosk reports missing. The kiosk never
pulls the Apple database and never treats sender absence as deletion authority.

## Kiosk runtime state

The BMO plugin starts its existing receiver/local feed and then independently
starts the configured phone-control coordinator. It sends resume at startup,
uses a content-free health request once per minute to detect recovery, and
schedules a bounded recent reconciliation weekly. Retired `source_config_path`,
`relay_config_path`, and `messages_root` feature settings are ignored and
acquire no mount, worker, source file, or relay-state resource.

The feed selects and presents a bounded window newest-first using Apple source
timestamps. Kiosk receipt time is not a display-order authority: several
recovered events can share the same receipt-clock tick.

Reaction events stay in the durable receipt record but are presented as active
badges on their target message rather than standalone feed rows. Removal folds
against the referenced addition when available and otherwise uses the same
target/part/sender/kind identity, so the badge disappears without deleting
either receipt.

## Migration cleanup

Repository cleanup removes:

- `source_mount.py` and the kiosk polling worker;
- the persistent source configurator and source example;
- the snapshot publisher, launchd example, and installer;
- snapshot/SSHFS production tests; and
- active documentation and example-feature references to the pull path.

Private and remote cleanup is deliberately separate because repository policy
forbids reading or modifying private configuration, and the phone/kiosk are not
connected to this development session. The operator cleanup inventory is:

- kiosk: unmount and remove only the obsolete relay-owned mount directory;
  remove `config/imessage_source.json`, its private password file, the
  kiosk-side sender configuration/state created only for polling, and the
  retired feature settings; retain receiver configuration, receiver secret,
  receipt database, received attachments, and UI data;
- phone: verify no snapshot launch job or publisher was installed, remove the
  exact `Match User pi-bmo` SSH policy, delete exact UID/GID 1003 only after
  identity checks, and delete `/private/var/imessage-relay-chroot`; retain the
  `mobile` maintenance login and never change Apple-owned Messages files; and
- kiosk setup: remove the now-unused SSHFS package requirement and uninstall
  the exact `sshfs` package after the obsolete mount is unmounted. Do not use
  broad package autoremove operations.

Each destructive remote action requires a fresh read-only identity/path check
and an immediately validated SSH configuration candidate. No broad recursive
target, guessed match-block range, or private receiver-state deletion is
allowed.

### Completed live migration cleanup

The operator completed the live cleanup on 2026-09-06:

- the kiosk unmounted and removed the retired relay-owned source path, removed
  the source and sender configuration/state plus stored SFTP password, and
  removed only the obsolete pull settings from the private feature entry;
- kiosk receiver configuration, receiver secret, receipt database, received
  attachments, and message UI data were retained;
- Raspberry Pi OS package `sshfs` `3.7.3-1.2~deb13u1` was removed without a
  broad autoremove operation;
- the phone had no snapshot publisher executable or launchd plist installed;
- the exact `Match User pi-bmo` policy was removed through a validated offline
  candidate, and the active SSH configuration passed `sshd -t` afterward; and
- exact UID/GID 1003 and `/private/var/imessage-relay-chroot` were removed. A
  temporary Procursus group-database repair was used only to let `pwd_mkdb`
  remove the account, after which the original group database was restored.

The `mobile` maintenance account and Apple-owned Messages database,
attachments, permissions, and content were not altered.

## Phone maintenance control

The sibling project provides `deployment/bmo-phone-relay-maintenance` for
installation as `/var/jb/usr/local/sbin/bmo-phone-relay`. A `mobile` SSH
administrator can invoke `status`, `start`, `stop`, or `uninstall` through this
one command. Stop boots the system launchd job out, which removes the observer,
control listener, retry timers, and all network activity rather than merely
pausing delivery. Start validates the fixed plist/runtime/config locations,
bootstraps the job when absent, waits briefly, and reports success only when
launchd still reports the process as running.

Uninstall requires the exact typed phrase `REMOVE BMO PHONE RELAY`, stops first,
then revokes the exact relay ACL, validates and deletes only the non-privileged
`pi-bmo` identity, and removes `/var/jb/var/lib/bmo-phone-relay`, the exact
launchd plist, and the command itself. It explicitly retains Apple Messages
data and `mobile`. The command uses fixed path guards and never expands a
wildcard or derives a recursive removal target from configuration. Because
this phone's Procursus group database lacks the `wheel` entry required by
`pwd_mkdb`, identity deletion makes a private group backup, temporarily adds
only `wheel:*:0:root`, and removes that entry immediately afterward. If
account deletion fails while the identity remains, the command restores the
group database and the relay's read-only ACL before stopping.

System launchd on this rootless jailbreak cannot give a Procursus-only UID the
iOS `mobile` persona needed for Apple's protected SMS path. The installed job
therefore starts in the built-in `mobile` context through one root-owned
sudoers rule that permits only the exact fixed Python launcher command. The
fragment sorts after the broader Procursus administrator rule because sudoers
uses the last matching authentication tag. The
launcher validates the account databases, clears supplementary groups,
permanently drops to the resolved non-privileged UID/GID, and only then imports
configuration or accesses Apple data. Post-drop UID and GID are verified
directly; this iOS build cannot reliably report supplementary groups for the
Procursus-only identity. The top-level service directory is mode `0751` only
so launchd can enter it before elevation; package files, private material,
state, and child directories remain restricted to root and `pi-bmo`. Uninstall
removes the exact sudoers rule.

## Stage 12 acceptance

Invented and physical acceptance must cover:

- Python 3.9.6/3.9.9-compatible phone imports and resource-free module import;
- read-only event observation, coalesced/back-to-back discovery, and cursor
  restart recovery;
- identifier-only backlog durability and deletion pruning;
- immediate delivery plus exactly five one-minute retries;
- a latched exhausted circuit that new messages cannot reset;
- authenticated kiosk resume as the sole retry reset;
- lost ACK, duplicate event, sender/receiver restart, and ordered backlog;
- text, reaction add/remove, photo, video, and bounded attachment resume;
- kiosk-owned feed persistence without an SSHFS mount;
- bounded weekly reconciliation and selective resend;
- TLS/HMAC/replay protection, redacted diagnostics, cleanup, and shutdown;
- `pi-bmo` service ownership, complete `mobile`-administered maintenance
  stop/start/uninstall, and scoped read-only Apple SMS ACL behavior; and
- unchanged Apple database, WAL/SHM, attachments, ownership, POSIX mode bits,
  content, and Messages process state (apart from the explicit read-only ACL).

Stop when the physical incoming matrix passes. Outbound text, media, and
reaction commands remain Stage 13 and require separate authorization.
