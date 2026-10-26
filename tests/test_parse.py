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
    SubcommandConflict,
    TooFewValues,
    TooManyValues,
    UnknownArgument,
    ValueParser,
    ValueSource,
)
from argbuilder._spec import is_negative_number


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
    error = err(VALUE, "-n", "a", "-n", "b")
    assert error.kind == ArgumentConflict("--name <NAME>", None)
    # None means "repeated", so the wording must not fall through to the
    # two-argument branch and print "cannot be used with 'None'."
    assert error.message == "the argument '--name <NAME>' cannot be used multiple times"


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


LAST = Command("prog").arg(Arg("mode")).arg(Arg("rest").action("append").last(True))


def test_last_is_empty_without_double_dash() -> None:
    matches = ok(LAST, "fast")
    assert matches.get_one("mode", str) == "fast"
    assert matches.get_many("rest", str) == ()


def test_last_takes_every_token_after_double_dash_verbatim() -> None:
    matches = ok(LAST, "fast", "--", "build", "--release", "-j8")
    assert matches.get_one("mode", str) == "fast"
    assert matches.get_many("rest", str) == ("build", "--release", "-j8")


def test_last_cannot_be_reached_without_double_dash() -> None:
    error = err(LAST, "fast", "extra")
    assert isinstance(error.kind, UnknownArgument)
    assert error.tip == "to pass 'extra' as a value, use '-- extra'"


def test_last_usage_and_error_naming_show_the_double_dash() -> None:
    assert LAST.render_usage() == "Usage: prog [OPTIONS] [MODE] -- [REST]..."
    required = Command("prog").arg(Arg("rest").action("append").required(True).last(True))
    error = err(required)
    assert "-- <REST>..." in error.message


TRAILING = Command("prog").arg(
    Arg("command").num_args(1, None).required(True).trailing_var_arg(True),
)


def test_trailing_var_arg_takes_every_token_without_double_dash() -> None:
    matches = ok(TRAILING, "cargo", "build", "--release", "-j8")
    assert matches.get_many("command", str) == ("cargo", "build", "--release", "-j8")


def test_trailing_var_arg_parses_options_before_it_starts() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("verbose").short("v").action("count"))
        .arg(Arg("command").num_args(1, None).trailing_var_arg(True))
    )
    matches = ok(cmd, "-v", "cargo", "build", "--release")
    assert matches.get_count("verbose") == 1
    assert matches.get_many("command", str) == ("cargo", "build", "--release")


def test_trailing_var_arg_with_allow_hyphen_can_start_with_a_flag() -> None:
    cmd = Command("p").arg(
        Arg("args").num_args(1, None).trailing_var_arg(True).allow_hyphen_values(True),
    )
    assert ok(cmd, "-x", "--foo").get_many("args", str) == ("-x", "--foo")
    assert ok(cmd, "--foo", "-j8").get_many("args", str) == ("--foo", "-j8")


def test_a_known_option_still_wins_before_a_trailing_run() -> None:
    cmd = (
        Command("p")
        .arg(Arg("verbose").short("v").long("verbose").action("set_true"))
        .arg(
            Arg("args").num_args(1, None).trailing_var_arg(True).allow_hyphen_values(True),
        )
    )
    matches = ok(cmd, "-v", "--foo")
    assert matches.get_flag("verbose")
    assert matches.get_many("args", str) == ("--foo",)


def test_trailing_var_arg_starts_after_a_double_dash_separator() -> None:
    assert ok(TRAILING, "--", "cargo", "build").get_many("command", str) == (
        "cargo",
        "build",
    )


def test_trailing_var_arg_keeps_a_later_double_dash_as_a_value() -> None:
    assert ok(TRAILING, "cargo", "--", "--release").get_many("command", str) == (
        "cargo",
        "--",
        "--release",
    )


def test_trailing_var_arg_still_allows_a_subcommand_before_it_starts() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("command").num_args(1, None).trailing_var_arg(True))
        .subcommand(Command("sub").arg(Arg("x")))
    )
    matches = ok(cmd, "sub", "value")
    assert matches.subcommand_name() == "sub"
    assert matches.get_many("command", str) == ()


def test_trailing_var_arg_parser_errors_are_returned() -> None:
    cmd = Command("p").arg(
        Arg("n").num_args(1, None).trailing_var_arg(True).value_parser(int),
    )
    assert isinstance(err(cmd, "1", "x").kind, InvalidValue)
    assert ok(cmd, "1", "2", "3").get_many("n", int) == (1, 2, 3)


def test_trailing_var_arg_can_be_required() -> None:
    cmd = Command("prog").arg(
        Arg("command").num_args(1, None).required(True).trailing_var_arg(True),
    )
    error = err(cmd)
    assert error.kind == MissingRequiredArgument(("<COMMAND>...",))


