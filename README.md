# argbuilder ([clap](https://docs.rs/clap/latest/clap/) for python)

[![CI](https://github.com/Tomperez98/argbuilder/actions/workflows/ci.yml/badge.svg)](https://github.com/Tomperez98/argbuilder/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/argbuilder)](https://pypi.org/project/argbuilder/)

Build command-line interfaces in Python from typed, immutable builders — the
[clap] model.

A broken *definition* fails when the command is built, in CI, not in front of a
user. A broken *command line* comes back as an `Error` you can inspect, with the
message, typo suggestion and help ready to print.

> **Python 3.12+** · no dependencies ·
> [github.com/Tomperez98/argbuilder](https://github.com/Tomperez98/argbuilder)

```python
from argbuilder import Arg, Command, ValueValidation


def cli() -> Command:
    return (
        Command("git")
        .about("A fictional versioning CLI")
        .version("1.0.0")
        .subcommand_required(True)
        .arg(Arg("verbose").short("v").long("verbose").action("count"))
        .subcommand(
            Command("push")
            .about("Pushes things")
            .arg(Arg("remote").required(True))
            .arg(
                Arg("port")
                .short("p")
                .long("port")
                .value_parser(range(1, 65536))
                .env("GIT_PORT")
                .default_value("22")
            )
            .arg(Arg("force").short("f").long("force").action("set_true"))
        )
    )


if __name__ == "__main__":
    matches = cli().get_matches()  # reads sys.argv + os.environ, exits on error
    match matches.subcommand():
        case ("push", sub):
            remote = sub.get_required("remote", str)  # str: required(True), never None
            port = sub.get_required("port", int)  # int: it has a default
            force = sub.get_flag("force")  # bool
            if remote.startswith("-"):
                sub.error(ValueValidation(), "remote must not start with '-'").exit()
```

```text
$ git push origin -p 99999
error: invalid value '99999' for '--port <PORT>': 99999 is not in 1..=65535

Usage: git push [OPTIONS] <REMOTE>

For more information, try '--help'.
```

A fuller CLI is in [`examples/git.py`](examples/git.py)
(`uv run examples/git.py --help`).

## Or derive it from classes

Like clap's `#[derive(Parser)]`: fields describe the arguments, their types
pick the action, and parsing returns an instance. The derive only builds a
`Command`, so help, errors and the rules above are the same.

```python
from __future__ import annotations  # lets Git name Clone before it's defined

from pathlib import Path

from argbuilder import Parser, arg


class Git(Parser, version="1.0.0"):
    """A fictional versioning CLI."""  # the docstring's first paragraph is `about`

    verbose: int = arg(short=True, long=True, action="count", global_=True)
    command: Clone | Push  # add `| None = None` to make it optional


class Clone(Parser):
    """Clones repos."""

    remote: str
    dir: Path | None = None


class Push(Parser):
    """Pushes things."""

    port: int = arg(short=True, long=True, value_parser=range(1, 65536), default=22)
    force: bool = arg(short=True, long=True)


git = Git.parse()  # or Git.try_parse_from(argv, env) -> Git | Error
match git.command:
    case Push(port=port, force=force):
        ...
    case Clone(remote=remote):
        ...
```

| Field | Becomes |
|---|---|
| `x: T` | required; `T` picks the value parser (`int`, `Path`, a `Literal` alias, any `str -> T` callable) |
| `x: T = 22` or `arg(default=22)` | `default_value("22")`, checked to parse back to `22` |
| `x: T \| None` | optional, `None` when absent |
| `x: tuple[T, ...]` | `append`: every value, `()` when absent; `arg(required=True)` for at least one |
| `x: bool` | `set_true` flag; `arg(action="set_false")` for the opposite |
| `x: int = arg(action="count")` | `count` flag |
| `x: A \| B` (`Parser` classes) | the subcommand, named in kebab-case (`RemoteAdd` → `remote-add`) |
| `x: Shared` (an `Args` class) | its fields, flattened in (clap's `#[command(flatten)]`) |

Without `short` or `long` a field is positional. `short=True` / `long=True`
/ `env=True` derive `-d` / `--dry-run` / `DRY_RUN` from the field name.
Command options go on the class: `name`, `about`, `version`, `aliases`,
`visible_aliases`, `arg_required_else_help`, `disable_help_flag`,
`disable_version_flag`, `disable_help_subcommand`.

Subclasses are frozen, keyword-only dataclasses (don't add `@dataclass`),
and type checkers see them that way. Definition bugs still panic: class
options at the `class` statement, fields at the first `to_command()` or
parse, since annotations may name classes defined further down. Test them
with `Git.to_command().debug_assert()`.

For anything the derive doesn't cover, extend the builder and read the
result back: `Git.from_arg_matches(Git.to_command().arg(...).get_matches())`.
The same CLI as [`examples/git.py`](examples/git.py), derived, is in
[`examples/git_derive.py`](examples/git_derive.py).

Argument types are read at runtime, so keep their imports out of
`if TYPE_CHECKING:`. With ruff's `TC` rules, add:

```toml
[lint.flake8-type-checking]
runtime-evaluated-base-classes = ["argbuilder.Parser", "argbuilder.Args"]
```

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

## Docs

`cmd.render_markdown()` turns a `Command` into a Markdown page: one `#`
section for the command, one `##` section per subcommand at any depth, named
by its full path (`git remote add`). Content and visibility mirror
`render_help` exactly — hidden args and hidden aliases stay out, an inherited
global argument is documented again on every subcommand, the same as
`--help` shows it there — so the two can never quietly drift apart.

```python
from pathlib import Path

Path("docs/cli.md").write_text(cli().render_markdown())
```

There's no separate build step or CLI: run that wherever you'd otherwise
regenerate docs (a script, a `pytest` golden test, a CI job) and commit the
result.

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

Also supported: `env`, `default_value(s)`, `default_missing_value`,
`conflicts_with(_all)`, `requires`, `ArgGroup` (`required`, `multiple`),
`allow_hyphen_values`, `value_delimiter`, `last`, `hide`, `arg_required_else_help`,
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
coverage, and a build-and-import smoke test of the wheel — is one
[`mise`](https://mise.jdx.dev) task:

```bash
mise run ci
```

The pieces on their own:

```bash
uv run ruff check           # lint
uv run ruff format --check  # format
uv run ty check             # type check
uv run pytest               # tests
```

CI runs the fast checks once and the tests on Python 3.12–3.14
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)). To release, bump the
version in a PR (`uv version --bump patch`), merge it, then run
`mise run release:tag`: the tag triggers
[`.github/workflows/release.yml`](.github/workflows/release.yml), which
publishes to PyPI and then checks the published package
([`.github/workflows/release_validate.yml`](.github/workflows/release_validate.yml),
also run daily).

[clap]: https://docs.rs/clap/latest/clap/_tutorial/index.html
