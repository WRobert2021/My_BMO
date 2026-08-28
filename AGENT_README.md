# iMessage Relay Agent Continuation Record

## Project Objective

Build an incremental, read-only relay for incoming iMessage text, photos,
videos, and tapbacks from a Dopamine/rootless jailbroken iPhone to the Be More
Agent Raspberry Pi kiosk. Delivery must be at least once with explicit kiosk
acknowledgements and idempotent kiosk ingestion. Control traffic may be
bidirectional; message content is iPhone-to-kiosk only.

## Environment

- Repository: existing Be More Agent Qt/QML kiosk application.
- Development host observed 2026-08-28: macOS workspace, project `.venv`
  running Python 3.13.12, SQLite CLI 3.43.2.
- Primary deployment target: Raspberry Pi 5, 16 GB RAM, 64-bit Raspberry Pi OS,
  Python 3.13.5 per repository policy.
- iPhone: Dopamine/rootless jailbreak; SSH/SFTP/SCP account `mobile`; Python 3
  installed through Sileo, exact version and packages not yet verified.
- Jailbreak home: `/var/jb/var/mobile`; this is not the Messages store.
- Live Messages root, not accessed: `/var/mobile/Library/SMS`.
- Reference snapshots are private, untracked, and ignored:
  `iphone_snapshot_stage0/` is the Stage 0 baseline and `iphone_snapshot/` is
  the primary controlled-test corpus for Stage 1.
- Both DB/WAL/SHM trios are readable and pass logical `quick_check` from
  disposable copies. The baseline has 6 logical messages and 1 attachment;
  the controlled snapshot has 36 logical messages, 4 attachment rows, and 8
  attachment-tree files covering JPEG, QuickTime video, and a Live Photo
  bundle. No private values were copied into tracked artifacts.

## Safety Constraints

- Apple's live Messages database, WAL/SHM, attachments, metadata, and chat
  state are strictly read-only external data.
- Never insert, update, delete, change read state or reactions, send a message,
  or invoke an API that changes Messages state.
- Keep relay queues, checkpoints, retries, ACKs, errors, and kiosk records in
  separate relay-owned storage.
- Never treat network transmission alone as delivery; only a validated kiosk
  ACK after durable processing completes delivery.
- Do not install a launch daemon. Initial iPhone operation remains manual and
  must support graceful Ctrl-C shutdown.
- Do not connect to or deploy onto the live iPhone before its authorized stage.
- Do not commit the private snapshot, credentials, message contents, handles,
  or attachment data. Operational logs must omit content by default.

## Current Stage

**Current Stage: Stage 2 — Read-Only Message Parser (Complete).**

Stages 0–2 are complete. Stage 2 was explicitly authorized and completed on
2026-08-28. This is the required stop point; Stage 3 has not started and needs
new explicit authorization.

## Stage Status

| Stage | Status | Result / gate |
| --- | --- | --- |
| 0 — Project Audit and Snapshot Validation | Complete | Inputs, tooling, safety boundary, documentation, and next inspection checklist recorded. |
| 1 — Messages Schema Investigation | Complete | `docs/SCHEMA_REPORT.md` records supported behavior, Stage 2 contracts, and explicit evidence gaps. |
| 2 — Read-Only Message Parser | Complete | Stateless read-only parser, immutable event contracts, sanitized tests, and controlled-snapshot acceptance pass. |
| 3 — Relay State and Durable Queue | Not Started | Ready only after new explicit authorization. |
| 4 — Kiosk Receiver Prototype | Not Started | Blocked by event contract and protocol design. |
| 5 — End-to-End Simulated Relay | Not Started | Blocked by Stages 2–4. |
| 6 — Reconciliation | Not Started | Blocked by simulated reliability acceptance. |
| 7 — Attachments | Not Started | Blocked by manifest/protocol foundations. |
| 8 — Live iPhone Read-Only Integration | Not Started | Requires explicit authorization and prior local acceptance. |
| 9 — Live iPhone-to-Kiosk Relay | Not Started | Blocked by live read-only acceptance. |
| 10 — Kiosk UI / Operational Polish | Not Started | Blocked by stable backend contracts. |

## Work Completed

- Completed Stage 2 after explicit authorization and stopped before Stage 3.
- Added the independent `iphone_relay` package without registering it in or
  coupling it to the kiosk runtime. It has no new third-party dependency.
- Added immutable, versioned message, reaction, sender, attachment, issue, and
  scan-batch contracts. GUIDs remain external IDs and ROWIDs remain source
  cursors only.
- Implemented a mandatory SQLite `mode=ro` plus `query_only` boundary, schema
  validation, a single read transaction per scan, ascending bounded batches,
  positive iMessage service filtering, and contained per-record diagnostics.
