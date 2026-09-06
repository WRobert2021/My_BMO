# Runtime Integration

## Stage and boundary

Stage 10 integrates iMessage Relay as an explicitly configured BMO
feature/service. It is not a default feature, launch daemon, independent
service installation, phone deployment, or authorization to send through
Messages. Stage 9's physical-Pi live-delivery gate completed on 2026-09-05.

Offline development used only invented local data and the repository virtual
environment. The authorized physical gate may use temporary private kiosk
configuration and the retained restricted phone snapshot, but it must remain a
manual run with no default enablement, deployment, or automatic startup.

## Ownership and lifecycle

- `bmo.features.imessage_relay` owns feature configuration, registration,
  listener/thread lifetime, content-free status, on-demand reconciliation,
  failure isolation, and cleanup.
- Import and menu-metadata registration open no config, socket, store, worker,
  source, or UI.
- A disabled feature entry is skipped before import and starts nothing.
- Enabled registration may load the existing private receiver and relay config
  contracts. Before an incoming worker starts, the enabled plugin creates and
  secures its configured relay-state parent as owner-only; no operator command
  is required during or after UI startup. Receiver or relay-state startup
  failure registers a visibly unavailable status surface instead of blocking
  BMO or another plugin.
- A healthy service starts exactly one owned receiver listener. Reconciliation
  starts only from an explicit UI action, permits at most one bounded job, uses
  a stable disposable source copy, and reuses Stage 6 idempotent protocol and
  state transitions.
- Cleanup invalidates callbacks, closes the active view, joins the
  reconciliation worker, stops the listener, closes the receiver store, and
  releases the port exactly once.

## UI and privacy contract

The Qt hosted view may show only service availability and aggregate durable
counts: received/pending events, completed/partial attachments, queue states,
and the latest bounded reconciliation report. It provides refresh, recent
window, and UTC calendar-month controls. Controls remain visibly unavailable
when the listener, relay configuration, or read-only source is unavailable.

The UI, logs, exceptions, and callbacks must not expose message text, handles,
chat IDs, GUIDs, ROWIDs, filenames, paths, attachment bytes/digests,
credentials, environment-variable values, or private configuration content.
Failures cross the boundary only as fixed error codes and safe status text.
The Stage 12 private feed is the sole content-bearing exception. Its periodic
status update does not replace an unchanged message model, and a user who has
scrolled away from the top retains that bounded position when the feed changes.

## Acceptance gate

Stage 10 implementation acceptance requires invented tests for resource-free
import/metadata, explicit enable/disable, healthy and degraded registration,
later-plugin isolation, receiver receipt/status updates, recent and month
reconciliation controls, duplicate job rejection, source/config failure,
content-free payloads, view close, registry shutdown, worker join, store close,
and port release. Qt/QML loading and action routing must pass offscreen.

The physical kiosk remains required for final touch/VNC, listener binding,
shutdown/restart, and long-running stability evidence. Stop before adding the
feature to defaults, installing a daemon, deploying, changing the phone access
policy, or proposing outbound Messages actions. Physical validation may create
only temporary mode-`0700` private configuration/state outside the repository,
mount the already authorized `/SMS` export read-only, and start BMO manually.

## Implemented surface and tests

- `bmo/features/imessage_relay/feature.py` owns resource-free settings, opt-in
  registration, degraded status, listener/store/thread lifecycle, aggregate
  status, and one on-demand recent/month reconciliation worker.
- `bmo/qt/views/imessage_relay.py` and
  `bmo/qt/qml/IMessageRelayView.qml` own the content-free hosted view and its
  refresh/reconciliation actions. The menu metadata references the existing
  protected `graphics/icons/message.png` asset; the graphic itself is not
  modified or copied.
- `tests/test_imessage_runtime.py` uses only temporary invented data and covers
  disabled/import/metadata behavior, registration isolation, healthy/degraded
  status, real loopback receipt, port release, recent/month repair,
  source/config failure, job exclusion, redaction, view actions, and cleanup.

## Physical acceptance record

Physical validation began on 2026-09-05 with new mode-`0700` kiosk work and
mount directories outside the repository. The retained restricted phone
snapshot mounted through SSHFS with read-only FUSE options. A 64-byte ephemeral
secret existed only in the operator shell; temporary mode-`0600` configuration
used an ephemeral `127.0.0.1` listener and private state paths.

A direct real-service lifecycle pass reported available, listening, and
reconciliation-capable with zero initial aggregate counts. Calling close twice
was safe, the receiver thread stopped, and rebinding the assigned port proved
release; exit status was zero. A subsequent recent-reconciliation worker pass
exited zero only after asserting that it started, completed within its bound,
and reached `complete`. Hidden before/after hashes proved the mounted source
trio unchanged, and both durable databases were mode `0600`. The operator paste
did not retain the content-free report mapping, so detailed reconciliation
counts remain unrecorded rather than being inferred; the subsequent visible UI
provided the required bounded reconciliation evidence.

The isolated production `typed_agent.py` path subsequently loaded on the
physical Qt display with exactly one relay menu item and no metadata failures.
The hosted view rendered the expected compact face, available/listening state,
aggregate counters, and reconciliation controls without private output. Its
Recent action completed and visibly reported `Checked 3; requeued 0`.

That run exposed one physical-only timing defect: Recent and Check Month stayed
disabled after completion until Refresh was pressed. The completion callback
runs before its worker thread returns, while `status()` had treated thread
liveness as the availability signal. `status()` now uses the locked
reconciliation state, so a completion callback sees controls available as soon
as state becomes complete; `_start_reconciliation()` still uses actual thread
liveness to reject overlapping jobs. A regression captures status inside the
callback. Local results are 1 focused test passed, all 13 runtime tests passed,
and all 113 relay tests plus 17 subtests passed.

The relay menu now references the existing protected
`graphics/icons/message.png` asset selected by the operator. A resource-free
metadata test fixes that path contract. Post-change verification passed the
focused metadata test, all 13 runtime tests, and all 113 relay tests plus 17
subtests; the image file itself was not modified. The physical Pi subsequently
confirmed the existing icon was readable and passed all 13 runtime tests in
1.06 seconds.

The updated physical UI then completed both Recent and Check Month actions.
After each action, both reconciliation controls returned to enabled without a
manual Refresh, clearing the completion-callback race regression. Across two
manual production-Qt launches, the listener and hosted view started normally,
the UI remained stable through consecutive bounded actions, and the final run
closed normally with exit status zero. Stage 10 was accepted on 2026-09-05.
