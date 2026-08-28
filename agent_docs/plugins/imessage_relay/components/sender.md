# Simulated Relay Sender

## Status and boundary

Stage 5 is complete. `iphone_relay.sender` connects Stage 3 queue claims to the
fixed Stage 4 receiver protocol for local simulation. It uses only the Python
standard library, does not read Apple data itself, and has no CLI, deployment,
daemon, automatic startup, BMO registration, reconciliation, or attachment-byte
transfer. Live-iPhone access remains prohibited until Stage 8.

The sender module is imported explicitly as `iphone_relay.sender`; it is not
re-exported by `iphone_relay.__init__` because the kiosk protocol already
depends on the normalized `iphone_relay` contracts. Keeping the import explicit
avoids a package initialization cycle while both standalone packages remain
owned by this plugin.

## Delivery contract

`RelaySender.deliver_once()` claims the oldest eligible `RelayStateStore`
entry, builds the path-free version-one event envelope, creates a fresh request
ID and nonce, signs the exact bytes, and performs one transport attempt. It
acknowledges the durable sender queue only when all of these checks pass:

- response media type is JSON and the bounded body uses strict JSON that
  rejects duplicate keys;
- protocol version, HTTP status, ACK status, request ID, and stable event ID
  are the exact expected values; and
- `201 accepted` or `200 duplicate` is returned.

Every timeout, connection failure, NACK, malformed response, or mismatched ACK
is recorded through the existing bounded retry/dead-letter transitions. The
sender preserves recognized receiver codes, including the distinct
`stale_request`; unknown safe NACKs become `receiver_nack`. It never persists
exception text or response content. A lost ACK retries the identical canonical
event with fresh request authentication, allowing the receiver's stable-ID
idempotency to return a duplicate ACK.

`SenderStatus` contains queue and attempt counts plus one bounded error code.
It excludes event IDs, handles, chats, message text, paths, and response bodies.
The manual `run_forever()` loop emits this content-free status through an
optional callback, idles with a bounded poll interval, catches Ctrl-C, and
closes its transport in all exit paths. The caller continues to own and close
the relay store.

## Transport and lifecycle

`HTTPEventTransport` opens one standard-library HTTP(S) connection per attempt
and closes it after the bounded response. HTTPS is accepted for configured
origins; plaintext HTTP fails closed unless explicitly enabled for a literal
loopback simulation endpoint. Credentials in URLs, paths, query strings, and
fragments are rejected. The transport has bounded connect/read time and a
64-KiB response limit, and `close()` is idempotent.

Construction opens no socket. Importing the module starts no worker, listener,
store, or loop. Stage 5 deliberately has no sender configuration file or
standalone process entrypoint; production endpoint trust and private secret
provisioning remain later live-stage decisions.

## Stage 5 verification

`tests/test_imessage_relay_e2e.py` uses invented temporary data and covers the
actual parser-to-queue-to-loopback-HTTP-to-durable-receiver chain, source hash
preservation, path stripping, offline-before-send and connection-loss faults,
lost ACK and duplicate receipt, fresh authentication, sender and receiver
restart, strict ACK validation, distinct NACKs, ordered backlog, poison-event
bypass/dead-letter/requeue recovery, content-free status, Ctrl-C, and sender,
server, thread, store, and connection cleanup.

No test contacts an iPhone, uses a private configuration, deploys a service, or
installs a daemon.
