"""How output is dressed for a terminal: wrap width and ANSI color.

Rendering takes a `Style` as a plain parameter and stays pure. Only
`terminal_style()` looks at the process, and only `Error.exit()` calls it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

from argbuilder._invariant import invariant

if TYPE_CHECKING:
    from collections.abc import Mapping

MIN_WIDTH = 20
"""Narrowest wrap width. Anything smaller cannot fit a flag and its help."""
MAX_WIDTH = 100
"""Widest wrap width. Longer lines are hard to read, even on a wide terminal."""

_BOLD = "\x1b[1m"
_UNDERLINE = "\x1b[4m"
_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_RESET = "\x1b[0m"


@dataclass(frozen=True, slots=True)
class Style:
    """Color and wrap width for rendered output.

    `Style()` is plain: no color, no wrapping. Rendering uses it unless told
    otherwise, so output in tests is stable. `get_matches()` picks a style
    from the terminal it prints to.
    """

    color: bool = False
    width: int | None = None
    """Wrap help text to this many columns; None leaves lines as they are."""

    def __post_init__(self) -> None:
        invariant(
            isinstance(self.color, bool),
            f"Style color must be a bool, got {self.color!r}",
        )
        invariant(
            self.width is None
            or (
                isinstance(self.width, int)
                and not isinstance(self.width, bool)
                and self.width >= MIN_WIDTH
            ),
            f"Style width must be None or an int >= {MIN_WIDTH}, got {self.width!r}",
        )

    def header(self, text: str) -> str:
        """Section titles: `Usage:`, `Options:`."""
        return self._paint(text, _BOLD + _UNDERLINE)

    def literal(self, text: str) -> str:
        """Things the user types: flags and subcommand names."""
        return self._paint(text, _BOLD)

    def error(self, text: str) -> str:
        return self._paint(text, _BOLD + _RED)

    def tip(self, text: str) -> str:
        return self._paint(text, _GREEN)

    def _paint(self, text: str, codes: str) -> str:
        return f"{codes}{text}{_RESET}" if self.color else text


PLAIN = Style()


def style_for(*, is_tty: bool, columns: int | None, env: Mapping[str, str]) -> Style:
    """Choose a style from facts about the output stream. Pure, so it can be tested.

    Color only on a terminal, and never when `NO_COLOR` is set (no-color.org)
    or `TERM=dumb`. Width comes from `COLUMNS`, then the terminal size, then
    `MAX_WIDTH`, and is kept within `MIN_WIDTH..=MAX_WIDTH`.
    """
    color = is_tty and env.get("NO_COLOR", "") == "" and env.get("TERM") != "dumb"
    override = env.get("COLUMNS", "")
    if override.isdecimal() and int(override) > 0:
        columns = int(override)
    width = MAX_WIDTH if columns is None or columns <= 0 else columns
    return Style(color=color, width=max(MIN_WIDTH, min(width, MAX_WIDTH)))


def terminal_style(stream: TextIO) -> Style:
    """The style for printing to `stream`. Reads the process: call it only at the edge."""
    is_tty = stream.isatty()
    columns = None
    if is_tty:
        try:
            columns = os.get_terminal_size(stream.fileno()).columns
        except (OSError, ValueError):
            columns = None  # a tty-like stream without a real terminal behind it
    return style_for(is_tty=is_tty, columns=columns, env=os.environ)
