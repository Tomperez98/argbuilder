"""Validate a command tree once and resolve every inferred setting.

Everything downstream (parser, help, matches) reads `Resolved*` values only:
no `None`-means-default fields, no re-validation. Every check here is a
definition bug, so each one panics.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from argbuilder._invariant import bug, invariant
from argbuilder._spec import SHELLS, ArgAction, ArgSpec, CommandSpec, takes_values
from argbuilder._value_parser import Invalid, ValueParser

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from argbuilder._spec import ValueHint

MAX_COMMAND_DEPTH = 32
"""Subcommand nesting bound. A deeper tree is a construction bug, not a real CLI."""

_STRING: ValueParser[str] = ValueParser(lambda raw: raw)
_FLAG_DEFAULTS: Mapping[ArgAction, tuple[Any, ...]] = MappingProxyType(
    {"set_true": (False,), "set_false": (True,), "count": (0,)},
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

_COMPLETION_SUBCOMMAND = CommandSpec(
    name="completion",
    about="Generate a shell completion script",
    args=(
        ArgSpec(
            id="shell",
            value_name="SHELL",
            required=True,
            value_parser=ValueParser.choices(*SHELLS),
            help="Shell to generate completions for",
        ),
    ),
)
"""Added by `completion_subcommand(True)`; the process edge prints its script."""


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
    overrides_with: frozenset[str]
    exclusive: bool
    required_unless_present: frozenset[str]
    required_if_eq: tuple[tuple[str, str], ...]
    allow_hyphen_values: bool
    allow_negative_numbers: bool
    require_equals: bool
    value_delimiter: str | None
    last: bool
    trailing_var_arg: bool
    hide: bool
    global_: bool
    value_hint: ValueHint | None
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
    arity_mins: tuple[tuple[ResolvedArg, int], ...]
    """Positionals with `min_values > 0`, precomputed so validation is O(given)."""
    required_args: tuple[ResolvedArg, ...]
    """Args with `required(True)`, precomputed for the missing-argument check."""
    conflicting_args: tuple[ResolvedArg, ...]
    """Args with a non-empty `conflicts_with`, precomputed for the conflict check."""
    requiring_args: tuple[ResolvedArg, ...]
    """Args with a non-empty `requires`, precomputed for the requires check."""
    conditional_args: tuple[ResolvedArg, ...]
    """Args with conditional requirements, precomputed for validation."""
    groups: tuple[ResolvedGroup, ...]
    subcommands: Mapping[str, ResolvedCommand]
    """By canonical name, in definition order, the auto `help` subcommand last."""
    subcommand_names: Mapping[str, str]
    """Every name or alias that selects a subcommand, to its canonical name."""
    help_subcommand: bool
    """`subcommands["help"]` is the automatic one, which prints help instead of matching."""
    completion_subcommand: bool
    """`completion_subcommand(True)` opted into the automatic `completion` command."""
    aliases: tuple[str, ...]
    visible_aliases: tuple[str, ...]
    inherited: frozenset[str]
    """Ids of the global arguments this command got from its ancestors."""
    env_names: frozenset[str]
    """Every environment variable this command or a subcommand below it reads."""
    subcommand_required: bool
    args_conflicts_with_subcommands: bool
    arg_required_else_help: bool
    hidden: bool
    help_hint: str | None
    """How errors point at help, e.g. `'--help'`; None when help is disabled."""


@functools.lru_cache(maxsize=256)
def build(spec: CommandSpec) -> ResolvedCommand:
    """Resolve the whole tree, panicking on the first definition bug.

    Pure: the result depends only on the immutable `CommandSpec`, so the same
    command reuses one resolved tree instead of rebuilding it on every parse
    or render. The bound keeps a program that builds many throwaway commands
    from retaining them all. Failures are not cached.
    """
    return _build(spec, (), 0, ())


def descendants(cmd: ResolvedCommand) -> Iterator[ResolvedCommand]:
    """Every subcommand below `cmd`, depth first. Depth is bounded by the build."""
    for sub in cmd.subcommands.values():
        yield sub
        yield from descendants(sub)


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
    invariant(
        depth > 0 or not spec.hidden,
        f"{where}: hide() only applies to subcommands; a top-level command is never hidden",
    )

    args = _resolve_args(spec, where, inherited)
    by_id, by_short, by_long = _index_args(args, where)
    _check_negative_number_shorts(args, by_short, where)

    positionals = tuple(arg for arg in args if arg.is_positional)
    _check_positionals(positionals, where)
    _check_cross_references(args, by_id, where)
    groups = _resolve_groups(spec, by_id, where)

    globals_ = tuple(arg for arg in args if arg.global_)  # inherited ones first
    # Precompute the subsets `_validate` needs, so a parse scans every argument
    # only once (in the matched loop), not four times including auto/hidden ones.
    arity_mins = tuple((arg, arg.min_values) for arg in positionals if arg.min_values > 0)
    required_args = tuple(arg for arg in args if arg.required)
    conflicting_args = tuple(arg for arg in args if arg.conflicts_with)
    requiring_args = tuple(arg for arg in args if arg.requires)
    conditional_args = tuple(
        arg for arg in args if arg.required_unless_present or arg.required_if_eq
    )
    _check_conditional_requirements(conditional_args, args, where)
    _check_subcommand_conflicts(spec, required_args, groups, where)

    subcommands, subcommand_names, help_subcommand = _resolve_subcommands(
        spec, path, depth, globals_, where
    )
    env_names = frozenset(arg.env for arg in args if arg.env is not None) | frozenset(
        name for sub in subcommands.values() for name in sub.env_names
    )
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
        arity_mins=arity_mins,
        required_args=required_args,
        conflicting_args=conflicting_args,
        requiring_args=requiring_args,
        conditional_args=conditional_args,
        groups=tuple(groups),
        subcommands=MappingProxyType(subcommands),
        subcommand_names=MappingProxyType(subcommand_names),
        help_subcommand=help_subcommand,
        completion_subcommand=spec.completion_subcommand,
        aliases=spec.aliases,
        visible_aliases=spec.visible_aliases,
        inherited=frozenset(arg.id for arg in inherited),
        env_names=env_names,
        subcommand_required=spec.subcommand_required,
        args_conflicts_with_subcommands=spec.args_conflicts_with_subcommands,
        arg_required_else_help=spec.arg_required_else_help,
        hidden=spec.hidden,
        help_hint=None if help_arg is None else _help_hint(help_arg),
    )


def _resolve_args(
    spec: CommandSpec,
    where: str,
    inherited: tuple[ResolvedArg, ...],
) -> list[ResolvedArg]:
    """Resolve the command's arguments, validating them alongside inherited globals and flags."""
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
    # The automatic flags are keyed on the *action*, not the id. Keying on the
    # id let an unrelated argument that happened to be named `help` or `version`
    # silently delete the flag; reusing a reserved id is a definition bug.
    has_help = any(arg.action == "help" for arg in args)
    has_version = any(arg.action == "version" for arg in args)
    if not spec.disable_help_flag and not has_help:
        invariant(
            "help" not in user_ids,
            f"{where}: argument id 'help' is reserved for the automatic -h/--help flag; "
            f"rename the argument, or give it action 'help' to replace the flag",
        )
        args.append(_resolve_arg(_HELP_SPEC, where))
    if spec.version is not None and not spec.disable_version_flag and not has_version:
        invariant(
            "version" not in user_ids,
            f"{where}: argument id 'version' is reserved for the automatic "
            f"-V/--version flag; rename the argument, or give it action 'version' "
            f"to replace the flag",
        )
        args.append(_resolve_arg(_VERSION_SPEC, where))
    invariant(
        spec.version is not None or not has_version,
        f"{where}: an argument uses action 'version' but the command has no version()",
    )
    return args


