# Feature plans

Plans for the work after shell completion. Each file is a handoff-sized plan:
goal, proposed API, implementation steps, tests, acceptance criteria and risks.

Current baseline:

- shell completion engine and scripts: implemented
- `completion <SHELL>` subcommand: implemented
- 100% package branch coverage
- fish/PowerShell still need a final CI run after the `C`/`D` protocol change
- parser correctness and validation semantics: implemented (`require_equals`,
  `allow_negative_numbers`, `trailing_var_arg`, `overrides_with` / `exclusive`,
  conditional requirements, `args_conflicts_with_subcommands`)
- none of this is released yet

## Order

| Plan | Feature | Why now |
|---|---|---|
| [01](01-ship-completion.md) | Ship completion | The feature is done but unreleased; verify the shell matrix first |
| [02](02-install-completion.md) | Durable `completion --install` | Completes the completion UX; ephemeral path already exists |
| [03](03-help-structure.md) | Headings, long help, help text sections | Biggest remaining help/clap parity gap |
| [10](10-man-pages.md) | Man page generation | Natural sibling to Markdown/completion renderers |
| [11](11-response-files.md) | `@file` response files | Long command lines and automation |
| [12](12-external-subcommands.md) | External/plugin subcommands | git-style plugins |
| [13](13-completion-polish.md) | Remaining completion gaps | Path hints after `=`, fish dirs, non-path hints |
| [14](14-ergonomics.md) | `infer_subcommands`, `ignore_case` | Convenience features, lower priority |

## Non-goals

Do not add these unless a real user need appears:

- config-file parsing (TOML/YAML) in the parser
- prompting/password input
- i18n
- a `help_template` DSL
- alternate option prefixes (`/`, `+`)
- busybox-style multicall
- a derive/decorator API

## Working rules

- Definition mistakes panic (`AssertionError`); user mistakes return `Error`.
- `try_get_matches_from` stays pure. Process and file-system edges belong in
  `get_matches` / `get_matches_from` or in explicitly injected helpers.
- New public API needs README, CHANGELOG, tests and 100% branch coverage.
- Keep the zero-runtime-dependency promise.
