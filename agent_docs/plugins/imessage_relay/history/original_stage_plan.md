# Archived iMessage Relay Staged Development Plan

> Preserved detailed stage specification. Current stage/status is owned solely
> by `../progress.md`; current future-stage routing is distilled in
> `../roadmap.md`.

## Purpose and boundaries

This plan governs the incremental development of a read-only iMessage relay
from a jailbroken iPhone to the Raspberry Pi kiosk. Message content moves only
from the iPhone to the kiosk. Acknowledgements, health checks, synchronization
requests, and kiosk-online notifications may move in either direction.

The initial content scope is incoming iMessage text, photos, videos, and
tapbacks. SMS/MMS is out of scope except for the filtering needed to exclude
it. Sending through Messages is out of scope. Apple's Messages database and
attachment tree are external, strictly read-only sources. Relay checkpoints,
queues, delivery state, and kiosk records must live in relay-owned storage.

Every stage below is a separate authorization boundary. At the end of a stage,
update `AGENT_README.md`, report the results, and stop. Do not begin the next
stage until the user explicitly requests it.

## Proposed ownership and layout

The expected layout is provisional until the relevant stage validates it:

```text
docs/
  IMESSAGE_RELAY_PLAN.md       # this staged plan
  SCHEMA_REPORT.md             # created and completed in Stage 1
  IMESSAGE_RELAY_PROTOCOL.md   # created when protocol design begins
  issues/                      # detailed issue records when needed
iphone_relay/                  # iPhone-side reader, normalization, state, transport
kiosk_receiver/                # kiosk ingestion, persistence, reconciliation, status
tests/                         # focused relay tests and sanitized fixtures
iphone_snapshot/               # ignored, private reference input; never implementation
```

The relay should remain a separately owned subsystem while its backend is
developed. If Stage 10 connects it to the existing kiosk application, the UI
adapter must follow `docs/AGENT_ARCHITECTURE.md`: registration, configuration,
failure handling, cleanup, and tests stay inside the relay feature boundary;
the core app must still start when the relay is disabled or unavailable.

## Global verification rules

- Never use live Messages data as a writable test target.
- Open source databases with an explicit read-only URI and `PRAGMA query_only`;
  perform exploratory SQLite work on a disposable copy of the complete
  `sms.db`/WAL/SHM trio because SQLite may update SHM lock-state bytes even for
  a read-only connection.
- Do not log or document message bodies, addresses, attachment names, or other
  private content. Sanitized fixtures must contain invented data.
- Preserve discovery, queueing, transmission, and acknowledgement as distinct
  states. Network transmission alone never means delivery.
- Add failure-path tests with every behavioral stage and run the full project
  suite after code changes.
- Keep Python dependencies minimal and compatible with Python 3.13 on
  Raspberry Pi OS aarch64. Apply the repository dependency policy before
  adding any package.

## Stage 0 — Project Audit and Snapshot Validation

**Objective:** Establish a safe starting point, verify inputs and tooling, and
leave durable documentation without implementing relay behavior.

**Inputs:** Repository guidance and documentation; local
`iphone_snapshot/SMS/` database trio and attachment tree; local Python and
SQLite tooling.

**Implementation scope:** Inventory the repository, verify required paths and
read permissions, run a non-content SQLite integrity check, protect the private
snapshot from accidental Git inclusion, create the relay plan and continuation
record, update the operator README, and record blockers and unknowns. Do not
inspect the application schema, implement code, contact the iPhone, or deploy.

**Tests/checks:** Required file and permission checks; attachment aggregate and
MIME check; SQLite WAL-mode and `quick_check`; source fingerprints around the
check; documentation link and Git diff review.

**Completion criteria:** Required snapshot inputs are accessible; database
integrity is sufficient to begin investigation; the complete plan, status
record, issues, and exact Stage 1 checklist are persisted.

**Expected artifacts:** `AGENT_README.md`, this plan,
`docs/issues/README.md`, an operator README update, and an ignore rule for the
private snapshot.

**Known risks:** Snapshot provenance and iOS build are not yet known; a small
sample may not contain every event type; SQLite SHM files are mutable lock
coordination artifacts.

**STOP POINT:** Stage 0 documentation and validation only. Stage 1 requires a
new explicit instruction.

## Stage 1 — Messages Schema Investigation