def test_trailing_var_arg_usage_has_no_double_dash() -> None:
    assert TRAILING.render_usage() == "Usage: prog [OPTIONS] <COMMAND>..."


STASH = (
    Command("stash")
    .args_conflicts_with_subcommands(True)
    .arg(Arg("message").short("m").long("message"))
    .subcommand(Command("push").arg(Arg("file")))
    .subcommand(Command("pop"))
)


def test_parent_argument_with_a_subcommand_conflicts() -> None:
    error = err(STASH, "--message", "wip", "push", "file")
    assert error.kind == SubcommandConflict("--message <MESSAGE>", "push")
    assert "cannot be used with the subcommand 'push'" in error.message


def test_parent_argument_alone_is_allowed() -> None:
    assert ok(STASH, "--message", "wip").get_one("message", str) == "wip"


def test_subcommand_alone_is_allowed() -> None:
    matches = ok(STASH, "push", "file")
    assert matches.subcommand_name() == "push"


def test_parent_default_and_env_do_not_conflict_with_a_subcommand() -> None:
    defaulted = (
        Command("stash")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("message").long("message").default_value("wip"))
        .subcommand(Command("push"))
    )
    assert ok(defaulted, "push").subcommand_name() == "push"

    from_env = (
        Command("stash")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("message").long("message").env("MESSAGE"))
        .subcommand(Command("push"))
    )
    assert ok(from_env, "push", env={"MESSAGE": "wip"}).subcommand_name() == "push"


def test_a_defaulted_required_group_does_not_block_subcommands() -> None:
    cmd = (
        Command("p")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("a").long("a").default_value("x"))
        .arg(Arg("b").long("b"))
        .group(ArgGroup("g").args(["a", "b"]).required(True))
        .subcommand(Command("sub"))
    )
    assert ok(cmd, "sub").subcommand_name() == "sub"


def test_an_explicit_parent_global_conflicts_but_an_inherited_one_does_not() -> None:
    cmd = (
        Command("p")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("verbose").short("v").action("count").global_(True))
        .subcommand(Command("sub"))
    )
    assert err(cmd, "-v", "sub").kind == SubcommandConflict("-v", "sub")
    assert ok(cmd, "sub", "-v").subcommand_name() == "sub"


def test_args_conflicts_with_subcommands_applies_per_level() -> None:
    cmd = (
        Command("p")
        .arg(Arg("g").long("g"))
        .subcommand(
            Command("sub")
            .args_conflicts_with_subcommands(True)
            .arg(Arg("x").long("x"))
            .subcommand(Command("deep")),
        )
    )
    assert ok(cmd, "--g", "1", "sub", "deep").subcommand_name() == "sub"
    assert err(cmd, "sub", "--x", "1", "deep").kind == SubcommandConflict(
        "--x <X>",
        "deep",
    )


def test_subcommand_conflict_uses_the_canonical_name_for_an_alias() -> None:
    cmd = (
        Command("p")
        .args_conflicts_with_subcommands(True)
        .arg(Arg("x").long("x"))
        .subcommand(Command("push").alias("p"))
    )
    assert err(cmd, "--x", "1", "p").kind == SubcommandConflict("--x <X>", "push")


COLOR = (
    Command("p")
    .arg(Arg("color").long("color").action("set_true").overrides_with("no_color"))
    .arg(Arg("no_color").long("no-color").action("set_true").overrides_with("color"))
)


def test_overrides_with_is_last_one_wins() -> None:
    first = ok(COLOR, "--color", "--no-color")
    assert first.get_flag("color") is False
    assert first.get_flag("no_color") is True
    assert first.value_source("color") == "default_value"

    second = ok(COLOR, "--no-color", "--color")
    assert second.get_flag("color") is True
    assert second.get_flag("no_color") is False


def test_overrides_with_all_accumulates_targets() -> None:
    cmd = (
        Command("p")
        .arg(Arg("a").long("a").action("set_true").overrides_with_all(["b", "c"]))
        .arg(Arg("b").long("b").action("set_true"))
        .arg(Arg("c").long("c").action("set_true"))
    )
    matches = ok(cmd, "--b", "--c", "--a")
    assert matches.get_flag("a") is True
    assert matches.get_flag("b") is False
    assert matches.get_flag("c") is False


