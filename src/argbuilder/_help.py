"""Pure rendering of help, usage, version and argument names, in clap's layout."""

import textwrap
from collections.abc import Sequence

from argbuilder._build import ResolvedArg, ResolvedCommand
from argbuilder._error import Error, ErrorKind
from argbuilder._invariant import invariant
from argbuilder._spec import takes_values
from argbuilder._style import PLAIN, Style

MIN_HELP_COLUMN = 20
"""Help text narrower than this moves below its flag instead of beside it."""
_NEXT_LINE_INDENT = 10


def value_hint(arg: ResolvedArg) -> str:
    name = f"<{arg.value_name}>"
    if arg.max_values == 1:
        return name if arg.min_values == 1 else f"[{name}]"
    if arg.min_values == arg.max_values:
        return " ".join([name] * arg.min_values)
    return f"{name}..." if arg.min_values >= 1 else f"[{name}]..."


def display_arg(arg: ResolvedArg) -> str:
    """How errors name an argument: `--port <PORT>`, `-v`, `<FILE>...`."""
    if arg.is_positional:
        return f"<{arg.value_name}>{'...' if arg.is_multiple else ''}"
    flag = f"--{arg.long}" if arg.long is not None else f"-{arg.short}"
    return f"{flag} {value_hint(arg)}" if takes_values(arg.action) else flag


def render_usage(cmd: ResolvedCommand) -> str:
    parts = [" ".join(cmd.path)]
    options = [arg for arg in cmd.args if not arg.is_positional and not arg.hide]
    if any(not arg.required for arg in options):
        parts.append("[OPTIONS]")
    parts.extend(display_arg(arg) for arg in options if arg.required)
    parts.extend(_positional_label(arg) for arg in cmd.positionals if not arg.hide)
    if cmd.subcommands:
        parts.append("<COMMAND>" if cmd.subcommand_required else "[COMMAND]")
    return " ".join(parts)


def usage_error(
    cmd: ResolvedCommand, kind: ErrorKind, message: str, tip: str | None = None
) -> Error:
    """An error that points at `cmd`'s usage and help flag."""
    return Error(kind, message, tip, render_usage(cmd), cmd.help_hint)


def render_help(cmd: ResolvedCommand, style: Style = PLAIN) -> str:
    lines: list[str] = []
    if cmd.about:
        lines += [*_wrap(cmd.about, style.width), ""]
    lines.append(f"{style.header('Usage:')} {render_usage(cmd)}")
    if cmd.subcommands:
        rows = [(name, _subcommand_details(sub)) for name, sub in cmd.subcommands.items()]
        lines += ["", style.header("Commands:"), *_table(rows, style)]
    visible = [arg for arg in cmd.args if not arg.hide]
    positionals = [(_positional_label(arg), _details(arg)) for arg in visible if arg.is_positional]
    if positionals:
        lines += ["", style.header("Arguments:"), *_table(positionals, style)]
    options = [(_option_label(arg), _details(arg)) for arg in visible if not arg.is_positional]
    if options:
        lines += ["", style.header("Options:"), *_table(options, style)]
    return "\n".join(lines) + "\n"


def render_version(cmd: ResolvedCommand) -> str:
    invariant(cmd.version is not None, f"{' '.join(cmd.path)!r} has no version to render")
    return f"{' '.join(cmd.path)} {cmd.version}\n"


def _positional_label(arg: ResolvedArg) -> str:
    base = f"<{arg.value_name}>" if arg.required else f"[{arg.value_name}]"
    return f"{base}{'...' if arg.is_multiple else ''}"


def _option_label(arg: ResolvedArg) -> str:
    if arg.short is not None and arg.long is not None:
        flag = f"-{arg.short}, --{arg.long}"
    elif arg.short is not None:
        flag = f"-{arg.short}"
    else:
        flag = f"    --{arg.long}"
    if takes_values(arg.action):
        return f"{flag} {value_hint(arg)}"
    return f"{flag}..." if arg.action == "count" else flag


def _details(arg: ResolvedArg) -> str:
    parts = [arg.help] if arg.help else []
    if arg.defaults_raw:
        parts.append(f"[default: {', '.join(arg.defaults_raw)}]")
    if arg.env is not None:
        parts.append(f"[env: {arg.env}]")
    if arg.visible_aliases:
        parts.append(f"[aliases: {', '.join(f'--{name}' for name in arg.visible_aliases)}]")
    if arg.visible_short_aliases:
        shorts = ", ".join(f"-{char}" for char in arg.visible_short_aliases)
        parts.append(f"[short aliases: {shorts}]")
    if arg.parser is not None and arg.parser.possible_values:
        parts.append(f"[possible values: {', '.join(arg.parser.possible_values)}]")
    return " ".join(parts)


def _subcommand_details(sub: ResolvedCommand) -> str:
    parts = [sub.about] if sub.about else []
    if sub.visible_aliases:
        parts.append(f"[aliases: {', '.join(sub.visible_aliases)}]")
    return " ".join(parts)


def _table(rows: Sequence[tuple[str, str]], style: Style) -> list[str]:
    """Two columns: labels, then help beside them, wrapped to fit `style.width`.

    Padding is measured on the plain label, then color is added, so escape
    codes never shift the columns.
    """
    label_width = max(len(label) for label, _ in rows)
    indent = 2 + label_width + 2
    beside = style.width is None or style.width - indent >= MIN_HELP_COLUMN
    lines: list[str] = []
    for label, detail in rows:
        head = f"  {style.literal(label)}"
        if not detail:
            lines.append(head)
        elif style.width is None:
            lines.append(f"{head}{' ' * (label_width - len(label))}  {detail}")
        elif beside:
            first, *rest = _wrap(detail, style.width - indent)
            lines.append(f"{head}{' ' * (label_width - len(label))}  {first}")
            lines.extend(" " * indent + piece for piece in rest)
        else:
            lines.append(head)
            wrapped = _wrap(detail, style.width - _NEXT_LINE_INDENT)
            lines.extend(" " * _NEXT_LINE_INDENT + piece for piece in wrapped)
    return lines


def _wrap(text: str, width: int | None) -> list[str]:
    """Wrap each line of `text` on spaces only, so `--flags` and paths stay whole."""
    if width is None:
        return [text]
    lines: list[str] = []
    for line in text.splitlines():
        pieces = textwrap.wrap(line, width, break_long_words=False, break_on_hyphens=False)
        lines.extend(pieces or [""])
    return lines