**Objective:** Derive the relevant Messages schema and a safe incremental read
strategy primarily from the supplied snapshot.

**Inputs:** A disposable copy of the complete snapshot database trio and the
attachment tree; the Stage 1 inspection checklist in `AGENT_README.md`.

**Implementation scope:** Inspect SQLite metadata and narrowly query relevant
rows to document incoming/outgoing and iMessage/SMS distinctions, handles,
chats and participants, timestamps, text and `attributedBody`, attachments,
tapbacks, stable identifiers, edits, and incremental scan behavior. Create
small read-only exploratory queries where they improve repeatability. Do not
create the production parser or contact the live iPhone.

**Tests/checks:** Re-run integrity on a disposable trio; prove all report claims
with aggregate/redacted queries; validate timestamp conversions against
multiple non-private values; verify query plans/index availability where
incremental scanning is proposed; fingerprint the original snapshot before and
after inspection.

**Completion criteria:** `docs/SCHEMA_REPORT.md` answers every item required by
the specification, distinguishes facts from hypotheses, identifies evidence
gaps, and recommends an explicitly read-only incremental query and external ID.

**Expected artifacts:** `docs/SCHEMA_REPORT.md`; optional exploratory SQL or
tests that reveal no private values; updated `AGENT_README.md`.

**Known risks:** The snapshot may lack videos, tapbacks, edits, group chats, or
other variants. Apple schema fields may be version-specific. Archived objects
inside `attributedBody` require defensive decoding and must not be treated as a
safe generic object-deserialization input.

**STOP POINT:** Stop after the report and its validation. Do not implement the
parser.

## Stage 2 — Read-Only Message Parser

**Status:** Complete on 2026-08-28. The implementation and evidence are
recorded in `docs/IMESSAGE_PARSER.md`; Stage 3 remains separately authorized.

**Objective:** Normalize supported iMessage records from local reference data.

**Inputs:** Approved schema report, snapshot, and sanitized fixtures for cases
not safely represented by the snapshot.

**Implementation scope:** Implement an explicitly read-only database boundary,
incoming-iMessage selection, sender/chat normalization, plain and attributed
text extraction, attachment discovery, and tapback normalization. Exclude
unsupported SMS/MMS. No networking, queue, or live-iPhone deployment.

**Tests/checks:** Incoming text; outgoing categorization; SMS exclusion;
one-to-one and group identity; empty `text` with `attributedBody`; photo/video
metadata; reaction add/remove/target; malformed records; duplicate scan;
read-only enforcement; provider-present/unavailable cases for any optional
decoder.

**Completion criteria:** Parser returns versioned normalized events for every
supported fixture without modifying the source, and failures are isolated and
diagnostic without exposing message content.

**Expected artifacts:** `iphone_relay` reader/parser modules, sanitized test
fixtures, parser tests, documentation updates.

**Known risks:** Unsafe or incomplete attributed-body decoding; attachment path
differences between snapshot and phone; schema variants absent from samples.

**STOP POINT:** Stop when local parser tests and the full suite pass.

## Stage 3 — Relay State and Durable Queue

**Status:** Complete on 2026-08-28. The implementation, state machine, schema,
and evidence are recorded in `docs/IMESSAGE_STATE.md`; Stage 4 remains
separately authorized.

**Objective:** Persist discovery and at-least-once delivery state independently
from Apple's database.

**Inputs:** Normalized event contract and identifier/checkpoint decisions from
Stages 1–2.

**Implementation scope:** Design and implement relay-owned SQLite state for
discovered, queued, attempted, acknowledged, and dead-letter events; separate
the discovery high-water mark from delivery state; add bounded backoff,
attempt/error metadata, restart recovery, and idempotent transitions. Decide
and document whether payloads are persisted or regenerated.

**Tests/checks:** Crash/restart at every transition; duplicate discovery and
ACK; lost ACK; retry timing; permanently bad record; checkpoint cannot skip an
unqueued event; schema migration/invalid state; clean close.

**Completion criteria:** No discovered event can be lost because delivery is
unacknowledged, retries survive restart, and poison items become visible
dead-letter records without blocking the queue forever.

**Expected artifacts:** Relay state schema/manager, retry policy configuration,
reliability tests, state documentation.

**Known risks:** Transaction boundaries between source discovery and queue
commit; payload availability if Apple later removes a source record; storage
growth and retry starvation.