def test_overrides_with_follows_a_chain() -> None:
    cmd = (
        Command("p")
        .arg(Arg("a").long("a").action("set_true").overrides_with("b"))
        .arg(Arg("b").long("b").action("set_true").overrides_with("c"))
        .arg(
            Arg("c").long("c").action("set_true").overrides_with("a").overrides_with("b"),
        )
    )
    forward = ok(cmd, "--a", "--b", "--c")
    assert (forward.get_flag("a"), forward.get_flag("b"), forward.get_flag("c")) == (
        False,
        False,
        True,
    )
    backward = ok(cmd, "--c", "--b", "--a")
    assert (backward.get_flag("a"), backward.get_flag("b"), backward.get_flag("c")) == (
        True,
        False,
        False,
    )


def test_overrides_with_removes_append_and_count_values() -> None:
    append = (
        Command("p")
        .arg(
            Arg("tags").long("tags").action("append"),
        )
        .arg(Arg("no_tags").long("no-tags").action("set_true").overrides_with("tags"))
    )
    assert ok(append, "--tags", "a", "--tags", "b", "--no-tags").get_many("tags", str) == ()

    count = (
        Command("p")
        .arg(
            Arg("verbose").short("v").action("count"),
        )
        .arg(Arg("quiet").short("q").action("set_true").overrides_with("verbose"))
    )
    assert ok(count, "-vv", "-q").get_count("verbose") == 0


def test_overrides_with_falls_back_to_default_and_env() -> None:
    defaulted = (
        Command("p")
        .arg(
            Arg("color").long("color").default_value("auto"),
        )
        .arg(Arg("plain").long("plain").action("set_true").overrides_with("color"))
    )
    matches = ok(defaulted, "--plain")
    assert matches.get_one("color", str) == "auto"
    assert matches.value_source("color") == "default_value"

    from_env = (
        Command("p")
        .arg(
            Arg("color").long("color").env("COLOR"),
        )
        .arg(Arg("plain").long("plain").action("set_true").overrides_with("color"))
    )
    matches = ok(from_env, "--plain", env={"COLOR": "blue"})
    assert matches.get_one("color", str) == "blue"
    assert matches.value_source("color") == "env_variable"


def test_overrides_with_removes_a_plain_set_value() -> None:
    cmd = (
        Command("p")
        .arg(Arg("color").long("color"))
        .arg(
            Arg("no_color").long("no-color").action("set_true").overrides_with("color"),
        )
    )
    matches = ok(cmd, "--color", "red", "--no-color")
    assert matches.get_one("color", str) is None
    assert not matches.contains_id("color")


def test_global_overrides_follow_command_line_order_across_levels() -> None:
    cmd = (
        Command("p")
        .arg(Arg("verbose").short("v").action("count").global_(True).overrides_with("quiet"))
        .arg(Arg("quiet").short("q").action("set_true").global_(True).overrides_with("verbose"))
        .subcommand(Command("sub"))
    )
    assert ok(cmd, "-q", "sub", "-v").get_count("verbose") == 1
    assert ok(cmd, "-v", "sub", "-q").get_count("verbose") == 0


EXCLUSIVE = (
    Command("p")
    .arg(Arg("version_info").long("version-info").action("set_true").exclusive(True))
    .arg(Arg("color").long("color").action("set_true"))
    .arg(Arg("mode").long("mode").default_value("auto"))
)


def test_exclusive_allows_itself_and_ignores_defaults() -> None:
    matches = ok(EXCLUSIVE, "--version-info")
    assert matches.get_flag("version_info") is True
    assert matches.get_one("mode", str) == "auto"


def test_exclusive_conflicts_with_any_other_explicit_argument() -> None:
    error = err(EXCLUSIVE, "--version-info", "--color")
    assert error.kind == ArgumentConflict("--version-info", "--color")


def test_exclusive_counts_environment_values() -> None:
    cmd = (
        Command("p")
        .arg(
            Arg("version_info").long("version-info").action("set_true").exclusive(True),
        )
        .arg(Arg("color").long("color").env("COLOR"))
    )
    assert err(cmd, "--version-info", env={"COLOR": "blue"}).kind == ArgumentConflict(
        "--version-info",
        "--color <COLOR>",
    )


def test_repeated_exclusive_argument_is_still_a_repeat_error() -> None:
    assert err(EXCLUSIVE, "--version-info", "--version-info").kind == ArgumentConflict(
        "--version-info",
        None,
    )


TOKEN = (
    Command("p")
    .arg(Arg("token").required_unless_present("anonymous"))
    .arg(Arg("anonymous").long("anonymous").action("set_true"))
)


def test_required_unless_present() -> None:
    assert err(TOKEN).kind == MissingRequiredArgument(("<TOKEN>",))
    assert ok(TOKEN, "secret").get_one("token", str) == "secret"
    assert ok(TOKEN, "--anonymous").get_one("token", str) is None


