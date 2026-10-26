"""The parser: a pure function from (command, tokens, env) to `ArgMatches | Error`.

No IO, no globals: the environment arrives as a mapping, and output is
produced only by the caller at the edge (`Error.exit()`).
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from argbuilder._error import (
    ArgumentConflict,
    DisplayHelp,
    DisplayHelpOnMissingArgumentOrSubcommand,
    DisplayVersion,
    Error,
    ErrorKind,
    InvalidSubcommand,
    InvalidValue,
    MissingRequiredArgument,
    MissingSubcommand,
    ParseFailure,
    SubcommandConflict,
    TooFewValues,
    TooManyValues,
    UnknownArgument,
    describe,
)
from argbuilder._help import display_arg, render_help, render_version, usage_error
from argbuilder._invariant import bug, invariant
from argbuilder._matches import ArgMatches, MatchedArg
from argbuilder._spec import is_negative_number, takes_values
from argbuilder._suggest import suggest
from argbuilder._value_parser import Invalid, parse_boolish

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from argbuilder._build import ResolvedArg, ResolvedCommand


def parse(
    cmd: ResolvedCommand,
    tokens: Sequence[str],
    env: Mapping[str, str],
) -> ArgMatches | Error:
    """Parse the tokens after the command name. Recurses once per subcommand level."""
    return _Parser(
        cmd,
        env,
        (),
        {},
        given_globals=set(),
        raw_globals={},
    ).run(tokens)


class _Parser:
    """Mutable state for parsing a single command level, discarded afterwards."""

    def __init__(
        self,
        cmd: ResolvedCommand,
        env: Mapping[str, str],
        ancestors: tuple[ResolvedCommand, ...],
        globals_: dict[str, list[Any]],
        *,
        given_globals: set[str],
        raw_globals: dict[str, list[str]],
    ) -> None:
        self._cmd = cmd
        self._env = env
        self._ancestors = ancestors
        """Commands above this one, root first. Only used to word error tips."""
        self._local: dict[str, list[Any]] = {}
        """Command-line values of this level's own arguments."""
        self._globals = globals_
        """Command-line values of global arguments, shared by every level of one parse.

        Each level finishes after all tokens are consumed (a subcommand takes
        the rest of the line), so every level sees the complete values.
        """
        self._given_globals = given_globals
        """Ids of global arguments given anywhere on this command line."""
        self._raw_local: dict[str, list[str]] = {}
        """Raw command-line spellings of this level's own arguments."""
        self._raw_globals = raw_globals
        """Raw command-line spellings of global arguments, shared across levels."""
        self._given_here: set[str] = set()
        """Ids of arguments given explicitly at this level, globals included."""
        self._positional_index = 0
        self._subcommand: tuple[str, ArgMatches] | None = None
        self._escaped = False
        """After a literal "--", every token is positional; a `last` positional opens up."""
        self._trailing = False
        """A `trailing_var_arg` positional has started; every later token is its value."""

    def run(self, tokens: Sequence[str], start: int = 0) -> ArgMatches | Error:
        cmd = self._cmd
        if cmd.arg_required_else_help and start >= len(tokens):
            return _help_error(DisplayHelpOnMissingArgumentOrSubcommand(), cmd)
        index = start
        while index < len(tokens):
            if self._trailing:
                step = self._trailing_values(tokens, index)
                if isinstance(step, Error):
                    return step
                index = step
                continue
            token = tokens[index]
            if self._escaped:
                step = self._positional(token, index)
            elif token == "--":
                self._escaped = True
                step = index + 1
            elif token.startswith("--"):
                step = self._long(tokens, index)
            elif token.startswith("-") and token != "-":
                if is_negative_number(token) and self._negative_positional() is not None:
                    step = self._positional(token, index)
                else:
                    step = self._short(tokens, index)
            elif token in cmd.subcommand_names:
                name = cmd.subcommand_names[token]
                child = _Parser(
                    cmd.subcommands[name],
                    self._env,
                    (*self._ancestors, cmd),
                    self._globals,
                    given_globals=self._given_globals,
                    raw_globals=self._raw_globals,
                )
                sub = child.run(tokens, index + 1)
                if isinstance(sub, Error):
                    return sub
                if name == "help" and cmd.help_subcommand:
                    return _help_for(cmd, sub.get_many("command", str))
                self._subcommand = (name, sub)
                break
            else:
                step = self._positional(token, index)
            if isinstance(step, Error):
                return step
            # Each step consumes >= 1 token, so the loop runs at most len(tokens) times.
            # Static message: an f-string here would format a token on every step.
            invariant(step > index, "parser made no progress")
            index = step
        return self._finish()

    # -- tokens -------------------------------------------------------------

    def _long(self, tokens: Sequence[str], index: int) -> int | Error:
        token = tokens[index]
        name, has_value, inline = token[2:].partition("=")
        arg = self._cmd.by_long.get(name)
        if arg is None:
            candidates = [
                f"--{long}"
                for long, known in self._cmd.by_long.items()
                if not known.hide and long not in known.aliases
            ]
            return self._unknown(token, index, f"--{name}", candidates)
        if takes_values(arg.action):
            return self._take_values(
                arg,
                inline if has_value else None,
                tokens,
                index + 1,
                flag=f"--{name}",
            )
        if has_value:
            return self._unexpected_value(arg, inline)
        return self._flag(arg, index + 1)

    def _short(self, tokens: Sequence[str], index: int) -> int | Error:
        token = tokens[index]
        cluster = token[1:]
        if cluster[0] not in self._cmd.by_short:
            return self._unknown(token, index, f"-{cluster[0]}", [])
        for offset, char in enumerate(cluster):
            arg = self._cmd.by_short.get(char)
            if arg is None:
                return self._error(
                    UnknownArgument(f"-{char}"),
                    tip=self._defined_elsewhere(f"-{char}")
                    or f"to pass '{token}' as a value, use '-- {token}'",
                )
            rest = cluster[offset + 1 :]
            if takes_values(arg.action):
                if arg.require_equals and rest and not rest.startswith("="):
                    return self._missing_equals(arg, f"-{char}")
                inline = rest.removeprefix("=") if rest else None
                return self._take_values(
                    arg,
                    inline,
                    tokens,
                    index + 1,
                    flag=f"-{char}",
                )
            if rest.startswith("="):
                return self._unexpected_value(arg, rest[1:])
            step = self._flag(arg, index + 1)
            if isinstance(step, Error):
                return step
        return index + 1

    def _positional(self, token: str, index: int) -> int | Error:
        arg = self._current_positional()
        if arg is None:
            if self._pending_last() is not None:
                return self._error(
                    UnknownArgument(token),
                    tip=f"to pass '{token}' as a value, use '-- {token}'",
                )
            if self._cmd.subcommands:
                closest = suggest(token, _visible_subcommand_names(self._cmd))
                return self._error(
                    InvalidSubcommand(token, closest),
                    tip=_similar_tip("subcommand", closest),
                )
            return self._error(UnknownArgument(token))
        values = self._parse_values(arg, [token], env=None)
        if isinstance(values, Error):
            return values
        stored = self._local.setdefault(arg.id, [])
        stored.extend(values)
        self._raw_store(arg).setdefault(arg.id, []).append(token)
        self._mark_given(arg)
        self._remove_overridden(arg)
        if arg.trailing_var_arg:
            self._trailing = True
        if arg.max_values is not None and len(stored) >= arg.max_values:
            self._positional_index += 1
        return index + 1

    def _trailing_values(self, tokens: Sequence[str], index: int) -> int | Error:
        """Take every remaining token as a value of the trailing positional."""
        arg = self._current_positional()
        if arg is None or not arg.trailing_var_arg:
            bug("trailing mode without a trailing positional")
        values = self._parse_values(arg, list(tokens[index:]), env=None)
        if isinstance(values, Error):
            return values
        raw_values = list(tokens[index:])
        self._local.setdefault(arg.id, []).extend(values)
        self._raw_store(arg).setdefault(arg.id, []).extend(raw_values)
        self._mark_given(arg)
        self._remove_overridden(arg)
        self._positional_index += 1
        return len(tokens)

    def _unknown(self, token: str, index: int, flag: str, candidates: list[str]) -> int | Error:
        """`token` names no argument here; `flag` is the `--name` or `-c` it starts with."""
        current = self._current_positional()
        if current is not None and current.allow_hyphen_values:
            return self._positional(token, index)
        closest = suggest(token, candidates)
        tip = (
            self._defined_elsewhere(flag)
            or _similar_tip("argument", closest)
            or f"to pass '{token}' as a value, use '-- {token}'"
        )
        return self._error(UnknownArgument(token, closest), tip)

    # -- actions ------------------------------------------------------------

    def _flag(self, arg: ResolvedArg, next_index: int) -> int | Error:
        match arg.action:
            case "set" | "append":
                bug(f"_flag() called for value-taking argument {arg.id!r}")
            case "help":
                return _help_error(DisplayHelp(), self._cmd)
            case "version":
                return Error(DisplayVersion(), render_version(self._cmd))
            case "count":
                store = self._store(arg)
                (count,) = store.get(arg.id, [0])
                store[arg.id] = [count + 1]
                self._mark_given(arg)
                self._remove_overridden(arg)
            case "set_true" | "set_false":  # pragma: no branch
                store = self._store(arg)
                if arg.id in store:
                    return self._repeated(arg)
                store[arg.id] = [arg.action == "set_true"]
                self._mark_given(arg)
                self._remove_overridden(arg)
        return next_index

    def _take_values(
        self,
        arg: ResolvedArg,
        inline: str | None,
        tokens: Sequence[str],
        index: int,
        *,
        flag: str | None = None,
    ) -> int | Error:
        if inline is not None:
            raws = [inline]
        elif arg.require_equals:
            if arg.min_values > 0:
                return self._missing_equals(arg, flag)
            # `--color` with num_args(0, ...) is present with no value; the
            # next token belongs to the caller, never to this option.
            raws = []
        else:
            raws = []
            while (
                index < len(tokens)
                and (arg.max_values is None or len(raws) < arg.max_values)
                and _is_value(tokens[index], arg)
            ):
                raws.append(tokens[index])
                index += 1
        if not raws and arg.min_values > 0:
            nearby = tokens[index] if index < len(tokens) else None
            tip = None
            if nearby is not None and nearby.startswith("-") and not arg.is_positional:
                flag = f"--{arg.long}" if arg.long is not None else f"-{arg.short}"
                tip = f"to pass '{nearby}' as a value, use '{flag}={nearby}'"
            return self._error(InvalidValue(display_arg(arg), None), tip)
        stored_raws = raws
        if raws:
            values = self._parse_values(arg, raws, env=None)
            if isinstance(values, Error):
                return values
        else:
            values = list(arg.default_missing)
            stored_raws = list(arg.default_missing_raw)
        store = self._store(arg)
        if arg.action == "set":
            if arg.id in store:
                return self._repeated(arg)
            store[arg.id] = values
        else:
            store.setdefault(arg.id, []).extend(values)
        self._raw_store(arg).setdefault(arg.id, []).extend(stored_raws)
        self._mark_given(arg)
        self._remove_overridden(arg)
        return index

    def _parse_values(
        self,
        arg: ResolvedArg,
        raws: list[str],
        env: str | None,
        *,
        complete: bool = False,
    ) -> list[Any] | Error:
        """Split, count-check and parse raw strings. `env` names the variable they came from.

        `complete` says `raws` is the argument's whole value set (an environment
        value), not one command-line token. Positionals are filled token by token
        and checked for minimum arity after the line, so only a complete set can
        be checked here for them.
        """
        parser = arg.parser
        if parser is None:
            bug(f"argument {arg.id!r} takes values but has no parser")
        if arg.value_delimiter is not None:
            raws = [piece for raw in raws for piece in raw.split(arg.value_delimiter)]
        arity = complete or not arg.is_positional
        if arity and len(raws) < arg.min_values:
            return self._error(TooFewValues(display_arg(arg), arg.min_values, len(raws), env))
        if arity and arg.max_values is not None and len(raws) > arg.max_values:
            return self._error(TooManyValues(display_arg(arg), raws[arg.max_values], env))
        values: list[Any] = []
        for raw in raws:
            value = parser.parse(raw)
            if not isinstance(value, Invalid):
                values.append(value)
                continue
            shown = display_arg(arg)
            if parser.possible_values:
                closest = suggest(raw, parser.possible_values)
                kind = InvalidValue(shown, raw, value.message, parser.possible_values, closest, env)
                return self._error(kind, tip=_similar_tip("value", closest))
            return self._error(InvalidValue(shown, raw, value.message, env=env))
        return values

    # -- after the last token -----------------------------------------------

    def _finish(self) -> ArgMatches | Error:
        matched: dict[str, MatchedArg] = {}
        for arg in self._cmd.args:
            store = self._store(arg)
            if arg.id in store:
                matched[arg.id] = MatchedArg(
                    tuple(store[arg.id]),
                    "command_line",
                    tuple(self._raw_store(arg).get(arg.id, ())),
                )
                continue
            raw = self._env.get(arg.env, "") if arg.env is not None else ""
            if raw != "":
                values = self._env_values(arg, raw)
                if isinstance(values, Error):
                    return values
                matched[arg.id] = MatchedArg(
                    tuple(values),
                    "env_variable",
                    (raw,) if takes_values(arg.action) else (),
                )
            elif arg.defaults:
                matched[arg.id] = MatchedArg(
                    arg.defaults,
                    "default_value",
                    arg.defaults_raw if takes_values(arg.action) else (),
                )
        if self._runs_completion_command():
            return ArgMatches(self._cmd, matched, self._subcommand)
        problem = self._validate(matched)
        if problem is not None:
            return problem
        return ArgMatches(self._cmd, matched, self._subcommand)

    def _runs_completion_command(self) -> bool:
        """Whether this level chose the automatic `completion` command.

        That command is a meta command like `help`: it prints a script from the
        command tree, so this level's required arguments, conflicts and arity do
        not apply. The completion command's own arguments were validated by its
        parser before this level finished.
        """
        return (
            self._cmd.completion_subcommand
            and self._subcommand is not None
            and self._subcommand[0] == "completion"
        )

    def _env_values(self, arg: ResolvedArg, raw: str) -> list[Any] | Error:
        if takes_values(arg.action):
            return self._parse_values(arg, [raw], arg.env, complete=True)
        flag = parse_boolish(raw)
        if isinstance(flag, Invalid):
            return self._error(InvalidValue(display_arg(arg), raw, flag.message, env=arg.env))
        return [flag if arg.action == "set_true" else not flag]

    def _validate(self, matched: Mapping[str, MatchedArg]) -> Error | None:
        explicit = {id for id, m in matched.items() if m.source != "default_value"}
        conflict = self._check_conflicts(explicit)
        if conflict is not None:
            return conflict
        missing = self._collect_missing(matched, explicit)
        if missing:
            return self._error(MissingRequiredArgument(tuple(missing)))
        arity = self._check_arity()
        if arity is not None:
            return arity
        return self._check_subcommand()

    def _check_conflicts(self, explicit: set[str]) -> Error | None:
        """Reject arguments that exclude each other, or a parent argument beside a subcommand."""
        cmd = self._cmd
        for arg in cmd.conflicting_args:
            if arg.id not in explicit:
                continue
            for other in sorted(arg.conflicts_with & explicit):
                return self._conflict(arg, cmd.by_id[other])
        for arg in cmd.args:
            if not arg.exclusive or arg.id not in explicit:
                continue
            other = next(
                (
                    candidate
                    for candidate in cmd.args
                    if candidate.id in explicit and candidate is not arg
                ),
                None,
            )
            if other is not None:
                return self._conflict(arg, other)
        if cmd.args_conflicts_with_subcommands and self._subcommand is not None:
            given = next(
                (
                    arg
                    for arg in cmd.args
                    if arg.id in self._given_here
                    and (not arg.global_ or arg.id in self._given_globals)
                ),
                None,
            )
            if given is not None:
                return self._error(SubcommandConflict(display_arg(given), self._subcommand[0]))
        for group in cmd.groups:
            present = [cmd.by_id[member] for member in group.members if member in explicit]
            if not group.multiple and len(present) > 1:
                return self._conflict(present[0], present[1])
        return None

    def _collect_missing(
        self,
        matched: Mapping[str, MatchedArg],
        explicit: set[str],
    ) -> list[str]:
        """Required arguments, groups, dependencies and conditional requirements."""
        cmd = self._cmd
        missing: list[str] = [
            display_arg(arg) for arg in cmd.required_args if arg.id not in explicit
        ]
        for group in cmd.groups:
            if group.required and not any(
                self._present(matched, member) for member in group.members
            ):
                members = "|".join(display_arg(cmd.by_id[member]) for member in group.members)
                missing.append(f"<{members}>")
        for arg in cmd.requiring_args:
            if arg.id not in explicit:
                continue
            for needed in sorted(arg.requires):
                if self._present(matched, needed):
                    continue
                shown = display_arg(cmd.by_id[needed])
                if shown not in missing:
                    missing.append(shown)
        for arg in cmd.conditional_args:
            if self._present(matched, arg.id):
                continue
            if arg.required_unless_present and any(
                self._present(matched, target) for target in arg.required_unless_present
            ):
                continue
            if arg.required_if_eq and not any(
                configured in matched[trigger].raws
                for trigger, configured in arg.required_if_eq
                if trigger in matched
            ):
                continue
            shown = display_arg(arg)
            if shown not in missing:
                missing.append(shown)
        return missing

    def _present(self, matched: Mapping[str, MatchedArg], id: str) -> bool:
        """Present for a condition: explicit, or a user-written default, not a flag's implicit one."""
        entry = matched.get(id)
        if entry is None:
            return False
        return entry.source != "default_value" or bool(self._cmd.by_id[id].defaults_raw)

    def _check_arity(self) -> Error | None:
        for arg, min_values in self._cmd.arity_mins:
            count = len(self._local.get(arg.id, ()))
            if 0 < count < min_values:
                return self._error(TooFewValues(display_arg(arg), min_values, count))
        return None

    def _check_subcommand(self) -> Error | None:
        cmd = self._cmd
        if cmd.subcommand_required and self._subcommand is None:
            visible = tuple(name for name, sub in cmd.subcommands.items() if not sub.hidden)
            return self._error(MissingSubcommand(" ".join(cmd.path), visible))
        return None

    # -- helpers ------------------------------------------------------------

    def _defined_elsewhere(self, flag: str) -> str | None:
        """A tip when `flag` is unknown here but exists on a parent or subcommand."""
        owners = [
            other
            for other in (*reversed(self._ancestors), *_visible_descendants(self._cmd))
            if _owns(other, flag)
        ]
        if not owners:
            return None
        if len(owners) > 1:
            listed = ", ".join(f"'{' '.join(owner.path)}'" for owner in owners)
            return f"'{flag}' is an option of {listed}"
        (owner,) = owners
        here = self._cmd.path
        if len(owner.path) < len(here):
            between = " ".join(here[len(owner.path) :])
            return f"'{flag}' is an option of '{' '.join(owner.path)}'; put it before '{between}'"
        between = " ".join(owner.path[len(here) :])
        return f"'{flag}' is an option of '{' '.join(owner.path)}'; put it after '{between}'"

    def _store(self, arg: ResolvedArg) -> dict[str, list[Any]]:
        return self._globals if arg.global_ else self._local

    def _raw_store(self, arg: ResolvedArg) -> dict[str, list[str]]:
        return self._raw_globals if arg.global_ else self._raw_local

    def _mark_given(self, arg: ResolvedArg) -> None:
        """Remember that `arg` came from this level's command line, not env/default."""
        self._given_here.add(arg.id)
        if arg.global_:
            self._given_globals.add(arg.id)

    def _remove_overridden(self, arg: ResolvedArg) -> None:
        """Last one wins: drop earlier command-line values of `arg.overrides_with`."""
        if not arg.overrides_with:
            return
        store = self._store(arg)
        raw_store = self._raw_store(arg)
        for target in arg.overrides_with:
            store.pop(target, None)
            raw_store.pop(target, None)
        self._given_here.difference_update(arg.overrides_with)
        if arg.global_:
            self._given_globals.difference_update(arg.overrides_with)

    def _current_positional(self) -> ResolvedArg | None:
        positionals = self._cmd.positionals
        index = self._positional_index
        if index >= len(positionals):
            return None
        arg = positionals[index]
        # A `last` positional only opens up after a literal "--"; before that,
        # it isn't there to fill, so an extra token is unknown, not assigned to it.
        return None if arg.last and not self._escaped else arg

    def _negative_positional(self) -> ResolvedArg | None:
        """The current positional, when it opted into negative numeric values."""
        arg = self._current_positional()
        return arg if arg is not None and arg.allow_negative_numbers else None

    def _pending_last(self) -> ResolvedArg | None:
        """The `last` positional, when it's the reason `_current_positional()` is None."""
        positionals = self._cmd.positionals
        index = self._positional_index
        if self._escaped or index >= len(positionals):
            return None
        arg = positionals[index]
        return arg if arg.last else None

    def _error(self, kind: ParseFailure, tip: str | None = None) -> Error:
        return usage_error(self._cmd, kind, describe(kind), tip)

    def _repeated(self, arg: ResolvedArg) -> Error:
        return self._error(ArgumentConflict(display_arg(arg), None))

    def _missing_equals(self, arg: ResolvedArg, flag: str | None) -> Error:
        """`require_equals` was set but the value did not use `=`."""
        used = flag or (f"--{arg.long}" if arg.long is not None else f"-{arg.short}")
        return self._error(
            InvalidValue(display_arg(arg), None),
            tip=f"use '{used}=<{arg.value_name}>' (with an equals sign)",
        )

    def _conflict(self, first: ResolvedArg, second: ResolvedArg) -> Error:
        return self._error(ArgumentConflict(display_arg(first), display_arg(second)))

    def _unexpected_value(self, arg: ResolvedArg, value: str) -> Error:
        return self._error(TooManyValues(display_arg(arg), value))