def _index_args(
    args: Sequence[ResolvedArg],
    where: str,
) -> tuple[dict[str, ResolvedArg], dict[str, ResolvedArg], dict[str, ResolvedArg]]:
    """Index by id and by every short/long spelling, panicking on a collision."""
    by_id = {arg.id: arg for arg in args}
    by_short: dict[str, ResolvedArg] = {}
    by_long: dict[str, ResolvedArg] = {}
    for arg in args:
        for short in arg.shorts:
            _claim(by_short, short, "-", arg, where)
        for long in arg.longs:
            _claim(by_long, long, "--", arg, where)
    return by_id, by_short, by_long


def _check_negative_number_shorts(
    args: Sequence[ResolvedArg],
    by_short: Mapping[str, ResolvedArg],
    where: str,
) -> None:
    """`allow_negative_numbers` and a digit short both claim `-5`; refuse the ambiguity."""
    if not any(arg.allow_negative_numbers for arg in args):
        return
    for short in sorted(by_short):
        invariant(
            not short.isdigit(),
            f"{where}: short '-{short}' collides with allow_negative_numbers(); "
            f"a token like '-{short}' could be either a flag or a value",
        )


def _check_cross_references(
    args: Sequence[ResolvedArg],
    by_id: Mapping[str, ResolvedArg],
    where: str,
) -> None:
    """Every cross-reference must name a real argument in scope, with coherent rules."""
    for arg in args:
        for other in sorted(arg.conflicts_with | arg.requires | arg.overrides_with):
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
        for other in sorted(arg.overrides_with):
            target = by_id[other]
            invariant(
                arg.global_ == target.global_,
                f"{where}: argument {arg.id!r} overrides {other!r}, but one is global "
                f"and the other is not; override targets must share the same scope",
            )
            invariant(
                other not in arg.conflicts_with and arg.id not in target.conflicts_with,
                f"{where}: argument {arg.id!r} both overrides and conflicts with {other!r}",
            )


