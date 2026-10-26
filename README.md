# argbuilder

**CLI bugs should fail in your test, not in your user's terminal.**

[![CI](https://github.com/Tomperez98/argbuilder/actions/workflows/ci.yml/badge.svg)](https://github.com/Tomperez98/argbuilder/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/argbuilder)](https://pypi.org/project/argbuilder/)

argbuilder is a zero-dependency Python CLI builder with a checkable
correctness contract. A broken *definition* raises `AssertionError` at the
builder call — or at build, for rules that span arguments. A broken *command
line* comes back as a structured `Error` from `try_get_matches_from`, so a
test can assert on it; `get_matches()` prints it and exits.

Parsing itself is pure: `try_get_matches_from(argv, env=...)` never reads
`sys.argv`, `os.environ` or the terminal, so the CLI contract can be verified
in one fast test — no subprocess, no terminal, no mocked environment.

The [clap] model, for Python: immutable builders, typed getters, and one
source of truth for help, Markdown docs and shell completion.

> **Python 3.12+** · no dependencies ·
> [github.com/Tomperez98/argbuilder](https://github.com/Tomperez98/argbuilder)

```python
from argbuilder import Arg, Command


def cli() -> Command:
    return (
        Command("greet")
        .arg(Arg("name").required(True))
        .arg(
            Arg("times")
            .long("times")
            .env("GREET_TIMES")
            .value_parser(range(1, 6))
            .default_value("1")
        )
    )


if __name__ == "__main__":
    matches = cli().get_matches()  # reads sys.argv + os.environ, exits on error
    name = matches.get_required("name", str)  # required(True): never None
    times = matches.get_required("times", int)  # defaulted: never None
    for _ in range(times):
        print(f"hello, {name}")
```

```text
$ greet Ada --times 6
error: invalid value '6' for '--times <TIMES>': 6 is not in 1..=5

Usage: greet [OPTIONS] <NAME>

For more information, try '--help'.
```

Verify the same CLI without a process:

```python
from argbuilder import ArgMatches


def test_cli() -> None:
    cli().debug_assert()  # the definition is legal
    matches = cli().try_get_matches_from(["greet", "Ada"], env={"GREET_TIMES": "3"})
    assert isinstance(matches, ArgMatches)
    assert matches.get_required("times", int) == 3
```

A fuller CLI with subcommands is in [`examples/git.py`](examples/git.py)
(`uv run examples/git.py --help`).

## Built for the edit → verify loop

This is the property that matters when a coding agent is writing the CLI:
the agent does not have to remember to test every failure mode, because most
of the mechanical ones cannot pass silently.

- **Definition bugs fail at the definition.** Duplicate shorts, a default the
  parser rejects, `required(True)` plus a default, `short("ab")` — an
  `AssertionError` names the command and argument. Cross-argument rules fail
  at build or `debug_assert()`. Raised explicitly, so `python -O` does not
  strip it.
- **Reads are typed at the call site.** `get_required("port", int)` returns
  an `int` or raises there. `get_one` is `T | None`; `get_many` is a tuple;
  `get_flag` is a `bool`. No dictionary lookups, no stringly-typed parsed
  values, and the optional case is explicit.
- **The parser is pure.** `try_get_matches_from(argv, env={...})` never
  touches `sys.argv`, `os.environ`, or the terminal. Tests are deterministic,
  fast, and parallel.
- **Errors are data.** `ErrorKind` is a union of frozen dataclasses. Match
  `InvalidValue(...)` or `UnknownArgument(suggestion="--port")`; do not regex
  a message.
- **One definition, every output.** Help, Markdown docs and shell completion
  render from the same tree; the pure renderers make drift a test failure.

**What the contract catches:** invalid CLI structure, wrong getter/type/
action, unknown ids, invalid values, missing required arguments, conflicts,
and contradictory requirements.

**What it does not:** what your `main` does with the parsed values. argbuilder
checks the CLI boundary, not your business logic.

Working with a coding agent? Put [`AGENTS.md`](AGENTS.md) in context.

## Install

```bash
uv add argbuilder
# or
pip install argbuilder
```

Python 3.12+ and no dependencies. To track an unreleased `main` instead of a
release:

```bash
uv add git+https://github.com/Tomperez98/argbuilder
# or
pip install "argbuilder @ git+https://github.com/Tomperez98/argbuilder"
```

## The contract: bugs panic, user mistakes return values

| Who made the mistake | Example | What happens |
|---|---|---|
| **You**, defining the CLI | two args claim `-v`, `required(True)` plus a default, a default the parser rejects, `short("ab")`, an argument reusing the reserved id `help` / `version` | `AssertionError`, naming the command and argument. Builder-local mistakes fail at the builder call, cross-argument ones at build. Raised explicitly, so `python -O` doesn't strip them. |
| **You**, reading matches | unknown id, `get_one("port", str)` on an int, `get_one` on an `Append` arg, `get_flag` on a value arg, `get_required` on an arg that can be absent | `AssertionError` at the call |
| **The user**, typing the command | unknown flag, bad value, missing required arg, `--help` | `try_get_matches_from` **returns** an `Error`. `get_matches` prints it and exits (0 for help/version, 2 otherwise). |

That second row is why matches are read with typed getters, not a dictionary:

| Getter | Use it for |
|---|---|
| `get_required(id, T)` | an arg that is `required(True)` or has a default — never `None` |
| `get_one(id, T)` | an optional value, as `T \| None` |
| `get_many(id, T)` | `append` and multi-value args: a `tuple`, empty when absent |
| `get_flag(id)` | a `set_true` / `set_false` flag, as `bool` |
| `get_count(id)` | a `count` flag, as `int` |
| `contains_id(id)` | whether a value is present from any source, defaults included |
| `value_source(id)` | `"default_value"`, `"env_variable"` or `"command_line"` |

Catch definition bugs in CI the way clap recommends:

```python
def test_cli() -> None:
    cli().debug_assert()
```

Test parsing with no process involved. The parser is pure, and the environment
is a parameter that defaults to empty:

```python
from argbuilder import ArgMatches

result = cli().try_get_matches_from(["git", "push", "origin"], env={"GIT_PORT": "8080"})
assert isinstance(result, ArgMatches)
sub = result.subcommand_matches("push")
assert sub is not None and sub.get_required("port", int) == 8080
```

Post-parse validation uses the same error format through
`ArgMatches.error()` (or `Command.error()`):

```python
from argbuilder import ValueValidation

matches.error(ValueValidation(), "--from must precede --to").exit()
```

Only `get_matches()` reads `sys.argv` and `os.environ` for parsing. Printing
(`Error.exit()`) is the only other place that looks at the process: it checks
the terminal it writes to, below.

## Terminal output

When `get_matches()` prints help or an error, it styles the output for the
stream it writes to:

- **Color** only on a terminal, and never when `NO_COLOR` is set or `TERM=dumb`.
- **Wrapping** of help text to the terminal width (or `COLUMNS`), capped at
  100 columns. Help moves below its flag when the terminal is too narrow for
  two columns.

Rendering itself is pure and plain by default. Pass a `Style` to see what a
terminal gets:

```python
from argbuilder import Style

assert "\x1b[" not in cli().render_help()
print(cli().render_help(Style(color=True, width=60)))
```

## Shell completion

### The `completion` command

Enable a visible `completion <SHELL>` command with one builder call on the
root command:

```python
cli = Command("mycli").completion_subcommand(True)
```

Then load completion for the current shell session, with no files to copy:

```bash
# bash
eval "$(mycli completion bash)"

# zsh
eval "$(mycli completion zsh)"

# fish
mycli completion fish | source

# PowerShell
mycli completion powershell | Out-String | Invoke-Expression
```

Nothing is written to `~/.bashrc`, `~/.zshrc`, `~/.config/fish/config.fish` or
`$PROFILE`; completion lasts until the session ends. To keep it, source the
same command from a startup file or install a generated script where the
shell looks for completions.

The command is opt-in, listed in help, and accepted only on the root command;
a nested `completion_subcommand(True)` is a definition bug. The executable
must be on `PATH` under the same name as `Command(...)`: running a file as
`python mycli.py` does not create a `mycli` executable.

`get_matches()` and `get_matches_from()` print the script to stdout and exit 0.
`try_get_matches_from()` stays pure: it returns the parsed `ArgMatches` and
never prints or exits. A custom parser that only calls `try_get_matches_from()`
must call `render_completion()` itself.

### Generated scripts

`cmd.render_completion(shell)` returns a completion script for `bash`, `zsh`,
`fish` or `powershell`. The script is a thin adapter: it calls the program as
`tool __complete <cursor> <argv...>`, and `get_matches()` answers that request
before parsing. There is no hidden command to add, and no regeneration step in
the hot path.

Generate the script wherever you already generate docs:

```python
from pathlib import Path

command = cli()
Path("tool.bash").write_text(command.render_completion("bash"))
Path("_tool").write_text(command.render_completion("zsh"))
Path("tool.fish").write_text(command.render_completion("fish"))
Path("tool.ps1").write_text(command.render_completion("powershell"))
```

Install it the way each shell expects:

- **bash**: `source tool.bash` from `~/.bashrc`, or put it in
  `/etc/bash_completion.d/`. Bash 3.2 (macOS) is supported; bash 4+ can also
  honour the directory-only and no-file directives.
- **zsh**: save the output as `_tool` in a directory on `$fpath`, then run
  `compinit`.
- **fish**: save it as `~/.config/fish/completions/tool.fish`.
- **PowerShell**: `. tool.ps1` from `$PROFILE`.

Candidates come from `Command.complete(argv, cursor)`, which walks the same
resolved command tree as the parser and returns a `CompletionResult` plus a
`CompletionDirective`. It is pure and directly testable:

```python
result = command.complete(["git", "push", "--color", ""])
assert "auto" in [candidate.value for candidate in result.candidates]
```

Point shell completion at paths and directories:

```python
Arg("config").long("config").value_hint("file")
Arg("workdir").long("workdir").value_hint("dir")
```

`ValueHint` supports `any_path`, `file`, `executable` (file completion) and
`dir` (directory-only completion). clap's `command`, `username`, `hostname`
and `env_var` hints are not accepted: they need shell-specific knowledge this
package does not implement, so accepting them would silently do nothing.

Hidden arguments and hidden subcommands are never offered; use
`Command("__internal").hide(True)` for those. `hide(True)` applies to
subcommands only. The generated scripts rely on `get_matches()`;
`get_matches_from()` also handles the `completion` command. If an application
uses `try_get_matches_from()` directly, it should call `complete()` and
`render_completion()` itself.

Directive support varies by shell. zsh honours file, directory-only and
no-file completion. bash 4+ honours directory-only and no-file completion;
bash 3.2 always lets the shell fall back to files. fish can suppress file
completion, but neither fish nor PowerShell can restrict completion to
directories, so `dir` still offers files there. Path hints apply to a separate
value word: `--config ` completes paths, while `--config=` suppresses path
completion, so `--config=path` has to be typed in full. Choice values such as
`--color=auto` are completed by the engine either way. For a
`require_equals()` option, completion offers the option name; type `=` before
the value. Offering the trailing `=` itself needs per-shell no-space support
and is still a follow-up.

## Markdown docs

`cmd.render_markdown()` turns a `Command` into a Markdown page: one `#`
section for the command, one `##` section per subcommand at any depth, named
by its full path (`git remote add`). Content and visibility mirror
`render_help` exactly — hidden args, hidden aliases and hidden subcommands
stay out, an inherited global argument is documented again on every
subcommand, the same as `--help` shows it there — so the two can never
quietly drift apart.

```python
from pathlib import Path

Path("docs/cli.md").write_text(cli().render_markdown())
```

There's no separate build step or CLI: run that wherever you'd otherwise
regenerate docs (a script, a `pytest` golden test, a CI job) and commit the
result.

For agent-facing context, see [`AGENTS.md`](AGENTS.md); for a compact index
that LLM tools can fetch first, see [`llms.txt`](llms.txt).

## clap → argbuilder

Coming from [clap]? The builder API maps almost one to one:

| clap | argbuilder |
|---|---|
| `Command::new("x")` / `Arg::new("x")` | `Command("x")` / `Arg("x")`, both immutable (each method returns a new value) |
| `.value_parser(value_parser!(u16).range(1..))` | `.value_parser(range(1, 65536))`, `ValueParser.integer(min=1)` |
| `.value_parser(["a", "b"])`, `ValueEnum` | `.value_parser(["a", "b"])`, `.value_parser(Mode)` with `type Mode = Literal["a", "b"]` |
| `value_parser!(PathBuf)` | `.value_parser(Path)`. Any `str -> T` callable works, and a `ValueError` becomes a user error. |
| `ArgAction::{Set, Append, SetTrue, SetFalse, Count, Help, Version}` | `"set"`, `"append"`, `"set_true"`, `"set_false"`, `"count"`, `"help"`, `"version"` (default: `"set"`) |
| `ValueSource::{DefaultValue, EnvVariable, CommandLine}` | `"default_value"`, `"env_variable"`, `"command_line"` |
| `ErrorKind::InvalidValue`, plus `Error::get(ContextKind::…)` | `InvalidValue(argument, value, reason, …)`: the context is fields on the kind |
| `.num_args(1..)`, `.num_args(0..=1)`, `.num_args(2)` | `.num_args(1, None)`, `.num_args(0, 1)`, `.num_args(2)` |
| `get_one::<T>`, `get_many::<T>`, `get_flag`, `get_count` | `get_one(id, T)`, `get_many(id, T)` (a tuple, empty if absent), `get_flag`, `get_count` |
| `get_one::<T>(id).expect(..)` on a required or defaulted arg | `get_required(id, T)` |
| `try_get_matches_from` → `Result<ArgMatches, Error>` | `try_get_matches_from` → `ArgMatches \| Error` |
| `Error::exit`, `ErrorKind`, `Command::error` | `Error.exit()`, `ErrorKind`, `Command.error()`, and `ArgMatches.error()` for the subcommand you're in |
| `Arg::global(true)` | `.global_(True)` (`global` is a Python keyword). See below for how repeats work. |
| `Arg::last(true)` | `.last(True)`: a positional filled only after a literal `--`, taking every token after it verbatim (`mytool run -- cargo build --release`). |
| `Arg::require_equals(true)` | `.require_equals(True)`: only `--color=always` / `-c=always`; the next token is never consumed. |
| `Arg::allow_negative_numbers(true)` | `.allow_negative_numbers(True)`: `-5`, `-0.5`, `-1.5e-3` are values; other hyphen tokens still parse as flags. |
| `Arg::trailing_var_arg(true)` | `.trailing_var_arg(True)`: after the first value, every token is captured verbatim, with no `--`. |
| `Arg::overrides_with`, `Arg::exclusive` | `.overrides_with(id)`, `.overrides_with_all(ids)`, `.exclusive(True)`. |
| `Arg::required_unless_present`, `Arg::required_if_eq` | The same names. |
| `Command::args_conflicts_with_subcommands(true)` | `.args_conflicts_with_subcommands(True)`. |
| `alias`, `visible_alias`, `short_alias`, `visible_short_alias` | The same names, on `Arg` and (`alias` / `visible_alias`) on `Command`. Call once per alias. |
| the `help` subcommand, `disable_help_subcommand` | The same: `git help`, `git help push` |

`ArgAction` and `ValueSource` are `Literal` strings, so a type checker
catches a typo like `.action("cout")`, and at runtime it panics with a
suggestion. `ErrorKind` is a union of frozen dataclasses that carry what went
wrong, so you can act on an error without parsing its message:

```python
match result.kind:
    case DisplayHelp() | DisplayVersion():
        ...
    case InvalidValue(argument=argument, value=None):
        ...  # the option was given with no value
    case UnknownArgument(argument=typed, suggestion=str(closest)):
        ...  # e.g. typed "--prot", closest "--port"
```

`require_equals(True)` applies to both spellings of an option: `--color=always`
and `-c=always` work, while `--color always`, `-c always` and `-calways` are
errors. It only applies to value-taking options with `short()` or `long()`;
a positional has no `=` spelling. With `num_args(0, 1)`, a bare `--color`
still selects the argument and uses `default_missing_value()` or no value,
and never consumes the next token. `value_delimiter()` may split the single
inline value, so `--tags=a,b` can produce several values.

`allow_negative_numbers(True)` accepts the plain negative numeric grammar
`-5`, `-0.5`, `-1.5e-3` (no underscores, `nan`, `inf`, or bare `-`). It works
for options and positionals; `-x` still parses as a flag. A digit short such
as `-5` cannot coexist with it on the same command, because both would claim
the same token.

`trailing_var_arg(True)` is the no-`--` wrapper mode:
`mytool run cargo build --release` stores `("cargo", "build", "--release")`.
It must be the final positional with `num_args(..., None)` and cannot be
combined with `last()` or `allow_hyphen_values()`. A subcommand name still
wins before the trailing positional starts; a later `--` is a value.

`overrides_with(id)` is last-one-wins: using the argument removes earlier
command-line values of `id`. Defaults and environment values are not erased;
they become effective again if the overridden argument has no explicit value.
Both arguments must be global or both local, and an argument cannot both
override and conflict with the same target. `exclusive(True)` reports an
`ArgumentConflict` when any other argument is explicit; defaults do not count,
environment values do.

`required_unless_present(id)` requires an argument unless `id` has a value
from the command line or environment, or has a user-written default. A flag's
implicit `False`/`0` does not count. `required_if_eq(id, value)` requires the
argument when `id`'s effective raw spelling equals `value`; the comparison is
on the raw command-line, environment or default string, not the parsed value.
Both forms combine all missing arguments into one `MissingRequiredArgument`.
A conditional argument is a definition bug if it is also `required(True)` or
has a default.

`args_conflicts_with_subcommands(True)` makes a command's own arguments
mutually exclusive with its subcommands: `stash --message wip` and
`stash push file` work, while mixing them returns `SubcommandConflict`.
Defaults and environment values do not count as parent arguments, but an
explicit parent global does; a global given only inside the subcommand does
not. A required parent argument or required group would make every subcommand
unusable, so that combination panics when the command is built.

Also supported: `env`, `default_value(s)`, `default_missing_value`,
`conflicts_with(_all)`, `requires`, `overrides_with(_all)`, `exclusive`,
`required_unless_present`, `required_if_eq`, `ArgGroup` (`required`, `multiple`),
`allow_hyphen_values`, `allow_negative_numbers`, `require_equals`,
`value_delimiter`, `last`, `trailing_var_arg`, `hide`, `value_hint`,
`args_conflicts_with_subcommands`, `arg_required_else_help`,
`disable_help_flag` / `disable_version_flag`, typo suggestions for arguments,
subcommands and values, and a tip when an option is used at the wrong level
(`git push -V`: "'-V' is an option of 'git'; put it before 'push'").

`-h/--help` and `-V/--version` are added for you. `help` and `version` are
reserved ids: an argument with one of them must use the matching `help` /
`version` action (which replaces the automatic flag) or be renamed.

A global option is read the same way at every level (`matches.get_count("verbose")`
and `sub.get_count("verbose")` agree), and the whole command line counts as
one list of occurrences. `git -v push -v` counts 2, and `append` values add up
left to right. A `set` option given at two levels is an error ("cannot be used
multiple times"). clap would silently keep the deeper value instead. Globals
can't be positional or required, and their `conflicts_with` / `requires` may
only name other globals, because every subcommand has to be able to check them.

## Development

Everything CI runs — lint, format, type check, the tests at 100% branch
coverage, a build-and-import smoke test of the wheel, and the shape and
behavior contract checks — is one [`mise`](https://mise.jdx.dev) task:

```bash
mise run ci
```

The pieces on their own:

```bash
uv run ruff check           # lint
uv run ruff format --check  # format
uv run ty check --error-on-warning  # type check, warnings fatal
uv run pytest               # tests
mise run contract:check     # this build against this spec
mise run contract:compat    # this build against the last release
```

The contract tasks need the .NET SDK (`global.json` pins it).

CI runs the fast checks once and the tests on Python 3.12–3.15
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)). To release, write
the [`CHANGELOG.md`](CHANGELOG.md) entry and bump the version in the same PR
(`uv version --bump patch`), merge it, then run `mise run release:tag`: the
tag triggers [`release.yml`](.github/workflows/release.yml), which publishes
to PyPI and then checks the published package
([`release_validate.yml`](.github/workflows/release_validate.yml), also run
weekly). The full checklist and the recovery steps for a failed release are
in [`RELEASING.md`](RELEASING.md).

[clap]: https://docs.rs/clap/latest/clap/_tutorial/index.html