def test_required_unless_present_counts_defaults_and_env() -> None:
    defaulted = (
        Command("p")
        .arg(Arg("token").required_unless_present("anonymous"))
        .arg(Arg("anonymous").long("anonymous").default_value("yes"))
    )
    assert ok(defaulted).get_one("token", str) is None

    from_env = (
        Command("p")
        .arg(Arg("token").required_unless_present("anonymous"))
        .arg(Arg("anonymous").long("anonymous").env("ANONYMOUS"))
    )
    assert ok(from_env, env={"ANONYMOUS": "yes"}).get_one("token", str) is None


OUTPUT = (
    Command("p")
    .arg(Arg("mode").long("mode").default_value("read"))
    .arg(Arg("output").long("output").required_if_eq("mode", "write"))
)


def test_required_if_eq_follows_the_effective_value() -> None:
    assert ok(OUTPUT).get_one("output", str) is None
    assert ok(OUTPUT, "--mode", "read", "--output", "x").get_one("output", str) == "x"
    assert err(OUTPUT, "--mode", "write").kind == MissingRequiredArgument(
        ("--output <OUTPUT>",),
    )
    assert ok(OUTPUT, "--mode", "write", "--output", "x").get_one("output", str) == "x"


def test_required_if_eq_uses_the_raw_spelling_not_the_parsed_value() -> None:
    cmd = (
        Command("p")
        .arg(Arg("mode").long("mode").value_parser(str.upper))
        .arg(Arg("output").long("output").required_if_eq("mode", "write"))
    )
    assert err(cmd, "--mode", "write").kind == MissingRequiredArgument(
        ("--output <OUTPUT>",),
    )
    # Parsed as "WRITE", but the raw spelling does not equal "write".
    assert ok(cmd, "--mode", "WRITE").get_one("output", str) is None


def test_required_if_eq_reads_a_default_missing_value() -> None:
    cmd = (
        Command("p")
        .arg(Arg("mode").long("mode").num_args(0, 1).default_missing_value("on"))
        .arg(Arg("output").long("output").required_if_eq("mode", "on"))
    )
    assert isinstance(err(cmd, "--mode").kind, MissingRequiredArgument)
    assert isinstance(err(cmd, "--mode=on").kind, MissingRequiredArgument)
    assert ok(cmd, "--mode=off").get_one("output", str) is None


def test_required_if_eq_reads_env_and_default_raw_values() -> None:
    from_env = (
        Command("p")
        .arg(Arg("mode").long("mode").env("MODE"))
        .arg(Arg("output").long("output").required_if_eq("mode", "write"))
    )
    assert err(from_env, env={"MODE": "write"}).kind == MissingRequiredArgument(
        ("--output <OUTPUT>",),
    )

    from_default = (
        Command("p")
        .arg(Arg("mode").long("mode").default_value("write"))
        .arg(Arg("output").long("output").required_if_eq("mode", "write"))
    )
    assert err(from_default).kind == MissingRequiredArgument(("--output <OUTPUT>",))


def test_conditional_requirements_combine_into_one_missing_error() -> None:
    cmd = (
        Command("p")
        .arg(Arg("a").long("a").required_if_eq("mode", "write"))
        .arg(Arg("b").long("b").required_unless_present("skip"))
        .arg(Arg("mode").long("mode"))
        .arg(Arg("skip").long("skip").action("set_true"))
    )
    assert err(cmd, "--mode", "write").kind == MissingRequiredArgument(
        ("--a <A>", "--b <B>"),
    )
    assert ok(cmd, "--mode", "write", "--a", "1", "--skip").get_one("a", str) == "1"


def test_an_invalid_trigger_value_wins_over_a_conditional_requirement() -> None:
    cmd = (
        Command("p")
        .arg(Arg("mode").long("mode").value_parser(["read", "write"]))
        .arg(Arg("output").long("output").required_if_eq("mode", "write"))
    )
    assert isinstance(err(cmd, "--mode", "nope").kind, InvalidValue)


def test_requires_and_conditional_missing_do_not_duplicate() -> None:
    cmd = (
        Command("p")
        .arg(Arg("x").long("x").action("set_true").requires("y"))
        .arg(Arg("y").long("y").required_unless_present("skip"))
        .arg(Arg("skip").long("skip").action("set_true"))
    )
    assert err(cmd, "--x").kind == MissingRequiredArgument(("--y <Y>",))


def test_conditional_arguments_stay_optional_in_usage() -> None:
    assert "[TOKEN]" in TOKEN.render_usage()
    assert "[OUTPUT]" not in OUTPUT.render_usage()
    assert "--output <OUTPUT>" in OUTPUT.render_help()


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


NEGATIVE = Command("prog").arg(
    Arg("offset").long("offset").value_parser(float).allow_negative_numbers(True),
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("-5", -5.0), ("-0.5", -0.5), ("-1.5e-3", -1.5e-3), ("-2E+2", -200.0)],
)
def test_allow_negative_numbers_parses_numeric_values(raw: str, expected: float) -> None:
    assert ok(NEGATIVE, "--offset", raw).get_one("offset", float) == expected


