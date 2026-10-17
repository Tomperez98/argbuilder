"""The standard `completion <SHELL>` command."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest

from argbuilder import (
    ArgMatches,
    Command,
    DisplayHelp,
    Error,
    InvalidValue,
    MissingRequiredArgument,
)

if TYPE_CHECKING:
    from pathlib import Path

SHELLS = ("bash", "zsh", "fish", "powershell")


def cli() -> Command:
    return Command("p").about("A tool").completion_subcommand(True)


def test_completion_command_is_visible_in_help_and_markdown() -> None:
    cmd = cli()
    help_text = cmd.render_help()
    assert "completion" in help_text
    assert "Generate a shell completion script" in help_text
    markdown = cmd.render_markdown()
    assert "## `p completion`" in markdown
    assert "Generate a shell completion script" in markdown


def test_completion_command_is_opt_in() -> None:
    cmd = Command("p")
    assert "completion" not in cmd.render_help()
    assert "completion" not in cmd._resolved().subcommands  # noqa: SLF001


def test_completion_subcommand_is_idempotent() -> None:
    cmd = Command("p").completion_subcommand(True).completion_subcommand(True)
    names = list(cmd._resolved().subcommands)  # noqa: SLF001
    assert names.count("completion") == 1


def test_completion_subcommand_can_be_turned_off() -> None:
    cmd = Command("p").completion_subcommand(True).completion_subcommand(False)
    assert "completion" not in cmd._resolved().subcommands  # noqa: SLF001


@pytest.mark.parametrize("value", [1, "yes", None])
def test_completion_subcommand_requires_a_bool(value: object) -> None:
    with pytest.raises(AssertionError, match=r"completion_subcommand\(\) takes a bool"):
        Command("p").completion_subcommand(cast("bool", value))


def test_nested_completion_subcommand_is_rejected() -> None:
    cmd = Command("p").subcommand(Command("sub").completion_subcommand(True))
    with pytest.raises(AssertionError, match="only applies to the root command"):
        cmd.debug_assert()


@pytest.mark.parametrize("names", [("completion",), ("other", "completion")])
def test_completion_name_collision_is_rejected(names: tuple[str, ...]) -> None:
    sub = Command(names[0])
    if len(names) > 1:
        sub = sub.alias(names[1])
    cmd = Command("p").completion_subcommand(True).subcommand(sub)
    with pytest.raises(AssertionError, match="subcommand name 'completion' is already used"):
        cmd.debug_assert()


@pytest.mark.parametrize("shell", SHELLS)
def test_each_shell_parses(shell: str) -> None:
    matches = cli().try_get_matches_from(["p", "completion", shell])
    assert isinstance(matches, ArgMatches)
    assert matches.subcommand_name() == "completion"
    sub = matches.subcommand_matches("completion")
    assert sub is not None
    assert sub.get_required("shell", str) == shell


def test_missing_shell_is_a_normal_parse_error() -> None:
    error = cli().try_get_matches_from(["p", "completion"])
    assert isinstance(error, Error)
    assert isinstance(error.kind, MissingRequiredArgument)
    assert error.exit_code == 2
    assert "p completion [OPTIONS] <SHELL>" in error.render()


def test_invalid_shell_lists_choices_and_suggests() -> None:
    error = cli().try_get_matches_from(["p", "completion", "bas"])
    assert isinstance(error, Error)
    assert isinstance(error.kind, InvalidValue)
    assert error.kind.possible_values == SHELLS
    assert error.kind.suggestion == "bash"
    rendered = error.render()
    assert "possible values: bash, zsh, fish, powershell" in rendered
    assert "a similar value exists: 'bash'" in rendered


def test_pure_parsing_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert isinstance(
        cli().try_get_matches_from(["p", "completion", "bash"]),
        ArgMatches,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_completion_help() -> None:
    error = cli().try_get_matches_from(["p", "completion", "--help"])
    assert isinstance(error, Error)
    assert isinstance(error.kind, DisplayHelp)
    assert error.exit_code == 0
    assert "Generate a shell completion script" in error.render()

    via_help = cli().try_get_matches_from(["p", "help", "completion"])
    assert isinstance(via_help, Error)
    assert isinstance(via_help.kind, DisplayHelp)
    assert via_help.render() == error.render()


def test_get_matches_from_prints_the_script_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd = cli()
    with pytest.raises(SystemExit) as exited:
        cmd.get_matches_from(["p", "completion", "bash"])
    assert exited.value.code == 0
    assert capsys.readouterr().out == cmd.render_completion("bash")


def test_get_matches_prints_the_script_and_exits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd = cli()
    monkeypatch.setattr(sys, "argv", ["p", "completion", "fish"])
    with pytest.raises(SystemExit) as exited:
        cmd.get_matches()
    assert exited.value.code == 0
    assert capsys.readouterr().out == cmd.render_completion("fish")


def test_get_matches_exits_2_for_bad_shell(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["p", "completion"])
    with pytest.raises(SystemExit) as exited:
        cli().get_matches()
    assert exited.value.code == 2
    assert "required arguments were not provided" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["p", "completion", "tcsh"])
    with pytest.raises(SystemExit) as exited:
        cli().get_matches()
    assert exited.value.code == 2
    assert "invalid value 'tcsh'" in capsys.readouterr().err


def test_get_matches_still_returns_for_other_subcommands() -> None:
    cmd = Command("p").completion_subcommand(True).subcommand(Command("other"))
    matches = cmd.get_matches_from(["p", "other"])
    assert matches.subcommand_name() == "other"


def test_get_matches_still_returns_without_a_subcommand() -> None:
    assert cli().get_matches_from(["p"]).subcommand_name() is None


def test_completion_engine_offers_the_command_and_shells() -> None:
    cmd = cli()
    root = {candidate.value for candidate in cmd.complete(["p", ""]).candidates}
    assert "completion" in root
    after = {candidate.value for candidate in cmd.complete(["p", "completion", ""]).candidates}
    assert set(SHELLS) <= after
    assert tuple(
        candidate.value for candidate in cmd.complete(["p", "completion", "z"]).candidates
    ) == ("zsh",)


def test_the_command_prints_the_public_script_through_an_executable(tmp_path: Path) -> None:
    launcher = tmp_path / "p"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "from argbuilder import Command\n"
        "Command('p').completion_subcommand(True).get_matches()\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    result = subprocess.run(
        [str(launcher), "completion", "bash"],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == Command("p").completion_subcommand(True).render_completion("bash")
