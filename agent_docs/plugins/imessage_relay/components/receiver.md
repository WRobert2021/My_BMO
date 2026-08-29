# Kiosk Receiver Implementation

## Ownership and boundary

Stage 4 is implemented by the standalone standard-library `kiosk_receiver`
package. `config.py` owns exact private config validation and TLS/loopback
policy; `auth.py` owns HMAC signing/verification; `protocol.py` owns strict
wire serialization; `store.py` owns receipt/nonce SQLite; `server.py` owns the
transport-neutral application and HTTP(S) listener. Wire details live only in
`../api/receiver_protocol.md`.

The receiver does not read Apple data, contact an iPhone, consume the Stage 3
queue, register with BMO, install a daemon, or accept attachment bytes.

## Runtime and storage

`load_receiver_config` rejects symlink/non-file/oversized/duplicate/unknown or
mistyped config and loads the minimum-32-byte secret only from the configured
environment variable. TLS cert/key are paired; absent TLS is allowed only with
explicit loopback development. `build_server` loads TLS before binding, opens
the private store, constructs authenticator/application/server, and closes
partial resources on any failure.

`ReceiverStateStore` uses an `IMKR` application ID, schema version 1, WAL,
foreign keys, `synchronous=FULL`, a `0600` file, and locked transactions over
its shared connection. It stores canonical event JSON/digest keyed by stable
event ID and durable `(key_id, nonce)` replay records. Identical content returns
duplicate; conflict or storage error never ACKs. Status returns counts and last
receipt only.

Stage 6 adds a read-only, bounded receipt membership lookup. Under the same
store lock it classifies at most 20 sender-provided event ID/digest pairs as
`present`, `missing`, or `conflict` in request order. It never returns other
kiosk IDs and has no delete or overwrite path.

`ReceiverServer` is threaded, size/time bounded, rejects chunked/unsupported
bodies, suppresses content logging, and closes incomplete connections. The
standalone main loop runs until Ctrl-C, then closes socket and store. A future
runtime adapter must wrap the same ownership with plugin failure isolation; it
does not exist yet.

## Configuration and tests

Tracked schema: `config/example.imessage_receiver.json`; real config, state,
certificates, keys, and secret are private/ignored. Run:

```text
python -m kiosk_receiver.server --config config/imessage_receiver.json
```

only after deliberate local provisioning. Primary
`tests/test_imessage_receiver.py` covers schema/path stripping, HMAC and replay,
durable restart/idempotency/conflict, auth-first health/status, failure mapping,
config security, socket cleanup, real loopback HTTP, reconciliation membership
and bounds, kiosk-only preservation, and timeout.