@pytest.mark.parametrize("raw", ["-x", "--other", "-1_000", "-.5"])
def test_allow_negative_numbers_rejects_other_hyphen_tokens(raw: str) -> None:
    error = err(NEGATIVE, "--offset", raw)
    assert isinstance(error.kind, InvalidValue)
    assert error.kind.value is None


def test_allow_negative_numbers_applies_to_positionals() -> None:
    cmd = Command("prog").arg(Arg("n").value_parser(int).allow_negative_numbers(True))
    assert ok(cmd, "-3").get_one("n", int) == -3

    plain = Command("prog").arg(Arg("n").value_parser(int))
    assert err(plain, "-3").kind == UnknownArgument("-3")


def test_allow_hyphen_values_still_accepts_arbitrary_hyphens() -> None:
    cmd = Command("prog").arg(
        Arg("n").long("n").allow_hyphen_values(True).allow_negative_numbers(True),
    )
    assert ok(cmd, "--n", "-x").get_one("n", str) == "-x"
    assert ok(cmd, "--n", "-5").get_one("n", str) == "-5"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("-5", True),
        ("-0.5", True),
        ("-1.5e-3", True),
        ("-2E+2", True),
        ("-0", True),
        ("-", False),
        ("-x", False),
        ("-1_000", False),
        ("-.5", False),
        ("+1", False),
        ("5", False),
        ("--5", False),
    ],
)
def test_negative_number_grammar(token: str, expected: bool) -> None:
    assert is_negative_number(token) is expected


# -- num_args -----------------------------------------------------------------


def test_optional_value_with_default_missing() -> None:
    cmd = Command("prog").arg(
        Arg("color")
        .long("color")
        .num_args(0, 1)
        .default_value("auto")
        .default_missing_value("always"),
    )
    assert ok(cmd).get_one("color", str) == "auto"
    assert ok(cmd, "--color").get_one("color", str) == "always"
    assert ok(cmd, "--color", "never").get_one("color", str) == "never"
    assert ok(cmd, "--color").get_required("color", str) == "always"


EQUALS = Command("prog").arg(
    Arg("color").short("c").long("color").require_equals(True),
)


@pytest.mark.parametrize("argv", [["--color=always"], ["-c=always"]])
def test_require_equals_accepts_the_equals_spelling(argv: list[str]) -> None:
    assert ok(EQUALS, *argv).get_one("color", str) == "always"


@pytest.mark.parametrize("argv", [["--color", "always"], ["-c", "always"], ["-calways"]])
def test_require_equals_rejects_a_space_or_cluster_value(argv: list[str]) -> None:
    error = err(EQUALS, *argv)
    assert error.kind == InvalidValue("--color=<COLOR>", None)
    assert error.tip is not None and "equals sign" in error.tip


def test_require_equals_still_accepts_an_empty_inline_value() -> None:
    # `--color=` is an explicit empty value, not a missing one.
    assert ok(EQUALS, "--color=").get_one("color", str) == ""
    assert ok(EQUALS, "-c=").get_one("color", str) == ""


OPTIONAL_EQUALS = (
    Command("prog")
    .arg(
        Arg("color")
        .short("c")
        .long("color")
        .num_args(0, 1)
        .default_value("auto")
        .default_missing_value("always")
        .require_equals(True),
    )
    .arg(Arg("rest"))
)


def test_require_equals_optional_value_does_not_consume_the_next_token() -> None:
    for spelling in ("--color", "-c"):
        matches = ok(OPTIONAL_EQUALS, spelling, "blue")
        assert matches.get_one("color", str) == "always"
        assert matches.get_one("rest", str) == "blue"


def test_require_equals_optional_value_accepts_inline_and_empty_values() -> None:
    assert ok(OPTIONAL_EQUALS, "--color=never").get_one("color", str) == "never"
    assert ok(OPTIONAL_EQUALS, "-c=never").get_one("color", str) == "never"
    assert ok(OPTIONAL_EQUALS, "--color=").get_one("color", str) == ""


def test_require_equals_without_default_missing_stores_no_value() -> None:
    cmd = Command("prog").arg(
        Arg("color").long("color").num_args(0, 1).require_equals(True),
    )
    matches = ok(cmd, "--color")
    assert matches.contains_id("color")
    assert matches.get_one("color", str) is None


def test_require_equals_with_a_delimiter_can_split_one_inline_value() -> None:
    cmd = Command("prog").arg(
        Arg("tags").long("tags").num_args(1, None).value_delimiter(",").require_equals(True),
    )
    assert ok(cmd, "--tags=a,b").get_many("tags", str) == ("a", "b")
    assert isinstance(err(cmd, "--tags", "a,b").kind, InvalidValue)


