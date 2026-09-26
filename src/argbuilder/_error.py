"""The one error vocabulary for *user* mistakes on the command line."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn

from argbuilder._invariant import check_variant, invariant, variant_classes
from argbuilder._style import PLAIN, Style, terminal_style

if TYPE_CHECKING:
    from collections.abc import Callable

# -- ErrorKind: why parsing stopped (the relevant subset of clap's `ErrorKind`)
#
# Variants carry what went wrong as data, so callers can inspect an error
# without parsing its message. `argument` fields hold the argument as help and
# errors show it: `--port <PORT>`, `-v`, `<FILE>...`.


@dataclass(frozen=True, slots=True)
class InvalidValue:
    """A value the argument's parser rejects, or no value where one is required."""

    argument: str
    value: str | None
    """What the user gave; None when no value was supplied at all."""
    reason: str | None = None
    """The parser's explanation, e.g. `99999 is not in 1..=65535`."""
    possible_values: tuple[str, ...] = ()
    suggestion: str | None = None
    """The closest possible value, if any is close."""
    env: str | None = None
    """The environment variable the value came from, if not the command line."""


@dataclass(frozen=True, slots=True)
class UnknownArgument:
    """An option or positional the command does not define."""

    argument: str
    """As typed: `--prot`, `-x`, `extra`."""
    suggestion: str | None = None
    """The closest option this command does define, if any is close."""


@dataclass(frozen=True, slots=True)
class InvalidSubcommand:
    """A subcommand name the command does not define."""

    name: str
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class TooManyValues:
    """More values than `num_args` allows."""

    argument: str
    value: str
    """The first value that did not fit."""
    env: str | None = None


@dataclass(frozen=True, slots=True)
class TooFewValues:
    """Fewer values than `num_args` requires."""

    argument: str
    expected: int
    actual: int
    env: str | None = None


@dataclass(frozen=True, slots=True)
class ArgumentConflict:
    """Arguments that cannot be used together, or one argument used twice."""

    argument: str
    other: str | None
    """The argument it conflicts with; None when `argument` was repeated."""


@dataclass(frozen=True, slots=True)
class MissingRequiredArgument:
    """Required arguments or groups that are absent."""

    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MissingSubcommand:
    """`subcommand_required(True)` and no subcommand was given."""

    command: str
    """The command path, e.g. `git stash`."""
    subcommands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValueValidation:
    """For your own post-parse checks via `ArgMatches.error()` or `Command.error()`."""


@dataclass(frozen=True, slots=True)
class DisplayHelp:
    """`--help` was given: print help to stdout, exit 0."""


@dataclass(frozen=True, slots=True)
class DisplayHelpOnMissingArgumentOrSubcommand:
    """`arg_required_else_help(True)` and no arguments: help to stderr, exit 2."""


@dataclass(frozen=True, slots=True)
class DisplayVersion:
    """`--version` was given: print the version to stdout, exit 0."""


type ParseFailure = (
    InvalidValue
    | UnknownArgument
    | InvalidSubcommand
    | TooManyValues
    | TooFewValues
    | ArgumentConflict
    | MissingRequiredArgument
    | MissingSubcommand
)
"""The kinds the parser produces for a bad command line. `describe()` words them."""

type ErrorKind = (
    ParseFailure
    | ValueValidation
    | DisplayHelp
    | DisplayHelpOnMissingArgumentOrSubcommand
    | DisplayVersion
)
"""What `Error.kind` holds. Inspect it with `match error.kind: case InvalidValue(value=v): ...`."""


_ERROR_KINDS = variant_classes(ErrorKind)


def describe(kind: ParseFailure) -> str:
    """The message for a parse failure, in clap's wording. The one place it is written."""
    match kind:
        case InvalidValue(argument, None):
            return f"a value is required for '{argument}' but none was supplied"
        case InvalidValue(argument, value, reason, possible_values, _, env):
            where = _where(argument, env)
            if possible_values:
                return (
                    f"invalid value '{value}' for {where}\n"
                    f"  [possible values: {', '.join(possible_values)}]"
                )
            return f"invalid value '{value}' for {where}: {reason}"
        case UnknownArgument(argument):
            return f"unexpected argument '{argument}' found"
        case InvalidSubcommand(name):
            return f"unrecognized subcommand '{name}'"
        case TooManyValues(argument, value, env):
            return (
                f"unexpected value '{value}' for {_where(argument, env)} found; "
                f"no more were expected"
            )
        case TooFewValues(argument, expected, actual, env):
            return (
                f"{expected} values required by {_where(argument, env)}; "
                f"only {actual} were provided"
            )
        case ArgumentConflict(argument, None):
            return f"the argument '{argument}' cannot be used multiple times"
        case ArgumentConflict(argument, other):
            return f"the argument '{argument}' cannot be used with '{other}'"
        case MissingRequiredArgument(arguments):
            listed = "\n".join(f"  {shown}" for shown in arguments)
            return f"the following required arguments were not provided:\n{listed}"
        case MissingSubcommand(command, subcommands):
            return (
                f"'{command}' requires a subcommand but one was not provided\n"
                f"  [subcommands: {', '.join(subcommands)}]"
            )


def _where(argument: str, env: str | None) -> str:
    return f"'{argument}'" + (
        "" if env is None else f" (from environment variable {env})"
    )


@dataclass(frozen=True, slots=True)
class Error:
    """Parsing did not produce matches. A returned value, not an exception.

    `--help` and `--version` arrive here too (exit code 0), as in clap.
    """

    kind: ErrorKind
    message: str
    tip: str | None = None
    usage: str | None = None
    help_hint: str | None = None
    restyle: Callable[[Style], str] | None = field(
        default=None, repr=False, compare=False
    )
    """Renders `message` again for a given `Style`. Set for help, which can wrap and color."""

    def __post_init__(self) -> None:
        check_variant(self.kind, _ERROR_KINDS, "ErrorKind", "Error kind")
        invariant(
            isinstance(self.message, str),
            f"Error message must be a str, got {self.message!r}",
        )

    @property
    def exit_code(self) -> int:
        return 0 if isinstance(self.kind, DisplayHelp | DisplayVersion) else 2

    @property
    def use_stderr(self) -> bool:
        return not isinstance(self.kind, DisplayHelp | DisplayVersion)

    def render(self, style: Style = PLAIN) -> str:
        """The text `exit()` prints. Plain unless you pass a `Style`."""
        if isinstance(
            self.kind,
            DisplayHelp | DisplayVersion | DisplayHelpOnMissingArgumentOrSubcommand,
        ):
            return self.message if self.restyle is None else self.restyle(style)
        blocks = [f"{style.error('error:')} {self.message}"]
        if self.tip is not None:
            blocks.append(f"  {style.tip('tip:')} {self.tip}")
        if self.usage is not None:
            blocks.append(f"{style.header('Usage:')} {self.usage}")
        if self.help_hint is not None:
            blocks.append(f"For more information, try {self.help_hint}.")
        return "\n\n".join(blocks) + "\n"

    def exit(self) -> NoReturn:
        """The edge: print to the right stream, styled for it, and exit with the right code."""
        stream = sys.stderr if self.use_stderr else sys.stdout
        stream.write(self.render(terminal_style(stream)))
        stream.flush()
        sys.exit(self.exit_code)
