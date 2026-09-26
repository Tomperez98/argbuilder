"""Value parsers: raw command-line string -> typed value, or `Invalid`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAliasType, get_args, get_origin

from argbuilder._invariant import bug, invariant


@dataclass(frozen=True, slots=True)
class Invalid:
    """A raw value the parser rejects. An expected failure: the user typed it."""

    message: str


@dataclass(frozen=True, slots=True)
class ValueParser[T]:
    """Turns one raw string into a `T`, or returns `Invalid`.

    `possible_values` is non-empty when the parser accepts a closed set; help
    and error output list them and suggest the closest one.
    """

    parse: Callable[[str], T | Invalid]
    possible_values: tuple[str, ...] = ()

    @staticmethod
    def from_fn[U](fn: Callable[[str], U | Invalid]) -> ValueParser[U]:
        """Adapt a plain function such as `float`, `Path` or your own.

        The function may return `Invalid` or raise `ValueError`; both become an
        invalid-value error for the user. Any *other* exception is a bug in
        the function and propagates.
        """

        def parse(raw: str) -> U | Invalid:
            try:
                return fn(raw)
            except ValueError as exc:
                return Invalid(str(exc) or f"cannot parse {raw!r}")

        return ValueParser(parse)

    @staticmethod
    def integer(min: int | None = None, max: int | None = None) -> ValueParser[int]:
        """Base-10 integers, optionally bounded (inclusive): clap's `value_parser!(i64).range(..)`."""
        invariant(
            min is None or max is None or min <= max,
            f"ValueParser.integer: min {min} is greater than max {max}",
        )
        bounds = f"{'' if min is None else min}..{'' if max is None else f'={max}'}"

        def parse(raw: str) -> int | Invalid:
            if raw == "":
                return Invalid("cannot parse integer from empty string")
            try:
                value = int(raw, 10)
            except ValueError:
                return Invalid("invalid digit found in string")
            if (min is not None and value < min) or (max is not None and value > max):
                return Invalid(f"{value} is not in {bounds}")
            return value

        return ValueParser(parse)

    @staticmethod
    def from_range(accepted: range) -> ValueParser[int]:
        """Integers inside a Python `range`, step included."""
        invariant(len(accepted) > 0, f"ValueParser.from_range: {accepted!r} is empty")
        if accepted.step == 1:
            return ValueParser.integer(accepted.start, accepted.stop - 1)
        base = ValueParser.integer()

        def parse(raw: str) -> int | Invalid:
            value = base.parse(raw)
            if isinstance(value, Invalid) or value in accepted:
                return value
            return Invalid(f"{value} is not in {accepted!r}")

        return ValueParser(parse)

    @staticmethod
    def floating() -> ValueParser[float]:
        """Floats as Python's `float()` reads them, with error messages meant for users."""

        def parse(raw: str) -> float | Invalid:
            if raw == "":
                return Invalid("cannot parse float from empty string")
            try:
                return float(raw)
            except ValueError:
                return Invalid("invalid float literal")

        return ValueParser(parse)

    @staticmethod
    def boolean() -> ValueParser[bool]:
        """Exactly `true` or `false`. Plain `bool("false")` is `True`, so never use that."""

        def parse(raw: str) -> bool | Invalid:
            if raw == "true":
                return True
            if raw == "false":
                return False
            return Invalid("expected 'true' or 'false'")

        return ValueParser(parse, ("true", "false"))

    @staticmethod
    def choices(*values: str) -> ValueParser[str]:
        """One of a closed set of strings, matched exactly."""
        invariant(len(values) > 0, "ValueParser.choices: needs at least one possible value")
        invariant(
            all(isinstance(value, str) for value in values),
            f"ValueParser.choices: possible values must be str, got {values!r}",
        )
        invariant(
            len(set(values)) == len(values),
            f"ValueParser.choices: duplicate possible values in {values!r}",
        )
        accepted = frozenset(values)

        def parse(raw: str) -> str | Invalid:
            return raw if raw in accepted else Invalid(f"expected one of {', '.join(values)}")

        return ValueParser(parse, values)

    @staticmethod
    def from_literal(form: object) -> ValueParser[str]:
        """One of a `Literal` type's strings: `type Mode = Literal["fast", "safe"]`.

        Accepts the `type` alias (which type checkers accept too) or a bare
        `Literal[...]`. Read the value back with `get_one(id, str)`.
        """
        target = _unalias(form)
        invariant(
            get_origin(target) is Literal,
            f"ValueParser.from_literal: expected a Literal of str, got {form!r}",
        )
        values = get_args(target)
        invariant(
            all(isinstance(value, str) for value in values),
            f"ValueParser.from_literal: {form!r} must hold only str values, got {values!r}",
        )
        return ValueParser.choices(*values)


type ValueParserLike = (
    ValueParser[Any] | Callable[[str], Any] | Sequence[str] | range | TypeAliasType
)
"""What `Arg.value_parser()` accepts, like clap's `impl Into<ValueParser>`."""


def into_value_parser(like: object) -> ValueParser[Any]:
    """Normalize every shorthand to a `ValueParser`, once, at the builder call."""
    like = _unalias(like)
    if get_origin(like) is Literal:
        return ValueParser.from_literal(like)
    if isinstance(like, ValueParser):
        return like
    if isinstance(like, range):
        return ValueParser.from_range(like)
    if isinstance(like, str):
        bug(
            f"value_parser({like!r}): a str is ambiguous; "
            f"pass a list of possible values like [{like!r}]"
        )
    if like is bool:
        return ValueParser.boolean()
    if like is int:
        return ValueParser.integer()
    if like is float:
        return ValueParser.floating()
    if callable(like):
        return ValueParser.from_fn(like)
    if isinstance(like, Sequence):
        return ValueParser.choices(*like)
    bug(f"value_parser({like!r}): expected a ValueParser, callable, range, Literal, or list of str")


_MAX_ALIAS_DEPTH = 16
"""How many `type A = B` hops to follow. A longer chain is a definition bug."""


def _unalias(like: object) -> object:
    """`type Mode = Literal[...]` -> `Literal[...]`; anything else passes through."""
    for _ in range(_MAX_ALIAS_DEPTH):
        if not isinstance(like, TypeAliasType):
            return like
        like = like.__value__
    bug(f"value_parser(): type alias chain is deeper than {_MAX_ALIAS_DEPTH}; is it recursive?")


def parse_boolish(raw: str) -> bool | Invalid:
    """Lenient booleans for environment variables that drive flags."""
    lowered = raw.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSEY:
        return False
    return Invalid(f"expected one of {', '.join(sorted(_TRUTHY | _FALSEY))}")


_TRUTHY = frozenset({"1", "true", "yes", "on", "y"})
_FALSEY = frozenset({"0", "false", "no", "off", "n"})
