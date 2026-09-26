"""`Arg` and `ArgGroup`: fluent, immutable builders in the style of clap's builder API."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, overload

from argbuilder._invariant import bug, invariant
from argbuilder._spec import ArgAction, ArgSpec, GroupSpec, check_action
from argbuilder._value_parser import ValueParserLike, into_value_parser

if TYPE_CHECKING:
    from collections.abc import Iterable


def _check_bool(owner: str, method: str, value: object) -> bool:
    invariant(isinstance(value, bool), f"{owner}.{method}() takes a bool, got {value!r}")
    return bool(value)


def _check_id(kind: str, value: object) -> str:
    invariant(
        isinstance(value, str) and value != "" and not value.isspace(),
        f"{kind} id must be a non-empty str, got {value!r}",
    )
    return str(value)


class Arg:
    """One argument, built fluently: `Arg("port").short("p").long("port")`.

    With no `short()`/`long()` it is positional. Every method returns a new
    `Arg`, so a definition can be shared between commands. Mistakes local to
    one argument panic right here, at the builder call. Mistakes that span
    arguments (duplicate shorts, dangling `requires`) panic when the command
    is built.
    """

    __slots__ = ("_spec",)
    _spec: ArgSpec

    def __init__(self, id: str) -> None:
        self._spec = ArgSpec(id=_check_id("Arg", id))

    def __repr__(self) -> str:
        return f"Arg({self._spec.id!r})"

    def get_id(self) -> str:
        return self._spec.id

    def _with(self, **changes: Any) -> Arg:
        new: Arg = Arg.__new__(Arg)
        new._spec = dataclasses.replace(self._spec, **changes)
        return new

    @property
    def _owner(self) -> str:
        return f"Arg({self._spec.id!r})"

    def short(self, char: str) -> Arg:
        """`-c`. A single character other than `-`, `=` or whitespace."""
        return self._with(short=_check_short(self._owner, "short", char))

    def long(self, name: str) -> Arg:
        """`--name`. Pass it without the leading dashes."""
        return self._with(long=_check_long(self._owner, "long", name))

    def alias(self, name: str) -> Arg:
        """A hidden extra `--name`: it parses, but help and suggestions leave it out."""
        name = _check_long(self._owner, "alias", name)
        return self._with(aliases=(*self._spec.aliases, name))

    def visible_alias(self, name: str) -> Arg:
        """An extra `--name`, listed in help as `[aliases: --name]`."""
        name = _check_long(self._owner, "visible_alias", name)
        return self._with(visible_aliases=(*self._spec.visible_aliases, name))

    def short_alias(self, char: str) -> Arg:
        """A hidden extra `-c`."""
        char = _check_short(self._owner, "short_alias", char)
        return self._with(short_aliases=(*self._spec.short_aliases, char))

    def visible_short_alias(self, char: str) -> Arg:
        """An extra `-c`, listed in help as `[short aliases: -c]`."""
        char = _check_short(self._owner, "visible_short_alias", char)
        return self._with(visible_short_aliases=(*self._spec.visible_short_aliases, char))

    def global_(self, yes: bool) -> Arg:
        """Also accept this option in every subcommand below, and read it at any level.

        `git -v push` and `git push -v` both count. The whole command line
        counts as one occurrence list: `count` and `append` add up across
        levels, and a `set` option given at two levels is used twice.
        """
        return self._with(global_=_check_bool(self._owner, "global_", yes))

    def help(self, text: str) -> Arg:
        invariant(isinstance(text, str), f"{self._owner}.help() takes a str, got {text!r}")
        return self._with(help=text)

    def value_name(self, name: str) -> Arg:
        """Placeholder in help and errors: `--port <PORT>`. Defaults to the id, uppercased."""
        invariant(
            isinstance(name, str) and name != "",
            f"{self._owner}.value_name() takes a non-empty str, got {name!r}",
        )
        return self._with(value_name=name)

    def required(self, yes: bool) -> Arg:
        return self._with(required=_check_bool(self._owner, "required", yes))

    def action(self, action: ArgAction) -> Arg:
        """Defaults to `"set"`: an argument takes a value unless told otherwise.

        `Arg("v").short("v").action("count")`
        """
        action = check_action(self._owner, action)
        return self._with(action=action)

    def value_parser(self, parser: ValueParserLike) -> Arg:
        """How raw strings become typed values.

        Accepts a `ValueParser`, a callable (`int`, `float`, `Path`, ...), a
        `range`, a `Literal` of strings (best as `type Mode = Literal[...]`), or
        a list of possible values.
        """
        return self._with(value_parser=into_value_parser(parser))

    @overload
    def num_args(self, exactly: int, /) -> Arg: ...
    @overload
    def num_args(self, min: int, max: int | None, /) -> Arg: ...
    def num_args(self, *bounds: int | None) -> Arg:
        """Values per occurrence: `num_args(2)`, `num_args(0, 1)`, `num_args(1, None)` (unbounded)."""
        invariant(
            len(bounds) in (1, 2),
            f"{self._owner}.num_args() takes 1 or 2 bounds, got {bounds}",
        )
        low = bounds[0]
        high = bounds[-1]
        if not isinstance(low, int) or isinstance(low, bool) or low < 0:
            bug(f"{self._owner}.num_args(): min must be an int >= 0, got {low!r}")
        if high is not None and (not isinstance(high, int) or isinstance(high, bool)):
            bug(f"{self._owner}.num_args(): max must be an int or None, got {high!r}")
        invariant(
            high is None or high >= max(low, 1),
            f"{self._owner}.num_args{bounds}: max must be >= min and >= 1; "
            f"for an argument that takes no value, use action('set_true')",
        )
        return self._with(num_args=(low, high))

    def default_value(self, value: str) -> Arg:
        """Used when the argument is absent from both the command line and the environment."""
        return self.default_values([value])

    def default_values(self, values: Iterable[str]) -> Arg:
        collected = tuple(values)
        invariant(
            len(collected) > 0 and all(isinstance(value, str) for value in collected),
            f"{self._owner}.default_values() takes a non-empty list of str, got {collected!r}",
        )
        return self._with(default_values=collected)

    def default_missing_value(self, value: str) -> Arg:
        """Used when the argument is present with no value, e.g. `--color` for `num_args(0, 1)`."""
        invariant(
            isinstance(value, str),
            f"{self._owner}.default_missing_value() takes a str, got {value!r}",
        )
        return self._with(default_missing_values=(value,))

    def env(self, name: str) -> Arg:
        """Fall back to this environment variable. An empty value counts as unset."""
        invariant(
            isinstance(name, str) and name != "" and "=" not in name,
            f"{self._owner}.env() takes a variable name, got {name!r}",
        )
        return self._with(env=name)

    def conflicts_with(self, id: str) -> Arg:
        return self._with(conflicts_with=self._spec.conflicts_with | {_check_id("Arg", id)})

    def conflicts_with_all(self, ids: Iterable[str]) -> Arg:
        checked = {_check_id("Arg", id) for id in ids}
        return self._with(conflicts_with=self._spec.conflicts_with | checked)

    def requires(self, id: str) -> Arg:
        return self._with(requires=self._spec.requires | {_check_id("Arg", id)})

    def allow_hyphen_values(self, yes: bool) -> Arg:
        """Accept values starting with `-`, such as `-5`, without `=` or `--`."""
        return self._with(allow_hyphen_values=_check_bool(self._owner, "allow_hyphen_values", yes))

    def value_delimiter(self, char: str) -> Arg:
        """Split each value on `char`: `--tags a,b,c`."""
        invariant(
            isinstance(char, str) and len(char) == 1,
            f"{self._owner}.value_delimiter() takes one character, got {char!r}",
        )
        return self._with(value_delimiter=char)

    def last(self, yes: bool) -> Arg:
        """Only ever filled after a literal `--`; every token after it is taken verbatim.

        For a positional that passes the rest of the line through unparsed,
        like `mytool run -- cargo build --release -j8`. Must be a positional
        (no `short()`/`long()`), and the last one; at most one per command.
        Before `--`, an extra token is an error with a tip pointing at `--`,
        the same as it would be with no positional left to fill.
        """
        return self._with(last=_check_bool(self._owner, "last", yes))

    def hide(self, yes: bool) -> Arg:
        """Leave the argument out of help and usage."""
        return self._with(hide=_check_bool(self._owner, "hide", yes))


def _check_short(owner: str, method: str, char: object) -> str:
    invariant(
        isinstance(char, str) and len(char) == 1 and char not in "-=" and not char.isspace(),
        f"{owner}.{method}() takes one character other than '-' or '=', got {char!r}",
    )
    return str(char)


def _check_long(owner: str, method: str, name: object) -> str:
    invariant(
        isinstance(name, str)
        and name != ""
        and not name.startswith("-")
        and "=" not in name
        and not any(char.isspace() for char in name),
        f"{owner}.{method}() takes a name without leading '-', '=' or spaces, got {name!r}",
    )
    return str(name)


class ArgGroup:
    """A named set of arguments: `ArgGroup("mode").args(["fast", "safe"]).required(True)`.

    By default at most one member may be used (`multiple(False)`).
    """

    __slots__ = ("_spec",)
    _spec: GroupSpec

    def __init__(self, id: str) -> None:
        self._spec = GroupSpec(id=_check_id("ArgGroup", id))

    def __repr__(self) -> str:
        return f"ArgGroup({self._spec.id!r})"

    def _with(self, **changes: Any) -> ArgGroup:
        new: ArgGroup = ArgGroup.__new__(ArgGroup)
        new._spec = dataclasses.replace(self._spec, **changes)
        return new

    def arg(self, id: str) -> ArgGroup:
        return self.args([id])

    def args(self, ids: Iterable[str]) -> ArgGroup:
        members = self._spec.args + tuple(_check_id("Arg", id) for id in ids)
        invariant(
            len(set(members)) == len(members),
            f"ArgGroup({self._spec.id!r}): duplicate members in {members}",
        )
        return self._with(args=members)

    def required(self, yes: bool) -> ArgGroup:
        """At least one member must be present."""
        return self._with(required=_check_bool(repr(self), "required", yes))

    def multiple(self, yes: bool) -> ArgGroup:
        """Allow more than one member at once."""
        return self._with(multiple=_check_bool(repr(self), "multiple", yes))
