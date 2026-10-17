# Shell completion — implementation status

Status: **complete and green**. All four generated adapters pass end-to-end in
Docker (bash 5, zsh 5.9, fish 4.0, PowerShell 7.6), and bash 3.2 passes locally
on macOS. The package still has 100% branch coverage.

This file is a working handoff, not part of the public documentation.

## Goal

Add clap-style shell completion to `argbuilder`:

- `bash`, `zsh`, `fish`, `powershell` script generation
- subcommands, aliases, flags, global args, choices, `--`, `--opt=value`
- hidden args/subcommands omitted
- path/directory hints
- pure, testable candidate engine
- no runtime dependencies
- 100% package branch coverage preserved

## Architecture

### Pure engine

`src/argbuilder/_completion.py`

- `complete(cmd: ResolvedCommand, argv, cursor=None) -> CompletionResult`
  - `argv` includes the binary name, like `sys.argv`.
  - `cursor` is 0-based, like bash `COMP_CWORD`, defaults to the last word.
  - Walks the same resolved tree as the parser, without validating.
  - Returns `Completion` candidates plus a `CompletionDirective`.
- `render_completion(cmd, shell)` returns a thin shell adapter.
- `write_completion(cmd, argv, stream)` answers the process-edge protocol.
- `_completion_request()` parses `<program> __complete <cursor> <argv...>`.
- A user-defined `__complete` subcommand wins; the protocol is a fallback.

Protocol (line-oriented):

```text
C\t<value>
C\t<value>\t<help>
D\t<bits>
```

Bits:

| bit | meaning |
|---|---|
| 1 | `no_file` |
| 2 | `filter_dirs` |
| 4 | `filter_files` |

The `C`/`D` prefixes mean candidate values that start with `:` are safe. There is a
test for `:colon`.

### Process edge

`Command.get_matches()` in `src/argbuilder/_command.py` checks for a completion
request before parsing and exits 0 after writing the answer. This is why no hidden
command is added to the user's command tree. `get_matches_from()` also handles
the visible `completion` command: it prints the script and exits 0.

`try_get_matches_from()` remains pure. It returns `ArgMatches` for
`["tool", "completion", "bash"]` and never prints or exits. The generated
scripts rely on `get_matches()`.

### Public API

Exported from `argbuilder/__init__.py`:

- `Completion`
- `CompletionDirective`
- `CompletionResult`
- `Shell`
- `ValueHint`
- `Command.complete(argv, cursor=None)`
- `Command.render_completion(shell)`
- `Command.completion_subcommand(True)`
- `Command.hide(True)`
- `Arg.value_hint(hint)`

`ValueHint` is intentionally limited to the hints this package implements:
`any_path`, `file`, `dir`, `executable`. clap's `command`, `username`,
`hostname` and `env_var` hints need shell-specific knowledge that is not
implemented, so accepting them would silently do nothing. `executable` uses
file completion (shells are not asked to filter for the executable bit).

## Implemented behavior

- `completion_subcommand(True)` adds a visible `completion <SHELL>` command on
  the root. It is opt-in, root-only, rejects a name collision, and prints the
  same script as `render_completion(shell)`.
- Root completion offers visible subcommands plus long **and** short flags.
- Prefix filtering for commands/options/choices.
- Visible aliases offered; hidden aliases omitted.
- Hidden args and hidden subcommands omitted from completion, help, Markdown docs,
  and typo suggestions, but still parse by name.
- `help` subcommand completion:
  - `tool help ` offers the parent's commands.
  - `tool help add ` switches to `add`'s context.
- `--` disables option completion and opens `last(True)` positionals.
- Short clusters are walked correctly (`-ff`, `-nX`, `-p=x`).
- Inline values (`--opt=x`) and next-word values are tracked.
- Choices are completed with the original prefix (`--color=a` → `--color=always`).
- Path hints leave file/directory completion to the shell:
  - `file` / `any_path` / `executable` → `filter_files`
  - `dir` → `filter_dirs`
  - `--opt=` path values suppress file fallback because the `=` prefix is not
    handled by shell-native path completion. This is documented in the README.
