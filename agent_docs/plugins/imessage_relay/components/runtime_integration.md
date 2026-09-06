# BMO Runtime Integration

## Current boundary

The opt-in `bmo.features.imessage_relay` plugin currently owns only the kiosk
receiver, durable receipt/attachment store, and private Qt feed. The abandoned
Stage 12 SSHFS mount, kiosk-side Apple parser, continuous sender worker, and
local source reconciliation have been removed.

Import and menu metadata remain resource-free. A disabled, invalid, or missing
relay cannot block BMO or later plugins.

## Configuration

The feature entry accepts:

- `receiver_config_path`, defaulting to
  `config/imessage_receiver.json`; and
- `phone_control_config_path`, defaulting to
  `config/imessage_phone_control.json`; and
- `reconciliation_recent_days`, a validated phone-control bound from 1 through
  31.

Retired `source_config_path`, `relay_config_path`, and `messages_root` values
are ignored and do not open any resource. Operators should remove them from
private configuration during migration.

The receiver configuration continues to own bind address, port, durable state,
TLS, request limits, key ID, and private shared-secret source. Production LAN
binding requires TLS; plaintext remains limited to explicit loopback tests.

## Lifecycle

Enabled registration:

1. validates the private receiver configuration;
2. opens the private kiosk receipt store;
3. binds and starts one owned receiver thread; and
4. starts the independent phone-control coordinator when its private
   configuration is valid; and
5. exposes aggregate status plus the private newest-first incoming feed.

Failure registers a degraded relay surface without preventing BMO startup.
Cleanup closes the view, stops and joins the listener, closes the socket/store,
and releases the port exactly once.

The Stage 12 kiosk control coordinator is independently failure-isolated. It
sends an authenticated resume request when the receiver starts, uses a
content-free 60-second health probe to detect a later connectivity return, and
then sends resume as the sole retry-latch reset. It accepts one reconciliation
request at a time and schedules a bounded recent check weekly during a
long-running process. Cleanup joins the control worker and closes its transport.
It never reads Apple data or recreates the removed mount path.

Its private configuration path is `phone_control_config_path`, defaulting to
`config/imessage_phone_control.json`; the tracked shape is
`config/example.imessage_phone_control.json`. Missing or invalid control
configuration leaves the receiver and feed available while clearly disabling
phone control and reconciliation.

## UI

The relay view shows receiver availability, durable receipt/attachment counts,
and messages from the kiosk-owned receiver database. Its two-second refresh
reads local state only. The message model changes only when feed content changes
and preserves a non-top scroll position.

When phone control connects, incoming status reports the connection and both
bounded reconciliation controls are enabled. If the phone or its control
configuration is unavailable, the receiver and existing feed remain usable
and the controls clearly remain unavailable. No snapshot or mounted-source
status is exposed.

## Verification ownership

`tests/test_imessage_runtime.py` covers opt-in registration, resource-free
metadata, failure isolation, listener lifecycle, durable feed updates,
control-absent degradation, stable scrolling, view actions, and cleanup.
`tests/test_imessage_phone_control.py` owns strict configuration,
shared canonical/HMAC vectors, ACK handling, resume/probe scheduling,
single-flight reconciliation, and control cleanup. Receiver and attachment
protocol behavior remains owned by `tests/test_imessage_receiver.py` and
`tests/test_imessage_attachments.py`.
