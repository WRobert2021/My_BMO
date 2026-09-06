# BMO Runtime Integration

## Current boundary

The opt-in `bmo.features.imessage_relay` plugin currently owns only the kiosk
receiver, durable receipt/attachment store, and private Qt feed. The abandoned
Stage 12 SSHFS mount, kiosk-side Apple parser, continuous sender worker, and
local source reconciliation have been removed.

Import and menu metadata remain resource-free. A disabled, invalid, or missing
relay cannot block BMO or later plugins.

## Configuration

The feature entry currently accepts:

- `receiver_config_path`, defaulting to
  `config/imessage_receiver.json`; and
- `reconciliation_recent_days`, retained as a validated future phone-control
  bound from 1 through 31.

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
4. exposes aggregate status plus the private newest-first incoming feed.

Failure registers a degraded relay surface without preventing BMO startup.
Cleanup closes the view, stops and joins the listener, closes the socket/store,
and releases the port exactly once.

The future Stage 12 kiosk control client will be independently failure-isolated.
It will send an authenticated resume request when the receiver starts or kiosk
networking returns and will schedule bounded reconciliation once or twice
weekly. It must never read Apple data or recreate the removed mount path.

## UI

The relay view shows receiver availability, durable receipt/attachment counts,
and messages from the kiosk-owned receiver database. Its two-second refresh
reads local state only. The message model changes only when feed content changes
and preserves a non-top scroll position.

Until phone control is implemented, incoming status reads "Kiosk receiver is
ready for the phone relay," while Recent and Check Month remain disabled with
an explicit pending-Stage-12 explanation. No snapshot or mounted-source status
is exposed.

## Verification ownership

`tests/test_imessage_runtime.py` covers opt-in registration, resource-free
metadata, failure isolation, listener lifecycle, durable feed updates,
interim reconciliation unavailability, stable scrolling, view actions, and
cleanup. Receiver and attachment protocol behavior remains owned by
`tests/test_imessage_receiver.py` and `tests/test_imessage_attachments.py`.
