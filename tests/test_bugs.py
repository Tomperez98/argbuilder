"""Bugs panic: every definition or access mistake raises AssertionError at once."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeAliasType

import pytest

from argbuilder import (
    Arg,
    ArgGroup,
    ArgMatches,
    Command,
    DisplayHelp,
    DisplayVersion,
    Error,
    InvalidValue,
    TooManyValues,
    UnknownArgument,
    ValueParser,
    ValueValidation,
)
from argbuilder._invariant import _MAX_VARIANT_STEPS, variant_classes
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
    (lambda: ValueParser(42), "parse must be callable"),  # ty: ignore[invalid-argument-type]
    (
        lambda: ValueParser(lambda raw: raw, ["a"]),  # ty: ignore[invalid-argument-type]
        "possible_values must be a tuple",
    ),
    (
        lambda: ValueParser(lambda raw: raw, (1,)),  # ty: ignore[invalid-argument-type]
        "possible_values must hold only str",
    ),
    (
        lambda: ValueParser(lambda raw: raw, ("a", "a")),
        "possible_values must not repeat",
    ),
    (
        lambda: ValueParser.from_fn(42),  # ty: ignore[invalid-argument-type]
        "expects a callable",
    ),
    (
        lambda: ValueParser.integer(min="5"),  # ty: ignore[invalid-argument-type]
        "min must be an int",
    ),
    (
        lambda: ValueParser.integer(max=True),
        "max must be an int",
    ),
    (
        lambda: ValueParser.from_range([1, 2]),  # ty: ignore[invalid-argument-type]
        "expects a range",
    ),
    (lambda: ValueParser.integer(5, 1), "greater than max"),
    (lambda: ValueParser.from_range(range(5, 5)), "is empty"),
    (lambda: ArgGroup("g").args(["a", "a"]), "duplicate members"),
    (lambda: ArgGroup("g").args({"a"}), "ordered iterable"),
    (lambda: Arg("x").default_values(5), "takes an iterable"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").default_values({"a"}), "ordered iterable"),
    (lambda: Arg("x").default_values("22"), "takes an iterable"),
    (lambda: Arg("x").default_values([]), "non-empty list of str"),
    (lambda: Arg("x").default_values(["ok", 1]), "non-empty list of str"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").env("A=B"), "takes a variable name"),
    (lambda: Arg("x").env(""), "takes a variable name"),
    (lambda: Arg("x").env(1), "takes a variable name"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").conflicts_with_all(5), "takes an iterable"),  # ty: ignore[invalid-argument-type]
    (lambda: ArgGroup("g").args(5), "takes an iterable"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("my tool"), "without spaces"),
    (lambda: Command("x").arg("verbose"), "takes an Arg"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("x").args(Arg("a")), "use .arg"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("x").args(5), "takes a list of Arg"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("x").args({Arg("a")}), "ordered iterable"),
    (lambda: Command("x").subcommands(5), "takes a list of Command"),  # ty: ignore[invalid-argument-type]
    (lambda: Command("x").subcommands({Command("s")}), "ordered iterable"),
    (lambda: Arg("v").action("Count"), "did you mean 'count'"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("v").action(3), "takes one of set, append"),  # ty: ignore[invalid-argument-type]
    (lambda: Error(InvalidValue, "x"), r"pass InvalidValue\(\.\.\.\)"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").value_parser(Literal[1, 2]), "only str values"),  # ty: ignore[invalid-argument-type]
    (lambda: ValueParser.from_literal(int), "expected a Literal"),
    (lambda: Error(ValueValidation, "x"), r"pass ValueValidation\(\)"),  # ty: ignore[invalid-argument-type]
    (lambda: Error(ValueValidation(), 42), "message must be a str"),  # ty: ignore[invalid-argument-type]
    (
        lambda: Error(ValueValidation(), "x", restyle=42),  # ty: ignore[invalid-argument-type]
        "restyle must be callable",
    ),
    (
        lambda: Error(ValueValidation(), "x").render(42),  # ty: ignore[invalid-argument-type]
        "takes a Style",
    ),
    (lambda: Arg("x").alias("--x"), r"alias\(\) takes a name without leading"),
    (lambda: Arg("x").short_alias("xy"), r"short_alias\(\) takes one character"),
    (lambda: Arg("x").global_(1), r"global_\(\) takes a bool"),  # ty: ignore[invalid-argument-type]
    (lambda: Arg("x").last(1), r"last\(\) takes a bool"),  # ty: ignore[invalid-argument-type]
    (
        lambda: Arg("x").trailing_var_arg(1),  # ty: ignore[invalid-argument-type]
        r"trailing_var_arg\(\) takes a bool",
    ),
    (
        lambda: Command("x").args_conflicts_with_subcommands(1),  # ty: ignore[invalid-argument-type]
        r"args_conflicts_with_subcommands\(\) takes a bool",
    ),
    (lambda: Arg("x").exclusive(1), r"exclusive\(\) takes a bool"),  # ty: ignore[invalid-argument-type]
    (
        lambda: Arg("x").required_if_eq("y", 1),  # ty: ignore[invalid-argument-type]
        r"required_if_eq\(\) takes a str value",
    ),
    (
        lambda: Arg("x").overrides_with_all(5),  # ty: ignore[invalid-argument-type]
        r"overrides_with_all\(\) takes an iterable",
    ),
    (lambda: Command("x").visible_alias("a b"), r"visible_alias\(\) must be"),
]


@pytest.mark.parametrize(("make", "message"), BUILDER_BUGS)
def test_builder_bug(make: Callable[[], object], message: str) -> None:
    with panics(message):
        make()


class _UnhashableParser:
    __hash__ = None

    def __call__(self, raw: str) -> str:
        return raw


def test_an_unhashable_value_parser_still_builds() -> None:
    # A callable without __hash__ is a valid callable but not an lru_cache key.
    # The build must fall back to an uncached pass instead of raising TypeError.
    parser = ValueParser(_UnhashableParser())
    with pytest.raises(TypeError):
        hash(parser)
    cmd = Command("x").arg(Arg("a").long("a").value_parser(parser))
    cmd.debug_assert()
    matches = cmd.try_get_matches_from(["x", "--a", "v"])
    assert isinstance(matches, ArgMatches)
    assert matches.get_one("a", str) == "v"


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


def test_a_pathological_union_alias_chain_panics() -> None:
    # Build a runtime chain; `type` statements cannot loop.
    alias = TypeAliasType("alias", int)  # noqa: UP040
    for _ in range(_MAX_VARIANT_STEPS + 1):
        alias = TypeAliasType("alias", alias)  # noqa: UP040
    with panics("is it recursive"):
        variant_classes(alias)


type _Nested = InvalidValue | UnknownArgument
type _Outer = _Nested | TooManyValues


def test_variant_classes_flattens_a_nested_alias() -> None:
    # `A | (B | C)` must expand in order. A queue mutation that drops or
    # reorders a member silently shrinks the union `ErrorKind` validates.
    assert variant_classes(_Outer) == (InvalidValue, UnknownArgument, TooManyValues)


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
    (
        Command("x").arg(Arg("help").long("assist")),
        "argument id 'help' is reserved",
    ),
    (
        Command("x").version("1.0").arg(Arg("version").long("ver").action("set_true")),
        "argument id 'version' is reserved",
    ),
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
        Command("x").arg(Arg("a").num_args(0, 1).default_missing_value("1")),
        "default_missing_value\\(\\) needs an option",
    ),
    (
        Command("x").arg(Arg("a").long("a").value_delimiter(",")),
        "value_delimiter\\(\\) can produce several values",
    ),
    (
        Command("x").arg(Arg("a").last(True).allow_negative_numbers(True)),
        "allow_negative_numbers\\(\\) does nothing with last",
    ),
    (
        Command("x").arg(Arg("f").long("f").action("set_true").num_args(1)),
        "num_args",
    ),
    (
        Command("x").arg(Arg("f").long("f").action("set_true").require_equals(True)),
        "require_equals does nothing",
    ),
    (
        Command("x").arg(Arg("f").long("f").action("set_true").allow_negative_numbers(True)),
        "allow_negative_numbers does nothing",
    ),
    (
        Command("x")
        .arg(Arg("n").long("n").allow_negative_numbers(True))
        .arg(Arg("five").short("5").action("set_true")),
        "collides with allow_negative_numbers",
    ),
    (
        Command("x").arg(Arg("a").require_equals(True)),
        "needs short\\(\\) or long\\(\\)",
    ),
    (
        Command("x").arg(Arg("a").long("a").num_args(2, 2).require_equals(True)),
        "at most one value",
    ),
    (
        Command("x").arg(Arg("a").long("a").num_args(1, None).require_equals(True)),
        "at most one value",
    ),
    (
        Command("x").arg(Arg("f").long("f").action("set_true").default_value("true")),
        "default_value does nothing",
    ),
    (
        Command("x").arg(Arg("a").long("a").num_args(0, None).require_equals(True)),
        "at most one value",
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
    (Command("x").arg(Arg("a").long("a").overrides_with("a")), "refers to itself"),
    (
        Command("x").arg(Arg("a").long("a").overrides_with("nope")),
        "unknown argument 'nope'",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").overrides_with("b").conflicts_with("b"))
        .arg(Arg("b").long("b")),
        "both overrides and conflicts",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").overrides_with("b"))
        .arg(Arg("b").long("b").global_(True)),
        "share the same scope",
    ),
    (Command("x").arg(Arg("a").exclusive(True)), r"exclusive\(\) needs short\(\) or long\(\)"),
    (
        Command("x")
        .arg(Arg("a").required_unless_present("b").required_if_eq("b", "1"))
        .arg(Arg("b").long("b")),
        "combines required_unless_present",
    ),
    (
        Command("x")
        .arg(Arg("a").required(True).required_unless_present("b"))
        .arg(Arg("b").long("b")),
        "both required",
    ),
    (
        Command("x")
        .arg(Arg("a").required_unless_present("b").default_value("x"))
        .arg(Arg("b").long("b")),
        "conditional requirement could never apply",
    ),
    (
        Command("x").arg(Arg("a").required_unless_present("nope")),
        "unknown argument 'nope'",
    ),
    (
        Command("x").arg(Arg("a").required_unless_present("a")),
        "refers to itself",
    ),
    (
        Command("x").arg(Arg("a").required_if_eq("nope", "1")),
        "unknown argument 'nope'",
    ),
    (
        Command("x").arg(Arg("a").required_if_eq("a", "1")),
        "refers to itself",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").required_if_eq("b", "1").global_(True))
        .arg(Arg("b").long("b")),
        "not global",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").required_if_eq("b", "1"))
        .arg(Arg("b").long("b").action("set_true")),
        "does not take a value",
    ),
    (
        Command("x").arg(Arg("a").long("a").num_args(2).default_values(["one"])),
        "requires at least 2",
    ),
    (
        Command("x").arg(Arg("a").num_args(2, 2).default_values(["one"])),
        "requires at least 2",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").required(True).conflicts_with("b"))
        .arg(Arg("b").long("b").required(True)),
        "both required but conflict",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").requires("b").conflicts_with("b"))
        .arg(Arg("b").long("b")),
        "requires 'b' but also conflicts",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").action("set_true").exclusive(True).requires("b"))
        .arg(Arg("b").long("b")),
        "exclusive argument 'a' requires 'b'",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").requires("b"))
        .arg(Arg("b").long("b").action("set_true").exclusive(True)),
        "requires exclusive argument 'b'",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").requires("b").overrides_with("b"))
        .arg(Arg("b").long("b")),
        "requires 'b' but also overrides",
    ),
    (
        Command("x").arg(Arg("a").long("a").requires("h")).arg(Arg("h").long("h").action("help")),
        "only displays help or version",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").action("set_true").required(True))
        .arg(Arg("b").long("b").action("set_true").required(True))
        .group(ArgGroup("g").args(["a", "b"])),
        "both required",
    ),
    (
        Command("x")
        .arg(Arg("a").long("a").action("set_true").exclusive(True).required(True))
        .arg(Arg("b").long("b").required(True)),
        "is exclusive and required",
    ),
    (
        Command("x")
        .arg(Arg("e").long("e").action("set_true").exclusive(True).required(True))
        .arg(Arg("m").long("m"))
        .arg(Arg("n").long("n"))
        .group(ArgGroup("g").args(["m", "n"]).required(True)),
        "required group 'g' needs another argument",
    ),
    (Command("x").group(ArgGroup("g").arg("nope")), "unknown argument 'nope'"),
    (Command("x").arg(Arg("g")).group(ArgGroup("g").arg("g")), "already used"),
    (Command("x").subcommand_required(True), "no subcommands"),
    (
        Command("x")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("message").required(True))
        .subcommand(Command("sub")),
        "could never be used",
    ),
    (
        Command("x")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("a"))
        .arg(Arg("b"))
        .group(ArgGroup("g").args(["a", "b"]).required(True))
        .subcommand(Command("sub")),
        "could never be used",
    ),
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
    (
        Command("x").arg(Arg("a").long("a").last(True)),
        "last\\(\\) needs a positional argument",
    ),
    (
        Command("x").arg(Arg("a").short("a").action("set_true").last(True)),
        "last does nothing with action 'set_true'",
    ),
    (
        Command("x").arg(Arg("a").last(True)).arg(Arg("b").last(True)),
        "last\\(True\\) is set on more than one positional",
    ),
    (
        Command("x").arg(Arg("a").last(True)).arg(Arg("b")),
        "must be the final positional",
    ),
    (
        Command("x").arg(Arg("a").last(True).allow_hyphen_values(True)),
        "allow_hyphen_values\\(\\) does nothing with last\\(\\)",
    ),
    (
        Command("x").arg(Arg("a").long("a").num_args(1, None).trailing_var_arg(True)),
        "trailing_var_arg\\(\\) needs a positional",
    ),
    (
        Command("x").arg(
            Arg("a").num_args(1, None).last(True).trailing_var_arg(True),
        ),
        "different syntaxes",
    ),
    (
        Command("x").arg(Arg("a").num_args(1, 1).trailing_var_arg(True)),
        "unbounded num_args",
    ),
    (
        Command("x")
        .arg(Arg("a").num_args(1, None).trailing_var_arg(True))
        .arg(Arg("b").num_args(1, None).trailing_var_arg(True)),
        "more than one positional",
    ),
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


def test_the_depth_limit_admits_exactly_32_levels() -> None:
    # `depth < MAX_COMMAND_DEPTH` permits depths 0..=31, i.e. 32 levels; the
    # 33rd panics. A `<` -> `<=` mutant would let the tree grow one level too
    # deep, which only a boundary test notices.
    allowed = Command("leaf")
    for level in range(31):
        allowed = Command(f"l{level}").subcommand(allowed)
    allowed.debug_assert()
    too_deep = Command("leaf")
    for level in range(32):
        too_deep = Command(f"l{level}").subcommand(too_deep)
    with panics("nest deeper than 32"):
        too_deep.debug_assert()


def test_subcommand_required_accepts_a_single_subcommand() -> None:
    # The guard only needs one subcommand; a `len(...) > 1` mutant would
    # reject the common one-subcommand CLI at build time.
    Command("x").subcommand(Command("only")).subcommand_required(True).debug_assert()


def test_append_defaults_may_exceed_num_args_but_set_defaults_may_not() -> None:
    # An `append` argument accumulates, so more defaults than one occurrence
    # can hold are legal; a `set` argument cannot.
    Command("x").arg(
        Arg("tag").long("tag").action("append").num_args(1).default_values(["a", "b"]),
    ).debug_assert()
    with panics("default values"):
        Command("x").arg(
            Arg("name").long("name").num_args(1).default_values(["a", "b"]),
        ).debug_assert()


def test_freeing_the_help_short() -> None:
    Command("x").disable_help_flag(True).arg(Arg("host").short("h")).debug_assert()


def test_disable_version_flag_removes_the_automatic_flag() -> None:
    # The setter must actually reach the resolved command: neither the flag
    # nor its help line may survive.
    cmd = Command("x").version("1.0").disable_version_flag(True)
    cmd.debug_assert()
    assert "--version" not in cmd.render_help()
    result = cmd.try_get_matches_from(["x", "--version"])
    assert isinstance(result, Error)
    assert isinstance(result.kind, UnknownArgument)


def test_a_custom_help_action_replaces_the_automatic_flag() -> None:
    cmd = Command("x").arg(Arg("assist").long("assist").action("help"))
    assert "--help" not in cmd.render_help()
    result = cmd.try_get_matches_from(["x", "--assist"])
    assert isinstance(result, Error)
    assert result.kind == DisplayHelp()


def test_a_custom_version_action_replaces_the_automatic_flag() -> None:
    cmd = Command("x").version("1.0").arg(Arg("ver").long("ver").action("version"))
    result = cmd.try_get_matches_from(["x", "--ver"])
    assert isinstance(result, Error)
    assert result.kind == DisplayVersion()


# -- calling the parser wrong ---------------------------------------------------


def test_argv_misuse() -> None:
    with panics("not one str"):
        Command("x").try_get_matches_from("x --flag")
    with panics("binary name"):
        Command("x").try_get_matches_from([])
    with panics("must hold str"):
        Command("x").try_get_matches_from(["x", 1])  # ty: ignore[invalid-argument-type]


def test_env_misuse() -> None:
    with panics("mapping of str to str"):
        Command("x").try_get_matches_from(["x"], env=None)  # ty: ignore[invalid-argument-type]
    # Only the variables a command actually reads are checked; a non-str value
    # for a declared env() variable is still a bug.
    with panics("mapping of str to str"):
        Command("x").arg(Arg("a").long("a").env("A")).try_get_matches_from(
            ["x"],
            env={"A": 1},  # ty: ignore[invalid-argument-type]
        )
    # A subcommand's env() variable is in the same checked set, so an outer
    # parse still catches it.
    with panics("mapping of str to str"):
        Command("x").subcommand(
            Command("run").arg(Arg("p").long("p").env("P"))
        ).try_get_matches_from(
            ["x", "run"],
            env={"P": 1},  # ty: ignore[invalid-argument-type]
        )
    # The first bad variable is reported in sorted order, not frozenset order.
    with panics("'AAA' is 1"):
        Command("x").arg(Arg("a").env("BBB")).arg(Arg("b").env("AAA")).try_get_matches_from(
            ["x"],
            env={"BBB": 2, "AAA": 1},  # ty: ignore[invalid-argument-type]
        )
    # A key no argument reads is never followed, so a large environment costs
    # nothing per parse; see `_check_env`.
    unused = Command("x").try_get_matches_from(["x"], env={"UNUSED": 1})  # ty: ignore[invalid-argument-type]
    assert isinstance(unused, ArgMatches)


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
    (lambda m: m.get_one([], str), "argument id must be a str"),  # ty: ignore[invalid-argument-type]
    (lambda m: m.subcommand_matches([]), "subcommand name must be a str"),  # ty: ignore[invalid-argument-type]
    (lambda m: m.get_one("name", int), "holds str, not int"),
    (lambda m: m.get_one("name", "str"), "type_ must be a type"),  # ty: ignore[invalid-argument-type]
    (lambda m: m.get_required("name", "str"), "type_ must be a type"),  # ty: ignore[invalid-argument-type]
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


def test_value_getter_panic_names_the_getter() -> None:
    # The panic names which getter was misused; dropping that argument is a
    # behavioral change a message-only assertion would miss.
    with panics(r"get_one\('force'\): argument uses action 'set_true'"):
        matches().get_one("force", bool)
    with panics(r"get_many\('v'\): argument uses action 'count'"):
        matches().get_many("v", int)


def test_render_version_without_a_version_panics() -> None:
    with panics("has no version to render"):
        Command("x").render_version()


def test_a_bool_value_is_not_read_as_an_int() -> None:
    # bool is an int subclass, so isinstance alone would let this slip through.
    cmd = Command("x").arg(Arg("on").long("on").value_parser(bool))
    matches = cmd.try_get_matches_from(["x", "--on", "true"])
    assert isinstance(matches, ArgMatches)
    with panics("holds bool, not int"):
        matches.get_one("on", int)
    assert matches.get_one("on", bool) is True
    assert matches.get_one("on", object) is True


def test_definitions_are_immutable_and_shareable() -> None:
    base = Arg("name").long("name")
    required = base.required(True)
    assert base is not required
    one = Command("a").arg(base)
    two = Command("b").arg(required)
    assert isinstance(one.try_get_matches_from(["a"]), ArgMatches)
    assert not isinstance(two.try_get_matches_from(["b"]), ArgMatches)