- Implemented incoming sender, local-self reaction actor, chat, service-scoped
  participant, exact Apple timestamp, ordinary text, bounded typedstream
  fallback, and attachment normalization.
- Implemented exact attachment-prefix resolution, traversal and symlink
  containment, explicit missing/unsafe availability, declared-versus-actual
  size preservation, photo/video classification, and the demonstrated single
  DB-row Live Photo with deterministic still/motion components.
- Implemented all six observed standard reaction additions, the demonstrated
  3001 Thumbs Up removal, preserved unknown reaction-range values, and
  validated `p:<part>/<GUID>` target extraction.
- Preserved Stage 1 evidence gaps: emoji reaction rows remain ordinary text;
  retraction/edit events are not invented; real group/email/SMS variants and
  live schema behavior remain explicitly unverified.
- Added fully invented temporary SQLite fixtures plus optional ignored-snapshot
  acceptance. No private content or attachment bytes entered tracked files.
- Documented the public parser API, cursor boundary, privacy behavior, and
  exact unsupported cases in `docs/IMESSAGE_PARSER.md`.

- Preserved Stage 0 and marked Stage 1 In Progress before investigation.
- Fingerprinted both original DB/WAL/SHM trios, copied them to disposable
  storage, and performed every SQLite query only against the copies.
- Compared the baseline and controlled logical databases at table, row, and
  column level without placing private values in tracked output.
- Mapped message, handle, chat, participant, attachment, deletion, and join
  schema; documented exact timestamp units and conversions.
- Established `message.guid` as message/reaction event ID,
  `attachment.guid` as attachment ID, `chat.guid` as private chat ID, and
  `message.ROWID` as an insertion cursor only.
- Established standard reaction additions `2000`–`2005`; demonstrated that
  thumbs-up removal appends a `3001` event, deletes the earlier `2001` row, and
  leaves the deleted add GUID in sync-deletion state.
- Correlated normal photo, Live Photo, and video cases. The Live Photo uses one
  JPEG attachment row plus an unindexed paired MOV and byte-identical `.pvt`
  bundle files.
- Proved the controlled contact creation changed no handle, participant,
  historical message, or display-name identity data relevant to the relay.
- Identified `attributedBody` as Apple `streamtyped` attributed-string data and
  `message_summary_info` as a separate binary plist.
- Proved `immutable=1` misses WAL content in the controlled copy (22 rows
  visible versus 36 with `mode=ro`).
- Created the evidence-based schema report and privacy-safe repeatable probe.
- Did not implement the Stage 2 parser, networking, queue, deployment, live
  access, automatic startup, or any Apple database write.

## Tests Completed

- Stage 2 focused suite:
  `.venv/bin/python -m pytest -q tests/test_imessage_parser.py` completed with
  **19 passed in 0.11 seconds**.
- The optional controlled-snapshot acceptance ran (not skipped) and verified
  one WAL-visible read-only batch: 36 scoped source rows through ROWID 38,
  35 normalized events, 24 incoming ordinary messages, 11 standard reaction
  events, and 4 attachments classified as two photos, one video, and one Live
  Photo, with zero parse issues.
- Sanitized tests cover the six reaction additions, observed removal, unknown
  reaction types, target parts, incoming/outgoing actors, positive service
  filtering, one-to-one and synthetic group-shaped participants, repeat scans,
  cursor gaps, typedstream bounds, source-schema errors, missing/unsafe and
  symlink-escaping attachments, media/size metadata, and row failure isolation.
- Read-only enforcement test rejected an INSERT and confirmed the source
  `sms.db` hash was unchanged.
- `.venv/bin/python -m py_compile iphone_relay/*.py
  tests/test_imessage_parser.py`: passed.
- `git diff --check`: passed with no whitespace errors before final full-suite
  validation.
- Full repository suite: `.venv/bin/python -m pytest -q` completed with
  **728 passed, 9,985 subtests passed in 13.04 seconds**.
- Both disposable logical databases: WAL mode and `PRAGMA quick_check = ok`.
- Controlled-corpus probe assertion:
  `.venv/bin/python scripts/inspect_imessage_schema.py
  iphone_snapshot_stage0 iphone_snapshot --assert-controlled-corpus` passed.
- Probe verified baseline/current message counts 6/36, missing ROWIDs 13/16,
  attachment counts 1/4, two sync-deleted message GUIDs, reaction-code
  distribution, unchanged pre-existing message/handle rows, and unchanged
  original source fingerprints.
- Manual SQL evidence verified every typed standard reaction target resolves,
  both removal rows point to deleted add GUIDs, every message has exactly one
  chat, and all source message/attachment/chat GUIDs are unique in the corpus.
- `.venv/bin/python -m py_compile scripts/inspect_imessage_schema.py`: passed.
- Full repository suite: `.venv/bin/python -m pytest -q` completed with
  **709 passed, 9,985 subtests passed in 12.33 seconds**.
