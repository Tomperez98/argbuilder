"""Derive a `Command` from a class: the clap derive model on top of the builders.

```python
class Git(Parser, version="1.0.0"):
    \"\"\"A fictional versioning CLI.\"\"\"

    verbose: int = arg(short=True, long=True, action="count", global_=True)
    command: Clone | Push


class Clone(Parser):
    \"\"\"Clones repos.\"\"\"

    remote: str


class Push(Parser):
    \"\"\"Pushes things.\"\"\"

    port: int = arg(short=True, long=True, default=22)
    force: bool = arg(short=True, long=True)
```

A subclass is a frozen, keyword-only dataclass. The type of each field picks
the action, as in clap: `bool` is a flag, `T` is required, `T | None` is
optional, `tuple[T, ...]` collects every value, a union of `Parser` classes
is the subcommand, and an `Args` class is flattened in. The derive only
*describes* a `Command`, so parsing, help and errors are the builder's.

Definition bugs panic: at the class statement for class options, at the
first `to_command()` / parse for fields (annotations can name classes defined
later in the module).
"""

from __future__ import annotations

import dataclasses
import os
import re
import sys
import weakref
from collections.abc import Callable, Iterable
from dataclasses import MISSING, dataclass
from types import MappingProxyType, NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Self,
    Union,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    get_type_hints,
)

from argbuilder._arg import Arg
from argbuilder._command import Command
from argbuilder._error import Error
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
    from collections.abc import Mapping, Sequence

    from argbuilder._matches import ArgMatches

_NO_ENV: Mapping[str, str] = MappingProxyType({})

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


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(arg,))
class Args:
    """A reusable set of fields, flattened into every command that has a field of its type.

    ```python
    class Output(Args):
        json: bool = arg(long=True)


    class Status(Parser):
        output: Output
    ```

    Like clap's `#[command(flatten)]`. It cannot hold a subcommand.
    """

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        invariant(
            not issubclass(cls, Parser),
            f"{cls.__qualname__}: subclass Parser or Args, not both",
        )
        _make_dataclass(cls)


_PARSER_METHODS = frozenset(
    {"parse", "parse_from", "try_parse_from", "from_arg_matches", "to_command"}
)


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(arg,))
class Parser:
    """A command, defined by a class, like clap's `#[derive(Parser)]`.

    Class keywords configure the command:
    `class Git(Parser, name="git", version="1.0.0"): ...`. The name defaults
    to the class name in kebab-case (`CloneRepo` -> `clone-repo`), `about` to
    the first paragraph of the docstring. The same class works as the root or
    as a subcommand.
    """

    def __init_subclass__(
        cls,
        *,
        name: str | None = None,
        about: str | None = None,
        version: str | None = None,
        aliases: Iterable[str] = (),
        visible_aliases: Iterable[str] = (),
        arg_required_else_help: bool = False,
        disable_help_flag: bool = False,
        disable_version_flag: bool = False,
        disable_help_subcommand: bool = False,
    ) -> None:
        super().__init_subclass__()
        # Read before dataclass() fills in a generated signature as the docstring.
        doc = cls.__dict__.get("__doc__")
        _make_dataclass(cls)
        clash = sorted(_PARSER_METHODS & {field.name for field in _fields_of(cls)})
        invariant(
            not clash,
            f"{cls.__qualname__}: field {clash[0] if clash else ''!r} would hide "
            f"Parser.{clash[0] if clash else ''}(); rename the field",
        )
        cmd = Command(name if name is not None else _kebab(cls.__name__))
        about = about if about is not None else _about(doc)
        if about is not None:
            cmd = cmd.about(about)
        if version is not None:
            cmd = cmd.version(version)
        for alias in _names("aliases", aliases):
            cmd = cmd.alias(alias)
        for alias in _names("visible_aliases", visible_aliases):
            cmd = cmd.visible_alias(alias)
        _HEADS[cls] = (
            cmd.arg_required_else_help(arg_required_else_help)
            .disable_help_flag(disable_help_flag)
            .disable_version_flag(disable_version_flag)
            .disable_help_subcommand(disable_help_subcommand)
        )

    @classmethod
    def to_command(cls) -> Command:
        """The `Command` this class describes, for help, `debug_assert()` or adding to it.

        Parse a modified command and read it back with `from_arg_matches`.
        """
        invariant(cls is not Parser, "Parser.to_command(): call it on a subclass")
        return _command(cls, ())

    @classmethod
    def from_arg_matches(cls, matches: ArgMatches) -> Self:
        """Build an instance from matches of `to_command()` (or a command extending it)."""
        invariant(cls is not Parser, "Parser.from_arg_matches(): call it on a subclass")
        return _construct(cls, matches)

    @classmethod
    def try_parse_from(cls, argv: Iterable[str], env: Mapping[str, str] = _NO_ENV) -> Self | Error:
        """Pure, like `Command.try_get_matches_from`: an `Error` for what the user got wrong."""
        result = cls.to_command().try_get_matches_from(argv, env)
        return result if isinstance(result, Error) else cls.from_arg_matches(result)

    @classmethod
    def parse_from(cls, argv: Iterable[str], env: Mapping[str, str] = _NO_ENV) -> Self:
        """Like `try_parse_from`, but print the error and exit on failure."""
        result = cls.try_parse_from(argv, env)
        if isinstance(result, Error):
            result.exit()
        return result

    @classmethod
    def parse(cls) -> Self:
        """Parse `sys.argv` with `os.environ`, exiting on error."""
        return cls.parse_from(sys.argv, os.environ)


