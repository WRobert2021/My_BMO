# Simulated Relay Sender

## Status and boundary

Stages 5 and 7 are complete. `iphone_relay.sender` connects Stage 3 queue claims
to event delivery and bounded attachment transfer. It uses only the Python
standard library and has no deployment, daemon, automatic startup, or BMO
registration. Stage 6 reconciliation remains a separate module that reuses its
bounded transport. Stage 9 may compose the sender only through the explicit
manual acceptance runner and the authorized read-only source topology.

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

For an event with attachments, sender acknowledgement additionally requires
`attachment_status: complete`. A `202 attachments_pending` response starts or
resumes one upload session per ordinary attachment or Live Photo component.
Each source is opened read-only as a regular non-symlink file, checked against
its persisted size, hashed in 64-KiB reads, and sent in at-most-64-KiB chunks.
The sender validates every session/upload/request identity and next offset, then
repeats the event for final promotion. It rejects legacy metadata-only ACKs,
missing/unsafe/changed sources, and any malformed or mismatched partial result.

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

Stage 6 permits the same transport to send fixed event and reconciliation
paths. Stage 7 adds the fixed attachment-session path and strictly generated,
HMAC-bound chunk paths. Each HTTP request holds at most one 64-KiB chunk; no
whole attachment body is buffered by the transport.

Construction opens no socket. Importing the module starts no worker, listener,
store, or loop. Stage 5 deliberately has no sender configuration file or
standalone process entrypoint; production endpoint trust and private secret
provisioning remain later live-stage decisions.

Stage 9 adds `scripts/run_imessage_live_delivery.py` as a bounded manual
acceptance entrypoint. It constructs an ephemeral in-memory HMAC secret and a
literal-loopback receiver, retains durable state only in an operator-supplied
private directory outside the repository, and injects expected retry cases.
It does not change the sender's lifecycle or authorize unattended execution.

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

## Stage 7 verification

`tests/test_imessage_attachments.py` covers ordinary and Live Photo component
transfer, source hash preservation, hard size/chunk bounds, partial restart
resume, lost chunk responses, digest failure, unavailable sources,
metadata-only ACK rejection, transport-neutral application calls, real
loopback HTTP, and sender/receiver cleanup.

## Stage 9 verification

`tests/test_imessage_live_delivery.py` covers stable disposable snapshots,
private-state enforcement, authentication/receiver/lost-ACK fault injection,
sender and receiver restart, real attachment completion, exactly-once receiver
receipt, subsequent discovery, content-free output, and direct CLI startup.
