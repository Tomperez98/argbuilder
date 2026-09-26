"""Bugs panic: every definition or access mistake raises AssertionError at once."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest

from argbuilder import (
    Arg,
    ArgGroup,
    ArgMatches,
    Command,
    Error,
    InvalidValue,
    ValueParser,
    ValueValidation,
)
from argbuilder._invariant import variant_classes
from argbuilder._value_parser import into_value_parser

if TYPE_CHECKING:
    from collections.abc import Callable


def panics(match: str) -> pytest.RaisesExc[AssertionError]:
    return pytest.raises(AssertionError, match=match)


# -- at the builder call --------------------------------------------------------

BUILDER_BUGS: list[tuple[Callable[[], object], str]] = [
    (lambda: Arg(""), "non-empty"),
    (lambda: Arg("x").short("ab"), "one character"),
    (lambda: Arg("x").short("-"), "one character"),
    (lambda: Arg("x").long("--x"), "without leading"),
    (lambda: Arg("x").required("yes"), r"takes a bool"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").num_args(0), "max must be >= min and >= 1"),
    (lambda: Arg("x").num_args(3, 2), "max must be >= min"),
    (lambda: Arg("x").num_args(-1, None), "min must be an int >= 0"),
    (lambda: Arg("x").num_args(1, "2"), "max must be an int or None"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").value_parser("abc"), "a str is ambiguous"),
    (lambda: Arg("x").value_parser(42), "expected a ValueParser"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").value_parser([]), "at least one"),
    (lambda: ValueParser.integer(5, 1), "greater than max"),
    (lambda: ValueParser.from_range(range(5, 5)), "is empty"),
    (lambda: ArgGroup("g").args(["a", "a"]), "duplicate members"),
    (lambda: Command("my tool"), "without spaces"),
    (lambda: Command("x").arg("verbose"), "takes an Arg"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("x").args(Arg("a")), "use .arg"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("v").action("Count"), "did you mean 'count'"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("v").action(3), "takes one of set, append"),  # ty: ignore[invalid-argument-type]
    (lambda: Error(InvalidValue, "x"), r"pass InvalidValue\(\.\.\.\)"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").value_parser(Literal[1, 2]), "only str values"),  # ty: ignore[invalid-argument-type]
    (lambda: ValueParser.from_literal(int), "expected a Literal"),
    (lambda: Error(ValueValidation, "x"), r"pass ValueValidation\(\)"),  # ty: ignore[invalid-argument-type]
    (lambda: Error(ValueValidation(), 42), "message must be a str"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").alias("--x"), r"alias\(\) takes a name without leading"),
    (lambda: Arg("x").short_alias("xy"), r"short_alias\(\) takes one character"),
    (lambda: Arg("x").global_(1), r"global_\(\) takes a bool"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("x").visible_alias("a b"), r"visible_alias\(\) must be"),
]


@pytest.mark.parametrize(("make", "message"), BUILDER_BUGS)
def test_builder_bug(make: Callable[[], object], message: str) -> None:
    with panics(message):
        make()


def test_arg_get_id() -> None:
    assert Arg("port").get_id() == "port"


type _NotAClasses = int | Literal["x"]

type _Alias00 = int
type _Alias01 = _Alias00
type _Alias02 = _Alias01
type _Alias03 = _Alias02
type _Alias04 = _Alias03
type _Alias05 = _Alias04
type _Alias06 = _Alias05
type _Alias07 = _Alias06
type _Alias08 = _Alias07
type _Alias09 = _Alias08
type _Alias10 = _Alias09
type _Alias11 = _Alias10
type _Alias12 = _Alias11
type _Alias13 = _Alias12
type _Alias14 = _Alias13
type _Alias15 = _Alias14
type _Alias16 = _Alias15
type _Alias17 = _Alias16
type _Alias18 = _Alias17
type _Alias19 = _Alias18
type _Alias20 = _Alias19


def test_variant_classes_rejects_a_non_class_member() -> None:
    with panics("must be a union of classes"):
        variant_classes(_NotAClasses)


def test_recursive_alias_chain_panics() -> None:
    with panics("type alias chain is deeper than 16"):
        into_value_parser(_Alias20)


# -- when the command is built --------------------------------------------------

DEFINITION_BUGS: list[tuple[Command, str]] = [
    (
        Command("x").arg(Arg("a")).arg(Arg("a").long("a")),
        "'a' is defined more than once",
    ),
    (
        Command("x").arg(Arg("a").short("v")).arg(Arg("b").short("v")),
        "'-v' is used by both 'a' and 'b'",
    ),
    (Command("x").arg(Arg("host").short("h")), "disable_help_flag"),
    (Command("x").arg(Arg("a").required(True).default_value("1")), "is required"),
    (
        Command("x").arg(Arg("a").value_parser(int).default_value("one")),
        "default value 'one'",
    ),
    (
        Command("x").arg(Arg("a").value_parser(["x", "y"]).default_value("z")),
        "default value 'z'",
    ),
    (Command("x").arg(Arg("a").long("a").default_missing_value("1")), "num_args\\(0"),
    (
        Command("x").arg(Arg("f").long("f").action("set_true").num_args(1)),
        "num_args",
    ),
    (
        Command("x").arg(Arg("f").long("f").action("set_true").default_value("true")),
        "default_value does nothing",
    ),
    (
        Command("x").arg(Arg("f").action("set_true")),
        "needs short\\(\\) or long\\(\\)",
    ),
    (
        Command("x").arg(Arg("c").short("c").action("count").env("C")),
        "env\\(\\)",
    ),
    (
        Command("x").arg(Arg("files").num_args(1, None)).arg(Arg("out")),
        "must be the last",
    ),
    (
        Command("x").arg(Arg("maybe")).arg(Arg("must").required(True)),
        "comes after optional positional",
    ),
    (
        Command("x").arg(Arg("a").long("a").conflicts_with("nope")),
        "unknown argument 'nope'",
    ),
    (Command("x").arg(Arg("a").long("a").requires("a")), "refers to itself"),
    (Command("x").group(ArgGroup("g").arg("nope")), "unknown argument 'nope'"),
    (Command("x").arg(Arg("g")).group(ArgGroup("g").arg("g")), "already used"),
    (Command("x").subcommand_required(True), "no subcommands"),
    (Command("x").subcommand(Command("a")).subcommand(Command("a")), "more than once"),
    (Command("x").arg(Arg("v").long("v").action("version")), "has no version"),
    (
        Command("x").subcommand(Command("sub").arg(Arg("a")).arg(Arg("a"))),
        "Command 'x sub': argument id 'a'",
    ),
    (
        Command("x").arg(Arg("f").global_(True)),
        r"global_\(\) needs short\(\) or long\(\)",
    ),
    (
        Command("x").arg(Arg("f").long("f").required(True).global_(True)),
        "cannot be required",
    ),
    (
        Command("x").arg(Arg("h").long("hh").action("help").global_(True)),
        "cannot be global",
    ),
    (
        Command("x")
        .arg(Arg("v").short("v").action("count").global_(True))
        .subcommand(Command("sub").arg(Arg("v").long("v"))),
        "Command 'x sub': argument id 'v' is already a global argument",
    ),
    (
        Command("x")
        .arg(Arg("v").short("v").action("count").global_(True))
        .subcommand(Command("sub").arg(Arg("verb").short("v"))),
        "'v' is global, so it is already defined in every subcommand",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").global_(True).conflicts_with("b"))
        .arg(Arg("b").long("b")),
        "make 'b' global too",
    ),
    (Command("x").arg(Arg("a").alias("aa")), "aliases need short\\(\\) or long\\(\\)"),
    (Command("x").arg(Arg("a").long("a").alias("a")), "lists '--a' more than once"),
    (
        Command("x").arg(Arg("a").long("a")).arg(Arg("b").long("b").visible_alias("a")),
        "'--a' is used by both 'a' and 'b'",
    ),
    (
        Command("x").subcommand(Command("add")).subcommand(Command("stage").alias("add")),
        "subcommand name 'add' is used by both 'add' and 'stage'",
    ),
    (Command("x").alias("y"), "aliases only apply to subcommands"),
]


@pytest.mark.parametrize(("cmd", "message"), DEFINITION_BUGS)
def test_definition_bug(cmd: Command, message: str) -> None:
    with panics(message):
        cmd.debug_assert()
    with panics(message):
        cmd.try_get_matches_from(["x"])


def test_depth_is_bounded() -> None:
    cmd = Command("leaf")
    for level in range(40):
        cmd = Command(f"l{level}").subcommand(cmd)
    with panics("nest deeper than 32"):
        cmd.debug_assert()


def test_freeing_the_help_short() -> None:
    Command("x").disable_help_flag(True).arg(Arg("host").short("h")).debug_assert()


# -- calling the parser wrong ---------------------------------------------------


def test_argv_misuse() -> None:
    with panics("not one str"):
        Command("x").try_get_matches_from("x --flag")
    with panics("binary name"):
        Command("x").try_get_matches_from([])
    with panics("must hold str"):
        Command("x").try_get_matches_from(["x", 1])  # ty: ignore[invalid-argument-type]


# -- reading matches wrong ------------------------------------------------------

CMD = (
    Command("x")
    .arg(Arg("name").long("name").default_value("n"))
    .arg(Arg("tags").long("tag").action("append"))
    .arg(Arg("force").long("force").action("set_true"))
    .arg(Arg("v").short("v").action("count"))
    .arg(Arg("maybe").long("maybe"))
    .arg(Arg("color").long("color").num_args(0, 1).default_value("auto"))
    .subcommand(Command("sub").alias("s"))
)


def matches() -> ArgMatches:
    result = CMD.try_get_matches_from(["x"])
    assert isinstance(result, ArgMatches)
    return result


ACCESS_BUGS: list[tuple[Callable[[ArgMatches], object], str]] = [
    (lambda m: m.get_one("nmae", str), "unknown argument id 'nmae'"),
    (lambda m: m.get_one("name", int), "holds str, not int"),
    (lambda m: m.get_one("tags", str), "use get_many"),
    (lambda m: m.get_one("force", bool), "use get_flag"),
    (lambda m: m.get_many("v", int), "use get_count"),
    (lambda m: m.get_flag("name"), "not 'set_true' or 'set_false'"),
    (lambda m: m.get_count("force"), "not 'count'"),
    (lambda m: m.contains_id("nope"), "unknown argument id"),
    (lambda m: m.subcommand_matches("nope"), "no such subcommand"),
    (lambda m: m.subcommand_matches("s"), "'s' is an alias of 'sub'; pass the name"),
    (
        lambda m: m.get_required("maybe", str),
        "neither required\\(True\\) nor defaulted",
    ),
    (lambda m: m.get_required("color", str), "add default_missing_value"),
    (lambda m: m.get_required("tags", str), "use get_many"),
    (lambda m: m.get_required("force", bool), "use get_flag"),
    (lambda m: m.get_required("name", int), "holds str, not int"),
    (lambda m: m.error(ValueValidation(), 42), "message must be a str"),  # ty: ignore[invalid-argument-type]
    (lambda m: m.error(ValueValidation, "x"), r"pass ValueValidation\(\)"),  # ty: ignore[invalid-argument-type]
]


@pytest.mark.parametrize(("read", "message"), ACCESS_BUGS)
def test_access_bug(read: Callable[[ArgMatches], object], message: str) -> None:
    with panics(message):
        read(matches())


def test_definitions_are_immutable_and_shareable() -> None:
    base = Arg("name").long("name")
    required = base.required(True)
    assert base is not required
    one = Command("a").arg(base)
    two = Command("b").arg(required)
    assert isinstance(one.try_get_matches_from(["a"]), ArgMatches)
    assert not isinstance(two.try_get_matches_from(["b"]), ArgMatches)