**STOP POINT:** Stop after local reliability tests pass; no network service.

## Stage 4 — Kiosk Receiver Prototype

**Status:** In Progress — explicitly authorized on 2026-08-28. Work is limited
to the local kiosk receiver and protocol tests; Stage 5 sender integration has
not started.

**Objective:** Provide authenticated, durable, idempotent kiosk ingestion with
explicit ACK/NACK semantics.

**Inputs:** Normalized event and queue contracts; a documented comparison of
HTTPS request/response and persistent WebSocket transports.

**Implementation scope:** Select the simplest reliable transport; define
versioned JSON control schemas and binary attachment boundaries; implement
mutual request authentication appropriate to a private LAN, replay controls,
durable kiosk storage, duplicate-safe ingestion, health/status, and explicit
ACK/NACK. Use example configuration only; never commit secrets.

**Tests/checks:** Valid/invalid schema, duplicate transmission, duplicate ACK,
authentication/replay failure, malformed request, durable restart, negative
acknowledgement, timeouts, and disabled/unavailable service behavior.

**Completion criteria:** A locally running receiver durably commits once and
ACKs by stable event ID only after successful processing; unknown clients and
malformed data are rejected safely.

**Expected artifacts:** `docs/IMESSAGE_RELAY_PROTOCOL.md`, receiver service and
storage, example configuration, protocol and persistence tests.

**Known risks:** TLS and key provisioning on the jailbroken phone; dependency
availability on iPhone Python and Pi aarch64; replay-window clock skew.

**STOP POINT:** Stop after protocol tests pass; do not connect to the iPhone.

## Stage 5 — End-to-End Simulated Relay

**Objective:** Prove the parser, queue, sender, and receiver reliability model
locally under failure.

**Inputs:** Stages 2–4 components and controlled local fault injection.

**Implementation scope:** Connect only local simulations; implement sender
control flow, ACK validation, online/offline transitions, backlog draining,
bounded backoff, and machine-readable relay status.

**Tests/checks:** Offline before/during delivery; dropped connection; lost ACK;
duplicate send; malformed/negative response; iPhone-side and kiosk-side
restart; ordered backlog; poison event; connectivity recovery; graceful
SIGINT and resource cleanup.

**Completion criteria:** At-least-once delivery and kiosk idempotency hold
across faults; pending state survives restarts; one bad event cannot silently
disappear or permanently block later work.

**Expected artifacts:** Simulated sender, fault harness, end-to-end tests,
status contract, operational logging without content.

**Known risks:** Simulation may miss iOS filesystem and networking behavior;
ordering and dead-letter policy may need tuning.

**STOP POINT:** Stop after the simulated acceptance matrix passes.

## Stage 6 — Reconciliation

**Objective:** Detect and selectively repair recent or month-bounded kiosk
gaps without deleting extra kiosk history.

**Inputs:** Stable event IDs, durable stores, authenticated protocol, and
normalized manifest metadata.

**Implementation scope:** Implement configurable short windows (time and/or
count), month/range queries, paginated manifests, kiosk missing-ID comparison,
selective resend, progress/status, and bounded memory use. Reuse normal
idempotent ingestion and ACK paths.

**Tests/checks:** Last three days/30 records; boundary timestamps; pagination;
month selection; kiosk missing/extra events; duplicates; restart mid-query;
large manifests; attachment metadata without payload transfer.

**Completion criteria:** Both reconciliation modes transfer only missing
events, never delete kiosk-only history, and resume or fail visibly without
unbounded memory use.

**Expected artifacts:** Manifest protocol additions, reconciliation services,
tests, status documentation.

**Known risks:** Edited events and reaction targets outside the window;
identifier changes; concurrent new-message delivery during reconciliation.

**STOP POINT:** Stop after bounded reconciliation tests pass.

## Stage 7 — Attachments

**Objective:** Reliably deliver photos and videos without whole-file memory
loading and with unambiguous completion semantics.

**Inputs:** Attachment metadata from parser, authenticated protocol, kiosk
storage, and reconciliation flow.

**Implementation scope:** Resolve and contain source paths, stream binary data
separately from JSON control messages, validate declared size/type and digest,
persist partial/completed attachment state, and define whether an event ACK
requires all mandatory attachments. Support retries and missing/corrupt files.