- `hide(True)` is rejected on the root command at build time; it only applies to
  subcommands.

### Shell adapter behavior

| shell | mechanism | notes |
|---|---|---|
| bash | `COMP_WORDS` / `COMP_CWORD` → `__complete` | bash 3.2 registers `-o default`; bash 4+ uses `compopt` for no-file and directory-only completion |
| zsh | `words` / `CURRENT` → `__complete` | `compadd` values; `_files` / `_files -/` fallback |
| fish | `commandline -opc/-ct` → `__complete` | `complete -c ... -f -a ... -n __prepare`; returns 1 to let fish do file completion; cannot filter to directories |
| powershell | `Register-ArgumentCompleter -Native` | builds words from `$commandAst`, calls `__complete`, emits `CompletionResult`; cannot filter to directories, falls back to files |

## Files

### New

- `src/argbuilder/_completion.py`
- `tests/completion_cli.py` — rich fixture CLI used by unit + shell tests
- `tests/test_completion.py` — engine, protocol, public API, hidden commands
- `tests/test_completion_properties.py` — Hypothesis properties
- `tests/test_completion_shells.py` — real-shell adapters (`@pytest.mark.shell`)
- `tests/golden/completion_tool_{bash,zsh,fish,powershell}.txt` — generated scripts

### Modified

- `src/argbuilder/_spec.py` — `ValueHint`, `value_hint`, `hidden`
- `src/argbuilder/_arg.py` — `Arg.value_hint(...)`
- `src/argbuilder/_build.py` — resolve new fields, root-hide invariant
- `src/argbuilder/_command.py` — `hide`, `complete`, `render_completion`,
  `get_matches()` protocol hook
- `src/argbuilder/_help.py` — hidden subcommands in help/usage
- `src/argbuilder/_docs.py` — hidden subcommands and subtrees in Markdown
- `src/argbuilder/_parser.py` — hidden subcommands excluded from suggestions
- `src/argbuilder/__init__.py` — exports
- `README.md` — “Shell completion” section, hint scope and directive parity
- `CHANGELOG.md` — Unreleased “Added”
- `pyproject.toml` — `shell` pytest marker
- `mise.toml` — `test:completion`; `test` excludes shell; `ci` includes it
- `.github/workflows/ci.yml` — dedicated `Completion` job

## Verification (2026-10-16)

```bash
mise run ci:fast        # ruff check, format check, ty: PASS
mise run test           # 528 passed, 8 deselected, 100% coverage: PASS
uv run pytest -q        # 532 passed, 4 skipped (fish/pwsh/shellcheck missing): PASS
mise run test:completion # 4 passed, 4 skipped locally: PASS
mise run contract:check # 20 cases, all allowed: PASS
mise run contract:compat # behavior pass; expected declared 2.0.0 break vs v1.1.1
mise run smoke          # wheel build/install/examples: PASS
```

Docker run of `tests/test_completion_shells.py -m shell` with bash, zsh, fish,
PowerShell and shellcheck installed: **8 passed**.

`mise run test:completion` must keep `-o addopts=`; otherwise the shell-only run
fails the project-wide 100% coverage gate.

## Gotchas for the next agent

- Do **not** reintroduce raw tabs in the Python f-string shell templates.
  In `_completion.py`, the source must contain `\\t` so the emitted script contains
  the two characters `\t` (`$'\t'`), not an actual tab. Goldens contain the literal
  `\t` text.
- Shell tests are marked `@pytest.mark.shell`; `mise run test` excludes them.
- `mise run test:completion` uses `-o addopts=` and `-m shell`.
- Do not run shell tests in every Python-version matrix job; the dedicated
  `Completion` job is intentional.
- The protocol is line-oriented. Values/help tabs and newlines are replaced with
  spaces in `_one_line`; candidates are single-line by design.
- `complete()` must remain pure. File-system access belongs in the shell fallback,
  not in the engine.
- The fixture CLI is `tests/completion_cli.py`; shell tests launch it through a
  generated `tool` executable using `runpy`.
- Do not install fish/PowerShell on the user's machine without being asked; use
  Docker or CI for validation.
