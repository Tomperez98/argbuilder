"""Pure shell completion, and the scripts that call it.

Completion is split the same way parsing is:

- `complete()` walks the resolved command tree and returns data. It never
  reads the process, the environment or the file system.
- `render_completion()` writes a thin shell adapter. The adapter calls the
  program as `<name> __complete <cursor> <argv...>`, which `get_matches()`
  answers at the process edge.
- `write_completion()` is that edge. It is the only function here that writes
  to a stream.

Keeping the candidate logic in Python means the four shells share one
implementation and one set of tests. The shell scripts only translate their
native completion API to the `__complete` protocol.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from argbuilder._invariant import invariant
from argbuilder._spec import SHELLS, Shell, takes_values

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from typing import TextIO

    from argbuilder._build import ResolvedArg, ResolvedCommand

type CompletionKind = Literal["command", "option", "value"]
"""What a candidate is, for shells that display different kinds differently."""


@dataclass(frozen=True, slots=True)
class Completion:
    """One candidate. `help` is shown by shells that support descriptions."""

    value: str
    help: str | None = None
    kind: CompletionKind = "value"


@dataclass(frozen=True, slots=True)
class CompletionDirective:
    """How the shell should treat the candidates.

    The flags mirror the useful parts of clap's completion directives and
    Cobra's `ShellCompDirective`. They are plain booleans because this package
    deliberately does not use `enum` (see `ruff.toml`).
    """

    no_file: bool = False
    """Do not fall back to file completion, even when there are no candidates."""
    filter_dirs: bool = False
    """Complete directories only."""
    filter_files: bool = False
    """Complete files only."""


@dataclass(frozen=True, slots=True)
class CompletionResult:
    candidates: tuple[Completion, ...] = ()
    directive: CompletionDirective = CompletionDirective()


def complete(
    cmd: ResolvedCommand,
    argv: Iterable[str],
    cursor: int | None = None,
) -> CompletionResult:
    """Candidates for the word at `cursor` in `argv`.

    `argv` includes the binary name, like `sys.argv`. `cursor` is 0-based,
    like bash's `COMP_CWORD`; it defaults to the last word. Words after the
    cursor are ignored.
    """
    invariant(
        not isinstance(argv, str),
        "argv must be a list of str, not one str; split it first",
    )
    tokens = tuple(argv)
    invariant(len(tokens) >= 1, "argv must start with the binary name, like sys.argv")
    invariant(all(isinstance(token, str) for token in tokens), "argv must hold str")
    if cursor is None:
        cursor = len(tokens) - 1
    invariant(
        isinstance(cursor, int) and not isinstance(cursor, bool),
        f"cursor must be an int, got {cursor!r}",
    )
    invariant(0 <= cursor < len(tokens), f"cursor {cursor} is outside argv of {len(tokens)} words")
    if cursor == 0:
        return CompletionResult()
    state = _State(cmd)
    state.walk(tokens[1:cursor])
    return state.result(tokens[cursor])


def write_completion(
    cmd: ResolvedCommand,
    argv: Sequence[str],
    stream: TextIO,
) -> bool:
    """Answer a `__complete` request, if this is one. Returns whether it did.

    The protocol is line-oriented: one `C<TAB>value` or `C<TAB>value<TAB>help`
    line per candidate, then a final `D<TAB><bits>` line carrying the
    directive. Tabs and newlines in values and help are replaced with spaces;
    completion candidates are single-line strings by design.
    """
    request = _completion_request(cmd, argv)
    if request is None:
        return False
    cursor, words = request
    result = complete(cmd, words, cursor)
    stream.write(_format_result(result))
    stream.flush()
    return True


def render_completion(cmd: ResolvedCommand, shell: Shell) -> str:
    """Render the completion script for one shell."""
    invariant(
        shell in SHELLS,
        f"render_completion() takes one of {', '.join(SHELLS)}, got {shell!r}",
    )
    renderers: dict[Shell, Callable[[ResolvedCommand], str]] = {
        "bash": _bash,
        "zsh": _zsh,
        "fish": _fish,
        "powershell": _powershell,
    }
    return renderers[shell](cmd)


def _completion_request(
    cmd: ResolvedCommand,
    argv: Sequence[str],
) -> tuple[int, tuple[str, ...]] | None:
    """Parse `<name> __complete <cursor> <argv...>`, if that is what this is."""
    if len(argv) < 3 or argv[1] != "__complete":
        return None
    # A user-defined `__complete` subcommand wins; the protocol is a fallback,
    # not a reserved name that can never be used.
    if "__complete" in cmd.subcommand_names:
        return None
    try:
        cursor = int(argv[2], 10)
    except ValueError:
        return None
    words = tuple(argv[3:])
    if not 0 <= cursor < len(words):
        return None
    return cursor, words


def _format_result(result: CompletionResult) -> str:
    lines = [_protocol_line(candidate.value, candidate.help) for candidate in result.candidates]
    lines.append(f"D\t{_directive_bits(result.directive)}")
    return "\n".join(lines) + "\n"


def _protocol_line(value: str, help_text: str | None) -> str:
    value = _one_line(value)
    if help_text is None or help_text == "":
        return f"C\t{value}"
    return f"C\t{value}\t{_one_line(help_text)}"


def _one_line(text: str) -> str:
    return text.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _directive_bits(directive: CompletionDirective) -> int:
    bits = 0
    if directive.no_file:
        bits |= 1
    if directive.filter_dirs:
        bits |= 2
    if directive.filter_files:
        bits |= 4
    return bits


class _State:
    """Mutable completion state for one command level, discarded afterwards."""

    def __init__(self, cmd: ResolvedCommand) -> None:
        self.cmd = cmd
        self.positional_index = 0
        self.positional_count = 0
        self.escaped = False
        self.pending: ResolvedArg | None = None
        self.pending_count = 0
        self.help_parent: ResolvedCommand | None = None

    def walk(self, tokens: Sequence[str]) -> None:
        """Consume the words before the cursor, ignoring all validation."""
        for token in tokens:
            if self.pending is not None:
                if _value_like(token, self.pending):
                    self._consume_pending()
                    continue
                # The token looks like a flag. The real parser would reject a
                # missing option value, but completion should still offer the
                # flags the user can type next.
                self.pending = None
                self.pending_count = 0

            if self.escaped:
                self._consume_positional()
            elif token == "--":
                self.escaped = True
            elif token.startswith("--"):
                self._long(token)
            elif token.startswith("-") and token != "-":
                self._short(token)
            else:
                self._word(token)

    def _consume_pending(self) -> None:
        assert self.pending is not None
        self.pending_count += 1
        if self.pending.max_values is not None and self.pending_count >= self.pending.max_values:
            self.pending = None
            self.pending_count = 0

    def _long(self, token: str) -> None:
        name, has_value, inline = token[2:].partition("=")
        arg = self.cmd.by_long.get(name)
        if arg is None:
            return
        if not takes_values(arg.action):
            return
        self._start_pending(arg, 1 if has_value else 0)
        if has_value and inline != "" and self.pending is not None:
            self._consume_pending()

    def _short(self, token: str) -> None:
        cluster = token[1:]
        for offset, char in enumerate(cluster):
            arg = self.cmd.by_short.get(char)
            if arg is None:
                return
            if not takes_values(arg.action):
                continue
            rest = cluster[offset + 1 :]
            inline = rest.removeprefix("=") if rest else None
            self._start_pending(arg, 1 if inline is not None else 0)
            if inline not in (None, "") and self.pending is not None:
                self._consume_pending()
            return

    def _start_pending(self, arg: ResolvedArg, count: int) -> None:
        self.pending = arg
        self.pending_count = count
        if arg.max_values is not None and count >= arg.max_values:
            self.pending = None
            self.pending_count = 0

    def _word(self, token: str) -> None:
        if self.help_parent is not None and token in self.help_parent.subcommand_names:
            name = self.help_parent.subcommand_names[token]
            self._enter(self.help_parent.subcommands[name])
            self.help_parent = None
            return
        if token in self.cmd.subcommand_names:
            name = self.cmd.subcommand_names[token]
            if name == "help" and self.cmd.help_subcommand:
                self.help_parent = self.cmd
            self._enter(self.cmd.subcommands[name])
            return
        self._consume_positional()

    def _enter(self, cmd: ResolvedCommand) -> None:
        self.cmd = cmd
        self.positional_index = 0
        self.positional_count = 0
        self.escaped = False
        self.pending = None
        self.pending_count = 0

    def _consume_positional(self) -> None:
        arg = self._current_positional()
        if arg is None:
            return
        self.positional_count += 1
        if arg.max_values is not None and self.positional_count >= arg.max_values:
            self.positional_index += 1
            self.positional_count = 0

    def _current_positional(self) -> ResolvedArg | None:
        if self.positional_index >= len(self.cmd.positionals):
            return None
        arg = self.cmd.positionals[self.positional_index]
        if arg.last and not self.escaped:
            return None
        return arg

    def result(self, token: str) -> CompletionResult:
        """Candidates for the word currently being completed."""
        if self.escaped:
            return self._positional_result(token)
        if self.pending is not None and _can_be_value(token, self.pending):
            return _value_result(self.pending, token, prefix="")

        if token.startswith("--"):
            return self._long_result(token)
        if token.startswith("-"):
            return self._short_result(token)
        return self._word_result(token)

    def _long_result(self, token: str) -> CompletionResult:
        name, has_value, inline = token[2:].partition("=")
        arg = self.cmd.by_long.get(name)
        if has_value:
            if arg is None or not takes_values(arg.action):
                return CompletionResult(directive=CompletionDirective(no_file=True))
            return _value_result(arg, inline, prefix=f"--{name}=")

        candidates = [
            candidate
            for candidate in _option_candidates(self.cmd)
            if candidate.value.startswith(token)
        ]
        if arg is not None and takes_values(arg.action) and token == f"--{arg.long}":
            candidates = _without_duplicates(candidates)
        return CompletionResult(
            tuple(candidates),
            CompletionDirective(no_file=True),
        )

    def _short_result(self, token: str) -> CompletionResult:
        if "=" in token:
            name, _, inline = token[1:].partition("=")
            arg = self.cmd.by_short.get(name)
            if arg is None or not takes_values(arg.action):
                return CompletionResult(directive=CompletionDirective(no_file=True))
            return _value_result(arg, inline, prefix=f"-{name}=")

        candidates = [
            candidate
            for candidate in _option_candidates(self.cmd, short=True)
            if candidate.value.startswith(token)
        ]
        return CompletionResult(tuple(candidates), CompletionDirective(no_file=True))

    def _word_result(self, token: str) -> CompletionResult:
        candidates: list[Completion] = []
        directive = CompletionDirective()

        if self.help_parent is not None:
            candidates.extend(_subcommand_candidates(self.help_parent, token))
            return CompletionResult(
                tuple(candidates),
                CompletionDirective(no_file=True),
            )

        positional = self._current_positional()
        value_result = CompletionResult()
        if positional is not None and not token.startswith("-"):
            value_result = _value_result(positional, token, prefix="")
            # A path hint is best left to the shell: it knows about quoting,
            # directories, case sensitivity and the file system. Returning
            # option names here would suppress that fallback.
            if value_result.directive.filter_dirs or value_result.directive.filter_files:
                return value_result

        candidates.extend(_subcommand_candidates(self.cmd, token))
        candidates.extend(
            candidate
            for candidate in (
                *_option_candidates(self.cmd),
                *_option_candidates(self.cmd, short=True),
            )
            if candidate.value.startswith(token)
        )

        if value_result.candidates:
            candidates.extend(value_result.candidates)
            directive = value_result.directive
        elif not candidates:
            directive = value_result.directive

        if candidates and directive == CompletionDirective():
            directive = CompletionDirective(no_file=True)
        if token == "" and not candidates and positional is None:
            directive = CompletionDirective(no_file=bool(self.cmd.args))
        return CompletionResult(tuple(_without_duplicates(candidates)), directive)

    def _positional_result(self, token: str) -> CompletionResult:
        positional = self._current_positional()
        if positional is None:
            return CompletionResult()
        return _value_result(positional, token, prefix="")


def _subcommand_candidates(cmd: ResolvedCommand, prefix: str) -> list[Completion]:
    candidates: list[Completion] = []
    for sub in cmd.subcommands.values():
        if sub.hidden:
            continue
        candidates.extend(
            Completion(name, sub.about, "command")
            for name in (sub.name, *sub.visible_aliases)
            if name.startswith(prefix)
        )
    return candidates


def _option_candidates(
    cmd: ResolvedCommand,
    *,
    short: bool = False,
) -> list[Completion]:
    candidates: list[Completion] = []
    for arg in cmd.args:
        if arg.hide or arg.is_positional:
            continue
        if short:
            spellings = () if arg.short is None else (f"-{arg.short}",)
            spellings = (*spellings, *(f"-{char}" for char in arg.visible_short_aliases))
        else:
            spellings = () if arg.long is None else (f"--{arg.long}",)
            spellings = (*spellings, *(f"--{name}" for name in arg.visible_aliases))
        candidates.extend(Completion(name, arg.help, "option") for name in spellings)
    return candidates


def _value_result(arg: ResolvedArg, token: str, *, prefix: str) -> CompletionResult:
    parser = arg.parser
    choices = parser.possible_values if parser is not None else ()
    if choices:
        candidates = tuple(
            Completion(
                f"{prefix}{choice}" if prefix else choice,
                kind="value",
            )
            for choice in choices
            if choice.startswith(token)
        )
        if candidates:
            return CompletionResult(
                candidates,
                CompletionDirective(no_file=True),
            )
        return CompletionResult(directive=CompletionDirective(no_file=True))

    hint = arg.value_hint
    if hint == "dir":
        return CompletionResult(
            directive=CompletionDirective(no_file=bool(prefix), filter_dirs=True),
        )
    if hint in ("file", "any_path", "executable"):
        return CompletionResult(
            directive=CompletionDirective(no_file=bool(prefix), filter_files=True),
        )
    if prefix:
        return CompletionResult(directive=CompletionDirective(no_file=True))
    return CompletionResult()


def _without_duplicates(candidates: list[Completion]) -> list[Completion]:
    seen: set[str] = set()
    result: list[Completion] = []
    for candidate in candidates:
        if candidate.value in seen:
            continue
        seen.add(candidate.value)
        result.append(candidate)
    return result


def _value_like(token: str, arg: ResolvedArg) -> bool:
    return arg.allow_hyphen_values or token == "-" or not token.startswith("-")


def _can_be_value(token: str, arg: ResolvedArg) -> bool:
    if arg.allow_hyphen_values:
        return True
    return not token.startswith("-") or token == "-"


# -- shell scripts -----------------------------------------------------------


def _bash(cmd: ResolvedCommand) -> str:
    name = shlex.quote(cmd.name)
    function = _shell_name(cmd.name)
    return f"""\
