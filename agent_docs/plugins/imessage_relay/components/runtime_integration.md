# Runtime Integration

## Stage and boundary

Stage 10 integrates iMessage Relay as an explicitly configured BMO
feature/service. It is not a default feature, launch daemon, independent
service installation, phone deployment, or authorization to send through
Messages. Stage 9's physical-Pi live-delivery gate remains separately pending.

Development while the kiosk is offline uses only invented local data and the
repository virtual environment. It must not contact the phone or kiosk.

## Ownership and lifecycle

- `bmo.features.imessage_relay` owns feature configuration, registration,
  listener/thread lifetime, content-free status, on-demand reconciliation,
  failure isolation, and cleanup.
- Import and menu-metadata registration open no config, socket, store, worker,
  source, or UI.
- A disabled feature entry is skipped before import and starts nothing.
- Enabled registration may load the existing private receiver and relay config
  contracts. Receiver startup failure registers a visibly unavailable status
  surface instead of blocking BMO or another plugin.
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

## Acceptance gate

Stage 10 implementation acceptance requires invented tests for resource-free
import/metadata, explicit enable/disable, healthy and degraded registration,
later-plugin isolation, receiver receipt/status updates, recent and month
reconciliation controls, duplicate job rejection, source/config failure,
content-free payloads, view close, registry shutdown, worker join, store close,
and port release. Qt/QML loading and action routing must pass offscreen.

The physical kiosk remains required for final touch/VNC, listener binding,
shutdown/restart, and long-running stability evidence. Stop before adding the
feature to defaults, editing private configuration, installing a daemon,
deploying, contacting the phone, or proposing outbound Messages actions.

## Implemented surface and tests

- `bmo/features/imessage_relay/feature.py` owns resource-free settings, opt-in
  registration, degraded status, listener/store/thread lifecycle, aggregate
  status, and one on-demand recent/month reconciliation worker.
- `bmo/qt/views/imessage_relay.py` and
  `bmo/qt/qml/IMessageRelayView.qml` own the content-free hosted view and its
  refresh/reconciliation actions. The existing micro-SD menu icon is reused;
  no protected graphics were changed.
- `tests/test_imessage_runtime.py` uses only temporary invented data and covers
  disabled/import/metadata behavior, registration isolation, healthy/degraded
  status, real loopback receipt, port release, recent/month repair,
  source/config failure, job exclusion, redaction, view actions, and cleanup.
