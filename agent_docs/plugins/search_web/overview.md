---
id: plugin.search_web
type: plugin
plugin_type: feature
entrypoint: bmo.features.search_web
status: stable
tests: [tests/test_tool_routing.py, tests/test_tool_presentation.py]
---

# Plugin: Web Search

## Purpose

Perform bounded DuckDuckGo/DDGS text or news searches and return typed content
for direct presentation or local-model summarization.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration, request normalization, search | `bmo/features/search_web.py` |
| generic presentation/archive execution | feature contracts and conversation core |
| configuration | shared `online_timeout_seconds`; feature enable/settings |
| persistence | interaction archive details only |
| UI/workers | none |

`register(registry, settings)` registers `SearchWebTool`. Direct phrases and
model action data normalize to one query and search type. Execution calls the
installed `ddgs` package on demand, formats bounded results, and attaches
structured archive metadata under the web archive category. The tool owns no
long-lived client or cleanup.

## Failure and privacy

Missing library, provider, network, or malformed-result failures return an
expected typed error rather than breaking the turn loop. Search text and full
results may enter private interaction archives; default logs should not add
extra content. Disabling the feature removes aliases, prompt metadata, direct
matching, and execution without affecting ordinary model conversation.

## Tests and interfaces

Primary: `tests/test_tool_routing.py`,
`tests/test_tool_routing_characterization.py`, and
`tests/test_tool_presentation.py`. Shared: `tests/test_tool_registry.py` and
`tests/test_archive.py`.

Consumes typed tool presentation/archive contracts and shared timeout parsing.
Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