- Original source fingerprints match the values recorded before Stage 1;
  neither snapshot trio changed during this stage.
- Privacy scan found no real UUIDs, controlled message text, attachment names,
  MMCS URLs, or decryption-key material in tracked Stage 1 artifacts.
- Markdown local-link check: 5 files checked, 0 missing targets.
- `git diff --check`: passed with no whitespace errors.

## Current Known Issues

### S0-001 — Read-only SQLite inspection updates SHM lock state

- Classification: environment limitation / snapshot handling.
- Severity: Low.
- Stage discovered: Stage 0.
- Reproduction: Fingerprint the trio, open `sms.db` with SQLite URI `mode=ro`
  plus `PRAGMA query_only=ON`, run `PRAGMA quick_check`, and fingerprint again.
- Observed: `sms.db` and `sms.db-wal` hashes remained unchanged;
  `sms.db-shm` changed and its modification time advanced. No table data was
  selected or displayed.
- Current theory: SQLite's WAL reader coordination updates ephemeral shared
  memory lock/index bytes even while the database connection is read-only.
- Workaround: Stage 1 successfully fingerprinted the originals and inspected
  disposable copies of both complete DB/WAL/SHM trios. Continue that practice;
  treat SHM as coordination state, but do not delete/rewrite the supplied file.
- Blocks next stage: No.

### S0-002 — Original snapshot coverage was incomplete (partially resolved)

- Classification: unresolved database behavior / environment limitation.
- Severity: Low historical issue; superseded by the controlled snapshot.
- Stage discovered: Stage 0.
- Resolution: The newer controlled snapshot covers text, photo, Live Photo,
  video, all six standard reaction additions, and incoming/outgoing thumbs-up
  removals. Remaining absent/ambiguous behaviors are split into Stage 1 issues
  below.
- Blocks next stage: No.

### S1-001 — Emoji reaction lacks a semantic marker

- Classification: unresolved database behavior.
- Severity: Medium.
- Stage discovered: Stage 1.
- Observed: The grinning-face operation persisted as an ordinary incoming
  iMessage row with type/association zero/null. The emoji and target text exist
  only in localized visible text/typedstream; `reply_to_guid` is not unique to
  reaction rows in this conversation.
- Workaround: Treat it as ordinary text. Do not regex-classify it. Preserve an
  emoji-capable normalized model for later evidence.
- Blocks next stage: No for the supported parser; yes for reliable emoji
  reaction normalization.

### S1-002 — Undo Send / retraction was not observable

- Classification: unresolved database behavior.
- Severity: High for retraction correctness.
- Stage discovered: Stage 1.
- Observed: The controlled target remains an intact ordinary row with no
  replacement, tombstone, deletion record, revision record, or associated
  semantic event. The only sync-deleted GUIDs belong to removed reaction adds.
- Workaround: Do not infer unsend from generic deletion. Run documented
  pre/immediate/delayed sender-and-recipient controlled snapshots before
  implementing `message_retracted`.
- Blocks next stage: No for ordinary supported parsing; yes for retraction.

### S1-003 — Additional schema fixtures remain absent

- Classification: environment limitation / unresolved database behavior.
- Severity: Medium.
- Stage discovered: Stage 1.
- Missing evidence: group chat, email/Apple-ID handle, SMS/MMS service values,
  edited message, and null/empty `text` with usable `attributedBody` text.
- Workaround: Keep these paths guarded/unsupported and use the controlled tests
  listed in `docs/SCHEMA_REPORT.md` before claiming support.
- Blocks next stage: No for the observed one-to-one iMessage subset.

### S0-003 — Live environment details are unverified

- Classification: environment limitation.
- Severity: Low now; potentially High at Stage 8.
- Stage discovered: Stage 0.
- Description: Exact iOS build, Messages schema version, installed iPhone
  Python/SQLite versions, available packages, file permissions, TLS support,
  and production attachment-path behavior are unknown.
- Workaround: Do not assume or install anything. Verify only during the
  authorized live read-only integration stage.
- Blocks next stage: No.

## Decisions Made

- Stage boundaries remain authorization boundaries; Stage 3 did not begin.
- The parser is a stateless, independently owned subsystem. It is not a kiosk
  feature and has no application startup, registration, configuration,
  workers, networking, queue, or cleanup behavior in Stage 2.
- `MessagesReader.scan()` returns events plus privacy-safe issues and an
  examined-row boundary. Stage 3 must durably persist normalized events/issues
  before storing that cursor; it is not delivery or ACK state.
- Ordinary outgoing messages are recognized but omitted from the initial
  incoming-content scope. Outgoing reactions remain because their local-self
  actor is required to reconstruct reaction state.
