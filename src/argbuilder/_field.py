"""One annotated dataclass field -> one `Arg` plus how to read it back.

The pure half of the derive layer: option configuration (`arg()` and the
applier table), annotation introspection, and the reader descriptors that
say how a field is pulled out of `ArgMatches`. It knows nothing about
`Parser`/`Args`, so it can be tested without parsing or building a command.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from dataclasses import MISSING, dataclass
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Any, Literal, Union, cast, get_args, get_origin

from argbuilder._arg import Arg
from argbuilder._invariant import bug, invariant
from argbuilder._spec import check_action, takes_values
from argbuilder._value_parser import (
    Invalid,
    ValueParser,
    ValueParserLike,
    _unalias,
    into_value_parser,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

type FieldAction = Literal["set", "append", "set_true", "set_false", "count"]
"""The actions a field can take. Inferred from the type unless `arg(action=...)` says otherwise."""

_FIELD_ACTIONS: frozenset[str] = frozenset(get_args(FieldAction.__value__))
_METADATA_KEY = "argbuilder"


@dataclass(frozen=True, slots=True)
class _ArgOptions:
    short: str | bool = False
    long: str | bool = False
    help: str | None = None
    value_name: str | None = None
    action: FieldAction | None = None
    value_parser: ValueParserLike | None = None
    num_args: int | tuple[int, int | None] | None = None
    env: str | bool = False
    required: bool = False
    global_: bool = False
    hide: bool = False
    conflicts_with: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    visible_aliases: tuple[str, ...] = ()
    short_aliases: tuple[str, ...] = ()
    visible_short_aliases: tuple[str, ...] = ()
    allow_hyphen_values: bool = False
    value_delimiter: str | None = None
    default_missing_value: str | None = None
    last: bool = False


_NO_OPTIONS = _ArgOptions()


type _OptionApplier = Callable[[Arg, _ArgOptions, str], Arg]
"""Applies one `_ArgOptions` field to a freshly built `Arg`.

`name` is the field name, for options like `short=True` that derive their
value from it. Each applier is a no-op when its option is unset.
"""


def _apply_each(built: Arg, values: Iterable[str], method: Callable[[Arg, str], Arg]) -> Arg:
    """Apply a repeatable `Arg` method once per value; `()` leaves `built` untouched."""
    for value in values:
        built = method(built, value)
    return built


_OPTION_APPLIERS: dict[str, _OptionApplier] = {
    "short": lambda built, options, name: (
        built
        if options.short is False
        else built.short(name[0] if options.short is True else options.short)
    ),
    "long": lambda built, options, name: (
        built
        if options.long is False
        else built.long(name.replace("_", "-") if options.long is True else options.long)
    ),
    "env": lambda built, options, name: (
        built
        if options.env is False
        else built.env(name.upper() if options.env is True else options.env)
    ),
    "help": lambda built, options, _: built if options.help is None else built.help(options.help),
    "value_name": lambda built, options, _: (
        built if options.value_name is None else built.value_name(options.value_name)
    ),
    "num_args": lambda built, options, _: (
        built
        if options.num_args is None
        else built.num_args(*options.num_args)
        if isinstance(options.num_args, tuple)
        else built.num_args(options.num_args)
    ),
    "default_missing_value": lambda built, options, _: (
        built
        if options.default_missing_value is None
        else built.default_missing_value(options.default_missing_value)
    ),
    "value_delimiter": lambda built, options, _: (
        built if options.value_delimiter is None else built.value_delimiter(options.value_delimiter)
    ),
    "aliases": lambda built, options, _: _apply_each(built, options.aliases, Arg.alias),
    "visible_aliases": lambda built, options, _: _apply_each(
        built, options.visible_aliases, Arg.visible_alias
    ),
    "short_aliases": lambda built, options, _: _apply_each(
        built, options.short_aliases, Arg.short_alias
    ),
    "visible_short_aliases": lambda built, options, _: _apply_each(
        built, options.visible_short_aliases, Arg.visible_short_alias
    ),
    "global_": lambda built, options, _: built.global_(options.global_),
    "hide": lambda built, options, _: built.hide(options.hide),
    "allow_hyphen_values": lambda built, options, _: built.allow_hyphen_values(
        options.allow_hyphen_values
    ),
    "last": lambda built, options, _: built.last(options.last),
    "conflicts_with": lambda built, options, _: built.conflicts_with_all(options.conflicts_with),
    "requires": lambda built, options, _: _apply_each(built, options.requires, Arg.requires),
}

_SPECIAL_OPTIONS: frozenset[str] = frozenset({"action", "value_parser", "required"})
"""`_ArgOptions` fields `_value_field` consumes itself, not through the applier table.

