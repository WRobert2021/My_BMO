# Bounded Relay Reconciliation

## Status and boundary

Stage 6 is complete. `bmo.features.imessage_relay.relay.reconciliation` owns
explicit recent and UTC
calendar-month lookback windows, bounded source re-scan, authenticated receipt
membership requests, and selective resend decisions. It remains local
simulation code with no CLI, daemon, automatic schedule, BMO registration,
live-iPhone access, or attachment-byte transfer.

Import and construction acquire no socket, store, worker, or listener. The
caller explicitly supplies a `MessagesReader`, `RelayStateStore`, and Stage 5
transport and continues to own their lifecycle.

## Windowed source lookback

`ReconciliationWindow.recent(end_utc=..., days=...)` accepts one through 31
days. `calendar_month(year=..., month=...)` creates an exact half-open UTC month.
Both use integer Apple-epoch nanoseconds without float conversion.

`MessagesReader.scan_window()` applies the same read-only transaction and
normalization rules as the live cursor scan, but filters an explicit half-open
source-time window and paginates by source ROWID. `commit_reconciliation_batch()`
atomically inserts newly rediscovered events and issues without reading or
advancing `source_cursors`. Matching stable IDs are idempotent; conflicting
payloads roll back the page.

## Receipt membership and selective repair

The reconciler keyset-pages the durable relay queue and sends at most 20
path-free `(event_id, event_digest)` candidates per authenticated
`POST /v1/reconciliation`. The digest is the receiver's canonical wire-event
SHA-256, not the sender database digest that includes local fields.

The receiver classifies only the supplied candidates:

| Receipt | Sender action |
| --- | --- |
| `present` | Leave acknowledged entries unchanged; resolve an attempted pending/dead entry as acknowledged |
| `missing` | Requeue only an acknowledged entry; already queued/retrying/dead entries retain their current policy |
| `conflict` | Report the count and leave sender and receiver content unchanged |

New lookback discoveries are already queued and therefore need no additional
requeue transition. Repeating a reconciliation is idempotent: matching source
events are not copied and an already requeued missing receipt is not requeued
again.

Kiosk receipt lookup is read-only and order-preserving under the store lock. A
Stage 7 pending manifest is not a complete receipt and therefore classifies as
missing; because its sender event is not acknowledged, reconciliation does not
requeue or delete it. Lookup never enumerates kiosk-only IDs to the sender,
deletes a receipt, overwrites a conflict, or treats sender absence as deletion
authority.

## Bounds and failure behavior

The source scan, relay-state page, membership request, and response are all
bounded to at most 20 candidates at once. That limit keeps even maximum-length
escaped identifiers within the existing 64-KiB sender response cap. Memory is
therefore bounded independently of source, queue, or kiosk history size.

Authentication uses a fresh request ID and nonce over the exact reconciliation
path and body. A non-200 response, timeout, connection failure, malformed JSON,
unexpected media type, wrong request ID, missing/reordered receipt, or invalid
status fails closed. Validated earlier pages may already have made idempotent
repairs; rerunning the same window safely resumes the comparison.

## Stage 6 verification

`tests/test_imessage_reconciliation.py` and the reconciliation cases in the
parser/state/receiver suites cover recent and month windows, half-open and
read-only source paging, cursor preservation, rediscovery, idempotent reruns,
state keyset paging, worst-case wire bounds, HMAC application and real loopback
HTTP, present/missing/conflict classification, selective resend, response
mismatch, normal duplicate-safe delivery after repair, and preservation of an
invented kiosk-only receipt.

No test contacts an iPhone, uses private configuration, deploys a service, or
installs a daemon.
