# iMessage Relay Progress

current_stage: 12
current_chapter: Dedicated-account provisioning and physical activation gate
state: in_progress
next_action: Recreate the non-login pi-bmo service account, validate a narrow inherited read-only Apple SMS ACL, provision private HMAC/TLS material for kiosk 192.168.0.36 and phone 192.168.0.42, install/validate the phone launchd job and mobile-administered maintenance command, then run the Stage 12 physical incoming matrix. Do not begin Stage 13.
last_verified: 2026-09-06

## Stage index

| Stage | State | Result / gate |
| --- | --- | --- |
| 0–7 | complete | schema, parser, queue, receiver, simulation, reconciliation, and attachment protocol accepted |
| 8 | complete | authorized read-only live discovery accepted |
| 9 | complete | manual physical iPhone-to-kiosk delivery matrix accepted |
| 10 | complete | opt-in kiosk receiver/UI lifecycle accepted |
| 11 | complete | plugin package consolidation and full physical suite accepted |
| 12 | in progress | local event-driven phone push and kiosk control implementation accepted; physical activation remains |
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
- The sibling `phone_relay` PyCharm project is a standalone, dependency-free
  Python 3.9 runtime with no imports from the Python 3.13.5 BMO package. Its
  local compatibility environment is CPython 3.9.6 and the physical phone has
  CPython 3.9.9.
- The phone daemon runs as dedicated non-login `pi-bmo`; `mobile` remains the
  SSH administrator only. A narrowly scoped inherited read/traverse ACL must let `pi-bmo` read
  current and newly created Apple SMS inputs without write rights or POSIX mode
  changes. Because `/bin/chmod` is absent on the phone, a dependency-free
  Darwin ACL API helper owns exact grant/revoke behavior.
- A fresh phone state defaults to `new_only`, recording the current maximum
  Messages ROWID before observing new arrivals. Existing kiosk receipts remain
  intact and the explicit `all` option is reserved for controlled migrations.
- The kiosk exposes a query-only durable message-total and delta API for a
  future badge script. The caller owns its checkpoint and suppresses a badge
  when the delta is zero.
- The phone project provides a fixed-path `mobile`-administered maintenance
  command whose stop removes the launchd job completely and whose confirmed
  uninstall revokes the relay ACL, deletes the service identity, and removes
  relay-owned files. The `mobile` account and Apple Messages data are retained.

## Cleanup status

- Removed the Stage 12 SSHFS source manager, kiosk polling worker, source
  configurator/example, snapshot publisher/installer, and their focused tests.
- Reduced the BMO data plane to the durable receiver and local feed, then added
  only the separate authenticated phone-control coordinator; no retired source
  path or kiosk-side Apple reader was restored.
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

- Kiosk Stage 12 control/configuration and lifecycle focus: 19 tests passed.
- Standalone CPython 3.9.6 compatibility suite: 35 tests passed, including strict
  private configuration, cursor/backlog restart, the resume-only retry latch,
  read-only burst discovery, text/reaction/photo/video materialization,
  attachment streaming, bounded reconciliation, service orchestration, and a
  real loopback control-listener request plus a real macOS/Darwin SQLite-WAL
  filesystem wake. The Darwin ACL test verifies grant inheritance, exact
  revocation, preservation of unrelated ACL entries, and unchanged modes and
  owners. Deployment tests validate `pi-bmo` launchd ownership and bounded
  stop/start/status/uninstall command structure.
- Shared phone/kiosk control canonical body and HMAC vectors match. An actual
  local phone sender-to-kiosk receiver loopback delivered one invented event,
  accepted its duplicate idempotently, and left one durable kiosk receipt.

- Complete relay suite: 123 tests and 21 subtests passed.
- Complete repository suite: 838 tests and 10,006 subtests passed in 20.41
  seconds with exit status zero.
- Python 3.9 AST/import checks, tracked example JSON parsing, and `git diff
  --check` passed. Physical kiosk and phone migration cleanup is complete. The
  phone preflight found CPython 3.9.9 and no Apple BSD `/bin/chmod`; user/group
  next values were `1002:1001`. The new runtime has not been deployed: the dedicated account/ACL and production
  certificates/secrets are not provisioned, the phone's actual `kqueue`
  behavior has not been observed, and no launchd job is installed.