# -- derivation ---------------------------------------------------------------

type _Reader = Callable[[ArgMatches], object]


@dataclass(frozen=True, slots=True)
class _Subcommand:
    field: str
    by_name: Mapping[str, type[Parser]]
    optional: bool


@dataclass(frozen=True, slots=True)
class _Fields:
    args: tuple[Arg, ...]
    """This class's arguments, flattened ones included."""
    subcommand: _Subcommand | None
    readers: tuple[tuple[str, _Reader], ...]
    """How to read each field of the class from matches, in field order."""


_HEADS: weakref.WeakKeyDictionary[type, Command] = weakref.WeakKeyDictionary()
"""Each Parser class's command without args or subcommands, built at the class statement."""
_FIELDS: weakref.WeakKeyDictionary[type, _Fields] = weakref.WeakKeyDictionary()
_COMMANDS: weakref.WeakKeyDictionary[type, Command] = weakref.WeakKeyDictionary()


def _make_dataclass(cls: type) -> None:
    dataclass(frozen=True, kw_only=True)(cls)
    for field in _fields_of(cls):
        where = f"{cls.__qualname__}.{field.name}"
        invariant(field.init, f"{where}: init=False fields are not supported")
        invariant(
            field.default_factory is MISSING,
            f"{where}: default_factory is not supported; use an immutable default",
        )


def _fields_of(cls: type) -> tuple[dataclasses.Field[Any], ...]:
    return dataclasses.fields(cast("Any", cls))


def _command(cls: type[Parser], stack: tuple[type, ...]) -> Command:
    cached = _COMMANDS.get(cls)
    if cached is not None:
        return cached
    invariant(
        cls not in stack,
        f"{cls.__qualname__}: subcommands form a cycle: "
        f"{' -> '.join(c.__qualname__ for c in (*stack, cls))}",
    )
    fields = _fields(cls, ())
    cmd = _HEADS[cls].args(fields.args)
    sub = fields.subcommand
    if sub is not None:
        cmd = cmd.subcommands(
            _command(member, (*stack, cls)) for member in sub.by_name.values()
        ).subcommand_required(not sub.optional)
    _COMMANDS[cls] = cmd
    return cmd


def _construct[T](cls: type[T], matches: ArgMatches) -> T:
    readers = _fields(cls, ()).readers
    return cls(**{name: read(matches) for name, read in readers})


def _fields(cls: type, stack: tuple[type, ...]) -> _Fields:
    cached = _FIELDS.get(cls)
    if cached is not None:
        return cached
    invariant(
        cls not in stack,
        f"{cls.__qualname__}: flattened Args form a cycle: "
        f"{' -> '.join(c.__qualname__ for c in (*stack, cls))}",
    )
    try:
        hints = get_type_hints(cls)
    except NameError as exc:
        exc.add_note(
            f"argbuilder: resolving the annotations of {cls.__qualname__}; "
            f"classes and type aliases they name must be defined at module level"
        )
        raise
    args: list[Arg] = []
    readers: list[tuple[str, _Reader]] = []
    subcommand: _Subcommand | None = None
    for field in _fields_of(cls):
        where = f"{cls.__qualname__}.{field.name}"
        options = field.metadata.get(_METADATA_KEY)
        optional, members = _split_optional(hints[field.name])
        if any(_is_class(member, Parser) for member in members):
            invariant(
                subcommand is None,
                f"{where}: {cls.__qualname__} already has subcommand field "
                f"{subcommand.field if subcommand else ''!r}; a command has one",
            )
            subcommand = _subcommand_field(where, field, members, optional, options)
            readers.append((field.name, _subcommand_reader(where, subcommand)))
        elif any(_is_class(member, Args) for member in members):
            invariant(
                len(members) == 1 and not optional,
                f"{where}: a flattened Args field must have exactly one Args type",
            )
            invariant(
                options is None and field.default is MISSING,
                f"{where}: a flattened Args field takes no arg() or default",
            )
            group = cast("type", members[0])
            nested = _fields(group, (*stack, cls))
            args.extend(nested.args)
            readers.append((field.name, lambda matches, group=group: _construct(group, matches)))
        else:
            try:
                built, reader = _value_field(
                    where=where,
                    name=field.name,
                    members=members,
                    optional=optional,
                    default=field.default,
                    options=options or _NO_OPTIONS,
                )
            except AssertionError as exc:
                exc.add_note(f"argbuilder: in field {where}")
                raise
            args.append(built)
            readers.append((field.name, reader))
    invariant(
        subcommand is None or issubclass(cls, Parser),
        f"{cls.__qualname__}: an Args class cannot hold a subcommand; make it a Parser",
    )
    result = _Fields(tuple(args), subcommand, tuple(readers))
    _FIELDS[cls] = result
    return result