def _check_subcommand_conflicts(
    spec: CommandSpec,
    required_args: Sequence[ResolvedArg],
    groups: Sequence[ResolvedGroup],
    where: str,
) -> None:
    """`args_conflicts_with_subcommands` must not make subcommands unusable."""
    if not spec.args_conflicts_with_subcommands:
        return
    if required_args:
        bug(
            f"{where}: args_conflicts_with_subcommands(True) but argument "
            f"{required_args[0].id!r} is required; a subcommand could never be used",
        )
    required_groups = [group.id for group in groups if group.required]
    if required_groups:
        bug(
            f"{where}: args_conflicts_with_subcommands(True) but group "
            f"{required_groups[0]!r} is required; a subcommand could never be used",
        )


def _check_conditional_requirements(
    conditional_args: Sequence[ResolvedArg],
    args: Sequence[ResolvedArg],
    where: str,
) -> None:
    """Validate conditional requirement targets and reject contradictory forms."""
    by_id = {arg.id: arg for arg in args}
    for arg in conditional_args:
        if arg.required_unless_present and arg.required_if_eq:
            bug(
                f"{where}: argument {arg.id!r} combines required_unless_present() and "
                f"required_if_eq(); pick one condition form",
            )
        if arg.required:
            bug(
                f"{where}: argument {arg.id!r} is both required(True) and conditionally "
                f"required; drop required(True)",
            )
        if arg.defaults:
            bug(
                f"{where}: argument {arg.id!r} has a default value, so its conditional "
                f"requirement could never apply",
            )
        targets = [
            *sorted(arg.required_unless_present),
            *(trigger for trigger, _ in arg.required_if_eq),
        ]
        for target in targets:
            invariant(
                target != arg.id,
                f"{where}: argument {arg.id!r} refers to itself",
            )
            invariant(
                target in by_id,
                f"{where}: argument {arg.id!r} refers to unknown argument {target!r}",
            )
            invariant(
                not arg.global_ or by_id[target].global_,
                f"{where}: global argument {arg.id!r} refers to {target!r}, which is not "
                f"global, so subcommands could not check it; make {target!r} global too",
            )
        for trigger, _ in arg.required_if_eq:
            invariant(
                takes_values(by_id[trigger].action),
                f"{where}: argument {arg.id!r} uses required_if_eq() on {trigger!r}, "
                f"which does not take a value",
            )


