"""The parser: a pure function from (command, tokens, env) to `ArgMatches | Error`.

No IO, no globals: the environment arrives as a mapping, and output is
produced only by the caller at the edge (`Error.exit()`).
"""

from __future__ import annotations

import difflib
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
    TooFewValues,
    TooManyValues,
    UnknownArgument,
    describe,
)
from argbuilder._help import display_arg, render_help, render_version, usage_error
from argbuilder._invariant import bug, invariant
from argbuilder._matches import ArgMatches, MatchedArg
from argbuilder._spec import takes_values
from argbuilder._value_parser import Invalid, parse_boolish

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from argbuilder._build import ResolvedArg, ResolvedCommand


def parse(
    cmd: ResolvedCommand, tokens: Sequence[str], env: Mapping[str, str]
) -> ArgMatches | Error:
    """Parse the tokens after the command name. Recurses once per subcommand level."""
    return _Parser(cmd, env, (), {}).run(tokens)


class _Parser:
    """Mutable state for parsing a single command level, discarded afterwards."""

    def __init__(
        self,
        cmd: ResolvedCommand,
        env: Mapping[str, str],
        ancestors: tuple[ResolvedCommand, ...],
        globals_: dict[str, list[Any]],
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
        self._positional_index = 0
        self._subcommand: tuple[str, ArgMatches] | None = None

    def run(self, tokens: Sequence[str]) -> ArgMatches | Error:
        cmd = self._cmd
        if cmd.arg_required_else_help and not tokens:
            return _help_error(DisplayHelpOnMissingArgumentOrSubcommand(), cmd)
        index = 0
        escaped = False  # after "--", every token is positional
        while index < len(tokens):
            token = tokens[index]
            if escaped:
                step = self._positional(token, index)
            elif token == "--":
                escaped = True
                step = index + 1
            elif token.startswith("--"):
                step = self._long(tokens, index)
            elif token.startswith("-") and token != "-":
                step = self._short(tokens, index)
            elif token in cmd.subcommand_names:
                name = cmd.subcommand_names[token]
                child = _Parser(
                    cmd.subcommands[name],
                    self._env,
                    (*self._ancestors, cmd),
                    self._globals,
                )
                sub = child.run(tokens[index + 1 :])
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
            invariant(step > index, f"parser made no progress at token {token!r}")
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
                arg, inline if has_value else None, tokens, index + 1
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
                inline = rest.removeprefix("=") if rest else None
                return self._take_values(arg, inline, tokens, index + 1)
            if rest.startswith("="):
                return self._unexpected_value(arg, rest[1:])
            step = self._flag(arg, index + 1)
            if isinstance(step, Error):
                return step
        return index + 1

    def _positional(self, token: str, index: int) -> int | Error:
        arg = self._current_positional()
        if arg is None:
            if self._cmd.subcommands:
                closest = _closest(token, _visible_subcommand_names(self._cmd))
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
        if arg.max_values is not None and len(stored) >= arg.max_values:
            self._positional_index += 1
        return index + 1

    def _unknown(
        self, token: str, index: int, flag: str, candidates: list[str]
    ) -> int | Error:
        """`token` names no argument here; `flag` is the `--name` or `-c` it starts with."""
        current = self._current_positional()
        if current is not None and current.allow_hyphen_values:
            return self._positional(token, index)
        closest = _closest(token, candidates)
        tip = (
            self._defined_elsewhere(flag)
            or _similar_tip("argument", closest)
            or f"to pass '{token}' as a value, use '-- {token}'"
        )
        return self._error(UnknownArgument(token, closest), tip)

    # -- actions ------------------------------------------------------------

    def _flag(self, arg: ResolvedArg, next_index: int) -> int | Error:
        match arg.action:
            case "help":
                return _help_error(DisplayHelp(), self._cmd)
            case "version":
                return Error(DisplayVersion(), render_version(self._cmd))
            case "count":
                store = self._store(arg)
                (count,) = store.get(arg.id, [0])
                store[arg.id] = [count + 1]
            case "set_true" | "set_false":
                store = self._store(arg)
                if arg.id in store:
                    return self._repeated(arg)
                store[arg.id] = [arg.action == "set_true"]
            case "set" | "append":
                bug(f"_flag() called for value-taking argument {arg.id!r}")
        return next_index

    def _take_values(
        self, arg: ResolvedArg, inline: str | None, tokens: Sequence[str], index: int
    ) -> int | Error:
        if inline is not None:
            raws = [inline]
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
        if raws:
            values = self._parse_values(arg, raws, env=None)
            if isinstance(values, Error):
                return values
        else:
            values = list(arg.default_missing)
        store = self._store(arg)
        if arg.action == "set":
            if arg.id in store:
                return self._repeated(arg)
            store[arg.id] = values
        else:
            store.setdefault(arg.id, []).extend(values)
        return index

    def _parse_values(
        self, arg: ResolvedArg, raws: list[str], env: str | None
    ) -> list[Any] | Error:
        """Split, count-check and parse raw strings. `env` names the variable they came from."""
        parser = arg.parser
        if parser is None:
            bug(f"argument {arg.id!r} takes values but has no parser")
        if arg.value_delimiter is not None:
            raws = [piece for raw in raws for piece in raw.split(arg.value_delimiter)]
        shown = display_arg(arg)
        if not arg.is_positional and len(raws) < arg.min_values:
            return self._error(TooFewValues(shown, arg.min_values, len(raws), env))
        if (
            not arg.is_positional
            and arg.max_values is not None
            and len(raws) > arg.max_values
        ):
            return self._error(TooManyValues(shown, raws[arg.max_values], env))
        values: list[Any] = []
        for raw in raws:
            value = parser.parse(raw)
            if not isinstance(value, Invalid):
                values.append(value)
                continue
            if parser.possible_values:
                closest = _closest(raw, list(parser.possible_values))
                kind = InvalidValue(
                    shown, raw, value.message, parser.possible_values, closest, env
                )
                return self._error(kind, tip=_similar_tip("value", closest))
            return self._error(InvalidValue(shown, raw, value.message, env=env))
        return values

    # -- after the last token -----------------------------------------------

    def _finish(self) -> ArgMatches | Error:
        matched: dict[str, MatchedArg] = {}
        for arg in self._cmd.args:
            store = self._store(arg)
            if arg.id in store:
                matched[arg.id] = MatchedArg(tuple(store[arg.id]), "command_line")
                continue
            raw = self._env.get(arg.env, "") if arg.env is not None else ""
            if raw != "":
                values = self._env_values(arg, raw)
                if isinstance(values, Error):
                    return values
                matched[arg.id] = MatchedArg(tuple(values), "env_variable")
            elif arg.defaults:
                matched[arg.id] = MatchedArg(arg.defaults, "default_value")
        problem = self._validate(matched)
        if problem is not None:
            return problem
        return ArgMatches(self._cmd, matched, self._subcommand)

    def _env_values(self, arg: ResolvedArg, raw: str) -> list[Any] | Error:
        if takes_values(arg.action):
            return self._parse_values(arg, [raw], arg.env)
        flag = parse_boolish(raw)
        if isinstance(flag, Invalid):
            return self._error(
                InvalidValue(display_arg(arg), raw, flag.message, env=arg.env)
            )
        return [flag if arg.action == "set_true" else not flag]

    def _validate(self, matched: Mapping[str, MatchedArg]) -> Error | None:
        cmd = self._cmd
        explicit = {id for id, m in matched.items() if m.source != "default_value"}

        for arg in cmd.args:
            if arg.id not in explicit:
                continue
            for other in sorted(arg.conflicts_with & explicit):
                return self._conflict(arg, cmd.by_id[other])
        for group in cmd.groups:
            present = [
                cmd.by_id[member] for member in group.members if member in explicit
            ]
            if not group.multiple and len(present) > 1:
                return self._conflict(present[0], present[1])

        missing: list[str] = [
            display_arg(arg)
            for arg in cmd.args
            if arg.required and arg.id not in explicit
        ]
        for group in cmd.groups:
            if group.required and not any(
                member in explicit for member in group.members
            ):
                members = "|".join(
                    display_arg(cmd.by_id[member]) for member in group.members
                )
                missing.append(f"<{members}>")
        for arg in cmd.args:
            if arg.id not in explicit:
                continue
            for needed in sorted(arg.requires - explicit):
                shown = display_arg(cmd.by_id[needed])
                if shown not in missing:
                    missing.append(shown)
        if missing:
            return self._error(MissingRequiredArgument(tuple(missing)))

        for arg in cmd.positionals:
            count = len(self._local.get(arg.id, ()))
            if 0 < count < arg.min_values:
                return self._error(
                    TooFewValues(display_arg(arg), arg.min_values, count)
                )
        if cmd.subcommand_required and self._subcommand is None:
            return self._error(
                MissingSubcommand(" ".join(cmd.path), tuple(cmd.subcommands))
            )
        return None

    # -- helpers ------------------------------------------------------------

    def _defined_elsewhere(self, flag: str) -> str | None:
        """A tip when `flag` is unknown here but exists on a parent or subcommand."""
        owners = [
            other
            for other in (*reversed(self._ancestors), *_descendants(self._cmd))
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

    def _current_positional(self) -> ResolvedArg | None:
        positionals = self._cmd.positionals
        index = self._positional_index
        return positionals[index] if index < len(positionals) else None

    def _error(self, kind: ParseFailure, tip: str | None = None) -> Error:
        return usage_error(self._cmd, kind, describe(kind), tip)

    def _repeated(self, arg: ResolvedArg) -> Error:
        return self._error(ArgumentConflict(display_arg(arg), None))

    def _conflict(self, first: ResolvedArg, second: ResolvedArg) -> Error:
        return self._error(ArgumentConflict(display_arg(first), display_arg(second)))

    def _unexpected_value(self, arg: ResolvedArg, value: str) -> Error:
        return self._error(TooManyValues(display_arg(arg), value))


def _is_value(token: str, arg: ResolvedArg) -> bool:
    if token == "--":
        return False
    return arg.allow_hyphen_values or token == "-" or not token.startswith("-")


def _help_error(kind: ErrorKind, cmd: ResolvedCommand) -> Error:
    """Help as an `Error`: plain text now, restyled for the terminal at `exit()`."""
    return Error(kind, render_help(cmd), restyle=functools.partial(render_help, cmd))


def _help_for(cmd: ResolvedCommand, names: Sequence[str]) -> Error:
    """`cmd help a b`: the help of `cmd a b`, or an error naming the first unknown name."""
    target = cmd
    for name in names:
        canonical = target.subcommand_names.get(name)
        if canonical is None:
            closest = _closest(name, _visible_subcommand_names(target))
            kind = InvalidSubcommand(name, closest)
            return usage_error(
                target, kind, describe(kind), _similar_tip("subcommand", closest)
            )
        target = target.subcommands[canonical]
    return _help_error(DisplayHelp(), target)


def _visible_subcommand_names(cmd: ResolvedCommand) -> list[str]:
    """Names worth suggesting: canonical names and visible aliases, not hidden aliases."""
    return [
        name
        for name, canonical in cmd.subcommand_names.items()
        if name not in cmd.subcommands[canonical].aliases
    ]


def _descendants(cmd: ResolvedCommand) -> Iterator[ResolvedCommand]:
    """Every subcommand below `cmd`, depth first. Depth is bounded by the build."""
    for sub in cmd.subcommands.values():
        yield sub
        yield from _descendants(sub)


def _owns(cmd: ResolvedCommand, flag: str) -> bool:
    arg = (
        cmd.by_long.get(flag[2:])
        if flag.startswith("--")
        else cmd.by_short.get(flag[1:])
    )
    # An inherited global belongs to the ancestor that defined it, which is listed already.
    return arg is not None and not arg.hide and arg.id not in cmd.inherited


def _closest(typed: str, candidates: list[str]) -> str | None:
    matches = difflib.get_close_matches(typed, candidates, n=1)
    return matches[0] if matches else None


def _similar_tip(what: str, closest: str | None) -> str | None:
    return None if closest is None else f"a similar {what} exists: '{closest}'"
