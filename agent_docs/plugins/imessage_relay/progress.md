# iMessage Relay Progress

current_stage: 12
current_chapter: Event-driven phone push architecture reset
state: in_progress
next_action: Define the Python 3.9.6 phone backlog/observer and authenticated kiosk-resume contracts, then implement them without beginning Stage 13 outbound work.
last_verified: 2026-09-06

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0–7 | complete | schema, parser, queue, receiver, simulation, reconciliation, and attachment protocol accepted |
| 8 | complete | authorized read-only live discovery accepted |
| 9 | complete | manual physical iPhone-to-kiosk delivery matrix accepted |
| 10 | complete | opt-in kiosk receiver/UI lifecycle accepted |
| 11 | complete | plugin package consolidation and full physical suite accepted |
| 12 | in progress | snapshot/pull design retired; event-driven incoming push is now the required architecture |
| 13 | not started | outbound text, media, and reactions remain unauthorized |

## Current Stage 12 decisions

- Normal operation is phone-to-kiosk push. The kiosk never mounts, copies, or
  polls Apple's Messages database.
- The phone treats Messages filesystem activity as a wake hint, scans all rows
  after its cursor in a read-only transaction, and records only identifiers and
  retry state in its private backlog.
- The first outage episode gets one immediate attempt followed by five
  one-minute retries. After exhaustion, delivery remains latched dormant even
  when new messages arrive. Only an authenticated kiosk resume request resets
  the circuit.
- Deletion activity revalidates queued identifiers. Conclusively deleted,
  unacknowledged events may be pruned, but live deletion/unsend/edit schema
  behavior must be verified before coverage is claimed.
- The kiosk receiver database remains the independent message record. Weekly
  or twice-weekly bounded reconciliation is initiated by the kiosk but scanned
  on the phone; only missing events are resent.
- The sibling `phone_relay` PyCharm project exists with CPython 3.9.6 and no
  source files yet. It will be a standalone runtime with no imports from the
  Python 3.13.5 BMO package.

## Cleanup status

- Removed the Stage 12 SSHFS source manager, kiosk polling worker, source
  configurator/example, snapshot publisher/installer, and their focused tests.
- Reduced the BMO runtime to the durable receiver and local feed. It now reports
  receiver readiness while phone control and reconciliation remain explicitly
  unavailable rather than opening a retired source path.
- Preserved the stable message model/scroll behavior, kiosk receipt store,
  authenticated event/attachment protocol, and receiver-secret file support.
- Removed SSHFS/FUSE from `setup.sh` and its setup contract with explicit
  operator approval; the corrected runtime has no mount dependency.
- Live kiosk cleanup removed the retired source/sender configuration, stored
  source password, sender state, mount directories, and obsolete feature
  settings. Receiver configuration, secret, receipt database, attachments, and
  UI data were retained.
- Raspberry Pi OS package `sshfs` `3.7.3-1.2~deb13u1` was removed without an
  autoremove operation.
- Live phone cleanup verified that no publisher or launch plist was installed,
  removed the restricted `pi-bmo` SSH policy and exact UID/GID 1003, deleted
  the retired chroot, and retained the `mobile` maintenance account. The active
  SSH policy was syntax-validated, and the original Procursus group database
  was restored after account deletion.

## Verification status

- Local receiver/runtime focus after the architecture reset: 33 tests and 9
  subtests passed with loopback permission.
- Complete relay suite: 110 tests and 17 subtests passed.
- Combined relay and shared extension/runtime-menu/Qt/setup suite: 181 tests
  and 57 subtests passed.
- Complete repository suite: 825 tests and 10,002 subtests passed in 19.97
  seconds with exit status zero.
- Python compilation, example feature JSON parsing, and `git diff --check`
  passed. Physical kiosk and phone migration cleanup is complete. The new phone
  runtime remains unimplemented and therefore unverified.
