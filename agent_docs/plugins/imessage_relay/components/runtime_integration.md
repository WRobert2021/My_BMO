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
TLS, request limits, key ID, and private shared-secret source. It also owns the
user-facing completed-media destinations. Their defaults are
`/home/pi-bmo/Pictures/bmo/messages`, `/home/pi-bmo/Music/bmo/messages`, and
`/home/pi-bmo/Videos/bmo/messages`; each may be overridden with the absolute
`photo_directory`, `audio_directory`, and `video_directory` fields. Production
LAN binding requires TLS; plaintext remains limited to explicit loopback tests.

## Lifecycle

Enabled registration:

1. validates the private receiver configuration;
2. opens the private kiosk receipt store;
3. binds and starts one owned receiver thread; and
4. starts the independent phone-control coordinator when its private
   configuration is valid; and
5. exposes aggregate status plus a bounded private incoming feed selected and
   rendered newest-first by Apple source time; and
6. lazily publishes completed attachment blobs into the configured user-facing
   media directories when they enter that feed.

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

## Notification count boundary

`bmo.features.imessage_relay.received_message_count()` opens the existing
receiver database read-only and returns the durable count of message events.
`new_message_count()` compares that total with a caller-owned checkpoint and
clamps database replacement/reset to zero. Reactions, duplicate requests, and
attachment-pending events do not inflate the count. This API starts no plugin
resource and owns no badge state; a future notification feature decides whether
and how to publish a typed runtime attention.

Its private configuration path is `phone_control_config_path`, defaulting to
`config/imessage_phone_control.json`; the tracked shape is
`config/example.imessage_phone_control.json`. Missing or invalid control
configuration leaves the receiver and feed available while clearly disabling
phone control and reconciliation.

## UI

The relay view is intentionally only a full-size incoming-message list. It does
not render aggregate counters, receiver prose, headings, or reconciliation
controls. A compact header dot is green only when both the kiosk receiver and
phone control connection are healthy; it is red otherwise. Reconciliation
remains an owned background/control capability even though it is absent from
this screen.

Messages are read from the kiosk-owned receiver database in Apple source-time
order. Receipt time is not used for display ordering because an offline backlog
may arrive within one receipt-clock tick. The two-second refresh reads local
state only. The message model changes only when feed content changes and
preserves a non-top scroll position.

Each completed attachment is rendered as an explicit open button. The Qt
adapter permits selecting only a current feed path that exists as a regular,
non-symlink file. Photos render in a contained detail view following the Album
presentation pattern. Video and audio use the version-matched Qt Multimedia
player within that same hosted view, with play, pause, restart, and back
controls. No desktop handler, VLC window, shell command, or second process is
started. An unavailable blob or media decode error is reported in the view
without affecting receiver lifecycle, and closing the attachment or hosted
view stops playback.

Reaction receipts are not rendered as separate messages. Both incoming and
outgoing reactions are folded into their incoming target message. Each target
part and sender has one reaction slot: its newest addition replaces the prior
kind, while its newest removal clears the slot even when Apple supplies no
reference to an earlier addition.
Active reactions are aggregated into compact badges on the target message, and
a removal makes the corresponding badge disappear on the next local refresh.
Reaction state is resolved before messages are rendered, so Apple timestamp or
receipt ordering cannot suppress a valid badge.
Reaction badges use plugin-owned SVG icons rather than platform emoji fonts, so
heart, thumb, laugh, emphasize, and question artwork renders consistently on
the kiosk. Only an optional aggregate count uses text.
The Qt adapter converts feed tuples to native variant lists before QML receives
them; nested attachment and reaction models must never cross as opaque Python
objects.

If the phone or its control configuration is unavailable, the receiver and
existing feed remain usable and the header dot turns red. No snapshot or
mounted-source status is exposed.

## Verification ownership

`tests/test_imessage_runtime.py` covers opt-in registration, resource-free
metadata, failure isolation, listener lifecycle, durable feed updates,
reaction badge folding/removal, control-absent degradation, stable scrolling,
compact view structure, validated in-app attachment selection, and cleanup.
`tests/test_imessage_media_library.py` owns completed-media routing,
deterministic publication, Live Photo component separation, and unavailable
blob behavior.
`tests/test_imessage_phone_control.py` owns strict configuration,
shared canonical/HMAC vectors, ACK handling, resume/probe scheduling,
single-flight reconciliation, and control cleanup. Receiver and attachment
protocol behavior remains owned by `tests/test_imessage_receiver.py` and
`tests/test_imessage_attachments.py`. `tests/test_imessage_notifications.py`
owns read-only count/delta semantics and failure behavior.