def _resolve_groups(
    spec: CommandSpec,
    by_id: Mapping[str, ResolvedArg],
    where: str,
) -> list[ResolvedGroup]:
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
    return groups


def _resolve_subcommands(
    spec: CommandSpec,
    path: tuple[str, ...],
    depth: int,
    globals_: tuple[ResolvedArg, ...],
    where: str,
) -> tuple[dict[str, ResolvedCommand], dict[str, str], bool]:
    """Build the subcommands, index every name and alias, and add the automatic `help` subcommand."""
    invariant(
        depth == 0 or not spec.completion_subcommand,
        f"{where}: completion_subcommand(True) only applies to the root command",
    )
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
    if spec.completion_subcommand:
        invariant(
            "completion" not in subcommand_names,
            f"{where}: subcommand name 'completion' is already used; "
            f"completion_subcommand(True) adds one automatically",
        )
        subcommands["completion"] = _build(_COMPLETION_SUBCOMMAND, path, depth + 1, ())
        subcommand_names["completion"] = "completion"
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
    return subcommands, subcommand_names, help_subcommand


@dataclass(frozen=True, slots=True)
class _ValueShape:
    """How an argument counts and parses its values: the builder-specific part of `ResolvedArg`."""

    min_values: int
    max_values: int | None
    parser: ValueParser[Any] | None
    defaults: tuple[Any, ...]
    default_missing: tuple[Any, ...]


def _resolve_arg(spec: ArgSpec, where: str) -> ResolvedArg:
    action = spec.action
    label = f"{where}: argument {spec.id!r}"
    positional = spec.short is None and spec.long is None
    _check_arg_shape(spec, action, label, positional)
    shape = (
        _resolve_value_arg(spec, action, label, positional)
        if takes_values(action)
        else _resolve_flag_arg(spec, action, label, positional)
    )
    return ResolvedArg(
        id=spec.id,
        short=spec.short,
        long=spec.long,
        help=spec.help,
        value_name=spec.value_name or spec.id.upper(),
        required=spec.required,
        action=action,
        min_values=shape.min_values,
        max_values=shape.max_values,
        parser=shape.parser,
        defaults=shape.defaults,
        defaults_raw=spec.default_values,
        default_missing=shape.default_missing,
        env=spec.env,
        conflicts_with=spec.conflicts_with,
        requires=spec.requires,
        overrides_with=spec.overrides_with,
        exclusive=spec.exclusive,
        required_unless_present=spec.required_unless_present,
        required_if_eq=spec.required_if_eq,
        allow_hyphen_values=spec.allow_hyphen_values,
        allow_negative_numbers=spec.allow_negative_numbers,
        require_equals=spec.require_equals,
        value_delimiter=spec.value_delimiter,
        last=spec.last,
        trailing_var_arg=spec.trailing_var_arg,
        hide=spec.hide,
        global_=spec.global_,
        value_hint=spec.value_hint,
        aliases=spec.aliases,
        visible_aliases=spec.visible_aliases,
        short_aliases=spec.short_aliases,
        visible_short_aliases=spec.visible_short_aliases,
    )