# bash completion for {cmd.name}
_{function}() {{
    local line entry directive=0
    local -a candidates=()
    while IFS= read -r line; do
        case "$line" in
            D$'\\t'*) directive="${{line#D$'\\t'}}" ;;
            C$'\\t'*) entry="${{line#C$'\\t'}}"; candidates+=("${{entry%%$'\\t'*}}") ;;
        esac
    done < <(command {name} __complete "$COMP_CWORD" "${{COMP_WORDS[@]}}" 2>/dev/null)
    COMPREPLY=("${{candidates[@]}}")
    if type -t compopt >/dev/null 2>&1; then
        if (( directive & 1 )); then compopt +o default 2>/dev/null; else compopt -o default 2>/dev/null; fi
        if (( directive & 2 )); then compopt -o dirnames 2>/dev/null; fi
    fi
}}
if (( BASH_VERSINFO[0] < 4 )); then
    complete -o default -F _{function} {name}
else
    complete -F _{function} {name}
fi
"""


def _zsh(cmd: ResolvedCommand) -> str:
    name = shlex.quote(cmd.name)
    function = _shell_name(cmd.name)
    return f"""\
#compdef {cmd.name}
_{function}() {{
    local -a lines values descriptions
    local line entry directive=0
    lines=("${{(@f)$(command {name} __complete $((CURRENT - 1)) "${{words[@]}}" 2>/dev/null)}}")
    for line in "${{lines[@]}}"; do
        [[ -z "$line" ]] && continue
        if [[ "$line" == D$'\\t'* ]]; then
            directive="${{line#D$'\\t'}}"
        elif [[ "$line" == C$'\\t'* ]]; then
            entry="${{line#C$'\\t'}}"
            values+=("${{entry%%$'\\t'*}}")
            if [[ "$entry" == *$'\\t'* ]]; then
                descriptions+=("${{entry#*$'\\t'}}")
            else
                descriptions+=("")
            fi
        fi
    done
    if (( directive & 2 )); then
        _files -/
        return
    fi
    if (( ${{#values[@]}} == 0 )); then
        if (( ! (directive & 1) )); then _files; fi
        return
    fi
    compadd -Q -d descriptions -a values
}}
if [ "$funcstack[1]" = "_{function}" ]; then
    _{function} "$@"
else
    compdef _{function} {name}
fi
"""


def _fish(cmd: ResolvedCommand) -> str:
    name = shlex.quote(cmd.name)
    function = _shell_name(cmd.name)
    return f"""\
function __{function}_prepare
    set -l tokens (commandline -opc)
    set -l current (commandline -ct)
    set -l argv $tokens
    set -a argv "$current"
    set -l cursor (count $tokens)
    set -g __{function}_results
    set -l directive 0
    for line in (command {name} __complete $cursor $argv 2>/dev/null)
        set -l parts (string split -m 1 \\t -- $line)
        if test (count $parts) -lt 2
            continue
        end
        if test "$parts[1]" = D
            set directive "$parts[2]"
        else if test "$parts[1]" = C
            set -a __{function}_results "$parts[2]"
        end
    end
    if test (count $__{function}_results) -eq 0
        if test (math "$directive % 2") -ne 0
            return 0
        else
            return 1
        end
    end
    return 0
end
complete -c {name} -f -a '$__{function}_results' -n '__{function}_prepare'
"""


def _powershell(cmd: ResolvedCommand) -> str:
    name = _powershell_string(cmd.name)
    return f"""\
Register-ArgumentCompleter -Native -CommandName {name} -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)

    $words = @()
    foreach ($element in $commandAst.CommandElements) {{
        if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst]) {{
            $words += $element.Value
        }} else {{
            $words += $element.Extent.Text
        }}
    }}
    if ($wordToComplete -ne '') {{
        if ($words.Count -eq 0 -or $words[-1] -ne $wordToComplete) {{
            $words += $wordToComplete
        }}
    }} else {{
        $words += ''
    }}
    if ($words.Count -le 1) {{ return }}

    $cursor = $words.Count - 1
    $lines = @(& {name} __complete $cursor @words 2>$null)
    foreach ($line in $lines) {{
        if ($line -isnot [string] -or $line.Length -lt 2) {{ continue }}
        if ($line.Substring(0, 1) -eq 'D') {{ continue }}
        if ($line.Substring(0, 1) -ne 'C') {{ continue }}
        $line = $line.Substring(2)
        $parts = $line -split "`t", 2
        $value = $parts[0]
        $helpText = if ($parts.Count -gt 1) {{ $parts[1] }} else {{ $value }}
        $kind = if ($value.StartsWith('-')) {{
            [System.Management.Automation.CompletionResultType]::ParameterName
        }} else {{
            [System.Management.Automation.CompletionResultType]::ParameterValue
        }}
        [System.Management.Automation.CompletionResult]::new($value, $value, $kind, $helpText)
    }}
}}
"""


def _shell_name(name: str) -> str:
    return "argbuilder_" + "".join(char if char.isalnum() else "_" for char in name)


def _powershell_string(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"
