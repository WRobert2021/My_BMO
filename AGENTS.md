# AGENTS.md

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

Do not commit or push as part of the handoff.
