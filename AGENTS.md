# AGENTS.md

## Documentation lookup

For every repository task, read this file and then consult
[`agent_docs/INDEX.md`](agent_docs/INDEX.md). Read only the documents routed by
the index for the current task; do not bulk-read or recursively read
`agent_docs/`.

Instruction precedence is: the current user request, this file, the index,
current core/plugin/API/progress documentation, then historical evidence and
archives. Historical material never overrides verified current documentation.

## Project workflow

- Work only inside this repository and use its existing virtual environment.
- Inspect relevant source and tests before changing behavior.
- Keep changes focused and add or update tests when behavior changes.
- Never weaken, skip, alter, or delete tests merely to make them pass.
- During implementation, run the narrowest relevant tests first. Add shared
  contract or integration tests when a shared boundary changes; rerun failures
  directly instead of repeatedly running the whole suite.
- Before handoff, run the full suite for core runtime, extension contracts,
  shared utilities/configuration/persistence/UI, setup, or dependency changes.
  For isolated plugin work, run its complete primary tests and relevant shared
  contracts; run the full suite once when impact plausibly crosses plugin
  boundaries.
- For large full-suite runs, capture detailed output outside the conversation
  (for example, `python -m pytest -q --tb=short >
  /tmp/be_more_pytest.log 2>&1`) and report the concise final summary. If it
  fails, identify failures and inspect/rerun only the relevant sections. Never
  hide a failing exit status.

## Dependency policy

- Ask before removing or upgrading an existing dependency.
- Add a dependency only when it is compatible with Raspberry Pi 5, 64-bit
  Raspberry Pi OS (`aarch64`), and Python 3.13.5, and it is necessary,
  materially reduces project-owned code, measurably improves performance, or
  makes execution materially cleaner and more reliable.
- Establish upstream Python 3.13/aarch64 wheel or source-build support; a macOS
  install alone is insufficient. Keep versions and licenses explicit and the
  dependency surface minimal. Update `requirements.txt`, `setup.sh`, owning
  docs, and installation tests as applicable.
- In the handoff, state the justification and compatibility evidence. Include
  measurements for performance claims or the concrete code/runtime reduction
  for maintainability claims.

## Plugin invariants

- Features and modes are plugins: keep registration, configuration, lifecycle,
  failure handling, cleanup, persistence, UI, workers, and tests within the
  plugin or a narrowly owned neutral interface.
- A disabled, unavailable, broken, or removed plugin must not prevent startup
  or another plugin's core behavior. Optional cross-plugin integrations must
  be lazy, failure-isolated, visibly unavailable in UI, and tested with the
  provider present and absent.
- Evaluate genuinely shared behavior for the smallest neutral owner. Avoid
  circular plugin dependencies and catch-all utility modules.
- Importing a plugin must not start workers, listeners, sockets, stores, or
  other resources. Enabled registration/runtime lifecycle starts intrinsic
  long-lived resources; cleanup must stop and close them explicitly.

## Agent documentation maintenance

Agent documentation is part of the implementation contract.

When adding a plugin, create its `overview.md` and `progress.md` under its
plugin documentation directory, add index routing and repository ownership,
record configuration and primary tests, document lifecycle/background
resources, and document any cross-plugin callable API. Update core/shared docs
only when their contract changes.

When modifying a plugin, update its overview only when architecture,
ownership, configuration, persistence, public hooks, lifecycle, failure
boundaries, shared API use, or test ownership changes. Update progress when a
stage, chapter, blocker, next action, architectural decision, or implementation
state changes. Update the index only for plugin inventory/type/routing/trigger
changes, and update an API document when its callable contract changes. Do not
rewrite unrelated plugin docs. Keep progress cheap to load: retain only current
work and a compact stage index, and move detailed completed work into that
plugin's opt-in history.

A plugin is not complete until its applicable registration, configuration,
lifecycle/cleanup, failure isolation, tests, overview, progress, index entry,
and exposed API documentation are current. Removing a plugin also removes or
retires its active routing and ownership entries.

## Git and GitHub restrictions

- Do not stage, commit, amend, push, force-push, fetch, pull, or synchronize.
- Do not create pull requests, issues, releases, or tags; do not alter remotes
  or files inside `.git/`.
- Do not run destructive Git commands such as `git reset --hard`, `git clean`,
  or forced checkout. Leave changes unstaged for manual review.

## Privacy and local files

- Do not read, print, expose, or modify `.env`, credentials, keys, tokens, or
  passwords.
- Treat `config/settings.json`, `config/features.json`, legacy `config.json`,
  private relay data, and all non-example local configuration as private. Use
  tracked `config/example.*.json` files in docs and tests.
- Do not add ignored files. `.venv/`, `.idea/`, `piper/`, and `whisper.cpp/`
  remain untracked. `graphics/` contains local copyrighted fan-project assets
  and must not be modified, copied, staged, or uploaded.

## Licensing

- Preserve MIT and third-party notices. Do not copy third-party code, media,
  models, or datasets without identifying the license, and do not claim
  ownership of upstream material.

## Handoff requirements

Report files changed and why, exact tests/checks and results, anything not
verified, remaining risks/assumptions, manual verification steps, a concise
`git diff` summary, and a suggested commit message. Do not commit or push.
