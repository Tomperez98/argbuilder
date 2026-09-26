"""Invariants that must hold for every help layout.

Golden files pin one exact rendering; these tests pin the properties that
must hold at every width and for every command, so a wrap bug is caught even
at a width no golden covers. If a property here fails, the layout is wrong —
not just different.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from argbuilder import Arg, Command, Error, Style
from argbuilder._style import MAX_WIDTH, MIN_WIDTH

if TYPE_CHECKING:
    from collections.abc import Callable

WIDTHS = [MIN_WIDTH, 21, 30, 50, 79, MAX_WIDTH]
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def rich_command() -> Command:
    """Every feature that shows up in help: positionals, options, aliases, hidden."""
    return (
        Command("tool")
        .about("Does things with files, carefully and at length")
        .arg(Arg("input").required(True).help("The file to read"))
        .arg(Arg("extra").action("append").help("Extra values"))
        .arg(
            Arg("level")
            .short("l")
            .long("level")
            .value_parser(["low", "high"])
            .default_value("low")
            .help("How hard to try")
        )
        .arg(Arg("verbose").short("v").action("count").help("Be loud"))
        .arg(Arg("secret").long("secret").hide(True))
        .subcommand(
            Command("run").about("Runs it").arg(Arg("target").required(True).help("What to run"))
        )
        .subcommand(Command("clean").about("Cleans up").visible_alias("rm").alias("wipe"))
    )


def narrow_command() -> Command:
    """Only short labels, so every line except Usage must fit the wrap width."""
    return (
        Command("tool")
        .about("Short.")
        .arg(Arg("input").required(True).help("Input file"))
        .arg(Arg("out").long("out").help("Output file"))
        .arg(Arg("quiet").short("q").action("set_true"))
    )


BUILDERS: list[tuple[str, Callable[[], Command]]] = [
    ("rich", rich_command),
    ("narrow", narrow_command),
]


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[name for name, _ in BUILDERS])
def test_wrapping_only_changes_whitespace(
    name: str, build: Callable[[], Command], width: int
) -> None:
    # The token sequence is the content; wrapping may only move tokens
    # between lines, never lose, duplicate, or reorder them.
    wide = build().render_help().split()
    wrapped = build().render_help(Style(width=width)).split()
    assert wrapped == wide, f"{name} lost or reordered content at width {width}"


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[name for name, _ in BUILDERS])
def test_color_only_adds_escape_codes(name: str, build: Callable[[], Command], width: int) -> None:
    colored = build().render_help(Style(color=True, width=width))
    plain = build().render_help(Style(width=width))
    assert _ANSI.sub("", colored) == plain, f"{name} color shifted layout at width {width}"


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[name for name, _ in BUILDERS])
def test_help_has_no_trailing_whitespace_and_one_final_newline(
    name: str, build: Callable[[], Command], width: int
) -> None:
    rendered = build().render_help(Style(width=width))
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n"), f"{name} rendered a blank trailing line"
    assert all(line == line.rstrip() for line in rendered.splitlines()), f"{name} trailing spaces"


@pytest.mark.parametrize("width", WIDTHS)
def test_every_line_except_usage_fits_the_width(width: int) -> None:
    rendered = narrow_command().render_help(Style(width=width))
    for line in rendered.splitlines():
        if line.startswith("Usage:"):
            continue  # usage is deliberately kept on one line
        assert len(line) <= width, f"line {line!r} is wider than {width}"


def test_help_is_pure() -> None:
    assert rich_command().render_help() == rich_command().render_help()
    assert rich_command().render_help(Style(width=50)) == rich_command().render_help(
        Style(width=50)
    )


def test_hidden_arguments_never_appear() -> None:
    help_text = rich_command().render_help()
    assert "--secret" not in help_text
    assert "--level" in help_text
    assert "-v..." in help_text


def test_visible_aliases_appear_and_invisible_ones_do_not() -> None:
    help_text = rich_command().render_help()
    assert "rm" in help_text
    assert "wipe" not in help_text


@pytest.mark.parametrize(
    ("build", "has_options", "command_bracket"),
    [
        (narrow_command, True, None),  # -q and -h are optional options
        (lambda: Command("bare").disable_help_flag(True), False, None),
        (rich_command, True, "[COMMAND]"),  # subcommands exist, none required
    ],
    ids=["options", "bare", "subcommands"],
)
def test_usage_brackets_follow_the_command_shape(
    build: Callable[[], Command], has_options: bool, command_bracket: str | None
) -> None:
    usage = build().render_usage()
    assert ("[OPTIONS]" in usage) is has_options
    if command_bracket is None:
        assert "[COMMAND]" not in usage
        assert "<COMMAND>" not in usage
    else:
        assert command_bracket in usage


def test_usage_names_required_options_and_positionals_plainly() -> None:
    usage = rich_command().render_usage()
    assert "<INPUT>" in usage
    assert "[EXTRA]..." in usage
    assert "[COMMAND]" in usage


def test_error_usage_line_is_the_usage_renderer() -> None:
    result = narrow_command().try_get_matches_from(["tool"])
    assert isinstance(result, Error)
    assert result.usage is not None
    assert f"Usage: {result.usage}" == narrow_command().render_usage()


def test_subcommand_required_usage_uses_angle_brackets() -> None:
    cmd = Command("git").subcommand(Command("add")).subcommand_required(True)
    assert "<COMMAND>" in cmd.render_usage()