def test_require_equals_applies_to_visible_aliases() -> None:
    cmd = Command("prog").arg(
        Arg("color").long("color").visible_alias("colour").require_equals(True)
    )
    assert ok(cmd, "--colour=always").get_one("color", str) == "always"
    assert isinstance(err(cmd, "--colour", "always").kind, InvalidValue)


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        (
            Command("prog").arg(
                Arg("color").short("c").long("color").require_equals(True),
            ),
            "-c, --color=<COLOR>",
        ),
        (
            Command("prog").arg(
                Arg("color").long("color").num_args(0, 1).require_equals(True),
            ),
            "--color[=<COLOR>]",
        ),
    ],
)
def test_require_equals_help_and_usage_labels(cmd: Command, expected: str) -> None:
    assert expected in cmd.render_help()
    assert expected.strip() in cmd.render_markdown()


def test_require_equals_required_option_in_usage() -> None:
    cmd = Command("prog").arg(
        Arg("color").short("c").long("color").required(True).require_equals(True),
    )
    assert cmd.render_usage() == "Usage: prog [OPTIONS] --color=<COLOR>"


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        ([], {}, 22),
        ([], {"PORT": "80"}, 80),
        (["--port", "8080"], {"PORT": "80"}, 8080),
    ],
)
def test_get_required_on_a_defaulted_arg(
    argv: list[str],
    env: dict[str, str],
    expected: int,
) -> None:
    cmd = Command("prog").arg(
        Arg("port").long("port").value_parser(int).env("PORT").default_value("22"),
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


def test_default_values_satisfy_min_num_args() -> None:
    cmd = Command("prog").arg(Arg("pair").long("pair").num_args(2).default_values(["a", "b"]))
    assert ok(cmd).get_many("pair", str) == ("a", "b")


def test_env_on_a_positional_enforces_min_num_args() -> None:
    cmd = Command("prog").arg(Arg("files").num_args(2, 2).env("FILES"))
    error = err(cmd, env={"FILES": "one"})
    assert error.kind == TooFewValues("<FILES>...", 2, 1, "FILES")


def test_env_on_a_positional_within_num_args() -> None:
    cmd = Command("prog").arg(Arg("files").num_args(1, 2).env("FILES"))
    assert ok(cmd, env={"FILES": "one"}).get_many("files", str) == ("one",)


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


def test_integer_parser_bound_shapes() -> None:
    # Equal bounds are legal and either bound may be omitted; a mutant of the
    # `min <= max` guard or its short-circuit must not slip through.
    assert ValueParser.integer(5, 5).parse("5") == 5
    assert ValueParser.integer(1).parse("1") == 1
    assert ValueParser.integer(max=9).parse("9") == 9
    assert isinstance(ValueParser.integer(1).parse("0"), Invalid)
    with pytest.raises(AssertionError, match="greater than max"):
        ValueParser.integer(5, 1)


def test_boolean_parser_lists_its_alphabet_and_rejects_other_spellings() -> None:
    # Help and errors read `possible_values`; the parser is exact, unlike
    # `bool("false")`, so its alphabet and message are part of the contract.
    parser = ValueParser.boolean()
    assert parser.possible_values == ("true", "false")
    assert parser.parse("true") is True
    assert parser.parse("false") is False
    assert parser.parse("True") == Invalid("expected 'true' or 'false'")
    assert parser.parse("") == Invalid("expected 'true' or 'false'")


def test_possible_values_error_and_tip() -> None:
    cmd = Command("prog").arg(Arg("mode").long("mode").value_parser(["fast", "safe"]))
    error = err(cmd, "--mode", "saf")
    assert (
        error.message == "invalid value 'saf' for '--mode <MODE>'\n  [possible values: fast, safe]"
    )
    assert error.tip == "a similar value exists: 'safe'"


def test_choices_accept_a_set_or_frozenset() -> None:
    # A set is a natural spelling of "one of these"; the accepted values are the
    # same, and the listed order is sorted so help and errors are reproducible
    # across processes (a set's iteration order is not).
    for accepted in ({"fast", "safe"}, frozenset({"fast", "safe"})):
        parser = Arg("mode").value_parser(accepted)._spec.value_parser  # noqa: SLF001
        assert parser is not None
        assert parser.possible_values == ("fast", "safe")
        assert parser.parse("safe") == "safe"
        assert isinstance(parser.parse("other"), Invalid)


def test_set_possible_values_are_sorted_not_hash_ordered() -> None:
    # Regression: iterating a set leaked its hash order into help and errors, so
    # one definition rendered differently under different PYTHONHASHSEED values.
    parser = Arg("mode").value_parser({"gamma", "alpha", "delta", "beta"})._spec  # noqa: SLF001
    assert parser.value_parser is not None
    assert parser.value_parser.possible_values == ("alpha", "beta", "delta", "gamma")


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
    Arg("port").long("port").value_parser(int).env("PORT").default_value("22"),
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


def test_env_can_turn_a_flag_off() -> None:
    # For action "set_false" a truthy variable leaves the flag at its default
    # (False) and a falsy one sets it True, the opposite of "set_true"; the
    # branch must not return the raw bool for both actions.
    cmd = Command("prog").arg(Arg("clean").long("clean").action("set_false").env("CLEAN"))
    assert not ok(cmd, env={"CLEAN": "1"}).get_flag("clean")
    assert ok(cmd, env={"CLEAN": "0"}).get_flag("clean")


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


def test_conflicts_with_all_adds_to_the_conflicts_already_set() -> None:
    # `conflicts_with` and `conflicts_with_all` accumulate; an `&` instead of
    # `|` would drop both the earlier conflict and the new ones.
    cmd = (
        Command("prog")
        .arg(
            Arg("a")
            .long("a")
            .action("set_true")
            .conflicts_with("b")
            .conflicts_with_all(["c", "d"]),
        )
        .arg(Arg("b").long("b").action("set_true"))
        .arg(Arg("c").long("c").action("set_true"))
        .arg(Arg("d").long("d").action("set_true"))
    )
    for other in ("--b", "--c", "--d"):
        assert isinstance(err(cmd, "--a", other).kind, ArgumentConflict)


def test_conflict_check_skips_absent_arguments_without_stopping() -> None:
    # `--absent` is a conflicting argument that was not given, so the loop must
    # `continue` past it; a `break` would stop before `--a` and hide its
    # conflict with `--b`.
    cmd = (
        Command("prog")
        .arg(Arg("absent").long("absent").action("set_true").conflicts_with("b"))
        .arg(Arg("a").long("a").action("set_true").conflicts_with("b"))
        .arg(Arg("b").long("b").action("set_true"))
    )
    assert isinstance(err(cmd, "--a", "--b").kind, ArgumentConflict)


def test_requires() -> None:
    cmd = (
        Command("prog")
        .arg(Arg("user").long("user").requires("password"))
        .arg(Arg("password").long("password"))
    )
    assert "--password <PASSWORD>" in err(cmd, "--user", "u").message
    assert ok(cmd, "--user", "u", "--password", "p").get_one("user", str) == "u"
    # Absent, a requiring argument does not demand its dependency.
    assert ok(cmd).get_one("user", str) is None


def test_requires_accepts_a_user_written_default() -> None:
    cmd = (
        Command("p")
        .arg(Arg("x").long("x").action("set_true").requires("y"))
        .arg(Arg("y").long("y").default_value("d"))
    )
    assert ok(cmd, "--x").get_one("y", str) == "d"


def test_exclusive_can_require_a_defaulted_argument() -> None:
    cmd = (
        Command("p")
        .arg(Arg("x").long("x").action("set_true").exclusive(True).requires("y"))
        .arg(Arg("y").long("y").default_value("d"))
    )
    assert ok(cmd, "--x").get_one("y", str) == "d"


def test_requires_and_conflicts_are_allowed_when_the_target_is_defaulted() -> None:
    cmd = (
        Command("p")
        .arg(Arg("x").long("x").action("set_true").requires("y").conflicts_with("y"))
        .arg(Arg("y").long("y").default_value("d"))
    )
    assert ok(cmd, "--x").get_one("y", str) == "d"


def test_requires_may_target_an_exclusive_value_with_a_default() -> None:
    cmd = (
        Command("p")
        .arg(Arg("x").long("x").action("set_true").requires("y"))
        .arg(Arg("y").long("y").exclusive(True).default_value("d"))
    )
    assert ok(cmd, "--x").get_one("y", str) == "d"


def test_requires_lists_every_dependency_from_every_requiring_argument() -> None:
    # `--absent` comes first and is not given, so the loop must `continue` past
    # it, not `break`: a break would hide the two present arguments' missing
    # dependencies and the parse would wrongly succeed.
    cmd = (
        Command("prog")
        .arg(Arg("absent").long("absent").requires("password"))
        .arg(Arg("user").long("user").requires("password"))
        .arg(Arg("host").long("host").requires("port"))
        .arg(Arg("password").long("password"))
        .arg(Arg("port").long("port"))
    )
    error = err(cmd, "--user", "u", "--host", "h")
    assert isinstance(error.kind, MissingRequiredArgument)
    assert error.kind.arguments == ("--password <PASSWORD>", "--port <PORT>")


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


def test_an_exclusive_required_argument_can_satisfy_its_own_required_group() -> None:
    cmd = (
        Command("p")
        .arg(Arg("e").long("e").action("set_true").exclusive(True).required(True))
        .arg(Arg("x").long("x"))
        .group(ArgGroup("g").args(["e", "x"]).required(True))
    )
    assert ok(cmd, "--e").get_flag("e")


def test_an_exclusive_required_argument_may_coexist_with_a_defaulted_group() -> None:
    cmd = (
        Command("p")
        .arg(Arg("e").long("e").action("set_true").exclusive(True).required(True))
        .arg(Arg("m").long("m").default_value("d"))
        .arg(Arg("n").long("n"))
        .group(ArgGroup("g").args(["m", "n"]).required(True))
    )
    assert ok(cmd, "--e").get_one("m", str) == "d"


def test_a_required_group_accepts_a_user_written_default() -> None:
    cmd = (
        Command("p")
        .arg(Arg("a").long("a").default_value("x"))
        .arg(Arg("b").long("b"))
        .group(ArgGroup("g").args(["a", "b"]).required(True))
    )
    assert ok(cmd).get_one("a", str) == "x"


def test_a_required_group_does_not_count_a_flags_implicit_default() -> None:
    cmd = (
        Command("p")
        .arg(Arg("a").long("a").action("set_true"))
        .arg(Arg("b").long("b"))
        .group(ArgGroup("g").args(["a", "b"]).required(True))
    )
    assert isinstance(err(cmd).kind, MissingRequiredArgument)


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


def test_hidden_commands_arguments_and_aliases_do_not_leak_into_tips() -> None:
    cmd = (
        Command("p")
        .subcommand(Command("visible"))
        .subcommand(Command("internal").hide(True).arg(Arg("secret").long("secret").short("s")))
    )
    for typed in ("--secret", "-s"):
        error = err(cmd, typed)
        assert error.tip == f"to pass '{typed}' as a value, use '-- {typed}'"

    hidden_arg = Command("p").subcommand(
        Command("sub")
        .arg(Arg("hidden").long("hidden").short("H").hide(True))
        .arg(Arg("alias").long("alias").alias("hidden-alias").short_alias("Z"))
    )
    for typed in ("--hidden", "-H", "--hidden-alias", "-Z"):
        error = err(hidden_arg, typed)
        assert error.tip == f"to pass '{typed}' as a value, use '-- {typed}'"

    hidden_subtree = Command("p").subcommand(
        Command("internal")
        .hide(True)
        .subcommand(Command("child").arg(Arg("secret").long("secret")))
    )
    error = err(hidden_subtree, "--secret", "x")
    assert error.tip == "to pass '--secret' as a value, use '-- --secret'"

    hidden_ancestor = Command("p").subcommand(
        Command("internal")
        .hide(True)
        .arg(Arg("secret").long("secret"))
        .subcommand(Command("child"))
    )
    error = err(hidden_ancestor, "internal", "child", "--secret", "x")
    assert error.tip == "to pass '--secret' as a value, use '-- --secret'"


def test_missing_subcommand_lists_only_visible_commands() -> None:
    cmd = (
        Command("p")
        .subcommand_required(True)
        .subcommand(Command("visible"))
        .subcommand(Command("hidden").hide(True))
    )
    error = err(cmd)
    assert isinstance(error.kind, MissingSubcommand)
    assert error.kind.subcommands == ("visible", "help")
    assert "hidden" not in error.message


def test_missing_subcommand_can_have_no_visible_names() -> None:
    cmd = (
        Command("p")
        .subcommand_required(True)
        .disable_help_subcommand(True)
        .subcommand(Command("hidden").hide(True))
    )
    error = err(cmd)
    assert error.kind == MissingSubcommand("p", ())
    assert "subcommands:" not in error.message
    assert "<COMMAND>" in error.render()


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
        .arg(Arg("secret").long("secret").hide(True)),
    )
    .subcommand(Command("fetch").arg(Arg("all").long("all").action("set_true")))
    .subcommand(
        Command("remote")
        .subcommand(Command("add").arg(Arg("all").long("all").action("set_true")))
        .subcommand(Command("prune").arg(Arg("dry").long("dry-run").action("set_true"))),
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
        .subcommand(Command("prune")),
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
    argv: list[str],
    env: dict[str, str],
    kind: ErrorKind,
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


def test_args_and_subcommands_add_every_member() -> None:
    cmd = (
        Command("prog")
        .args([Arg("a").long("a"), Arg("b").long("b")])
        .subcommands([Command("one"), Command("two")])
    )
    assert ok(cmd, "--a", "x", "two").subcommand_name() == "two"
