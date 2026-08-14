# AGENTS.md

## Required documentation

- Read `AGENT_BRIEF.md` before working on a coding prompt for a high-level map
  of the repository's scripts and module ownership.
- Read `docs/AGENT_ARCHITECTURE.md` before changing application behavior,
  feature or mode boundaries, registration, configuration, runtime ownership,
  failure handling, cleanup, or tests.
- Read `docs/AGENT_LEARNING.md` when working on the Learning feature.
- Read `docs/AGENT_LOCATION_WEATHER.md` when working on location or weather
  behavior.

## Project workflow

- Work only inside this repository.
- Use the existing project virtual environment.
- Inspect relevant code and tests before modifying behavior.
- Keep changes focused on the requested task.
- Add or update tests whenever behavior changes.
- Run `python -m pytest -q` after code changes.
- Do not weaken, skip, or delete tests merely to make them pass.

## Dependency policy

- Ask before removing or upgrading an existing dependency.
- A new dependency may be added without separate approval only when both of
  these conditions are satisfied:
  1. It is compatible with the primary deployment target: Raspberry Pi 5 with
     16 GB RAM, 64-bit Raspberry Pi OS (`aarch64`), and Python 3.13.5.
  2. It is absolutely necessary, materially reduces the project-owned code
     needed for the planned feature, provides a measurable performance
     improvement, or makes the implementation or runtime materially cleaner
     and more reliable.
- Establish target compatibility before adding the dependency. Check upstream
  support and Python 3.13/aarch64 wheel or source-build availability, and run
  an install/import smoke test on the target when practical. A successful
  macOS installation alone is not sufficient. Do not add a dependency whose
  target compatibility cannot be established.
- Keep the dependency surface minimal. Identify the license, constrain the
  supported version where needed, and update `requirements.txt`, `setup.sh`,
  documentation, and tests that own installation behavior.
- In the handoff, state which justification applies and report compatibility
  evidence. Include before/after measurements when performance is the reason;
  for code reduction or cleaner execution, summarize the concrete reduction
  in project-owned code or runtime complexity.

## Feature modularity

- Every new or modified feature must follow the feature and mode extension
  contracts in `docs/AGENT_ARCHITECTURE.md`. Keep feature registration,
  configuration, runtime ownership, failure handling, cleanup, and tests inside
  the feature's module or its narrowly owned supporting modules.
- Features must remain independent of one another. Enabling, disabling,
  removing, or failing one feature must not break another feature's core
  behavior or prevent the application from starting.
- A feature may use a function from another script or feature only when that
  dependency cannot break the consuming feature's core behavior. Optional
  cross-feature integrations must be discovered or imported lazily rather than
  becoming import-time requirements.
- When a function starts being used by multiple features, or substantially the
  same function is being implemented in multiple features, explicitly evaluate
  whether it should be refactored into the smallest appropriate neutral core or
  shared module. Document the ownership decision and avoid circular feature
  dependencies or an unrelated catch-all utility module.
- If a feature uses another script, feature, or function only for a non-core
  capability, the consuming feature must continue to load and its core behavior
  must continue to work when that provider is changed, disabled, unavailable,
  or removed. In the application UI, the unavailable non-core action must be
  disabled or greyed out so the missing integration is visible rather than
  crashing, silently disappearing, or leaving an unusable control.
- Add tests for the provider-present and provider-unavailable cases of every
  optional cross-feature integration. Verify the consuming feature's core path,
  the disabled UI state, clean startup, and cleanup behavior.

## Git and GitHub restrictions

- Do not stage files.
- Do not create or amend commits.
- Do not push, force-push, fetch, pull, or synchronize with a remote.
- Do not create GitHub pull requests, issues, releases, or tags.
- Do not add, remove, rename, or modify Git remotes.
- Do not modify files inside `.git/`.
- Do not run destructive Git commands such as `git reset --hard`,
  `git clean`, or forced checkout operations.
- Leave all changes unstaged for manual review by the user.

## Privacy and local files

- Do not read, print, expose, or modify `.env` files, credentials,
  private keys, tokens, or passwords.
- Treat `config/settings.json`, `config/features.json`, and the legacy
  `config.json` as private local configuration.
- Use the `config/example.*.json` files when documentation or tests need
  configuration examples.
- Do not add ignored files or directories to Git.
- `graphics/` contains local copyrighted fan-project assets and must never be
  staged, committed, uploaded, copied, or modified.
- `.venv/`, `.idea/`, `piper/`, and `whisper.cpp/` are local dependencies or
  environment files and must remain untracked.

## Licensing

- Preserve existing MIT and third-party license notices.
- Do not copy new third-party code, graphics, sounds, models, or datasets into
  the repository without identifying their license first.
- Do not claim ownership of upstream or third-party material.

## Handoff requirements

At the end of every task, report:

- Files changed and the reason for each change.
- Tests and checks run, including exact results.
- Anything that could not be verified.
- Remaining risks and assumptions.
- Manual verification steps.
- A concise `git diff` summary.
- A concise suggested commit message describing the completed change.

Do not commit or push as part of the handoff.
