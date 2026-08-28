# Plugin and Extension Contract

## Boundaries

For agent documentation, every independently owned feature or mode is a
plugin. Features are one-shot tools or menu-owned views; modes own multiple
turns or a dedicated interaction until inactive. A service-style plugin may
own a listener or worker when intrinsic to its capability.

`config/features.json` owns the optional `features` and `modes` allowlists.
Omitting a list uses defaults in `bmo.features.loader` or `bmo.modes.loader`;
providing it replaces the defaults. Disabled entries are skipped before module
or settings validation and before import.

## Registration

Feature modules expose `register(registry, settings)`. Resource-owning tools may
also expose resource-free `register_metadata`; menu contributors expose
resource-free `register_menu_metadata`. Feature actions, aliases, prompt
metadata, direct matching, request normalization, typed results, archival, menu
hooks, attentions, notifications, and cleanup are validated by
`bmo.features.registry` and contracts.

Mode modules expose `register(registry, context, settings)` and optionally
`register_menu_metadata`. `ModeRuntimeContext` provides only approved model,
speech, memory, state, face, and presentation-dispatch services. Active modes
select `WAKE_WORD`, `CONTINUOUS`, or `SUSPENDED` input policy.

`bmo.extensions.load_configured_extensions` owns shared list validation,
ordered import, settings overlay, registration transactions, rollback, and
failure reporting. Partial registration is rolled back and candidates are
closed once. A failing module does not block later entries. Registry shutdown
closes registered resources in reverse order.

## Lifecycle and isolation

- Imports and menu metadata discovery must be resource-free.
- Start workers, clients, sockets, listeners, stores, and UI only during
  enabled registration, explicit view open, or first use.
- A disabled plugin starts no intrinsic resources.
- `close()` must be idempotent and stop workers/listeners, release devices and
  subprocesses, close stores, and invalidate late callbacks.
- Plugin startup or runtime failure must remain local; unrelated plugins and
  application startup continue where safe.
- Long-lived services follow the same rules. Binding a port at import time is
  prohibited; bind only while enabled, report degraded/unavailable startup,
  and release the port during cleanup.

## Optional integration

Plugins must not depend on another plugin for core behavior. Discover optional
providers lazily, expose an unavailable/disabled state rather than a crashing
or silently missing control, and test both provider-present and
provider-unavailable paths. Move only the smallest genuinely shared contract
to a neutral core/shared owner; avoid circular or catch-all dependencies.

## Menus and UI

Menu metadata becomes a namespaced `mode:` or `feature:` catalog item.
Presentation emits `MenuSelectionRequest(owner, name)`; the runtime validates a
fresh catalog before dispatch. Feature views receive `FeatureMenuContext`, not
the application coordinator. Modes and feature vision work that must run off
the Qt thread are queued to the interaction worker.

## Definition of done

A new plugin is complete only when applicable registration, configuration,
enable/disable behavior, lifecycle and cleanup, failure isolation, focused and
shared tests, overview/progress docs, index routing, and repository ownership
map are current. Document background resources and cross-plugin APIs. For
existing plugins, update only the documents owning facts that changed.

Contract tests: `tests/test_extension_architecture.py`,
`tests/test_feature_loading.py`, `tests/test_mode_loading.py`,
`tests/test_tool_registry.py`, `tests/test_menu_catalog.py`, and proof modules
under `tests/extension_modules/`.
