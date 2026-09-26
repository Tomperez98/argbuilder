"""Contracts that whole-file goldens and one-example-per-failure tests cannot pin.

`test_parse.py` shows one input per failure. These tests pin the *rules* that
hold across inputs: the order overlapping failures are reported in, the token
spellings each action accepts, the payload an environment-sourced failure
carries, and the fact that parsing is a pure function of
`(command, tokens, env)` with no hidden process state. Line/branch coverage is
already 100%; these are the properties a refactor could silently break while
staying covered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from argbuilder import (
    Arg,
    ArgGroup,
    ArgMatches,
    ArgumentConflict,
    Command,
    Error,
    InvalidValue,
    MissingRequiredArgument,
    TooFewValues,
    TooManyValues,
    UnknownArgument,
)
from argbuilder._help import value_hint

if TYPE_CHECKING:
    from collections.abc import Callable


def ok(cmd: Command, *args: str, env: dict[str, str] | None = None) -> ArgMatches:
    result = cmd.try_get_matches_from([cmd.get_name(), *args], env or {})
    assert isinstance(result, ArgMatches), result
    return result


def err(cmd: Command, *args: str, env: dict[str, str] | None = None) -> Error:
    result = cmd.try_get_matches_from([cmd.get_name(), *args], env or {})
    assert isinstance(result, Error), result
    return result


# -- parse purity ---------------------------------------------------------------

PURE = (
    Command("tool")
    .arg(Arg("name").long("name").env("NAME").default_value("d"))
    .arg(Arg("tag").short("t").action("append"))
    .subcommand(Command("sub").arg(Arg("x").required(True)))
)


@pytest.mark.parametrize("argv", [["-t", "a", "sub", "x"], ["--name", "z"], ["sub"]])
def test_parsing_is_a_pure_function(argv: list[str]) -> None:
    # The same input parsed twice must give the same result, including the
    # Error case, and parsing must not mutate the command it parsed with.
    before = PURE.render_help()
    first = PURE.try_get_matches_from(["tool", *argv])
    second = PURE.try_get_matches_from(["tool", *argv])
    assert type(first) is type(second)
    assert repr(first) == repr(second)
    assert PURE.render_help() == before
    assert PURE.render_markdown() == PURE.render_markdown()


def test_parsing_does_not_leak_between_commands() -> None:
    # Two commands sharing an Arg definition must parse independently: a lazy
    # resolved cache on one must not answer for the other.
    shared = Arg("name").long("name")
    one = Command("one").arg(shared).subcommand(Command("s"))
    two = Command("two").arg(shared)
    assert ok(one, "s").subcommand_name() == "s"
    assert not ok(two).contains_id("name")


# -- failure precedence ---------------------------------------------------------
#
# `_validate` checks relationships in a fixed order. When more than one thing
# is wrong, the *first* one is what the user sees, so the order is part of the
# contract. Each row below stacks two failures and pins which wins.


def conflict_over_missing() -> Command:
    return (
        Command("p")
        .arg(Arg("a").long("a").action("set_true").conflicts_with("b"))
        .arg(Arg("b").long("b").action("set_true"))
        .arg(Arg("c").required(True))
    )


def group_conflict_over_missing() -> Command:
    return (
        Command("p")
        .arg(Arg("m").long("m").action("set_true"))
        .arg(Arg("n").long("n").action("set_true"))
        .group(ArgGroup("g").args(["m", "n"]))
        .arg(Arg("z").required(True))
    )


def missing_over_arity() -> Command:
    return Command("p").arg(Arg("pair").num_args(2, 2)).arg(Arg("x").long("x").required(True))


def missing_over_subcommand() -> Command:
    return (
        Command("p").arg(Arg("x").required(True)).subcommand(Command("s")).subcommand_required(True)
    )


def arity_over_subcommand() -> Command:
    return (
        Command("p")
        .arg(Arg("pair").num_args(2, 2))
        .subcommand(Command("s"))
        .subcommand_required(True)
    )


PRECEDENCE: list[tuple[str, Callable[[], Command], list[str], type[object]]] = [
    ("conflict over missing required", conflict_over_missing, ["--a", "--b"], ArgumentConflict),
    (
        "group conflict over missing required",
        group_conflict_over_missing,
        ["--m", "--n"],
        ArgumentConflict,
    ),
    ("missing required over positional arity", missing_over_arity, ["1"], MissingRequiredArgument),
    (
        "missing required over missing subcommand",
        missing_over_subcommand,
        [],
        MissingRequiredArgument,
    ),
    ("positional arity over missing subcommand", arity_over_subcommand, ["1"], TooFewValues),
]


@pytest.mark.parametrize(
    ("build", "argv", "kind"),
    [(build, argv, kind) for _, build, argv, kind in PRECEDENCE],
    ids=[name for name, _, _, _ in PRECEDENCE],
)
def test_the_first_failure_wins(
    build: Callable[[], Command],
    argv: list[str],
    kind: type[object],
) -> None:
    assert isinstance(err(build(), *argv).kind, kind)


# -- environment-sourced failures carry the variable ----------------------------


def test_a_short_env_value_reports_the_variable() -> None:
    cmd = Command("p").arg(Arg("pair").long("pair").num_args(2, 2).env("PAIR"))
    assert err(cmd, env={"PAIR": "1"}).kind == TooFewValues("--pair <PAIR> <PAIR>", 2, 1, "PAIR")


def test_an_over_long_env_value_reports_the_variable() -> None:
    cmd = Command("p").arg(Arg("pair").long("pair").num_args(1, 2).value_delimiter(",").env("PAIR"))
    assert err(cmd, env={"PAIR": "1,2,3"}).kind == TooManyValues("--pair <PAIR>...", "3", "PAIR")


def test_an_invalid_env_choice_reports_the_variable_and_suggests() -> None:
    cmd = Command("p").arg(Arg("mode").long("mode").value_parser(["fast", "safe"]).env("MODE"))
    assert err(cmd, env={"MODE": "saf"}).kind == InvalidValue(
        "--mode <MODE>",
        "saf",
        "expected one of fast, safe",
        ("fast", "safe"),
        "safe",
        "MODE",
    )


# -- token spellings ------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--name="], ["-n="], ["--name", ""]])
def test_an_empty_value_is_a_value_not_a_missing_one(argv: list[str]) -> None:
    # `--name=` is an empty string the parser accepted, not "no value supplied".
    cmd = Command("p").arg(Arg("name").short("n").long("name"))
    assert ok(cmd, *argv).get_one("name", str) == ""


def test_a_short_cluster_reports_the_cluster_in_its_tip() -> None:
    # `-avx` is `-a`, `-v`, then an unknown `-x`; the tip points at the whole
    # token the user typed, not just the failing character.
    cmd = (
        Command("p")
        .arg(Arg("a").short("a").action("set_true"))
        .arg(Arg("v").short("v").action("count"))
    )
    error = err(cmd, "-avx")
    assert error.kind == UnknownArgument("-x")
    assert error.tip == "to pass '-avx' as a value, use '-- -avx'"


# -- groups ---------------------------------------------------------------------


def test_a_multiple_group_allows_every_member_at_once() -> None:
    cmd = (
        Command("p")
        .arg(Arg("major").long("major").action("set_true"))
        .arg(Arg("minor").long("minor").action("set_true"))
        .group(ArgGroup("any").args(["major", "minor"]).multiple(True))
    )
    matches = ok(cmd, "--major", "--minor")
    assert matches.get_flag("major") and matches.get_flag("minor")


def test_a_single_group_still_rejects_two_members() -> None:
    cmd = (
        Command("p")
        .arg(Arg("major").long("major").action("set_true"))
        .arg(Arg("minor").long("minor").action("set_true"))
        .group(ArgGroup("one").args(["major", "minor"]))
    )
    assert isinstance(err(cmd, "--major", "--minor").kind, ArgumentConflict)


# -- positional advancement -----------------------------------------------------


def test_a_fixed_arity_positional_advances_to_the_next_one() -> None:
    cmd = Command("cp").arg(Arg("pair").num_args(2, 2)).arg(Arg("dest"))
    matches = ok(cmd, "a", "b", "c")
    assert matches.get_many("pair", str) == ("a", "b")
    assert matches.get_one("dest", str) == "c"
    # Once every positional is full, the next token is unknown, not appended.
    assert isinstance(err(cmd, "a", "b", "c", "d").kind, UnknownArgument)


# -- usage and value hints ------------------------------------------------------


def test_usage_lists_required_options_before_positionals_and_commands() -> None:
    cmd = (
        Command("p")
        .arg(Arg("cfg").long("config").required(True))
        .arg(Arg("input").required(True))
        .subcommand(Command("s"))
    )
    assert cmd.render_usage() == "Usage: p [OPTIONS] --config <CFG> <INPUT> [COMMAND]"


@pytest.mark.parametrize(
    ("min_values", "max_values", "hint"),
    [
        (1, 1, "<X>"),
        (0, 1, "[<X>]"),
        (2, 2, "<X> <X>"),
        (1, 2, "<X>..."),
        (1, None, "<X>..."),
        (0, None, "[<X>]..."),
    ],
)
def test_value_hint_covers_every_arity_shape(
    min_values: int,
    max_values: int | None,
    hint: str,
) -> None:
    cmd = Command("p").arg(Arg("x").long("x").num_args(min_values, max_values))
    arg = cmd._resolved().by_long["x"]  # noqa: SLF001
    assert value_hint(arg) == hint
