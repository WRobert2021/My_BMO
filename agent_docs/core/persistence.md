# Shared Persistence Contract

## Neutral owner

`bmo.jsonio` owns strict JSON decoding and crash-safe replacement mechanics.
It rejects duplicate keys, non-finite numbers, excessive embedded-object depth,
and incomplete embedded objects. `atomic_write` writes a same-directory
temporary file, flushes and fsyncs it, replaces the destination atomically, and
removes the temporary file after failure. JSON and JSONL wrappers disable NaN;
callers opt into directory fsync where required.

`bmo.archive` separately owns contained interaction artifact allocation,
allowed categories/filenames/suffixes, strict JSONL event output, and manifests.
`bmo.memory` owns bounded conversation-history validation and atomic saving to
the ignored `bmo/data/memory.json` file.

## Domain ownership

Shared mechanics do not own domain schemas. Alarm Clock, Calendar, Learning,
Music, Twenty Questions, iMessage relay state, and the kiosk receiver each own
their schema, validation, retention, recovery, and privacy policy. Domain
stores must fail closed or visibly enter read-only recovery where documented;
they must not silently replace malformed or future-version data.

Private configuration and state stay outside source control. Paths must be
contained where a feature accepts a configurable root; symlink/path traversal
escapes are rejected at the owning boundary. SQLite plugins own distinct
application IDs, schema versions, transaction semantics, permission checks,
and cleanup. Apple's Messages database is never a shared persistence store and
is always read-only external input.

## Failure behavior

- Validate before state enters runtime.
- Keep schema errors domain-specific and avoid logging private payloads.
- Never advance a durable cursor/checkpoint ahead of the transaction that owns
  the corresponding event or visible issue.
- Flush/replace failures preserve the old destination and clean temporary
  files where possible.
- Closing stores is explicit and idempotent; import and metadata discovery do
  not open them.

Primary tests: `tests/test_jsonio.py`, `tests/test_archive.py`,
`tests/test_config_and_memory.py`, plus each plugin's store tests.
