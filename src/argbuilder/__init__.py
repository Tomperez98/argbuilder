"""Typed command-line parsing from immutable builders.

Bugs panic, user mistakes return values:

- A broken *definition* (duplicate `-v`, a default the parser rejects,
  `get_one` with the wrong type) raises `AssertionError` at the exact line.
- A bad *command line* is an `Error` value from `try_get_matches_from`, or a
  printed message plus exit code 2 from `get_matches`.

`ArgAction` and `ValueSource` are `Literal` strings: `.action("count")`.
`ErrorKind` is a union of frozen dataclasses that carry what went wrong:
`match error.kind: case InvalidValue(argument=a, value=v): ...`.
"""

from argbuilder._arg import Arg, ArgGroup
from argbuilder._command import Command
from argbuilder._error import (
    ArgumentConflict,
    DisplayHelp,
    DisplayHelpOnMissingArgumentOrSubcommand,
    DisplayVersion,
    Error,
    ErrorKind,
    InvalidSubcommand,
    InvalidValue,
    MissingRequiredArgument,
    MissingSubcommand,
    ParseFailure,
    TooFewValues,
    TooManyValues,
    UnknownArgument,
    ValueValidation,
)
from argbuilder._matches import ArgMatches, ValueSource
from argbuilder._spec import ArgAction
from argbuilder._style import Style
from argbuilder._value_parser import Invalid, ValueParser, ValueParserLike

__all__ = [
    "Arg",
    "ArgAction",
    "ArgGroup",
    "ArgMatches",
    "ArgumentConflict",
    "Command",
    "DisplayHelp",
    "DisplayHelpOnMissingArgumentOrSubcommand",
    "DisplayVersion",
    "Error",
    "ErrorKind",
    "Invalid",
    "InvalidSubcommand",
    "InvalidValue",
    "MissingRequiredArgument",
    "MissingSubcommand",
    "ParseFailure",
    "Style",
    "TooFewValues",
    "TooManyValues",
    "UnknownArgument",
    "ValueParser",
    "ValueParserLike",
    "ValueSource",
    "ValueValidation",
]
