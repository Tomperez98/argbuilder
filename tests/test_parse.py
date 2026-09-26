"""Expected failures: every user mistake comes back as an `Error` value."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from argbuilder import (
    Arg,
    ArgGroup,
    ArgMatches,
    ArgumentConflict,
    Command,
    DisplayHelp,
    Error,
    ErrorKind,
    Invalid,
    InvalidSubcommand,
    InvalidValue,
    MissingRequiredArgument,
    MissingSubcommand,
    TooFewValues,
    TooManyValues,
    UnknownArgument,
    ValueParser,
    ValueSource,
)


def ok(cmd: Command, *args: str, env: dict[str, str] | None = None) -> ArgMatches:
    result = cmd.try_get_matches_from([cmd.get_name(), *args], env or {})
    assert isinstance(result, ArgMatches), result.render() if isinstance(result, Error) else result
    return result


def err(cmd: Command, *args: str, env: dict[str, str] | None = None) -> Error:
    result = cmd.try_get_matches_from([cmd.get_name(), *args], env or {})
    assert isinstance(result, Error), result
    return result


# -- options, flags, positionals ----------------------------------------------

VALUE = Command("prog").arg(Arg("name").short("n").long("name"))


@pytest.mark.parametrize("argv", [["--name", "x"], ["--name=x"], ["-n", "x"], ["-nx"], ["-n=x"]])
def test_option_value_spellings(argv: list[str]) -> None:
    assert ok(VALUE, *argv).get_one("name", str) == "x"


def test_absent_option_is_none() -> None:
    matches = ok(VALUE)
    assert matches.get_one("name", str) is None
    assert not matches.contains_id("name")
    assert matches.value_source("name") is None


def test_set_twice_is_a_conflict() -> None:
    assert isinstance(err(VALUE, "-n", "a", "-n", "b").kind, ArgumentConflict)


def test_missing_value() -> None:
    error = err(VALUE, "--name")
    assert isinstance(error.kind, InvalidValue)
    assert "a value is required for '--name <NAME>'" in error.message


def test_flag_cluster_ending_in_value() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("all").short("a").action("set_true"))
        .arg(Arg("verbose").short("v").action("count"))
        .arg(Arg("out").short("o"))
    )
    matches = ok(cmd, "-avvofile")
    assert matches.get_flag("all")
    assert matches.get_count("verbose") == 2
    assert matches.get_one("out", str) == "file"


def test_flag_defaults() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("on").long("on").action("set_true"))
        .arg(Arg("off").long("no-off").action("set_false"))
        .arg(Arg("v").short("v").action("count"))
    )
    matches = ok(cmd)
    assert (
        matches.get_flag("on"),
        matches.get_flag("off"),
        matches.get_count("v"),
    ) == (
        False,
        True,
        0,
    )
    assert matches.value_source("on") == "default_value"
    flipped = ok(cmd, "--on", "--no-off")
    assert (flipped.get_flag("on"), flipped.get_flag("off")) == (True, False)


def test_value_given_to_flag() -> None:
    cmd = Command("prog").arg(Arg("force").short("f").long("force").action("set_true"))
    assert isinstance(err(cmd, "--force=yes").kind, TooManyValues)
    assert isinstance(err(cmd, "-f=yes").kind, TooManyValues)


def test_append_accumulates() -> None:
    cmd = Command("prog").arg(Arg("tag").short("t").action("append"))
    assert ok(cmd, "-t", "a", "-tb").get_many("tag", str) == ("a", "b")
    assert ok(cmd).get_many("tag", str) == ()


def test_positionals_in_order_and_variadic_last() -> None:
    cmd = (
        Command("cp")
        .arg(Arg("mode").long("mode"))
        .arg(Arg("source").required(True))
        .arg(Arg("targets").action("append"))
    )
    matches = ok(cmd, "a", "--mode", "fast", "b", "c")
    assert matches.get_one("source", str) == "a"
    assert matches.get_many("targets", str) == ("b", "c")
    assert matches.get_one("mode", str) == "fast"


def test_extra_positional() -> None:
    cmd = Command("prog").arg(Arg("one"))
    error = err(cmd, "a", "b")
    assert isinstance(error.kind, UnknownArgument)
    assert "unexpected argument 'b'" in error.message


def test_double_dash_and_single_dash() -> None:
    cmd = Command("prog").arg(Arg("files").action("append"))
    assert ok(cmd, "-", "--", "-x", "--y").get_many("files", str) == ("-", "-x", "--y")


def test_unknown_argument_suggests() -> None:
    cmd = Command("prog").arg(Arg("verbose").long("verbose").action("set_true"))
    error = err(cmd, "--verbos")
    assert isinstance(error.kind, UnknownArgument)
    assert error.tip == "a similar argument exists: '--verbose'"


def test_negative_number_needs_escape_or_opt_in() -> None:
    plain = Command("prog").arg(Arg("n").long("n").value_parser(int))
    assert err(plain, "--n", "-5").tip == "to pass '-5' as a value, use '--n=-5'"
    assert ok(plain, "--n=-5").get_one("n", int) == -5
    hyphen = Command("prog").arg(Arg("n").long("n").value_parser(int).allow_hyphen_values(True))
    assert ok(hyphen, "--n", "-5").get_one("n", int) == -5
    positional = Command("prog").arg(Arg("n").value_parser(int).allow_hyphen_values(True))
    assert ok(positional, "-5").get_one("n", int) == -5


# -- num_args -----------------------------------------------------------------


def test_optional_value_with_default_missing() -> None:
    cmd = Command("prog").arg(
        Arg("color")
        .long("color")
        .num_args(0, 1)
        .default_value("auto")
        .default_missing_value("always")
    )
    assert ok(cmd).get_one("color", str) == "auto"
    assert ok(cmd, "--color").get_one("color", str) == "always"
    assert ok(cmd, "--color", "never").get_one("color", str) == "never"
    assert ok(cmd, "--color").get_required("color", str) == "always"


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        ([], {}, 22),
        ([], {"PORT": "80"}, 80),
        (["--port", "8080"], {"PORT": "80"}, 8080),
    ],
)
def test_get_required_on_a_defaulted_arg(
    argv: list[str], env: dict[str, str], expected: int
) -> None:
    cmd = Command("prog").arg(
        Arg("port").long("port").value_parser(int).env("PORT").default_value("22")
    )
    assert ok(cmd, *argv, env=env).get_required("port", int) == expected


def test_get_required_on_a_required_arg() -> None:
    cmd = Command("prog").arg(Arg("input").required(True))
    assert ok(cmd, "in.txt").get_required("input", str) == "in.txt"


def test_unbounded_stops_at_next_option() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("files").long("files").num_args(1, None))
        .arg(Arg("x").short("x").action("set_true"))
    )
    matches = ok(cmd, "--files", "a", "b", "-x")
    assert matches.get_many("files", str) == ("a", "b")
    assert matches.get_flag("x")


def test_exact_count() -> None:
    cmd = Command("prog").arg(Arg("point").long("point").num_args(2).value_parser(int))
    assert ok(cmd, "--point", "1", "2").get_many("point", int) == (1, 2)
    assert isinstance(err(cmd, "--point", "1").kind, TooFewValues)
    assert isinstance(err(cmd, "--point=1").kind, TooFewValues)


def test_value_delimiter() -> None:
    cmd = Command("prog").arg(Arg("tags").long("tags").num_args(1, None).value_delimiter(","))
    assert ok(cmd, "--tags", "a,b", "c").get_many("tags", str) == ("a", "b", "c")
    assert ok(cmd, "--tags=a,b").get_many("tags", str) == ("a", "b")
    assert isinstance(err(cmd, "--tags=a,b", "c").kind, UnknownArgument)  # inline = one occurrence


# -- value parsers --------------------------------------------------------------


type Level = Literal["low", "very-high"]


def test_value_parser_shorthands() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("port").long("port").value_parser(range(1, 65536)))
        .arg(Arg("even").long("even").value_parser(range(0, 10, 2)))
        .arg(Arg("ratio").long("ratio").value_parser(float))
        .arg(Arg("path").long("path").value_parser(Path))
        .arg(Arg("level").long("level").value_parser(Level))
        .arg(Arg("mode").long("mode").value_parser(["fast", "safe"]))
        .arg(Arg("speed").long("speed").value_parser(Literal["slow", "fast"]))  # ty: ignore[invalid-argument-type]
        .arg(Arg("dry").long("dry").value_parser(bool))
    )
    matches = ok(
        cmd,
        *["--port", "80", "--even", "4", "--ratio", "0.5", "--path", "/tmp"],
        *["--level", "very-high", "--mode", "safe", "--dry", "false"],
    )
    assert matches.get_one("port", int) == 80
    assert matches.get_one("even", int) == 4
    assert matches.get_one("ratio", float) == 0.5
    assert matches.get_one("path", Path) == Path("/tmp")
    assert matches.get_one("level", str) == "very-high"
    assert matches.get_one("mode", str) == "safe"
    assert matches.get_one("speed", str) is None
    assert ok(cmd, "--speed", "fast").get_one("speed", str) == "fast"
    assert matches.get_one("dry", bool) is False
    assert "0 is not in 1..=65535" in err(cmd, "--port", "0").message
    assert "3 is not in range(0, 10, 2)" in err(cmd, "--even", "3").message
    assert err(cmd, "--ratio", "x").message.endswith(": invalid float literal")
    assert err(cmd, "--ratio=").message.endswith(": cannot parse float from empty string")
    assert err(cmd, "--port=").message.endswith(": cannot parse integer from empty string")
    assert isinstance(err(cmd, "--dry", "no").kind, InvalidValue)


def test_possible_values_error_and_tip() -> None:
    cmd = Command("prog").arg(Arg("mode").long("mode").value_parser(["fast", "safe"]))
    error = err(cmd, "--mode", "saf")
    assert (
        error.message == "invalid value 'saf' for '--mode <MODE>'\n  [possible values: fast, safe]"
    )
    assert error.tip == "a similar value exists: 'safe'"


def test_custom_parser_returning_invalid() -> None:
    def even(raw: str) -> int | Invalid:
        value = int(raw)
        return value if value % 2 == 0 else Invalid(f"{value} is odd")

    cmd = Command("prog").arg(Arg("n").value_parser(ValueParser.from_fn(even)))
    assert ok(cmd, "4").get_one("n", int) == 4
    assert "3 is odd" in err(cmd, "3").message
    assert "invalid literal" in err(cmd, "x").message  # ValueError from int()


def test_custom_parser_bug_propagates() -> None:
    def broken(raw: str) -> int:
        raise KeyError(raw)

    cmd = Command("prog").arg(Arg("n").value_parser(broken))
    with pytest.raises(KeyError):
        cmd.try_get_matches_from(["prog", "1"])


# -- environment and defaults ---------------------------------------------------

PORT = Command("prog").arg(
    Arg("port").long("port").value_parser(int).env("PORT").default_value("22")
)


@pytest.mark.parametrize(
    ("argv", "env", "port", "source"),
    [
        ([], {}, 22, "default_value"),
        ([], {"PORT": "80"}, 80, "env_variable"),
        ([], {"PORT": ""}, 22, "default_value"),
        (["--port", "443"], {"PORT": "80"}, 443, "command_line"),
    ],
)
def test_precedence(argv: list[str], env: dict[str, str], port: int, source: ValueSource) -> None:
    matches = ok(PORT, *argv, env=env)
    assert (matches.get_one("port", int), matches.value_source("port")) == (
        port,
        source,
    )


def test_env_is_hermetic_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "80")
    matches = PORT.try_get_matches_from(["prog"])
    assert isinstance(matches, ArgMatches)
    assert matches.get_one("port", int) == 22


def test_bad_env_value_names_the_variable() -> None:
    assert "(from environment variable PORT)" in err(PORT, env={"PORT": "x"}).message


def test_env_flag() -> None:
    cmd = Command("prog").arg(Arg("debug").long("debug").action("set_true").env("DEBUG"))
    assert ok(cmd, env={"DEBUG": "yes"}).get_flag("debug")
    assert not ok(cmd, env={"DEBUG": "0"}).get_flag("debug")
    assert isinstance(err(cmd, env={"DEBUG": "maybe"}).kind, InvalidValue)


def test_env_satisfies_required() -> None:
    cmd = Command("prog").arg(Arg("token").long("token").required(True).env("TOKEN"))
    assert ok(cmd, env={"TOKEN": "t"}).get_one("token", str) == "t"
    assert isinstance(err(cmd).kind, MissingRequiredArgument)


# -- relationships --------------------------------------------------------------


def test_required_lists_everything_missing() -> None:
    cmd = (
        Command("prog").arg(Arg("name").long("name").required(True)).arg(Arg("file").required(True))
    )
    error = err(cmd)
    assert isinstance(error.kind, MissingRequiredArgument)
    assert error.message.splitlines()[1:] == ["  --name <NAME>", "  <FILE>"]


def test_conflicts_are_symmetric_and_ignore_defaults() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("json").long("json").action("set_true").conflicts_with("format"))
        .arg(Arg("format").long("format").default_value("text"))
    )
    assert isinstance(err(cmd, "--format", "x", "--json").kind, ArgumentConflict)
    assert ok(cmd, "--json").get_flag("json")


def test_requires() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("user").long("user").requires("password"))
        .arg(Arg("password").long("password"))
    )
    assert "--password <PASSWORD>" in err(cmd, "--user", "u").message
    assert ok(cmd, "--user", "u", "--password", "p").get_one("user", str) == "u"


def test_groups() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("major").long("major").action("set_true"))
        .arg(Arg("minor").long("minor").action("set_true"))
        .group(ArgGroup("bump").args(["major", "minor"]).required(True))
    )
    assert "<--major|--minor>" in err(cmd).message
    assert isinstance(err(cmd, "--major", "--minor").kind, ArgumentConflict)
    assert ok(cmd, "--minor").get_flag("minor")
    both = cmd.group(ArgGroup("any").args(["major", "minor"]).multiple(True))
    assert isinstance(err(both, "--major", "--minor").kind, ArgumentConflict)  # "bump" still


# -- subcommands ----------------------------------------------------------------

GIT = (
    Command("git")
    .version("2.0")
    .arg(Arg("verbose").short("v").action("count"))
    .subcommand_required(True)
    .subcommand(Command("clone").arg(Arg("remote").required(True)))
    .subcommand(Command("stash").subcommand(Command("pop").arg(Arg("index").value_parser(int))))
)


def test_subcommand_dispatch() -> None:
    matches = ok(GIT, "-v", "clone", "origin")
    assert matches.get_count("verbose") == 1
    match matches.subcommand():
        case ("clone", sub):
            assert sub.get_one("remote", str) == "origin"
        case other:
            pytest.fail(f"unexpected {other!r}")
    assert matches.subcommand_matches("stash") is None


def test_nested_subcommand_errors_carry_the_path() -> None:
    error = err(GIT, "stash", "pop", "x")
    assert error.usage == "git stash pop [OPTIONS] [INDEX]"
    nested = ok(GIT, "stash", "pop", "3").subcommand_matches("stash")
    assert nested is not None
    pop = nested.subcommand_matches("pop")
    assert pop is not None
    assert pop.get_one("index", int) == 3


def test_subcommand_errors() -> None:
    assert isinstance(err(GIT).kind, MissingSubcommand)
    unknown = err(GIT, "clon")
    assert isinstance(unknown.kind, InvalidSubcommand)
    assert unknown.tip == "a similar subcommand exists: 'clone'"
    assert isinstance(err(GIT, "clone").kind, MissingRequiredArgument)


def test_subcommand_name_after_double_dash_is_positional() -> None:
    cmd = Command("run").arg(Arg("args").action("append")).subcommand(Command("sub"))
    assert ok(cmd, "--", "sub").get_many("args", str) == ("sub",)


LEVELS = (
    Command("git")
    .version("2.0")
    .arg(Arg("verbose").short("v").action("count"))
    .subcommand(
        Command("push")
        .arg(Arg("force").short("f").long("force").action("set_true"))
        .arg(Arg("secret").long("secret").hide(True))
    )
    .subcommand(Command("fetch").arg(Arg("all").long("all").action("set_true")))
    .subcommand(
        Command("remote")
        .subcommand(Command("add").arg(Arg("all").long("all").action("set_true")))
        .subcommand(Command("prune").arg(Arg("dry").long("dry-run").action("set_true")))
    )
)


@pytest.mark.parametrize(
    ("argv", "tip"),
    [
        (["push", "-V"], "'-V' is an option of 'git'; put it before 'push'"),
        (["push", "-fv"], "'-v' is an option of 'git'; put it before 'push'"),
        (
            ["remote", "add", "-v"],
            "'-v' is an option of 'git'; put it before 'remote add'",
        ),
        (
            ["--force", "push"],
            "'--force' is an option of 'git push'; put it after 'push'",
        ),
        (["-f"], "'-f' is an option of 'git push'; put it after 'push'"),
        (
            ["--dry-run=1"],
            "'--dry-run' is an option of 'git remote prune'; put it after 'remote prune'",
        ),
        (["--all"], "'--all' is an option of 'git fetch', 'git remote add'"),
        (["--secret", "x"], "to pass '--secret' as a value, use '-- --secret'"),
    ],
)
def test_option_from_another_level_gets_a_placement_tip(argv: list[str], tip: str) -> None:
    error = err(LEVELS, *argv)
    assert isinstance(error.kind, UnknownArgument)
    assert error.tip == tip


# -- global arguments -----------------------------------------------------------

GLOBAL = (
    Command("git")
    .arg(Arg("verbose").short("v").action("count").global_(True))
    .arg(Arg("color").long("color").default_value("auto").env("GIT_COLOR").global_(True))
    .arg(Arg("include").short("I").action("append").global_(True))
    .subcommand(
        Command("remote")
        .arg(Arg("dry").long("dry-run").action("set_true").global_(True))
        .subcommand(Command("add").arg(Arg("name")))
        .subcommand(Command("prune"))
    )
)


def _levels(matches: ArgMatches) -> list[ArgMatches]:
    levels = [matches]
    while (sub := levels[-1].subcommand()) is not None:
        levels.append(sub[1])
    return levels


@pytest.mark.parametrize(
    "argv",
    [
        ["-vv", "remote", "add", "-v"],
        ["remote", "-v", "add", "-vv"],
        ["remote", "add", "x", "-vvv"],
    ],
)
def test_global_count_adds_up_and_is_read_at_every_level(argv: list[str]) -> None:
    assert [level.get_count("verbose") for level in _levels(ok(GLOBAL, *argv))] == [
        3,
        3,
        3,
    ]


def test_global_append_keeps_command_line_order() -> None:
    matches = ok(GLOBAL, "-I", "a", "remote", "-I", "b", "add", "-I", "c")
    assert {level.get_many("include", str) for level in _levels(matches)} == {("a", "b", "c")}


def test_global_value_sources_are_the_same_at_every_level() -> None:
    for argv, env, expected in [
        (["remote", "add"], {}, ("auto", "default_value")),
        (["remote", "add"], {"GIT_COLOR": "never"}, ("never", "env_variable")),
        (["remote", "add", "--color", "always"], {}, ("always", "command_line")),
    ]:
        for level in _levels(ok(GLOBAL, *argv, env=env)):
            assert (
                level.get_one("color", str),
                level.value_source("color"),
            ) == expected


def test_global_set_given_at_two_levels_is_used_twice() -> None:
    error = err(GLOBAL, "--color", "never", "remote", "--color", "always")
    assert error.kind == ArgumentConflict("--color <COLOR>", None)
    assert error.usage == "git remote [OPTIONS] [COMMAND]"


def test_global_only_reaches_down() -> None:
    matches = ok(GLOBAL, "remote", "prune", "--dry-run")
    assert [level.get_flag("dry") for level in _levels(matches)[1:]] == [True, True]
    error = err(GLOBAL, "--dry-run", "remote")
    assert error.tip == "'--dry-run' is an option of 'git remote'; put it after 'remote'"


# -- aliases ----------------------------------------------------------------------

ALIASES = (
    Command("git")
    .arg(Arg("color").long("color").visible_alias("colour").alias("tint"))
    .arg(Arg("quiet").short("q").visible_short_alias("s").short_alias("Q").action("count"))
    .subcommand(Command("add").visible_alias("stage").alias("a"))
)


@pytest.mark.parametrize("flag", ["--color", "--colour", "--tint"])
def test_long_aliases_select_the_argument(flag: str) -> None:
    assert ok(ALIASES, f"{flag}=never").get_one("color", str) == "never"


def test_short_aliases_select_the_argument_and_cluster() -> None:
    assert ok(ALIASES, "-qsQ").get_count("quiet") == 3


def test_errors_name_the_argument_by_its_canonical_flag() -> None:
    error = err(ALIASES, "--colour", "a", "--tint", "b")
    assert error.kind == ArgumentConflict("--color <COLOR>", None)


@pytest.mark.parametrize("name", ["add", "stage", "a"])
def test_subcommand_aliases_report_the_canonical_name(name: str) -> None:
    matches = ok(ALIASES, name)
    assert matches.subcommand_name() == "add"
    assert matches.subcommand_matches("add") is not None


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        (["stag"], InvalidSubcommand("stag", "stage")),
        (["--colou"], UnknownArgument("--colou", "--colour")),
        (
            ["--tin"],
            UnknownArgument("--tin", None),
        ),  # hidden aliases are never suggested
    ],
)
def test_suggestions_offer_visible_aliases_only(argv: list[str], kind: ErrorKind) -> None:
    assert err(ALIASES, *argv).kind == kind


# -- the help subcommand ----------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        (["help"], []),
        (["help", "remote"], ["remote"]),
        (["help", "remote", "add"], ["remote", "add"]),
        (["-v", "help", "remote"], ["remote"]),
        (["help", "help"], ["help"]),
    ],
)
def test_help_subcommand_prints_the_named_help(argv: list[str], shown: list[str]) -> None:
    error = err(GLOBAL, *argv)
    assert (error.kind, error.exit_code) == (DisplayHelp(), 0)
    expected = err(GLOBAL, *shown, "--help") if shown != ["help"] else None
    if expected is not None:
        assert error.render() == expected.render()
    else:
        assert error.render().startswith("Print this message")


def test_help_subcommand_skips_the_parents_required_arguments() -> None:
    cmd = Command("x").arg(Arg("input").required(True)).subcommand(Command("sub"))
    assert err(cmd, "help").kind == DisplayHelp()


def test_help_subcommand_rejects_unknown_names() -> None:
    error = err(GLOBAL, "help", "remote", "ad")
    assert error.kind == InvalidSubcommand("ad", "add")
    assert error.usage == "git remote [OPTIONS] [COMMAND]"


def test_help_subcommand_accepts_aliases() -> None:
    assert err(ALIASES, "help", "stage").render() == err(ALIASES, "add", "--help").render()


def test_help_subcommand_can_be_disabled_or_replaced() -> None:
    off = Command("x").disable_help_subcommand(True).subcommand(Command("sub"))
    assert err(off, "help").kind == InvalidSubcommand("help", None)
    mine = Command("x").subcommand(Command("help").arg(Arg("topic")))
    assert ok(mine, "help", "sub").subcommand_name() == "help"


def test_leaf_commands_get_no_help_subcommand() -> None:
    cmd = Command("x").arg(Arg("name"))
    assert ok(cmd, "help").get_one("name", str) == "help"


# -- structured error kinds -----------------------------------------------------

KINDS = (
    Command("tool")
    .arg(Arg("port").short("p").long("port").value_parser(range(1, 100)).env("PORT"))
    .arg(Arg("mode").long("mode").value_parser(["fast", "safe"]))
    .arg(Arg("pair").long("pair").num_args(2))
    .arg(Arg("force").short("f").long("force").action("set_true").conflicts_with("mode"))
    .arg(Arg("input").required(True))
    .subcommand(Command("run"))
    .subcommand_required(True)
)


@pytest.mark.parametrize(
    ("argv", "env", "kind"),
    [
        (["in", "--port"], {}, InvalidValue("--port <PORT>", None)),
        (
            ["in", "--port", "0"],
            {},
            InvalidValue("--port <PORT>", "0", "0 is not in 1..=99"),
        ),
        (
            ["in"],
            {"PORT": "abc"},
            InvalidValue("--port <PORT>", "abc", "invalid digit found in string", env="PORT"),
        ),
        (
            ["in", "--mode", "saf"],
            {},
            InvalidValue(
                "--mode <MODE>",
                "saf",
                "expected one of fast, safe",
                ("fast", "safe"),
                "safe",
            ),
        ),
        (["in", "--prot", "1"], {}, UnknownArgument("--prot", "--port")),
        (["in", "-x"], {}, UnknownArgument("-x")),
        (["in", "rnu"], {}, InvalidSubcommand("rnu", "run")),
        (["in", "--pair=a"], {}, TooFewValues("--pair <PAIR> <PAIR>", 2, 1)),
        (["in", "--force=yes"], {}, TooManyValues("--force", "yes")),
        (["in", "-f", "-f"], {}, ArgumentConflict("--force", None)),
        (
            ["in", "-f", "--mode", "fast"],
            {},
            ArgumentConflict("--force", "--mode <MODE>"),
        ),
        ([], {}, MissingRequiredArgument(("<INPUT>",))),
        (["in"], {}, MissingSubcommand("tool", ("run", "help"))),
    ],
)
def test_error_kind_carries_what_went_wrong(
    argv: list[str], env: dict[str, str], kind: ErrorKind
) -> None:
    error = err(KINDS, *argv, env=env)
    assert error.kind == kind
    assert error.render().startswith(f"error: {error.message}")


def test_error_kind_is_matchable() -> None:
    match err(KINDS, "in", "--port", "0").kind:
        case InvalidValue(argument=argument, value=value, reason=reason):
            assert (argument, value, reason) == (
                "--port <PORT>",
                "0",
                "0 is not in 1..=99",
            )
        case other:
            pytest.fail(f"unexpected {other!r}")


# -- remaining paths ------------------------------------------------------------


def test_matches_repr_lists_values_and_subcommand() -> None:
    assert repr(ok(VALUE, "--name", "x")) == "ArgMatches({'name': ('x',)}, subcommand=None)"
    assert "subcommand=('clone', ArgMatches(" in repr(ok(GIT, "clone", "origin"))


def test_too_many_values_after_a_delimiter_split() -> None:
    cmd = Command("prog").arg(Arg("pair").long("pair").num_args(1, 2).value_delimiter(","))
    assert isinstance(err(cmd, "--pair=a,b,c").kind, TooManyValues)


def test_variadic_positional_too_few_values() -> None:
    cmd = Command("prog").arg(Arg("files").num_args(2, 2))
    assert isinstance(err(cmd, "a").kind, TooFewValues)


def test_unbounded_option_stops_at_double_dash() -> None:
    cmd = Command("prog").arg(Arg("files").long("files").num_args(0, None))
    assert ok(cmd, "--files", "--").get_many("files", str) == ()


def test_requires_a_required_argument_that_is_already_missing() -> None:
    cmd = (
        Command("prog").arg(Arg("a").long("a").requires("b")).arg(Arg("b").long("b").required(True))
    )
    error = err(cmd, "--a", "x")
    assert isinstance(error.kind, MissingRequiredArgument)
    assert error.kind.arguments.count("--b <B>") == 1
