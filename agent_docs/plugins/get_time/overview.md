---
id: plugin.get_time
type: plugin
plugin_type: feature
entrypoint: bmo.features.get_time
status: stable
tests: [tests/test_tool_routing.py, tests/test_feature_loading.py]
---

# Plugin: Get Time

## Purpose

Return the kiosk's current local time through deterministic phrases, an alias,
or model-routed action. This is a voice/tool plugin with no menu or UI.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration and execution | `bmo/features/get_time.py` |
| shared tool contract/routing | `bmo/features/contracts.py`, `registry.py` |
| configuration | feature enable/settings entry; no private file |
| persistence/UI/workers | none |

`register(registry, settings)` creates `GetTimeTool`. Its public action, alias,
schemas, prompt metadata, direct matching, and typed `ToolResult` are owned by
the module. Execution reads the local system clock and returns formatted text;
it acquires no resource and `close` is unnecessary.

## Runtime and failure boundary

The feature loader imports and registers it only when enabled. Direct matching
handles unambiguous current-time phrases; model routing uses the same action.
Disabling it removes every route without affecting conversation fallback or
other plugins. System-local time is authoritative; there is no timezone
provider or persistence.

## Tests

Primary: `tests/test_tool_routing.py`,
`tests/test_tool_routing_characterization.py`, and
`tests/test_feature_loading.py`. Shared contracts: `tests/test_tool_registry.py`
and `tests/test_intent.py`.

## Shared interfaces

Consumes typed tool result/presentation contracts. Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
