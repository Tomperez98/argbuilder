"""Markdown documentation, generated from a resolved command tree.

Reuses `_help.py`'s labels and detail strings verbatim, so `render_markdown`
can never quietly drift from `render_help`: a hidden arg stays hidden, an
inherited global repeats on every subcommand exactly as it does in
`--help`, and the auto `help` subcommand gets a section the same as any
other. One command is one section: the root gets a level-1 heading, and
every command below it gets a level-2 heading named by its full path
(`git remote add`), rather than nesting headings further — a real tree can
be deeper than Markdown has heading levels for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from argbuilder._build import descendants
from argbuilder._help import (
    arg_details,
    option_label,
    positional_label,
    render_usage,
    subcommand_details,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from argbuilder._build import ResolvedCommand


def render_markdown(cmd: ResolvedCommand) -> str:
    sections = [_section(cmd, top=True), *(_section(sub, top=False) for sub in descendants(cmd))]
    return "\n\n".join(sections) + "\n"


def _section(cmd: ResolvedCommand, *, top: bool) -> str:
    heading = "#" if top else "##"
    lines = [f"{heading} `{' '.join(cmd.path)}`"]
    if cmd.about:
        lines += ["", cmd.about]
    lines += ["", f"**Usage:** `{render_usage(cmd)}`"]

    if cmd.subcommands:
        rows = [(name, subcommand_details(sub)) for name, sub in cmd.subcommands.items()]
        lines += ["", "**Commands:**", "", *_bullets(rows)]

    visible = [arg for arg in cmd.args if not arg.hide]
    positionals = [
        (positional_label(arg), arg_details(arg)) for arg in visible if arg.is_positional
    ]
    if positionals:
        lines += ["", "**Arguments:**", "", *_bullets(positionals)]

    options = [(option_label(arg), arg_details(arg)) for arg in visible if not arg.is_positional]
    if options:
        lines += ["", "**Options:**", "", *_bullets(options)]

    return "\n".join(lines)


def _bullets(rows: Sequence[tuple[str, str]]) -> list[str]:
    # `option_label` left-pads a long-only flag with spaces to line up a plain-text
    # table column; that padding has no meaning inside a Markdown code span.
    lines = []
    for raw_label, detail in rows:
        label = raw_label.strip()
        lines.append(f"* `{label}` — {detail}" if detail else f"* `{label}`")
    return lines
