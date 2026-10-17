"""Real-shell checks for the generated completion adapters.

These are deliberately few: the candidate logic is covered by
`test_completion.py`. Here we only verify the parts Python cannot test -
word splitting, quoting, shell directives and the adapter protocol.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from argbuilder import Command

pytestmark = pytest.mark.shell

FIXTURE = Path(__file__).with_name("completion_cli.py")


def _require(shell: str) -> str:
    path = shutil.which(shell)
    if path is None:
        pytest.skip(f"{shell} is not installed")
    return path


def _launcher(tmp_path: Path) -> Path:
    """A `tool` executable that runs the fixture CLI through `get_matches()`."""
    path = tmp_path / "tool"
    path.write_text(
        f"#!{sys.executable}\n"
        "import runpy\n"
        f"cli = runpy.run_path({str(FIXTURE)!r})['cli']\n"
        "cli().get_matches()\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def _run(
    command: list[str], tmp_path: Path, *, timeout: float = 20
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=tmp_path,
        env=_env(tmp_path),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _candidates(output: str) -> set[str]:
    return {line.split("\t", 1)[0].strip() for line in output.splitlines() if line.strip()}


# -- bash ----------------------------------------------------------------------

BASH_HARNESS = r"""\
set -u
script=$1
line=$2
source "$script"
COMP_LINE="$line"
COMP_POINT=${#COMP_LINE}
read -r -a COMP_WORDS <<< "$line"
if [[ "$line" == *" " ]]; then
    COMP_WORDS+=("")
fi
COMP_CWORD=$((${#COMP_WORDS[@]} - 1))
fn=$(complete -p tool | sed -n 's/.*-F \([^ ]*\).*/\1/p')
"$fn"
printf '%s\n' "${COMPREPLY[@]}"
"""


def test_bash_script_syntax(tmp_path: Path) -> None:
    bash = _require("bash")
    script = tmp_path / "tool.bash"
    script.write_text(Command("tool").render_completion("bash"), encoding="utf-8")
    result = _run([bash, "-n", str(script)], tmp_path)
    assert result.returncode == 0, result.stderr


def test_bash_script_passes_shellcheck(tmp_path: Path) -> None:
    shellcheck = _require("shellcheck")
    script = tmp_path / "tool.bash"
    script.write_text(_fixture_cli().render_completion("bash"), encoding="utf-8")
    result = _run([shellcheck, "-s", "bash", str(script)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bash_completion_end_to_end(tmp_path: Path) -> None:
    bash = _require("bash")
    _launcher(tmp_path)
    script = tmp_path / "tool.bash"
    script.write_text(
        _fixture_cli().render_completion("bash"),
        encoding="utf-8",
    )
    harness = tmp_path / "harness.bash"
    harness.write_text(BASH_HARNESS, encoding="utf-8")

    root = _run([bash, "--noprofile", "--norc", str(harness), str(script), "tool "], tmp_path)
    assert root.returncode == 0, root.stderr
    assert {"add", "remote", "mode", "help", "-v", "--verbose"} <= _candidates(root.stdout)

    colors = _run(
        [bash, "--noprofile", "--norc", str(harness), str(script), "tool --color "],
        tmp_path,
    )
    assert colors.returncode == 0, colors.stderr
    assert _candidates(colors.stdout) == {"always", "auto", "never"}

    hidden = _run([bash, "--noprofile", "--norc", str(harness), str(script), "tool "], tmp_path)
    assert "__internal" not in _candidates(hidden.stdout)
    assert "--secret" not in _candidates(hidden.stdout)


# -- zsh -----------------------------------------------------------------------

ZSH_HARNESS = r"""\
script=$1
shift
compdef() { :; }
compadd() {
    local -a out
    while (( $# )); do
        case "$1" in
            -a) shift; out+=("${(@P)1}"); shift ;;
            -d|-S|-J|-V|-X) shift 2 ;;
            -*) shift ;;
            *) out+=("$1"); shift ;;
        esac
    done
    print -rl -- "${out[@]}"
}
_files() {
    if [[ "$1" == "-/" ]]; then print "__DIRS__"; else print "__FILES__"; fi
}
source "$script"
words=("$@")
CURRENT=${#words}
_argbuilder_tool
"""


def test_zsh_script_syntax(tmp_path: Path) -> None:
    zsh = _require("zsh")
    script = tmp_path / "_tool"
    script.write_text(Command("tool").render_completion("zsh"), encoding="utf-8")
    result = _run([zsh, "-n", str(script)], tmp_path)
    assert result.returncode == 0, result.stderr


def test_zsh_completion_end_to_end(tmp_path: Path) -> None:
    zsh = _require("zsh")
    _launcher(tmp_path)
    script = tmp_path / "_tool"
    script.write_text(_fixture_cli().render_completion("zsh"), encoding="utf-8")
    harness = tmp_path / "harness.zsh"
    harness.write_text(ZSH_HARNESS, encoding="utf-8")

    root = _run([zsh, "-f", str(harness), str(script), "tool", ""], tmp_path)
    assert root.returncode == 0, root.stderr
    assert {"add", "remote", "mode", "help", "-v", "--verbose"} <= _candidates(root.stdout)

    colors = _run([zsh, "-f", str(harness), str(script), "tool", "--color", ""], tmp_path)
    assert colors.returncode == 0, colors.stderr
    assert _candidates(colors.stdout) == {"always", "auto", "never"}

    files = _run([zsh, "-f", str(harness), str(script), "tool", "add", ""], tmp_path)
    assert files.returncode == 0, files.stderr
    assert "__FILES__" in files.stdout

    dirs = _run([zsh, "-f", str(harness), str(script), "tool", "--workdir", ""], tmp_path)
    assert dirs.returncode == 0, dirs.stderr
    assert "__DIRS__" in dirs.stdout

    no_files = _run([zsh, "-f", str(harness), str(script), "tool", "--color=zzz"], tmp_path)
    assert no_files.returncode == 0, no_files.stderr
    assert "__FILES__" not in no_files.stdout
    assert "__DIRS__" not in no_files.stdout


# -- fish ----------------------------------------------------------------------


def test_fish_script_syntax(tmp_path: Path) -> None:
    fish = _require("fish")
    script = tmp_path / "tool.fish"
    script.write_text(Command("tool").render_completion("fish"), encoding="utf-8")
    result = _run([fish, "-n", str(script)], tmp_path)
    assert result.returncode == 0, result.stderr


def test_fish_completion_end_to_end(tmp_path: Path) -> None:
    fish = _require("fish")
    _launcher(tmp_path)
    script = tmp_path / "tool.fish"
    script.write_text(_fixture_cli().render_completion("fish"), encoding="utf-8")

    root = _run([fish, "-N", "-c", f"source {script}; complete -C 'tool '"], tmp_path)
    assert root.returncode == 0, root.stderr
    assert {"add", "remote", "mode", "help"} <= _candidates(root.stdout)

    colors = _run(
        [fish, "-N", "-c", f"source {script}; complete -C 'tool --color '"],
        tmp_path,
    )
    assert colors.returncode == 0, colors.stderr
    assert _candidates(colors.stdout) == {"always", "auto", "never"}


# -- PowerShell ----------------------------------------------------------------


def test_powershell_completion_end_to_end(tmp_path: Path) -> None:
    pwsh = _require("pwsh")
    _launcher(tmp_path)
    script = tmp_path / "tool.ps1"
    script.write_text(_fixture_cli().render_completion("powershell"), encoding="utf-8")
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        """\
param($ScriptPath, $Line)
. $ScriptPath
$result = [System.Management.Automation.CommandCompletion]::CompleteInput(
    $Line, $Line.Length, $null
)
$result.CompletionMatches | ForEach-Object { $_.CompletionText }
""",
        encoding="utf-8",
    )

    colors = _run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(harness),
            str(script),
            "tool --color ",
        ],
        tmp_path,
    )
    assert colors.returncode == 0, colors.stderr
    assert _candidates(colors.stdout) == {"always", "auto", "never"}


def _fixture_cli() -> Command:
    import runpy

    return runpy.run_path(str(FIXTURE))["cli"]()
