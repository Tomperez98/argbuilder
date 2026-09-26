"""Immutable definitions the fluent builders produce. Plain data, no behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, get_args

from argbuilder._invariant import bug

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


def check_action(owner: str, value: object) -> ArgAction:
    """Panic unless `value` is one of `ArgAction`'s strings, suggesting the closest."""
    for action in ARG_ACTIONS:
        if value == action:
            return action
    import difflib

    close = difflib.get_close_matches(str(value).lower(), ARG_ACTIONS, n=1)
    hint = f"; did you mean {close[0]!r}?" if close else ""
    bug(f"{owner}.action() takes one of {', '.join(ARG_ACTIONS)}, got {value!r}{hint}")


def takes_values(action: ArgAction) -> bool:
    return action in {"set", "append"}


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
    allow_hyphen_values: bool = False
    value_delimiter: str | None = None
    last: bool = False
    hide: bool = False
    global_: bool = False
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
    arg_required_else_help: bool = False
    disable_help_flag: bool = False
    disable_version_flag: bool = False
    disable_help_subcommand: bool = False
    aliases: tuple[str, ...] = ()
    """Hidden extra names."""
    visible_aliases: tuple[str, ...] = ()