- A fixed, bounded, fail-closed decoder handles only the exact observed
  typedstream root-string variant. No generic Apple object deserialization or
  binary regex/string scan is used.
- Attachment joins are authoritative. Source paths are accepted only beneath
  the configured `Attachments/` root after resolution, and missing/unsafe
  attachments remain visible non-success states.
- No optional attributed-body provider or new dependency was needed.
- Both snapshots are private reference input, never code/commit candidates.
- `message.guid` is the external message/reaction event ID; reaction removals
  use the removal row's GUID. `message.ROWID` is only an ascending insertion
  cursor and must tolerate gaps.
- `attachment.guid` is the attachment ID. Live Photo component IDs are proposed
  deterministic `:still`/`:motion` suffixes because the paired MOV has no DB
  attachment row.
- `chat.guid` is the stable chat ID but is private and must not be logged because
  its observed form embeds address-like material.
- Use a positive `message.service='iMessage'` and chat-service allowlist.
- Incoming sender is `handle_id`; outgoing sender is local `self` and the handle
  is the recipient.
- Standard reaction add mapping is 2000 Heart, 2001 Thumbs Up, 2002 Thumbs Down,
  2003 HaHa, 2004 Emphasize, and 2005 Question. Only removal 3001 is observed;
  other 3000-series mappings remain guarded inferences.
- A reaction removal is its own normalized event. It must not duplicate/delete
  the target message.
- Message timestamps are integer nanoseconds since 2001 UTC; attachment dates
  are integer seconds since 2001 UTC.
- Prefer `message.text`; attachment-only U+FFFC becomes null text. Empty-text
  fallback requires a bounded typedstream decoder and a missing fixture.
- Contacts-name resolution is optional and separate from `sms.db` identity.
- Open live SQLite with URI `mode=ro` plus connection `query_only`; never use
  `immutable=1` on the changing live WAL database and never checkpoint it.
- Discovery uses a message ROWID cursor, a separate sync-deletion cursor,
  recent source fingerprints/lookback, GUID dedupe, and reconciliation. It is
  separate from durable queue, transmission, and ACK state.
- Emoji reaction and retraction extraction remain explicitly unsupported until
  additional evidence exists.
- The relay backend is provisionally separate from existing kiosk features. A
  future UI integration must be optional and failure-isolated under the
  repository feature contract.

## Files Added or Changed

- `.gitignore`: ignores both private snapshot trees.
- `AGENT_README.md`: persistent stage, safety, issue, test, and continuation
  state.
- `README.md`: human-facing Stage 2 status, scope, and safety notice.
- `docs/IMESSAGE_RELAY_PLAN.md`: complete Stage 0–10 plan, stop gates, and
  Stage 2 completion marker.
- `docs/SCHEMA_REPORT.md`: Stage 1 evidence, SQL/schema contract, decisions,
  and unresolved behaviors.
- `docs/IMESSAGE_PARSER.md`: Stage 2 parser API, supported normalization,
  failure/privacy contract, cursor semantics, and evidence gaps.
- `docs/issues/README.md`: privacy-safe issue-record format.
- `scripts/inspect_imessage_schema.py`: disposable-copy, redacted Stage 1
  evidence probe with controlled-corpus assertions.
- `iphone_relay/__init__.py`: public Stage 2 package exports.
- `iphone_relay/contracts.py`: immutable normalized event, attachment, issue,
  and batch records.
- `iphone_relay/errors.py`: parser-specific database/schema/record/path errors.
- `iphone_relay/timestamps.py`: exact Apple-epoch timestamp conversions.
- `iphone_relay/attributed_body.py`: bounded exact-variant typedstream text
  fallback.
- `iphone_relay/attachments.py`: contained path resolution and media/Live Photo
  normalization.
- `iphone_relay/reader.py`: read-only schema validation, bounded scan, joins,
  and event normalization.
- `tests/test_imessage_parser.py`: invented fixture tests and optional private
  snapshot acceptance without tracked private data.

## Stage 2 Completion Evidence

`docs/IMESSAGE_PARSER.md` records the implemented contract and unsupported
evidence gaps. The parser test suite proves versioned normalized output,
read-only rejection, stable repeat scans, failure isolation, path containment,
the sanitized typedstream fallback, and controlled-snapshot acceptance. The
parser contains no networking, relay-owned state, live-phone access, or kiosk
runtime integration.

## Next Required Action

**STOP. Wait for explicit user authorization before Stage 3. If authorized,
implement relay-owned durable queue/checkpoint/retry state as specified in
`docs/IMESSAGE_RELAY_PLAN.md`, keeping discovery, delivery, and ACK state
separate. Do not add networking or contact the live iPhone in Stage 3.**

## Last Updated

2026-08-28 — Stage 2 completed; parser acceptance passed and work stopped
before Stage 3.
