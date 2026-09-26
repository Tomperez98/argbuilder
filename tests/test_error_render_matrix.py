"""`Error.render` as a structural matrix: every combination of its parts.

`test_output.py` checks a couple of the shapes and the goldens pin the real
messages. This file pins the *format* independently of any one error message:
one line per present block, in a fixed order (`tip`, `usage`, `help_hint`), and
the three `Display*` kinds that bypass that layout entirely. A change to the
separator, the order, or the restyle rule fails here rather than silently
rewriting every golden.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from argbuilder import (
    DisplayHelp,
    DisplayHelpOnMissingArgumentOrSubcommand,
    DisplayVersion,
    Error,
    Style,
    UnknownArgument,
    ValueValidation,
)

if TYPE_CHECKING:
    from argbuilder import ErrorKind

DisplayKind = DisplayHelp | DisplayVersion | DisplayHelpOnMissingArgumentOrSubcommand

# Every subset of the optional blocks, in the order they are emitted. `None`
# means "absent" and is omitted from the constructed Error.
BLOCK_CASES: list[tuple[str, str | None, str | None, str | None, str]] = [
    ("none", None, None, None, "error: boom\n"),
    ("tip", "try harder", None, None, "error: boom\n\n  tip: try harder\n"),
    ("usage", None, "p [OPTIONS]", None, "error: boom\n\nUsage: p [OPTIONS]\n"),
    ("hint", None, None, "'--help'", "error: boom\n\nFor more information, try '--help'.\n"),
    ("tip+usage", "t", "u", None, "error: boom\n\n  tip: t\n\nUsage: u\n"),
    (
        "tip+hint",
        "t",
        None,
        "h",
        "error: boom\n\n  tip: t\n\nFor more information, try h.\n",
    ),
    (
        "usage+hint",
        None,
        "u",
        "h",
        "error: boom\n\nUsage: u\n\nFor more information, try h.\n",
    ),
    (
        "all",
        "t",
        "u",
        "h",
        "error: boom\n\n  tip: t\n\nUsage: u\n\nFor more information, try h.\n",
    ),
]


@pytest.mark.parametrize(
    ("tip", "usage", "help_hint", "expected"),
    [(tip, usage, hint, expected) for _, tip, usage, hint, expected in BLOCK_CASES],
    ids=[name for name, *_ in BLOCK_CASES],
)
def test_render_lays_out_one_block_per_present_part(
    tip: str | None, usage: str | None, help_hint: str | None, expected: str
) -> None:
    error = Error(ValueValidation(), "boom", tip, usage, help_hint)
    assert error.render() == expected


def test_a_styled_render_only_wraps_the_lead_labels() -> None:
    error = Error(ValueValidation(), "boom", "t", "u", "h")
    styled = error.render(Style(color=True))
    assert styled == (
        "\x1b[1m\x1b[31merror:\x1b[0m boom\n"
        "\n"
        "  \x1b[32mtip:\x1b[0m t\n"
        "\n"
        "\x1b[1m\x1b[4mUsage:\x1b[0m u\n"
        "\n"
        "For more information, try h.\n"
    )


def test_only_parse_failures_are_laid_out_as_errors() -> None:
    # A Display* kind bypasses the `error:`/`tip:`/`Usage:` layout even when
    # those fields are set; the others always use it.
    assert Error(DisplayHelp(), "BODY", tip="t", usage="u", help_hint="h").render() == "BODY"
    assert (
        Error(ValueValidation(), "BODY", tip="t", usage="u", help_hint="h").render()
        == "error: BODY\n\n  tip: t\n\nUsage: u\n\nFor more information, try h.\n"
    )


@pytest.mark.parametrize(
    "kind",
    [DisplayHelp(), DisplayVersion(), DisplayHelpOnMissingArgumentOrSubcommand()],
    ids=["help", "version", "help-on-missing"],
)
def test_display_kinds_render_the_message_verbatim(kind: DisplayKind) -> None:
    error = Error(kind, "BODY")
    assert error.render() == "BODY"
    assert error.render(Style(color=True, width=50)) == "BODY"


@pytest.mark.parametrize(
    "kind",
    [DisplayHelp(), DisplayVersion(), DisplayHelpOnMissingArgumentOrSubcommand()],
    ids=["help", "version", "help-on-missing"],
)
def test_display_kinds_restyle_when_asked(kind: DisplayKind) -> None:
    seen: list[Style] = []

    def restyle(style: Style) -> str:
        seen.append(style)
        return "RESTYLED"

    error = Error(kind, "BODY", restyle=restyle)
    assert error.render(Style(color=True, width=50)) == "RESTYLED"
    assert error.render() == "RESTYLED"  # the plain style goes through restyle too
    assert seen[-1] == Style()


def test_parse_failures_ignore_restyle() -> None:
    # `restyle` is only meaningful for help, which can wrap and color.
    error = Error(UnknownArgument("--x"), "unexpected '--x' found", restyle=lambda _: "ignored")
    assert (
        error.render(Style(color=True)) == "\x1b[1m\x1b[31merror:\x1b[0m unexpected '--x' found\n"
    )


@pytest.mark.parametrize(
    ("kind", "code", "stderr"),
    [
        (DisplayHelp(), 0, False),
        (DisplayVersion(), 0, False),
        (DisplayHelpOnMissingArgumentOrSubcommand(), 2, True),
        (ValueValidation(), 2, True),
        (UnknownArgument("--x"), 2, True),
    ],
    ids=["help", "version", "help-on-missing", "validation", "unknown"],
)
def test_exit_contract_for_every_kind(kind: ErrorKind, code: int, stderr: bool) -> None:
    error = Error(kind, "BODY")
    assert (error.exit_code, error.use_stderr) == (code, stderr)


def test_render_is_a_pure_function() -> None:
    def make() -> Error:
        return Error(ValueValidation(), "boom", "t", "u", "h")

    assert make().render() == make().render()
    assert make().render(Style(color=True)) == make().render(Style(color=True))
