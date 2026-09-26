"""Terminal styling: wrap width and color, chosen at the edge, rendered purely."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from argbuilder import (
    Arg,
    Command,
    DisplayHelp,
    DisplayHelpOnMissingArgumentOrSubcommand,
    Error,
    ErrorKind,
    Style,
)
from argbuilder._style import MAX_WIDTH, MIN_WIDTH, style_for, terminal_style

if TYPE_CHECKING:
    from collections.abc import Callable

CMD = (
    Command("tool")
    .about("Does things with files, carefully and at length")
    .arg(Arg("input").required(True).help("The file to read, which must already exist"))
    .arg(
        Arg("level")
        .short("l")
        .long("level")
        .value_parser(["low", "high"])
        .default_value("low")
        .help("How hard to try")
    )
    .arg(Arg("quiet").short("q").action("set_true"))
)


def test_plain_is_the_default() -> None:
    assert CMD.render_help() == CMD.render_help(Style())
    assert "\x1b[" not in CMD.render_help()


def test_help_wraps_beside_the_labels(golden: Callable[[str, str], None]) -> None:
    golden("help_tool_wrapped_width50", CMD.render_help(Style(width=50)))


def test_help_moves_below_the_labels_when_too_narrow(
    golden: Callable[[str, str], None],
) -> None:
    golden("help_tool_narrow", CMD.render_help(Style(width=MIN_WIDTH)))


def test_color_does_not_shift_columns() -> None:
    colored = CMD.render_help(Style(color=True, width=50))
    assert "\x1b[1m\x1b[4mOptions:\x1b[0m" in colored
    assert "  \x1b[1m-h, --help\x1b[0m           Print help\n" in colored
    assert _strip_ansi(colored) == CMD.render_help(Style(width=50))


def test_error_colors() -> None:
    error = CMD.try_get_matches_from(["tool", "in", "--levl", "x"])
    assert isinstance(error, Error)
    colored = error.render(Style(color=True))
    assert colored.startswith("\x1b[1m\x1b[31merror:\x1b[0m unexpected argument '--levl' found")
    assert "  \x1b[32mtip:\x1b[0m a similar argument exists" in colored
    assert "\x1b[1m\x1b[4mUsage:\x1b[0m tool [OPTIONS] <INPUT>" in colored
    assert _strip_ansi(colored) == error.render()


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        (["--help"], DisplayHelp()),
        ([], DisplayHelpOnMissingArgumentOrSubcommand()),
    ],
)
def test_help_errors_restyle(argv: list[str], kind: ErrorKind) -> None:
    cmd = CMD.arg_required_else_help(True)
    error = cmd.try_get_matches_from(["tool", *argv])
    assert isinstance(error, Error) and error.kind == kind
    assert error.message == cmd.render_help()
    style = Style(color=True, width=40)
    assert error.render(style) == cmd.render_help(style)


def test_exit_styles_for_the_stream(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COLUMNS", raising=False)
    with pytest.raises(SystemExit):
        CMD.get_matches_from(["tool", "--help"])
    # Captured output is not a terminal: no color, but wrapped to the default width.
    assert capsys.readouterr().out == CMD.render_help(Style(width=MAX_WIDTH))


@pytest.mark.parametrize(
    ("is_tty", "columns", "env", "expected"),
    [
        (True, 80, {}, Style(color=True, width=80)),
        (False, None, {}, Style(color=False, width=MAX_WIDTH)),
        (True, 80, {"NO_COLOR": "1"}, Style(color=False, width=80)),
        (True, 80, {"NO_COLOR": ""}, Style(color=True, width=80)),
        (True, 80, {"TERM": "dumb"}, Style(color=False, width=80)),
        (True, 80, {"COLUMNS": "60"}, Style(color=True, width=60)),
        (True, 80, {"COLUMNS": "wide"}, Style(color=True, width=80)),
        (True, 300, {}, Style(color=True, width=MAX_WIDTH)),
        (True, 5, {}, Style(color=True, width=MIN_WIDTH)),
        (True, 1, {}, Style(color=True, width=MIN_WIDTH)),
        (True, 0, {}, Style(color=True, width=MAX_WIDTH)),
        (True, None, {"COLUMNS": "1"}, Style(color=True, width=MIN_WIDTH)),
        (True, None, {"COLUMNS": "0"}, Style(color=True, width=MAX_WIDTH)),
    ],
)
def test_style_for(is_tty: bool, columns: int | None, env: dict[str, str], expected: Style) -> None:
    assert style_for(is_tty=is_tty, columns=columns, env=env) == expected


@pytest.mark.parametrize(
    "make",
    [
        lambda: Style(width=MIN_WIDTH - 1),
        lambda: Style(width=True),
        lambda: Style(color="yes"),  # ty: ignore[invalid-argument-type]
        lambda: CMD.render_help(80),  # ty: ignore[invalid-argument-type]
    ],
)
def test_style_misuse_panics(make: object) -> None:
    with pytest.raises(AssertionError):
        make()  # ty: ignore[call-non-callable]


def _strip_ansi(text: str) -> str:
    for code in ("\x1b[1m", "\x1b[4m", "\x1b[31m", "\x1b[32m", "\x1b[0m"):
        text = text.replace(code, "")
    return text


class _TtyStream:
    """A stream that claims to be a terminal but has no size behind it."""

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 0


def test_terminal_style_survives_an_unqueryable_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_size(fd: int) -> object:
        raise OSError

    monkeypatch.setattr("argbuilder._style.os.get_terminal_size", no_size)
    style = terminal_style(_TtyStream())  # ty: ignore[invalid-argument-type]
    assert style == style_for(is_tty=True, columns=None, env=os.environ)