**Tests/checks:** Photo/video streams; large-file bounded memory; interrupted
transfer and resume/retry; duplicate attachment; wrong size/digest/MIME;
missing source; partial event; path traversal/symlink containment; restart.

**Completion criteria:** Required attachment receipt is durable and verified
before complete event ACK, or partial status is explicitly represented; retry
cannot duplicate kiosk media.

**Expected artifacts:** Streaming endpoints/client, attachment state and tests,
protocol and operational documentation.

**Known risks:** iOS attachment path aliases and permissions; large video disk
pressure; Live Photo/multi-part representations outside initial scope.

**STOP POINT:** Stop after attachment reliability and memory checks pass.

## Stage 8 — Live iPhone Read-Only Integration

**Objective:** Validate source discovery on the actual jailbroken iPhone while
preserving strict read-only behavior.

**Inputs:** User-authorized phone access, manually invoked relay, Stage 2
reader, documented deployment and rollback steps.

**Implementation scope:** Verify exact iOS/Python/SQLite environment and file
permissions; deploy only the necessary reader/relay files; open
`/var/mobile/Library/SMS/sms.db` explicitly read-only; initially inspect
discovery diagnostics without sending; verify attachment path resolution and
graceful SIGINT. Do not install a daemon.

**Tests/checks:** Before/after database/WAL observations where safe; read-only
failure proof; incoming/outgoing/iMessage filtering; new row discovery;
permission errors; process restart; zero Messages-state changes.

**Completion criteria:** Live discovery works from the correct path, produces
only non-content diagnostics, survives errors, and has evidence of no Apple
database or attachment mutation.

**Expected artifacts:** Environment/compatibility report, manual start/stop
instructions, live read-only acceptance record, issue updates.

**Known risks:** SQLite WAL/SHM lock behavior, jailbreak path/entitlement
differences, Python package availability, schema differences from snapshot.

**STOP POINT:** Stop after read-only validation; do not enable live delivery.

## Stage 9 — Live iPhone-to-Kiosk Relay

**Objective:** Validate authenticated, at-least-once delivery on the real phone
and Raspberry Pi.

**Inputs:** Accepted Stage 8 reader, staged kiosk receiver, private local
configuration, and a written acceptance checklist.

**Implementation scope:** Manually start both sides and test text, reactions,
photos, videos, offline recovery, lost ACK, duplicate prevention, backlog, and
manual restarts. Keep startup manual and secrets outside source control.

**Tests/checks:** Full live acceptance matrix with IDs/metadata only in logs;
network interruption; kiosk restart; relay restart; authentication failure;
backlog completion; clean shutdown; no database writes.

**Completion criteria:** Each supported event is durably present once on the
kiosk after ACK; failure recovery is documented; the source remains unchanged;
all serious issues are resolved or explicitly blocking.

**Expected artifacts:** Acceptance report, deployment/runbook updates,
compatibility evidence, current issue log.

**Known risks:** LAN variability, device sleep/respring, attachment throughput,
and real-world schema variants.

**STOP POINT:** Stop after documented live acceptance. Do not install automatic
startup.

## Stage 10 — Kiosk UI and Operational Polish

**Objective:** Expose useful relay health and user-triggered reconciliation in
the existing kiosk without coupling core startup to the relay.

**Inputs:** Stable backend status/reconciliation contracts and the existing
feature/QML extension architecture.

**Implementation scope:** Add a narrowly owned optional relay feature and QML
adapter showing connection state, last contact/ACK, pending/dead-letter counts,
backlog progress, and short/month reconciliation controls. Keep backend status
machine-readable and available without UI. Do not expand into message sending
or unrelated features.

**Tests/checks:** Enabled/disabled/unavailable backend; clean app startup;
status transitions; stale action rejection; reconciliation controls; worker
cleanup; Qt/QML smoke tests; full suite and physical 800x480 verification.

**Completion criteria:** Operators can understand relay health and initiate
bounded reconciliation; disabling or failing the relay cannot break other
features or application startup.

**Expected artifacts:** Feature registration/configuration, UI adapter/QML,
operator documentation, tests and manual acceptance notes.

**Known risks:** Cross-thread status updates, UI overload, and optional backend
lifecycle coupling.

**STOP POINT:** Stop after backend and physical UI acceptance. Any daemon or
message-sending proposal is a separate future scope.
