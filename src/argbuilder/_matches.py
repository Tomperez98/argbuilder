"""`ArgMatches`: typed, read-only access to what was parsed."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from argbuilder._build import ResolvedArg, ResolvedCommand
from argbuilder._error import Error, ErrorKind
from argbuilder._help import usage_error
from argbuilder._invariant import bug, invariant
from argbuilder._spec import takes_values

type ValueSource = Literal["default_value", "env_variable", "command_line"]
"""Where an argument's value came from, in increasing precedence.

`"default_value"` also covers a flag's implicit False/True/0.
"""


@dataclass(frozen=True, slots=True)
class MatchedArg:
    values: tuple[Any, ...]
    source: ValueSource


class ArgMatches:
    """The parse result for one command level.

    Accessing an id the command never defined, or reading an argument the
    wrong way (`get_one` on a flag, the wrong type), is a bug in your program
    and panics, as clap's typed getters do.
    """

    __slots__ = ("_cmd", "_matched", "_subcommand")

    def __init__(
        self,
        cmd: ResolvedCommand,
        matched: Mapping[str, MatchedArg],
        subcommand: tuple[str, ArgMatches] | None,
    ) -> None:
        self._cmd = cmd
        self._matched = matched
        self._subcommand = subcommand

    def __repr__(self) -> str:
        values = {id: matched.values for id, matched in self._matched.items()}
        return f"ArgMatches({values!r}, subcommand={self._subcommand!r})"

    def get_one[T](self, id: str, type_: type[T]) -> T | None:
        """The single value of a value-taking argument, or None when absent."""
        arg = self._value_arg(id, "get_one")
        invariant(
            not arg.is_multiple,
            f"argument {id!r} can hold several values; use get_many({id!r}, ...)",
        )
        values = self._values(id)
        return None if not values else _checked(id, values[0], type_)

    def get_required[T](self, id: str, type_: type[T]) -> T:
        """The single value of an argument that is always present: `required(True)` or defaulted.

        Use it instead of `get_one` to skip the `None` check. Calling it on an
        argument that can be absent panics on every run, not only on the runs
        where the user leaves it out.
        """
        arg = self._value_arg(id, "get_required")
        invariant(
            not arg.is_multiple,
            f"argument {id!r} can hold several values; use get_many({id!r}, ...)",
        )
        invariant(
            arg.required or bool(arg.defaults),
            f"get_required({id!r}): argument is neither required(True) nor defaulted, "
            f"so it can be absent; use get_one({id!r}, ...)",
        )
        invariant(
            arg.min_values >= 1 or bool(arg.default_missing),
            f"get_required({id!r}): num_args(0, ...) lets it be given without a value; "
            f"add default_missing_value() or use get_one({id!r}, ...)",
        )
        values = self._values(id)
        invariant(len(values) == 1, f"argument {id!r} resolved to {values!r}, not one value")
        return _checked(id, values[0], type_)

    def get_many[T](self, id: str, type_: type[T]) -> tuple[T, ...]:
        """Every value of a value-taking argument, in order; empty when absent."""
        self._value_arg(id, "get_many")
        return tuple(_checked(id, value, type_) for value in self._values(id))

    def get_flag(self, id: str) -> bool:
        arg = self._arg(id)
        invariant(
            arg.action in ("set_true", "set_false"),
            f"get_flag({id!r}): argument uses action {arg.action!r}, not 'set_true' or 'set_false'",
        )
        return _checked(id, self._values(id)[0], bool)

    def get_count(self, id: str) -> int:
        arg = self._arg(id)
        invariant(
            arg.action == "count",
            f"get_count({id!r}): argument uses action {arg.action!r}, not 'count'",
        )
        return _checked(id, self._values(id)[0], int)

    def contains_id(self, id: str) -> bool:
        """True when the argument has a value from any source, defaults included."""
        self._arg(id)
        return id in self._matched

    def value_source(self, id: str) -> ValueSource | None:
        self._arg(id)
        matched = self._matched.get(id)
        return None if matched is None else matched.source

    def error(self, kind: ErrorKind, message: str) -> Error:
        """Report your own post-parse validation failure, with this command's usage.

        Call it on the matches of the (sub)command that failed, so the usage
        line points at it: `sub.error(ValueValidation(), "...").exit()`.
        """
        return usage_error(self._cmd, kind, message)

    def subcommand(self) -> tuple[str, ArgMatches] | None:
        return self._subcommand

    def subcommand_name(self) -> str | None:
        return None if self._subcommand is None else self._subcommand[0]

    def subcommand_matches(self, name: str) -> ArgMatches | None:
        """The subcommand's matches by its name (not an alias), or None if it was not used."""
        canonical = self._cmd.subcommand_names.get(name, name)
        invariant(
            canonical == name,
            f"subcommand_matches({name!r}): {name!r} is an alias of {canonical!r}; "
            f"pass the name, as subcommand() reports it",
        )
        invariant(
            name in self._cmd.subcommands,
            f"subcommand_matches({name!r}): no such subcommand; "
            f"defined: {', '.join(sorted(self._cmd.subcommands)) or '(none)'}",
        )
        if self._subcommand is None or self._subcommand[0] != name:
            return None
        return self._subcommand[1]

    def _arg(self, id: str) -> ResolvedArg:
        arg = self._cmd.by_id.get(id)
        if arg is None:
            bug(f"unknown argument id {id!r}; defined ids: {', '.join(self._cmd.by_id)}")
        return arg

    def _value_arg(self, id: str, method: str) -> ResolvedArg:
        arg = self._arg(id)
        if not takes_values(arg.action):
            getter = "get_count" if arg.action == "count" else "get_flag"
            bug(
                f"{method}({id!r}): argument uses action {arg.action!r} "
                f"and holds no value; use {getter}({id!r})"
            )
        return arg

    def _values(self, id: str) -> tuple[Any, ...]:
        matched = self._matched.get(id)
        return () if matched is None else matched.values


def _checked[T](id: str, value: object, type_: type[T]) -> T:
    if not isinstance(value, type_):
        bug(
            f"argument {id!r} holds {type(value).__name__}, not {type_.__name__}; "
            f"check its value_parser()"
        )
    return value