def _subcommand_field(
    where: str,
    field: dataclasses.Field[Any],
    members: Sequence[object],
    optional: bool,
    options: _ArgOptions | None,
) -> _Subcommand:
    invariant(
        all(_is_class(member, Parser) for member in members),
        f"{where}: a subcommand field must be a union of Parser classes, got {members!r}",
    )
    invariant(options is None, f"{where}: arg() does not apply to a subcommand field")
    invariant(
        field.default is MISSING or (optional and field.default is None),
        f"{where}: a subcommand field can only default to None, and only with '| None'",
    )
    by_name: dict[str, type[Parser]] = {}
    for member in cast("Sequence[type[Parser]]", members):
        name = _HEADS[member].get_name()
        taken = by_name.get(name)
        invariant(
            taken is None,
            f"{where}: {taken.__qualname__ if taken else ''} and "
            f"{getattr(member, '__qualname__', member)} are both named {name!r}",
        )
        by_name[name] = member
    return _Subcommand(field.name, MappingProxyType(by_name), optional)


def _subcommand_reader(where: str, sub: _Subcommand) -> _Reader:
    def read(matches: ArgMatches) -> object:
        used = matches.subcommand()
        if used is None:
            invariant(sub.optional, f"{where}: required subcommand is missing")
            return None
        name, sub_matches = used
        cls = sub.by_name.get(name)
        if cls is None:
            bug(f"{where}: matched subcommand {name!r} is not one of {list(sub.by_name)}")
        return _construct(cls, sub_matches)

    return read


def _value_field(
    *,
    where: str,
    name: str,
    members: Sequence[object],
    optional: bool,
    default: object,
    options: _ArgOptions,
) -> tuple[Arg, _Reader]:
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

    built = Arg(name).action(action)
    if options.short is not False:
        built = built.short(name[0] if options.short is True else options.short)
    if options.long is not False:
        long = name.replace("_", "-") if options.long is True else options.long
        built = built.long(long)
    if options.env is not False:
        built = built.env(name.upper() if options.env is True else options.env)
    if options.help is not None:
        built = built.help(options.help)
    if options.value_name is not None:
        built = built.value_name(options.value_name)
    if options.num_args is not None:
        bounds = options.num_args
        built = built.num_args(*bounds) if isinstance(bounds, tuple) else built.num_args(bounds)
    if options.default_missing_value is not None:
        built = built.default_missing_value(options.default_missing_value)
    if options.value_delimiter is not None:
        built = built.value_delimiter(options.value_delimiter)
    for alias in options.aliases:
        built = built.alias(alias)
    for alias in options.visible_aliases:
        built = built.visible_alias(alias)
    for alias in options.short_aliases:
        built = built.short_alias(alias)
    for alias in options.visible_short_aliases:
        built = built.visible_short_alias(alias)
    built = (
        built.global_(options.global_)
        .hide(options.hide)
        .allow_hyphen_values(options.allow_hyphen_values)
        .last(options.last)
        .conflicts_with_all(options.conflicts_with)
    )
    for other in options.requires:
        built = built.requires(other)

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
            return built, lambda matches: matches.get_count(name)
        return built, lambda matches: matches.get_flag(name)

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
        return built, lambda matches: matches.get_many(name, check)
    if optional:
        return built, lambda matches: matches.get_one(name, check)
    return built, lambda matches: matches.get_required(name, check)


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


_KEBAB = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _kebab(name: str) -> str:
    """`CloneRepo` -> `clone-repo`, `HTTPServer` -> `http-server`."""
    return _KEBAB.sub("-", name).lower()


def _about(doc: str | None) -> str | None:
    """The docstring's first paragraph on one line, a lone trailing period dropped (as clap)."""
    if not doc:
        return None
    import inspect

    first = inspect.cleandoc(doc).split("\n\n", 1)[0]
    text = " ".join(first.split())
    return text.removesuffix(".") if text.count(". ") == 0 else text
