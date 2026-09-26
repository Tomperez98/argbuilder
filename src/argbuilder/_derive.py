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
from dataclasses import MISSING, dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast, dataclass_transform, get_type_hints

from argbuilder._command import Command
from argbuilder._error import Error
from argbuilder._field import (
    _METADATA_KEY,
    _NO_OPTIONS,
    FlagReader,
    ValueReader,
    _is_class,
    _names,
    _split_optional,
    _value_field,
    arg,
)
from argbuilder._invariant import bug, invariant

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from typing import Any, Self

    from argbuilder._arg import Arg
    from argbuilder._field import _ArgOptions
    from argbuilder._matches import ArgMatches

_NO_ENV: Mapping[str, str] = MappingProxyType({})


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
    {"parse", "parse_from", "try_parse_from", "from_arg_matches", "to_command"},
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


@dataclass(frozen=True, slots=True)
class _Subcommand:
    """How to read a subcommand field; doubles as the reader for that field."""

    where: str
    field: str
    by_name: Mapping[str, type[Parser]]
    optional: bool


@dataclass(frozen=True, slots=True)
class _FlattenReader:
    """How to read a flattened `Args` field: build its class from the matches."""

    field: str
    cls: type


type _Reader = ValueReader | FlagReader | _FlattenReader | _Subcommand
"""One per field, in field order; `_read` turns each into that field's value."""


@dataclass(frozen=True, slots=True)
class _Fields:
    args: tuple[Arg, ...]
    """This class's arguments, flattened ones included."""
    subcommand: _Subcommand | None
    readers: tuple[_Reader, ...]
    """The derivation, as data: one descriptor per field, in field order."""
    plan: tuple[tuple[str, Callable[[ArgMatches], object]], ...]
    """`readers` resolved to `(field, callable)` once, so parsing only calls.

    Resolving a descriptor to the getter it names is control-plane work: done
    here, once per class, not per field per parse.
    """


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
    return cls(**{name: read(matches) for name, read in _fields(cls, ()).plan})


def _resolve_reader(reader: _Reader) -> Callable[[ArgMatches], object]:
    """Bind one reader descriptor to the getter it names. Runs once per class."""
    match reader:
        case ValueReader(field=field, type_=type_, getter="get_one"):
            return lambda matches: matches.get_one(field, type_)
        case ValueReader(field=field, type_=type_, getter="get_required"):
            return lambda matches: matches.get_required(field, type_)
        case ValueReader(field=field, type_=type_, getter="get_many"):
            return lambda matches: matches.get_many(field, type_)
        case FlagReader(field=field, counter=True):
            return lambda matches: matches.get_count(field)
        case FlagReader(field=field):
            return lambda matches: matches.get_flag(field)
        case _FlattenReader(cls=group):
            return lambda matches: _construct(group, matches)
        case _Subcommand() as sub:
            return lambda matches: _read_subcommand(sub, matches)
        case _:  # pragma: no cover
            bug(f"unknown reader {reader!r}")


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
        bug(
            f"{cls.__qualname__}: cannot resolve its annotations: {exc}; "
            f"classes and type aliases they name must be defined at module level",
            exc,
        )
    args: list[Arg] = []
    readers: list[_Reader] = []
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
            readers.append(subcommand)
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
            readers.append(_FlattenReader(field=field.name, cls=group))
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
            readers.append(reader)
    invariant(
        subcommand is None or issubclass(cls, Parser),
        f"{cls.__qualname__}: an Args class cannot hold a subcommand; make it a Parser",
    )
    plan = tuple((reader.field, _resolve_reader(reader)) for reader in readers)
    result = _Fields(tuple(args), subcommand, tuple(readers), plan)
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
    return _Subcommand(where, field.name, MappingProxyType(by_name), optional)


def _read_subcommand(sub: _Subcommand, matches: ArgMatches) -> object:
    used = matches.subcommand()
    if used is None:
        invariant(sub.optional, f"{sub.where}: required subcommand is missing")
        return None
    name, sub_matches = used
    cls = sub.by_name.get(name)
    if cls is None:
        bug(f"{sub.where}: matched subcommand {name!r} is not one of {list(sub.by_name)}")
    return _construct(cls, sub_matches)


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
