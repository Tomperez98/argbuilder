"""Immutable definitions the fluent builders produce. Plain data, no behavior."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from argbuilder._invariant import bug
from argbuilder._suggest import suggest

if TYPE_CHECKING:
    from argbuilder._value_parser import ValueParser

type ArgAction = Literal["set", "append", "set_true", "set_false", "count", "help", "version"]
"""What happens when an argument is encountered. Mirrors clap's `ArgAction`.

- `"set"`: store the value(s); using the argument twice is an error. The default.
- `"append"`: store the value(s), accumulating across occurrences.
- `"set_true"` / `"set_false"`: a flag, True (False) when present.
- `"count"`: a flag counting its occurrences (`-vvv` is 3).
- `"help"` / `"version"`: print help or the version and exit.
"""

ARG_ACTIONS: tuple[ArgAction, ...] = get_args(ArgAction.__value__)


type Shell = Literal["bash", "zsh", "fish", "powershell"]
"""A shell with a generated completion adapter."""

SHELLS: tuple[Shell, ...] = get_args(Shell.__value__)


type ValueHint = Literal["any_path", "file", "dir", "executable"]
"""What a value is, so shell completion can offer the right candidates.

Only the path hints are accepted. clap's other hints (`command`, `username`,
`hostname`, `env_var`) need shell-specific knowledge this package does not
implement, so accepting them would silently do nothing. It only affects
completion; parsing never reads it.
"""

VALUE_HINTS: tuple[ValueHint, ...] = get_args(ValueHint.__value__)


def check_value_hint(owner: str, value: object) -> ValueHint:
    """Panic unless `value` is one of `ValueHint`'s strings, suggesting the closest."""
    if value in VALUE_HINTS:
        return cast("ValueHint", value)
    close = suggest(str(value).lower(), VALUE_HINTS)
    hint = f"; did you mean {close!r}?" if close else ""
    bug(f"{owner}.value_hint() takes one of {', '.join(VALUE_HINTS)}, got {value!r}{hint}")


def check_action(owner: str, value: object) -> ArgAction:
    """Panic unless `value` is one of `ArgAction`'s strings, suggesting the closest."""
    if value in ARG_ACTIONS:
        return cast("ArgAction", value)
    close = suggest(str(value).lower(), ARG_ACTIONS)
    hint = f"; did you mean {close!r}?" if close else ""
    bug(f"{owner}.action() takes one of {', '.join(ARG_ACTIONS)}, got {value!r}{hint}")


def takes_values(action: ArgAction) -> bool:
    return action in {"set", "append"}


_NEGATIVE_NUMBER = re.compile(r"-\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_NEGATIVE_NUMBER_PREFIX = re.compile(r"-\d+(?:\.\d*)?(?:[eE][+-]?\d*)?")


def is_negative_number(token: str) -> bool:
    """Whether `token` is a plain negative numeric literal: `-5`, `-0.5`, `-1.5e-3`.

    Deliberately narrower than `float()`: no underscores, `nan`, `inf`, leading
    `+`, or locale-specific forms. `-` alone is not a number.
    """
    return _NEGATIVE_NUMBER.fullmatch(token) is not None


def is_negative_number_prefix(token: str) -> bool:
    """Whether `token` is a prefix of a negative number, for completion (`-1.`)."""
    return _NEGATIVE_NUMBER_PREFIX.fullmatch(token) is not None


@dataclass(frozen=True, slots=True)
class ArgSpec:
    id: str
    short: str | None = None
    long: str | None = None
    help: str | None = None
    value_name: str | None = None
    required: bool = False
    action: ArgAction = "set"
    value_parser: ValueParser[Any] | None = None
    num_args: tuple[int, int | None] | None = None
    default_values: tuple[str, ...] = ()
    default_missing_values: tuple[str, ...] = ()
    env: str | None = None
    conflicts_with: frozenset[str] = frozenset()
    requires: frozenset[str] = frozenset()
    overrides_with: frozenset[str] = frozenset()
    exclusive: bool = False
    required_unless_present: frozenset[str] = frozenset()
    required_if_eq: tuple[tuple[str, str], ...] = ()
    allow_hyphen_values: bool = False
    allow_negative_numbers: bool = False
    require_equals: bool = False
    """Only accept a value with `=`: `--color=always`, never `--color always`."""
    value_delimiter: str | None = None
    last: bool = False
    trailing_var_arg: bool = False
    hide: bool = False
    global_: bool = False
    value_hint: ValueHint | None = None
    aliases: tuple[str, ...] = ()
    """Hidden extra long names."""
    visible_aliases: tuple[str, ...] = ()
    short_aliases: tuple[str, ...] = ()
    visible_short_aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GroupSpec:
    id: str
    args: tuple[str, ...] = ()
    required: bool = False
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    about: str | None = None
    version: str | None = None
    args: tuple[ArgSpec, ...] = ()
    groups: tuple[GroupSpec, ...] = ()
    subcommands: tuple[CommandSpec, ...] = ()
    subcommand_required: bool = False
    args_conflicts_with_subcommands: bool = False
    completion_subcommand: bool = False
    arg_required_else_help: bool = False
    disable_help_flag: bool = False
    disable_version_flag: bool = False
    disable_help_subcommand: bool = False
    hidden: bool = False
    aliases: tuple[str, ...] = ()
    """Hidden extra names."""
    visible_aliases: tuple[str, ...] = ()
