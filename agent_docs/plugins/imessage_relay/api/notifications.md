# Notification Count API

Owner: `bmo.features.imessage_relay.notifications`

This public API lets a future kiosk notification script inspect the durable
incoming-message total without starting the relay plugin or mutating its
receiver database:

```python
from bmo.features.imessage_relay import new_message_count, received_message_count

total = received_message_count(receiver_database_path)
badge_count = new_message_count(receiver_database_path, previous_total)
```

`received_message_count()` counts unique, durably acknowledged rows whose event
kind is `message`. Reactions do not increment it, duplicate delivery cannot
increment it, and attachment-pending events are excluded until their final
event commit. The database must already exist, have the current receiver
application/schema identifiers, be a regular non-symlink file, and have no
group/other permission bits. It is opened with SQLite `mode=ro` and
`query_only`; live WAL commits remain visible.

`new_message_count()` returns `max(0, current_total - previous_total)`. The
notification script owns and persists `previous_total`; when the result is
zero it should show no badge. A receiver-database replacement that lowers the
total also returns zero instead of producing a false badge. Invalid checkpoints
raise `ValueError`; unavailable or unsafe state raises
`NotificationCountError`.

This API does not publish a core runtime attention. If the later notification
feature adopts typed persistent attentions, that feature owns the checkpoint,
attention identity, acknowledgement, and badge lifecycle while continuing to
use this query-only relay boundary.
