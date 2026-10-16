# Changelog

All notable changes to argbuilder are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Write each entry in the same commit as the change. Before a release, the top
section is `## [Unreleased]`; the version-bump pull request turns it into
`## [X.Y.Z] - YYYY-MM-DD` (or adds a new section) and updates the compare link
at the bottom.

Breaking changes go first, under a `### ... (breaking)` heading, each with a
migration note. CI refuses a declared break whose version has no such heading
(`scripts/compat.py`), and `mise run release:tag` refuses a version with no
section here at all.

## [Unreleased]

## [1.1.1] - 2026-10-16

### Fixed

- A `set` or `frozenset` passed to `value_parser()` now lists its choices in
  sorted order, so help and error messages are identical under every
  `PYTHONHASHSEED` (previously the set's hash order leaked into the output).
- Environment variables are validated only for arguments that declare
  `env()`, so an unrelated non-`str` value in the mapping no longer fails a
  parse, and a large environment costs nothing per parse.

### Changed

- A subclass of a `@parser` class is no longer a command by inheritance:
  decorate it with `@parser` as well, or `to_command()` panics the same way
  it does for any undecorated class.
- A `@parser` or `@args` chain nested more than 32 deep now fails with a
  named error ("subcommands nest deeper than 32") instead of a
  `RecursionError`.

## [1.1.0] - 2026-09-27

### Changed (breaking)

- The class-derive API is decorators, not subclassing. Migrate:
  `class Git(Parser): ...` becomes `@parser class Git: ...`; `Git.parse()` becomes
  `parse(Git)`. The public `Parser` and `Args` classes are replaced by the
  `parser` and `args` decorators, and fields are registered with
  `arg(...)`.

### Added

- Module-level entry points for derived parsers: `to_command`, `parse`,
  `parse_from`, `try_parse_from`, and `from_arg_matches`, since a decorator
  cannot add typed methods a type checker will see.
- `@args` flattens a reusable group of fields into every command that has a
  field of its type (clap's `#[command(flatten)]`).
- `examples/git_derive.py`: the same CLI as `examples/git.py`, derived.

## [1.0.1] - 2026-09-26

### Added

- Close-match suggestions for a mistyped subcommand, argument, or option
  ("did you mean '...'?"), and the `arg()` field helper.

### Changed

- Stricter argument validation and error rendering, pinned by new property,
  error-matrix, and generative test suites.

## [1.0.0] - 2026-09-26

### Changed

- Declared the public API stable; the version is now under Semantic
  Versioning. No behavior changes.

## [0.1.3] - 2026-09-25

### Changed

- Faster command building, matching, and help lookup on the hot paths.

## [0.1.2] - 2026-09-25

### Added

- Release tooling in `scripts/release.py` (artifact checks, wheel smoke test,
  PyPI preflight, post-publish verification) and the tag-triggered
  `release.yml` / `release_validate.yml` workflows. Tagging a version now
  publishes to PyPI and checks the published package.
- `mise run release:tag` and the other `mise` tasks that CI runs.

### Changed

- README rewritten around the clap model, with runnable examples.

## [0.1.1] - 2026-09-25

### Added

- Markdown help generation (`argbuilder._docs`).
- Golden-file snapshots for help and error rendering, plus a rendering
  invariant test.

### Changed

- Refuse to publish a tag that is not on `main`.

## [0.1.0] - 2026-09-25

### Added

- First release: typed, immutable `Command` and `Arg` builders (the clap
  model), typed getters on `ArgMatches`, and user mistakes returned as an
  inspectable `Error` instead of raised.

[Unreleased]: https://github.com/Tomperez98/argbuilder/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/Tomperez98/argbuilder/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Tomperez98/argbuilder/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/Tomperez98/argbuilder/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Tomperez98/argbuilder/compare/v0.1.3...v1.0.0
[0.1.3]: https://github.com/Tomperez98/argbuilder/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Tomperez98/argbuilder/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Tomperez98/argbuilder/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Tomperez98/argbuilder/releases/tag/v0.1.0
