"""Help, version and error rendering, plus the process edge."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from argbuilder import (
    Arg,
    ArgMatches,
    Command,
    DisplayHelp,
    DisplayHelpOnMissingArgumentOrSubcommand,
    DisplayVersion,
    Error,
    ErrorKind,
    UnknownArgument,
    ValueValidation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CMD = (
    Command("tool")
    .about("Does things")
    .version("1.2.3")
    .arg(Arg("input").required(True).help("Input file"))
    .arg(Arg("extra").action("append"))
    .arg(Arg("level").short("l").long("level").value_parser(["low", "high"]).default_value("low"))
    .arg(Arg("verbose").short("v").action("count").help("Be loud"))
    .arg(Arg("secret").long("secret").hide(True))
    .arg(Arg("token").long("token").env("TOKEN"))
)


def test_help_layout(golden: Callable[[str, str], None]) -> None:
    golden("help_tool", CMD.render_help())


GIT = (
    Command("git")
    .arg(Arg("verbose").short("v").action("count").global_(True).help("Be loud"))
    .arg(Arg("color").long("color").visible_alias("colour").alias("kolor"))
    .subcommand(
        Command("add")
        .about("Adds things")
        .visible_alias("stage")
        .alias("a")
        .arg(Arg("force").short("f").visible_short_alias("F").action("set_true"))
    )
    .subcommand(Command("rm").alias("remove"))
)


def test_help_lists_visible_aliases_and_the_help_subcommand(
    golden: Callable[[str, str], None],
) -> None:
    golden("help_git", GIT.render_help())


def test_subcommand_help_lists_inherited_globals(
    golden: Callable[[str, str], None],
) -> None:
    result = GIT.try_get_matches_from(["git", "help", "add"])
    assert isinstance(result, Error)
    golden("help_git_add", result.render())


@pytest.mark.parametrize(
    ("args", "kind", "code", "stderr"),
    [
        (["--help"], DisplayHelp(), 0, False),
        (["-V"], DisplayVersion(), 0, False),
        (["--nope"], UnknownArgument("--nope", suggestion="--token"), 2, True),
    ],
)
def test_exit_contract(args: list[str], kind: ErrorKind, code: int, stderr: bool) -> None:
    result = CMD.try_get_matches_from(["tool", *args])
    assert isinstance(result, Error)
    assert (result.kind, result.exit_code, result.use_stderr) == (kind, code, stderr)


def test_help_wins_over_missing_required() -> None:
    result = CMD.try_get_matches_from(["tool", "-h"])
    assert isinstance(result, Error)
    assert result.render() == CMD.render_help()


def test_version_output() -> None:
    assert CMD.render_version() == "tool 1.2.3\n"


def test_error_layout(golden: Callable[[str, str], None]) -> None:
    result = CMD.try_get_matches_from(["tool", "in", "--levl", "x"])
    assert isinstance(result, Error)
    golden("error_unknown_argument", result.render())


def test_arg_required_else_help() -> None:
    cmd = Command("tool").arg_required_else_help(True).arg(Arg("x"))
    result = cmd.try_get_matches_from(["tool"])
    assert isinstance(result, Error)
    assert result.kind == DisplayHelpOnMissingArgumentOrSubcommand()
    assert (result.exit_code, result.use_stderr, result.render()) == (
        2,
        True,
        cmd.render_help(),
    )


def test_disabled_help_drops_the_hint() -> None:
    cmd = Command("tool").disable_help_flag(True)
    result = cmd.try_get_matches_from(["tool", "--help"])
    assert isinstance(result, Error)
    assert result.help_hint is None
    assert "For more information" not in result.render()


def test_user_error_uses_the_same_format() -> None:
    error = CMD.error(ValueValidation(), "input must not be empty")
    assert error.render().startswith("error: input must not be empty\n\nUsage: tool ")
    assert error.exit_code == 2


def test_matches_error_uses_the_subcommand_usage(golden: Callable[[str, str], None]) -> None:
    cli = Command("git").subcommand(Command("clone").arg(Arg("remote").required(True)))
    matches = cli.try_get_matches_from(["git", "clone", "x"])
    assert isinstance(matches, ArgMatches)
    sub = matches.subcommand_matches("clone")
    assert sub is not None
    error = sub.error(ValueValidation(), "remote must be a URL")
    assert error.exit_code == 2
    golden("error_subcommand_usage", error.render())


def test_get_matches_from_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        CMD.get_matches_from(["tool"])
    assert exited.value.code == 2
    assert "required arguments were not provided" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exited:
        CMD.get_matches_from(["tool", "--version"])
    assert exited.value.code == 0
    assert capsys.readouterr().out == "tool 1.2.3\n"


def test_get_matches_reads_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["tool", "in"])
    monkeypatch.setenv("TOKEN", "abc")
    assert CMD.get_matches().get_one("token", str) == "abc"


def test_render_usage() -> None:
    assert CMD.render_usage() == "Usage: tool [OPTIONS] <INPUT> [EXTRA]..."


def test_missing_subcommand_error_lists_subcommands(golden: Callable[[str, str], None]) -> None:
    cli = Command("git").subcommand(Command("add")).subcommand_required(True)
    result = cli.try_get_matches_from(["git"])
    assert isinstance(result, Error)
    golden("error_missing_subcommand", result.render())


def test_error_without_a_usage_or_help_hint() -> None:
    error = Error(ValueValidation(), "something went wrong")
    assert error.render() == "error: something went wrong\n"