def _check_arg_shape(spec: ArgSpec, action: ArgAction, label: str, positional: bool) -> None:
    """Alias and global() rules that apply whatever the action is."""
    invariant(
        not positional
        or not (
            spec.aliases or spec.visible_aliases or spec.short_aliases or spec.visible_short_aliases
        ),
        f"{label}: aliases need short() or long(); a positional has no flag to alias",
    )
    invariant(
        not (positional and spec.exclusive),
        f"{label}: exclusive() needs short() or long(); a positional cannot conflict with all others",
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


def _resolve_value_arg(
    spec: ArgSpec,
    action: ArgAction,
    label: str,
    positional: bool,
) -> _ValueShape:
    """Resolve a value-taking argument's arity, parser and parsed defaults, panicking on misuse."""
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
        not (positional and spec.require_equals),
        f"{label}: require_equals() needs short() or long(); a positional has no '=' spelling",
    )
    invariant(
        not spec.require_equals
        or spec.value_delimiter is not None
        or (max_values is not None and max_values <= 1),
        f"{label}: require_equals() supplies at most one value with '='; "
        f"use num_args(0, 1) or add value_delimiter() to split that value",
    )
    invariant(
        not spec.last or positional,
        f"{label}: last() needs a positional argument; give it neither short() nor long()",
    )
    invariant(
        not (spec.last and spec.allow_hyphen_values),
        f"{label}: allow_hyphen_values() does nothing with last(); "
        f"every value after '--' is already taken verbatim",
    )
    invariant(
        not spec.trailing_var_arg or positional,
        f"{label}: trailing_var_arg() needs a positional; give it neither short() nor long()",
    )
    invariant(
        not (spec.trailing_var_arg and spec.last),
        f"{label}: trailing_var_arg() and last() are different syntaxes; pick one",
    )
    invariant(
        not (spec.trailing_var_arg and spec.allow_hyphen_values),
        f"{label}: allow_hyphen_values() does nothing with trailing_var_arg(); "
        f"every token after it starts is already a value",
    )
    invariant(
        not spec.trailing_var_arg or max_values is None,
        f"{label}: trailing_var_arg() needs an unbounded num_args(..., None)",
    )
    invariant(
        action == "append" or max_values is None or len(spec.default_values) <= max_values,
        f"{label}: {len(spec.default_values)} default values, "
        f"but num_args allows at most {max_values}",
    )
    return _ValueShape(
        min_values,
        max_values,
        parser,
        tuple(_parse_default(parser, raw, label) for raw in spec.default_values),
        tuple(_parse_default(parser, raw, label) for raw in spec.default_missing_values),
    )


def _resolve_flag_arg(
    spec: ArgSpec,
    action: ArgAction,
    label: str,
    positional: bool,
) -> _ValueShape:
    """Resolve a flag argument, panicking on any option that would have no effect."""
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
            ("allow_negative_numbers", spec.allow_negative_numbers),
            ("require_equals", spec.require_equals),
            ("value_name", spec.value_name is not None),
            ("value_hint", spec.value_hint is not None),
            ("last", spec.last),
            ("trailing_var_arg", spec.trailing_var_arg),
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
    return _ValueShape(0, 0, None, _FLAG_DEFAULTS.get(action, ()), ())


def _parse_default(parser: ValueParser[Any], raw: str, label: str) -> Any:
    value = parser.parse(raw)
    if isinstance(value, Invalid):
        bug(f"{label}: default value {raw!r} is rejected by its value_parser: {value.message}")
    return value


def _check_positionals(positionals: Sequence[ResolvedArg], where: str) -> None:
    last_ids = [arg.id for arg in positionals if arg.last]
    invariant(
        len(last_ids) <= 1,
        f"{where}: last(True) is set on more than one positional: {last_ids}",
    )
    trailing_ids = [arg.id for arg in positionals if arg.trailing_var_arg]
    invariant(
        len(trailing_ids) <= 1,
        f"{where}: trailing_var_arg(True) is set on more than one positional: {trailing_ids}",
    )
    invariant(
        not trailing_ids or positionals[-1].id == trailing_ids[0],
        f"{where}: trailing_var_arg(True) positional "
        f"{trailing_ids[0] if trailing_ids else ''!r} must be the final positional",
    )
    invariant(
        not last_ids or positionals[-1].id == last_ids[0],
        f"{where}: last(True) positional {last_ids[0] if last_ids else ''!r} "
        f"must be the final positional",
    )
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
    key: str,
    dashes: str,
    arg: ResolvedArg,
    where: str,
) -> None:
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
            f"{_AUTO_FLAG_HINT if auto else inherited}",
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
