# AGENTS.md

## Project workflow

- Work only inside this repository.
- Use the existing project virtual environment.
- Inspect relevant code and tests before modifying behavior.
- Keep changes focused on the requested task.
- Add or update tests whenever behavior changes.
- Run `python -m pytest -q` after code changes.
- Do not weaken, skip, or delete tests merely to make them pass.
- Ask before adding, removing, or upgrading dependencies.

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
