"""Validate a command tree once and resolve every inferred setting.

Everything downstream (parser, help, matches) reads `Resolved*` values only:
no `None`-means-default fields, no re-validation. Every check here is a
definition bug, so each one panics.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from argbuilder._invariant import bug, invariant
from argbuilder._spec import ArgAction, ArgSpec, CommandSpec, takes_values
from argbuilder._value_parser import Invalid, ValueParser

MAX_COMMAND_DEPTH = 32
"""Subcommand nesting bound. A deeper tree is a construction bug, not a real CLI."""

_STRING: ValueParser[str] = ValueParser(lambda raw: raw)
_FLAG_DEFAULTS: Mapping[ArgAction, tuple[Any, ...]] = MappingProxyType(
    {"set_true": (False,), "set_false": (True,), "count": (0,)}
)
_HELP_SPEC = ArgSpec(id="help", short="h", long="help", help="Print help", action="help")
_VERSION_SPEC = ArgSpec(
    id="version",
    short="V",
    long="version",
    help="Print version",
    action="version",
)
_AUTO_FLAG_HINT = (
    "; -h/--help and -V/--version are added automatically, "
    "use disable_help_flag(True) / disable_version_flag(True) to free them"
)
_HELP_SUBCOMMAND = CommandSpec(
    name="help",
    about="Print this message or the help of the given subcommand(s)",
    args=(ArgSpec(id="command", value_name="COMMAND", action="append"),),
    disable_help_flag=True,
)
"""Added to every command with subcommands. The parser turns its matches into help."""


@dataclass(frozen=True, slots=True, eq=False)
class ResolvedArg:
    id: str
    short: str | None
    long: str | None
    help: str | None
    value_name: str
    required: bool
    action: ArgAction
    min_values: int
    max_values: int | None
    parser: ValueParser[Any] | None
    defaults: tuple[Any, ...]
    """Parsed values an absent argument resolves to (flags: False/True/0)."""
    defaults_raw: tuple[str, ...]
    """The user-written defaults, for help output."""
    default_missing: tuple[Any, ...]
    env: str | None
    conflicts_with: frozenset[str]
    requires: frozenset[str]
    allow_hyphen_values: bool
    value_delimiter: str | None
    hide: bool
    global_: bool
    aliases: tuple[str, ...]
    visible_aliases: tuple[str, ...]
    short_aliases: tuple[str, ...]
    visible_short_aliases: tuple[str, ...]

    @property
    def longs(self) -> tuple[str, ...]:
        """Every `--name` that selects this argument, the canonical one first."""
        own = () if self.long is None else (self.long,)
        return (*own, *self.visible_aliases, *self.aliases)

    @property
    def shorts(self) -> tuple[str, ...]:
        own = () if self.short is None else (self.short,)
        return (*own, *self.visible_short_aliases, *self.short_aliases)

    @property
    def is_positional(self) -> bool:
        return self.short is None and self.long is None

    @property
    def is_multiple(self) -> bool:
        return self.action == "append" or self.max_values is None or self.max_values > 1


@dataclass(frozen=True, slots=True, eq=False)
class ResolvedGroup:
    id: str
    members: tuple[str, ...]
    required: bool
    multiple: bool


@dataclass(frozen=True, slots=True, eq=False)
class ResolvedCommand:
    name: str
    path: tuple[str, ...]
    about: str | None
    version: str | None
    args: tuple[ResolvedArg, ...]
    by_id: Mapping[str, ResolvedArg]
    by_short: Mapping[str, ResolvedArg]
    by_long: Mapping[str, ResolvedArg]
    positionals: tuple[ResolvedArg, ...]
    groups: tuple[ResolvedGroup, ...]
    subcommands: Mapping[str, ResolvedCommand]
    """By canonical name, in definition order, the auto `help` subcommand last."""
    subcommand_names: Mapping[str, str]
    """Every name or alias that selects a subcommand, to its canonical name."""
    help_subcommand: bool
    """`subcommands["help"]` is the automatic one, which prints help instead of matching."""
    aliases: tuple[str, ...]
    visible_aliases: tuple[str, ...]
    inherited: frozenset[str]
    """Ids of the global arguments this command got from its ancestors."""
    subcommand_required: bool
    arg_required_else_help: bool
    help_hint: str | None
    """How errors point at help, e.g. `'--help'`; None when help is disabled."""


def build(spec: CommandSpec) -> ResolvedCommand:
    """Resolve the whole tree, panicking on the first definition bug."""
    return _build(spec, (), 0, ())


def _build(
    spec: CommandSpec,
    parent_path: tuple[str, ...],
    depth: int,
    inherited: tuple[ResolvedArg, ...],
) -> ResolvedCommand:
    """`inherited` holds the global arguments of every ancestor, root first."""
    path = (*parent_path, spec.name)
    where = f"Command {' '.join(path)!r}"
    invariant(
        depth < MAX_COMMAND_DEPTH,
        f"{where}: subcommands nest deeper than {MAX_COMMAND_DEPTH} levels",
    )
    invariant(
        depth > 0 or not (spec.aliases or spec.visible_aliases),
        f"{where}: aliases only apply to subcommands",
    )

    args = [_resolve_arg(arg, where) for arg in spec.args]
    duplicate = _first_duplicate([arg.id for arg in args])
    if duplicate is not None:
        bug(f"{where}: argument id {duplicate!r} is defined more than once")
    for arg in inherited:
        invariant(
            all(own.id != arg.id for own in args),
            f"{where}: argument id {arg.id!r} is already a global argument of a parent command",
        )
    args.extend(inherited)
    user_ids = {arg.id for arg in args}
    if not spec.disable_help_flag and "help" not in user_ids:
        args.append(_resolve_arg(_HELP_SPEC, where))
    if spec.version is not None and not spec.disable_version_flag and "version" not in user_ids:
        args.append(_resolve_arg(_VERSION_SPEC, where))
    invariant(
        spec.version is not None or all(arg.action != "version" for arg in args),
        f"{where}: an argument uses action 'version' but the command has no version()",
    )

    by_id = {arg.id: arg for arg in args}
    by_short: dict[str, ResolvedArg] = {}
    by_long: dict[str, ResolvedArg] = {}
    for arg in args:
        for short in arg.shorts:
            _claim(by_short, short, "-", arg, where)
        for long in arg.longs:
            _claim(by_long, long, "--", arg, where)

    positionals = tuple(arg for arg in args if arg.is_positional)
    _check_positionals(positionals, where)
    for arg in args:
        for other in sorted(arg.conflicts_with | arg.requires):
            invariant(other != arg.id, f"{where}: argument {arg.id!r} refers to itself")
            invariant(
                other in by_id,
                f"{where}: argument {arg.id!r} refers to unknown argument {other!r}",
            )
            invariant(
                not arg.global_ or by_id[other].global_,
                f"{where}: global argument {arg.id!r} refers to {other!r}, which is not "
                f"global, so subcommands could not check it; make {other!r} global too",
            )

    groups: list[ResolvedGroup] = []
    for group in spec.groups:
        invariant(
            group.id not in by_id and all(group.id != seen.id for seen in groups),
            f"{where}: group id {group.id!r} is already used by an argument or group",
        )
        invariant(len(group.args) > 0, f"{where}: group {group.id!r} has no arguments")
        for member in group.args:
            invariant(
                member in by_id,
                f"{where}: group {group.id!r} names unknown argument {member!r}",
            )
        groups.append(ResolvedGroup(group.id, group.args, group.required, group.multiple))

    globals_ = tuple(arg for arg in args if arg.global_)  # inherited ones first
    subcommands: dict[str, ResolvedCommand] = {}
    subcommand_names: dict[str, str] = {}
    for sub in spec.subcommands:
        invariant(
            sub.name not in subcommands,
            f"{where}: subcommand {sub.name!r} is defined more than once",
        )
        for name in (sub.name, *sub.visible_aliases, *sub.aliases):
            taken = subcommand_names.get(name)
            invariant(
                taken is None,
                f"{where}: subcommand name {name!r} is used by both {taken!r} and {sub.name!r}",
            )
            subcommand_names[name] = sub.name
        subcommands[sub.name] = _build(sub, path, depth + 1, globals_)
    invariant(
        not spec.subcommand_required or len(subcommands) > 0,
        f"{where}: subcommand_required(True) but no subcommands are defined",
    )
    help_subcommand = (
        bool(subcommands) and not spec.disable_help_subcommand and "help" not in subcommand_names
    )
    if help_subcommand:
        subcommands["help"] = _build(_HELP_SUBCOMMAND, path, depth + 1, ())
        subcommand_names["help"] = "help"

    help_arg = next((arg for arg in args if arg.action == "help"), None)
    return ResolvedCommand(
        name=spec.name,
        path=path,
        about=spec.about,
        version=spec.version,
        args=tuple(args),
        by_id=MappingProxyType(by_id),
        by_short=MappingProxyType(by_short),
        by_long=MappingProxyType(by_long),
        positionals=positionals,
        groups=tuple(groups),
        subcommands=MappingProxyType(subcommands),
        subcommand_names=MappingProxyType(subcommand_names),
        help_subcommand=help_subcommand,
        aliases=spec.aliases,
        visible_aliases=spec.visible_aliases,
        inherited=frozenset(arg.id for arg in inherited),
        subcommand_required=spec.subcommand_required,
        arg_required_else_help=spec.arg_required_else_help,
        help_hint=None if help_arg is None else _help_hint(help_arg),
    )


def _resolve_arg(spec: ArgSpec, where: str) -> ResolvedArg:
    action = spec.action
    label = f"{where}: argument {spec.id!r}"
    positional = spec.short is None and spec.long is None
    invariant(
        not positional
        or not (
            spec.aliases or spec.visible_aliases or spec.short_aliases or spec.visible_short_aliases
        ),
        f"{label}: aliases need short() or long(); a positional has no flag to alias",
    )
    if spec.global_:
        invariant(not positional, f"{label}: global_() needs short() or long()")
        invariant(
            not spec.required,
            f"{label}: a global argument cannot be required; it would be required at every level",
        )
        invariant(
            action not in ("help", "version"),
            f"{label}: action {action!r} cannot be global; every command gets its own",
        )
    if takes_values(action):
        default_arity = (1, None) if positional and action == "append" else (1, 1)
        min_values, max_values = spec.num_args if spec.num_args is not None else default_arity
        parser = spec.value_parser if spec.value_parser is not None else _STRING
        invariant(
            not (spec.required and spec.default_values),
            f"{label} is required, so its default value could never be used",
        )
        invariant(
            not spec.default_missing_values or min_values == 0,
            f"{label}: default_missing_value() needs num_args(0, ...) so the value can be omitted",
        )
        invariant(
            not (positional and spec.value_delimiter is not None),
            f"{label}: value_delimiter() is only supported on options",
        )
        invariant(
            action == "append" or max_values is None or len(spec.default_values) <= max_values,
            f"{label}: {len(spec.default_values)} default values, "
            f"but num_args allows at most {max_values}",
        )
        defaults = tuple(_parse_default(parser, raw, label) for raw in spec.default_values)
        default_missing = tuple(
            _parse_default(parser, raw, label) for raw in spec.default_missing_values
        )
    else:
        name = f"action {action!r}"
        invariant(
            not positional,
            f"{label}: {name} needs short() or long(); a positional always takes a value",
        )
        unused = [
            method
            for method, is_set in (
                ("num_args", spec.num_args is not None),
                ("value_parser", spec.value_parser is not None),
                ("default_value", bool(spec.default_values)),
                ("default_missing_value", bool(spec.default_missing_values)),
                ("value_delimiter", spec.value_delimiter is not None),
                ("allow_hyphen_values", spec.allow_hyphen_values),
                ("value_name", spec.value_name is not None),
            )
            if is_set
        ]
        invariant(not unused, f"{label}: {', '.join(unused)} does nothing with {name}")
        invariant(
            spec.env is None or action in ("set_true", "set_false"),
            f"{label}: env() does nothing with {name}",
        )
        invariant(
            not (spec.required and action in ("help", "version")),
            f"{label}: a required {name} argument makes the command unusable",
        )
        min_values, max_values = 0, 0
        parser = None
        defaults = _FLAG_DEFAULTS.get(action, ())
        default_missing = ()
    return ResolvedArg(
        id=spec.id,
        short=spec.short,
        long=spec.long,
        help=spec.help,
        value_name=spec.value_name or spec.id.upper(),
        required=spec.required,
        action=action,
        min_values=min_values,
        max_values=max_values,
        parser=parser,
        defaults=defaults,
        defaults_raw=spec.default_values,
        default_missing=default_missing,
        env=spec.env,
        conflicts_with=spec.conflicts_with,
        requires=spec.requires,
        allow_hyphen_values=spec.allow_hyphen_values,
        value_delimiter=spec.value_delimiter,
        hide=spec.hide,
        global_=spec.global_,
        aliases=spec.aliases,
        visible_aliases=spec.visible_aliases,
        short_aliases=spec.short_aliases,
        visible_short_aliases=spec.visible_short_aliases,
    )


def _parse_default(parser: ValueParser[Any], raw: str, label: str) -> Any:
    value = parser.parse(raw)
    if isinstance(value, Invalid):
        bug(f"{label}: default value {raw!r} is rejected by its value_parser: {value.message}")
    return value


def _check_positionals(positionals: Sequence[ResolvedArg], where: str) -> None:
    for arg in positionals[:-1]:
        invariant(
            arg.min_values == arg.max_values,
            f"{where}: positional {arg.id!r} takes a variable number of values, "
            f"so it must be the last positional",
        )
    optional_seen = None
    for arg in positionals:
        if optional_seen is not None:
            invariant(
                not arg.required,
                f"{where}: required positional {arg.id!r} comes after optional positional "
                f"{optional_seen!r}; values would be assigned ambiguously",
            )
        elif not arg.required:
            optional_seen = arg.id


def _claim(
    table: dict[str, ResolvedArg],
    key: str | None,
    dashes: str,
    arg: ResolvedArg,
    where: str,
) -> None:
    if key is None:
        return
    taken = table.get(key)
    if taken is arg:
        bug(f"{where}: argument {arg.id!r} lists '{dashes}{key}' more than once")
    if taken is not None:
        auto = {taken.action, arg.action} & {"help", "version"}
        inherited = ""
        if taken.global_ or arg.global_:
            owner = taken.id if taken.global_ else arg.id
            inherited = f"; {owner!r} is global, so it is already defined in every subcommand"
        bug(
            f"{where}: '{dashes}{key}' is used by both {taken.id!r} and {arg.id!r}"
            f"{_AUTO_FLAG_HINT if auto else inherited}"
        )
    table[key] = arg


def _help_hint(arg: ResolvedArg) -> str:
    return f"'--{arg.long}'" if arg.long is not None else f"'-{arg.short}'"


def _first_duplicate(items: Sequence[str]) -> str | None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            return item
        seen.add(item)
    return None
