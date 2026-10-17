# 01 — Ship shell completion

## Goal

Release the existing completion work after verifying every supported shell.

This is not a new feature; it is the release gate for the completion feature
already in the worktree.

## Current state

- `Command.render_completion(shell)` and `Command.complete(argv, cursor)` exist.
- `Command.completion_subcommand(True)` adds a visible `completion <SHELL>`
  command.
- `get_matches()` / `get_matches_from()` print the script and exit 0.
- Pure parsing stays pure.
- Local tests: 553 passed, 100% branch coverage, `ci:fast` passes.
- Fish and PowerShell tests were validated before the protocol changed from
  `:`-prefixed lines to `C`/`D`-prefixed lines. They have not been re-run since.
- Fish/PowerShell are not installed on the development machine.

## Release checklist

1. Run the full local suite:
   ```bash
   mise run ci:fast
   mise run test
   uv run pytest -q
   mise run test:completion
   mise run contract:check
   mise run contract:compat
   mise run smoke
   ```
2. Push a PR and wait for the new `Completion` CI job.
   - Confirm the job installs/finds `zsh`, `fish`, `pwsh`.
   - Confirm fish and PowerShell end-to-end tests run, not skip.
   - Confirm bash 3.2 behavior is not silently broken if macOS is supported.
3. Review the generated script goldens and shell adapters.
4. Review README, CHANGELOG and the example CLI changes.
5. Bump the version:
   ```bash
   uv version --bump minor   # 2.0.0 -> 2.1.0
   ```
   Update `CHANGELOG.md` from `Unreleased` to the new version.
6. Merge, then run `mise run release:tag`.
7. Confirm the published wheel/sdist include `_completion.py` and the new
   tests are not required at runtime.

## Acceptance criteria

- [ ] The `Completion` CI job is green with fish and PowerShell actually run.
- [ ] All local checks pass.
- [ ] README documents ephemeral completion and the lack of automatic install.
- [ ] CHANGELOG has a 2.1.0 entry.
- [ ] No shell configuration is modified by tests or the library.
- [ ] Release artifacts install cleanly in a fresh environment.

## Risks

- CI may not have `pwsh`; verify the runner image or install it explicitly.
- The fish adapter's tab-splitting and PowerShell's `C`/`D` parsing are the
  highest-risk code paths after the protocol change.
- Do not ship while those tests skip.