def _is_value(token: str, arg: ResolvedArg) -> bool:
    if token == "--":
        return False
    if arg.allow_hyphen_values or token == "-" or not token.startswith("-"):
        return True
    return arg.allow_negative_numbers and is_negative_number(token)


def _help_error(kind: ErrorKind, cmd: ResolvedCommand) -> Error:
    """Help as an `Error`: plain text now, restyled for the terminal at `exit()`."""
    return Error(kind, render_help(cmd), restyle=functools.partial(render_help, cmd))


def _help_for(cmd: ResolvedCommand, names: Sequence[str]) -> Error:
    """`cmd help a b`: the help of `cmd a b`, or an error naming the first unknown name."""
    target = cmd
    for name in names:
        canonical = target.subcommand_names.get(name)
        if canonical is None:
            closest = suggest(name, _visible_subcommand_names(target))
            kind = InvalidSubcommand(name, closest)
            return usage_error(target, kind, describe(kind), _similar_tip("subcommand", closest))
        target = target.subcommands[canonical]
    return _help_error(DisplayHelp(), target)


def _visible_descendants(cmd: ResolvedCommand) -> Iterator[ResolvedCommand]:
    """Every subcommand below `cmd` except hidden ones and their whole subtree."""
    for sub in cmd.subcommands.values():
        if sub.hidden:
            continue
        yield sub
        yield from _visible_descendants(sub)


def _visible_subcommand_names(cmd: ResolvedCommand) -> list[str]:
    """Names worth suggesting: canonical names and visible aliases, not hidden aliases."""
    return [
        name
        for name, canonical in cmd.subcommand_names.items()
        if not cmd.subcommands[canonical].hidden and name not in cmd.subcommands[canonical].aliases
    ]


def _owns(cmd: ResolvedCommand, flag: str) -> bool:
    """Whether `cmd` offers `flag` as a visible, non-inherited spelling.

    Hidden commands, hidden arguments and hidden aliases never appear in a tip,
    and an inherited global belongs to the ancestor that defined it.
    """
    if cmd.hidden:
        return False
    if flag.startswith("--"):
        name = flag[2:]
        arg = cmd.by_long.get(name)
        if arg is None or arg.hide or name in arg.aliases:
            return False
    else:
        char = flag[1:]
        arg = cmd.by_short.get(char)
        if arg is None or arg.hide or char in arg.short_aliases:
            return False
    return arg.id not in cmd.inherited


def _similar_tip(what: str, closest: str | None) -> str | None:
    return None if closest is None else f"a similar {what} exists: '{closest}'"