The applier table plus this set must cover every `_ArgOptions` field; a test
asserts it. Without that guard, adding an option to the table's blind spot
would be accepted by `arg()` and silently ignored.
"""


def _apply_options(built: Arg, options: _ArgOptions, name: str) -> Arg:
    """Apply every configured option to a freshly built `Arg`, in field order."""
    for field in dataclasses.fields(options):
        applier = _OPTION_APPLIERS.get(field.name)
        if applier is not None:
            built = applier(built, options, name)
    return built


def arg(
    *,
    default: Any = MISSING,
    short: str | bool = False,
    long: str | bool = False,
    help: str | None = None,
    value_name: str | None = None,
    action: FieldAction | None = None,
    value_parser: ValueParserLike | None = None,
    num_args: int | tuple[int, int | None] | None = None,
    env: str | bool = False,
    required: bool = False,
    global_: bool = False,
    hide: bool = False,
    conflicts_with: str | Iterable[str] = (),
    requires: str | Iterable[str] = (),
    aliases: str | Iterable[str] = (),
    visible_aliases: str | Iterable[str] = (),
    short_aliases: str | Iterable[str] = (),
    visible_short_aliases: str | Iterable[str] = (),
    allow_hyphen_values: bool = False,
    value_delimiter: str | None = None,
    default_missing_value: str | None = None,
    last: bool = False,
) -> Any:
    """Configure one field, like clap's `#[arg(...)]`.

    - `short=True` / `long=True` derive `-p` / `--dry-run` from the field
      name; pass a str to choose. With neither, the field is positional.
    - `env=True` reads the field name uppercased (`PORT`).
    - `default` is a typed value (`default=22`), the same as `port: int = 22`.
      It must survive `str()` and the value parser: help shows `[default: 22]`.
    - `required=True` is only for `tuple[T, ...]` (at least one value); for
      other fields, `T` is required and `T | None` is optional.
    - `last=True` needs a positional field (no `short`/`long`); it fills only
      after a literal `--`, taking every token after it verbatim.
    """
    options = _ArgOptions(
        short=short,
        long=long,
        help=help,
        value_name=value_name,
        action=action,
        value_parser=value_parser,
        num_args=num_args,
        env=env,
        required=required,
        global_=global_,
        hide=hide,
        conflicts_with=_names("conflicts_with", conflicts_with),
        requires=_names("requires", requires),
        aliases=_names("aliases", aliases),
        visible_aliases=_names("visible_aliases", visible_aliases),
        short_aliases=_names("short_aliases", short_aliases),
        visible_short_aliases=_names("visible_short_aliases", visible_short_aliases),
        allow_hyphen_values=allow_hyphen_values,
        value_delimiter=value_delimiter,
        default_missing_value=default_missing_value,
        last=last,
    )
    return dataclasses.field(default=default, metadata={_METADATA_KEY: options})


def _names(what: str, names: str | Iterable[str]) -> tuple[str, ...]:
    """One name or several: `requires="config"` and `requires=["a", "b"]` both work."""
    if isinstance(names, str):
        return (names,)
    invariant(
        isinstance(names, Iterable),
        f"arg({what}=...) takes a str or a list of str, got {names!r}",
    )
    collected = tuple(names)
    invariant(
        all(isinstance(name, str) for name in collected),
        f"arg({what}=...) takes a str or a list of str, got {collected!r}",
    )
    return collected


@dataclass(frozen=True, slots=True)
class ValueReader:
    """How to read one value-taking field from `ArgMatches`, as data rather than a closure.

    `getter` names the typed getter to call with `(field, type_)`; keeping it
    as data lets a test assert the derivation without parsing anything.
    """

    field: str
    type_: type
    getter: Literal["get_one", "get_required", "get_many"]


@dataclass(frozen=True, slots=True)
class FlagReader:
    """How to read a flag field from `ArgMatches`; `counter` for an `int` count field."""

    field: str
    counter: bool = False


def _value_field(
    *,
    where: str,
    name: str,
    members: Sequence[object],
    optional: bool,
    default: object,
    options: _ArgOptions,
) -> tuple[Arg, ValueReader | FlagReader]:
    invariant(
        len(members) == 1,
        f"{where}: a union of {members!r} is not supported; "
        f"use one type with a value_parser that returns it",
    )
    hint = members[0]
    invariant(
        get_origin(hint) is not list,
        f"{where}: use tuple[T, ...] instead of list[T]; fields are immutable",
    )
    many = get_origin(hint) is tuple
    element = hint
    if many:
        elements = get_args(hint)
        invariant(
            len(elements) == 2 and elements[1] is Ellipsis,
            f"{where}: use tuple[T, ...]; a fixed-size tuple is not supported",
        )
        invariant(
            not optional,
            f"{where}: tuple[T, ...] is already empty when absent; drop '| None'",
        )
        element = _unalias(elements[0])
    action = _action(where, element, many, optional, options.action)
    invariant(
        not options.required or many,
        f"{where}: required=True is only for tuple[T, ...]; "
        f"'T' is required and 'T | None' is optional already",
    )

    built = _apply_options(Arg(name).action(action), options, name)

    if not takes_values(action):
        implicit = {"set_true": False, "set_false": True, "count": 0}[action]
        invariant(
            default is MISSING or (default == implicit and type(default) is type(implicit)),
            f"{where}: action {action!r} always defaults to {implicit!r}, got {default!r}"
            + (
                "; for a flag that turns something off, use arg(action='set_false')"
                if action == "set_true"
                else ""
            ),
        )
        if action == "count":
            return built, FlagReader(field=name, counter=True)
        return built, FlagReader(field=name)

    like = (
        options.value_parser
        if options.value_parser is not None
        else _inferred_parser(where, element)
    )
    parser = into_value_parser(like) if like is not None else None
    if parser is not None:
        built = built.value_parser(parser)
    check = _check_type(where, element, explicit=options.value_parser is not None)

    if default is not MISSING:
        invariant(
            not optional or default is None,
            f"{where}: 'T | None' defaults to None; a default of {default!r} means it "
            f"is never None, so drop '| None'",
        )
        if many:
            if not isinstance(default, tuple):
                bug(f"{where}: a tuple[T, ...] default must be a tuple, got {default!r}")
            raws = [_raw_default(where, parser, value) for value in default]
            if raws:
                built = built.default_values(raws)
        elif default is not None:
            built = built.default_value(_raw_default(where, parser, default))
    elif not optional and not many:
        built = built.required(True)
    if options.required:
        built = built.required(True)

    if many:
        return built, ValueReader(field=name, type_=check, getter="get_many")
    if optional:
        return built, ValueReader(field=name, type_=check, getter="get_one")
    return built, ValueReader(field=name, type_=check, getter="get_required")


def _action(
    where: str,
    element: object,
    many: bool,
    optional: bool,
    explicit: FieldAction | None,
) -> FieldAction:
    """Infer the action from the type, or check the one `arg(action=...)` gave."""
    if explicit is not None:
        check_action(f"{where}: arg", explicit)
        invariant(
            explicit in _FIELD_ACTIONS,
            f"{where}: arg(action={explicit!r}) is not for fields; "
            f"use one of {', '.join(sorted(_FIELD_ACTIONS))}",
        )
    action: FieldAction = explicit or (
        "append" if many else "set_true" if element is bool else "set"
    )
    if action in ("set_true", "set_false"):
        invariant(
            element is bool and not many and not optional,
            f"{where}: action {action!r} needs a 'bool' field",
        )
    elif action == "count":
        invariant(
            element is int and not many and not optional,
            f"{where}: action 'count' needs an 'int' field",
        )
    elif action == "append":
        invariant(many, f"{where}: action 'append' collects values; annotate it tuple[T, ...]")
    return action


def _inferred_parser(where: str, element: object) -> ValueParserLike | None:
    if element is str:
        return None
    if get_origin(element) is Literal or isinstance(element, type):
        return cast("ValueParserLike", element)
    bug(f"{where}: cannot infer a value parser for {element!r}; pass arg(value_parser=...)")


def _check_type(where: str, element: object, *, explicit: bool) -> type:
    """The runtime type a matched value must have: what the getters check."""
    if get_origin(element) is Literal:
        return str
    if isinstance(element, type):
        return element
    invariant(explicit, f"{where}: unsupported field type {element!r}")
    return object


def _raw_default(where: str, parser: ValueParser[Any] | None, value: object) -> str:
    """The command-line spelling of a typed default, checked to parse back to it."""
    if isinstance(value, bool):
        raw = "true" if value else "false"
    else:
        raw = value if isinstance(value, str) else str(value)
    parsed = raw if parser is None else parser.parse(raw)
    if isinstance(parsed, Invalid):
        bug(f"{where}: default {value!r} is rejected by its value parser: {parsed.message}")
    invariant(
        parsed == value,
        f"{where}: default {value!r} is written as {raw!r}, which parses back as "
        f"{parsed!r}; pick a default whose str() round-trips",
    )
    return raw


def _split_optional(hint: object) -> tuple[bool, tuple[object, ...]]:
    """`A | B | None` -> `(True, (A, B))`, following `type` aliases."""
    hint = _unalias(hint)
    if get_origin(hint) is Union or isinstance(hint, UnionType):
        members = tuple(_unalias(member) for member in get_args(hint))
        present = tuple(member for member in members if member is not NoneType)
        return len(present) < len(members), present
    return False, (hint,)


def _is_class(value: object, base: type) -> bool:
    return isinstance(value, type) and issubclass(value, base)
