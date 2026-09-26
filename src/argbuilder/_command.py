"""`Command`: the root builder, and the only place that touches the process."""

from __future__ import annotations

import dataclasses
import os
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from argbuilder._arg import Arg, ArgGroup, _check_bool
from argbuilder._build import build
from argbuilder._error import Error, ErrorKind
from argbuilder._help import render_help, render_usage, render_version, usage_error
from argbuilder._invariant import invariant
from argbuilder._parser import parse
from argbuilder._spec import CommandSpec
from argbuilder._style import PLAIN, Style

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from argbuilder._matches import ArgMatches

_NO_ENV: Mapping[str, str] = MappingProxyType({})


class Command:
    """A command, or subcommand, built fluently like clap's `Command::new`.

    ```python
    cmd = (
        Command("git")
        .version("1.0.0")
        .arg(Arg("verbose").short("v").action("count"))
        .subcommand(Command("clone").arg(Arg("remote").required(True)))
    )
    matches = cmd.get_matches()
    ```

    Immutable: every method returns a new `Command`. Definition bugs panic
    (`AssertionError`) when the command is built. Call `debug_assert()` in a
    unit test to catch them before a user does.
    """

    __slots__ = ("_spec",)
    _spec: CommandSpec

    def __init__(self, name: str) -> None:
        self._spec = CommandSpec(name=_check_name("Command name", name))

    def __repr__(self) -> str:
        return f"Command({self._spec.name!r})"

    def get_name(self) -> str:
        return self._spec.name

    def _with(self, **changes: Any) -> Command:
        new: Command = Command.__new__(Command)
        new._spec = dataclasses.replace(self._spec, **changes)
        return new

    # -- definition ---------------------------------------------------------

    def about(self, text: str) -> Command:
        invariant(isinstance(text, str), f"{self!r}.about() takes a str, got {text!r}")
        return self._with(about=text)

    def version(self, version: str) -> Command:
        """Also adds `-V, --version` unless `disable_version_flag(True)`."""
        invariant(
            isinstance(version, str) and version != "",
            f"{self!r}.version() takes a non-empty str, got {version!r}",
        )
        return self._with(version=version)

    def alias(self, name: str) -> Command:
        """A hidden extra name for this subcommand: it parses, but help leaves it out."""
        name = _check_name(f"{self!r}.alias()", name)
        return self._with(aliases=(*self._spec.aliases, name))

    def visible_alias(self, name: str) -> Command:
        """An extra name for this subcommand, listed in help as `[aliases: name]`."""
        name = _check_name(f"{self!r}.visible_alias()", name)
        return self._with(visible_aliases=(*self._spec.visible_aliases, name))

    def arg(self, arg: Arg) -> Command:
        invariant(isinstance(arg, Arg), f"{self!r}.arg() takes an Arg, got {arg!r}")
        # Same-package handoff of an Arg's spec into the Command's spec tuple.
        return self._with(args=(*self._spec.args, arg._spec))  # noqa: SLF001

    def args(self, args: Iterable[Arg]) -> Command:
        invariant(
            not isinstance(args, Arg),
            f"{self!r}.args() takes a list; use .arg() for one",
        )
        result = self
        for arg in args:
            result = result.arg(arg)
        return result

    def group(self, group: ArgGroup) -> Command:
        invariant(
            isinstance(group, ArgGroup),
            f"{self!r}.group() takes an ArgGroup, got {group!r}",
        )
        # Same-package handoff of an ArgGroup's spec into the Command's spec tuple.
        return self._with(groups=(*self._spec.groups, group._spec))  # noqa: SLF001

    def subcommand(self, command: Command) -> Command:
        invariant(
            isinstance(command, Command),
            f"{self!r}.subcommand() takes a Command, got {command!r}",
        )
        return self._with(subcommands=(*self._spec.subcommands, command._spec))

    def subcommands(self, commands: Iterable[Command]) -> Command:
        invariant(
            not isinstance(commands, Command),
            f"{self!r}.subcommands() takes a list; use .subcommand() for one",
        )
        result = self
        for command in commands:
            result = result.subcommand(command)
        return result

    def subcommand_required(self, yes: bool) -> Command:
        return self._with(
            subcommand_required=_check_bool(repr(self), "subcommand_required", yes)
        )

    def arg_required_else_help(self, yes: bool) -> Command:
        """With no arguments at all, print help to stderr and exit 2."""
        return self._with(
            arg_required_else_help=_check_bool(
                repr(self), "arg_required_else_help", yes
            )
        )

    def disable_help_flag(self, yes: bool) -> Command:
        return self._with(
            disable_help_flag=_check_bool(repr(self), "disable_help_flag", yes)
        )

    def disable_version_flag(self, yes: bool) -> Command:
        return self._with(
            disable_version_flag=_check_bool(repr(self), "disable_version_flag", yes)
        )

    def disable_help_subcommand(self, yes: bool) -> Command:
        """Don't add the `help [COMMAND]...` subcommand a command with subcommands gets."""
        return self._with(
            disable_help_subcommand=_check_bool(
                repr(self), "disable_help_subcommand", yes
            )
        )

    # -- use ----------------------------------------------------------------

    def debug_assert(self) -> None:
        """Validate the whole command tree, panicking on the first definition bug.

        Put `cli().debug_assert()` in a unit test, as clap recommends.
        """
        build(self._spec)

    def try_get_matches_from(
        self, argv: Iterable[str], env: Mapping[str, str] = _NO_ENV
    ) -> ArgMatches | Error:
        """Parse `argv` (first element is the binary name, like `sys.argv`).

        Pure: returns `Error` for anything the user typed wrong, including
        `--help` and `--version`. `env` defaults to empty, so tests are
        hermetic unless they pass one.
        """
        invariant(
            not isinstance(argv, str),
            "argv must be a list of str, not one str; split it first",
        )
        tokens = tuple(argv)
        invariant(
            len(tokens) >= 1, "argv must start with the binary name, like sys.argv"
        )
        invariant(
            all(isinstance(token, str) for token in tokens),
            f"argv must hold str, got {tokens!r}",
        )
        return parse(build(self._spec), tokens[1:], env)

    def get_matches_from(
        self, argv: Iterable[str], env: Mapping[str, str] = _NO_ENV
    ) -> ArgMatches:
        """Like `try_get_matches_from`, but print the error and exit on failure."""
        result = self.try_get_matches_from(argv, env)
        if isinstance(result, Error):
            result.exit()
        return result

    def get_matches(self) -> ArgMatches:
        """Parse `sys.argv` with `os.environ`. The only read of process state."""
        return self.get_matches_from(sys.argv, os.environ)

    def render_help(self, style: Style = PLAIN) -> str:
        """Plain by default; pass a `Style` to color it and wrap it to a width."""
        invariant(
            isinstance(style, Style),
            f"{self!r}.render_help() takes a Style, got {style!r}",
        )
        return render_help(build(self._spec), style)

    def render_usage(self) -> str:
        return f"Usage: {render_usage(build(self._spec))}"

    def render_version(self) -> str:
        return render_version(build(self._spec))

    def error(self, kind: ErrorKind, message: str) -> Error:
        """Report your own post-parse validation failure in the same format.

        `cmd.error(ValueValidation(), "--from must precede --to").exit()`

        The usage line is this command's. For a failure inside a subcommand,
        prefer `ArgMatches.error()` on that subcommand's matches.
        """
        return usage_error(build(self._spec), kind, message)


def _check_name(what: str, name: object) -> str:
    invariant(
        isinstance(name, str)
        and name != ""
        and not name.startswith("-")
        and not any(char.isspace() for char in name),
        f"{what} must be a non-empty str without spaces or a leading '-', got {name!r}",
    )
    return str(name)
