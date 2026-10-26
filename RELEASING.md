# Releasing argbuilder

A release is one push: `mise run release:tag` tags a tested commit on
`origin/main`, and [`release.yml`](.github/workflows/release.yml) does the
rest — CI on the tag, build, publish to PyPI, GitHub release, then a check
that users actually get what shipped. This file is the checklist and the
recovery guide; the reasoning behind it is in the `ship` skill.

The invariant: **keep `main` releasable, and make every release boring —
scripted, re-runnable, verified.** Every step below is safe to run twice
except publishing, which is why publishing waits for a human.

## One-time setup

These live in GitHub and PyPI, not in the repo, so they are done once by a
maintainer. The release workflow assumes they exist.

1. **PyPI trusted publisher** — on PyPI, project *argbuilder* → *Publishing*
   → add a GitHub publisher with owner `Tomperez98`, repository `argbuilder`,
   workflow `release.yml`, environment `pypi`. No API token is stored.
2. **GitHub settings** — `mise run github:apply` (needs `gh` authenticated as
   a repository admin). It applies [`.github/settings.json`](.github/settings.json):
   - `main` ruleset: every CI job required, strict up-to-date checks, squash
     merges, auto-merge, and a PR required. Approvals and code-owner review
     stay off until a second maintainer exists; turn them on here when there
     is one. A merge queue needs an organization-owned public repo; while
     this repo is user-owned, strict up-to-date checks give the same
     serialized-merge guarantee for this volume.
   - `v*` tag ruleset: block updates and deletions, so a published tag can
     never move.
   - `pypi` environment: your reviewer approval and a deployment policy
     limited to `v*` tags. The approval *is* the deliberate "go" before the
     upload.
   - Actions: require SHA-pinned action refs.
3. *(Recommended)* **Immutable releases** — Settings → General → Releases →
   enable, so release assets cannot be edited after publishing. GitHub has
   no API for this setting, so it stays manual.

Verify what exists (needs `gh` with admin auth):

```bash
mise run github:check
gh api repos/Tomperez98/argbuilder/rulesets --jq '.[].name'
gh api repos/Tomperez98/argbuilder/environments/pypi --jq '.protection_rules'
```

`github:check` is also a release precondition: run it before tagging, and
fix drift before the tag exists.

## Every release

1. **Land the changes.** Normal PRs, CI green, the contract job's label read:
   `unchanged` or `additive` merges on green; a `breaking` label needs the
   spec owner's yes and a migration note.
2. **Write the changelog** in `CHANGELOG.md`: turn `## [Unreleased]` into
   `## [X.Y.Z] - YYYY-MM-DD`, breaking changes first under a
   `### ... (breaking)` heading with a migration note, and add the compare
   link at the bottom.
3. **Bump the version in the same PR.** Under SemVer the compatibility result
   picks the bump, not taste:

   ```bash
   uv version --bump patch    # fixes, no API change
   uv version --bump minor    # additive only
   uv version --bump major    # a declared break
   ```

   Commit the `pyproject.toml` bump together with the changelog entry.
4. **Merge, and wait for green.** The CI run on `main` for the merged commit
   must pass. Do not tag a red commit. Run `mise run github:check` first; a
   drifted ruleset or environment is a broken precondition.
5. **Tag.** This resolves `origin/main` to a SHA, checks the tag and version
   agree, and refuses a version without a changelog section or one that
   isn't newer than PyPI:

   ```bash
   mise run release:tag
   ```

6. **Approve the publish.** The Release workflow runs CI on the tag, builds
   and smoke-tests the wheel, then *waits* on the `pypi` environment for the
   required reviewer. This is the one point where an agent stops: it shows
   the commit, version, and changelog entry, and waits for a "go".
7. **Watch validation.** After publishing, `release_validate.yml` downloads
   the release from PyPI, checks the bytes match what was built, installs on
   Python 3.12–3.15, runs the released examples, and judges the wheel with
   the contract that shipped. The same check runs weekly.

## What the automation already guarantees

Know these so you know what *not* to re-check by hand:

- The tag must match `pyproject.toml` and the commit must be an ancestor of
  `main`; a tag off-mainline is refused before anything is built.
- `dist/` holds exactly this version's wheel and sdist; the wheel is
  installed into a clean venv and the examples run (`mise run smoke`).
- `release-manifest.json` records the version, the tag commit, and a sha256
  and size for every shipped file, including the contract spec, driver and
  plan. It is attached to the GitHub release next to the artifacts.
- `preflight` refuses a version PyPI already has with *different* bytes. If
  PyPI already has *some* of these exact bytes, the release resumes and
  uploads the rest — no version is burned.
- The GitHub release notes are the install facts plus this version's
  changelog section, and the release is created only after PyPI has the
  files.

## If a release fails

Fix the cause and **re-run the failed jobs** ("Re-run failed jobs" on the
run). Every step skips work that is already done, so a partial failure
never burns a version. GitHub emails the person who pushed the tag.

| Failure | What it means | What to do |
| --- | --- | --- |
| CI on the tag | A toolchain/runner issue, or main wasn't really green | Re-run; if a real bug, fix on `main` and bump the patch version |
| Tag/version or off-main check | Wrong tag, or a tag not on `main` | Nothing published. Delete the local tag, bump correctly, re-tag |
| `check-dist` / `smoke` | Build or wheel problem | Fix on `main`; the version is still free if unpublished |
| `preflight`: "version is taken" | PyPI has that version with different bytes | Bump the version; never overwrite |
| Publish stopped partway | Network or registry failure | Re-run failed jobs; `uv publish --check-url` skips files already uploaded |
| GitHub release missing | Publish succeeded, release job failed after | Re-run failed jobs; the job is idempotent |
| Validation failed | Users may be getting different bytes, or `pip install` broke | Treat as a bug: read the artifact name and both values, fix the release tooling on `main`, re-run |
| Bad release is public | The version is immutable | Never re-tag. Bump and ship a fix through this same process. Optionally yank the version on PyPI and mark the GitHub release, and tell users how to move |

An emergency where *upgrading itself* is broken has no shortcut: ship a new
version through this process. Keep the process fast enough that this is
never the slow option.

## Rules

- **Versions only go up.** A published version, or one burned by a failed
  attempt, is never reused.
- **Never re-tag or move a tag.** Fixes ship as a new version.
- **Tag `origin/main`, never your local HEAD** — a working tree can hold
  commits that `main` never had.
- **One release at a time.** Releases are never cancelled partway, and the
  validation shares the release lock.
