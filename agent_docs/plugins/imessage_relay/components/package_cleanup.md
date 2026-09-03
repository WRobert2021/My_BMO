# Package Cleanup

## Stage and boundary

Stage 11 consolidates all iMessage Relay Python implementation and manual
tooling under `bmo.features.imessage_relay`. It is an ownership and import-path
change only: protocol versions, database schemas, configuration schemas,
lifecycle behavior, safety boundaries, and supported message behavior do not
change.

The approved package layout is:

```text
bmo/features/imessage_relay/
  __init__.py
  feature.py
  relay/
  receiver/
  tools/
```

Qt adapters remain under `bmo/qt/views` and QML remains under `bmo/qt/qml`,
matching repository UI ownership conventions. Tests, example configuration,
and agent documentation remain in their normal repository directories.

## Migration rules

- Move the former root `iphone_relay` package to the nested `relay` package.
- Move the former root `kiosk_receiver` package to the nested `receiver`
  package.
- Move the Stage 10 feature module to `feature.py`; package `__init__.py`
  exposes only the feature registration surface and intended public metadata.
- Move plugin-specific schema/live-validation/manual-delivery scripts into the
  nested `tools` package and invoke them with `python -m`.
- Update every active source, test, example, CLI, ownership, and API reference.
  Historical archives remain unchanged.
- Do not leave root compatibility packages or forwarding shims. A stale import
  must fail visibly rather than preserve two package identities.
- Do not change private configuration or state, contact the phone or kiosk,
  deploy, enable the feature, install a daemon, or add dependencies.

## Acceptance gate

Before test execution, structural inspection must show no active
`iphone_relay` or `kiosk_receiver` import, no plugin-owned script left in the
root `scripts` directory, one resource-free BMO entrypoint, and no legacy
package directory. Python compilation, example JSON validation, and
`git diff --check` may run locally.

Per the operator's instruction, all pytest suites are deferred until the kiosk
is online. Stage 11 remains in progress until the complete relay, shared
extension/Qt, setup, and full repository suites pass in that validation cycle.

## Offline implementation status

The package relocation, import rewrites, active-documentation updates, and
legacy-root removal are complete. Static acceptance passed on 2026-09-02:

- all Python files in the nested package and iMessage Relay test modules
  compiled successfully;
- importing the package, relay, receiver, and three tool modules created no
  background thread;
- active source and documentation contain no legacy root-package import or old
  script path (historical archives and the migration description above retain
  those names intentionally);
- `config/example.features.json` passed JSON validation; and
- `git diff --check` passed.

No pytest suite, phone/kiosk connection, deployment, enablement, daemon, or
private-configuration operation was performed during this offline pass.
