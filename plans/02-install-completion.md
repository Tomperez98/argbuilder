# 02 — Durable completion installation

## Goal

Let users make completion persistent with one explicit command:

```bash
mycli completion bash --install
mycli completion fish --install
```

without the library silently editing `.bashrc`, `.zshrc`, `config.fish` or
`$PROFILE`.

## Current state

- `mycli completion <SHELL>` prints a script.
- `eval "$(mycli completion bash)"` is the ephemeral path.
- No files are written and no shell configuration is modified.
- The `completion` command is auto-added only with
  `Command.completion_subcommand(True)`.

## Proposed behavior

Extend the generated `completion` subcommand with:

- `--install` — write the script to a standard location and print the path.
- `--dry-run` — print the target path and what would be written; no writes.

Default behavior without `--install` stays exactly the same: print to stdout.

Example:

```text
$ mycli completion bash --install
Installed bash completion at /home/me/.local/share/bash-completion/completions/mycli
Start a new shell, or run: source /home/me/.local/share/bash-completion/completions/mycli
```

For shells without a standard auto-load directory, print a one-time setup line
instead of editing a profile.

## Target paths

Respect `XDG_*` variables. Use `Path.home()` only as a fallback.

| Shell | Target | Auto-loaded? |
|---|---|---|
| bash | `$XDG_DATA_HOME/bash-completion/completions/<name>` (`~/.local/share/...`) | yes with bash-completion 2 |
| fish | `$XDG_CONFIG_HOME/fish/completions/<name>.fish` (`~/.config/...`) | yes |
| zsh | `$XDG_DATA_HOME/zsh/site-functions/_<name>` | only if that directory is on `$fpath` |
| PowerShell | `$XDG_DATA_HOME/argbuilder/completions/<name>.ps1` | no; print the dot-source line |

For zsh and PowerShell, print the exact line the user must add once:

```zsh
fpath=("${XDG_DATA_HOME:-$HOME/.local/share}/zsh/site-functions" $fpath)
autoload -Uz compinit && compinit
```

```powershell
. "$HOME/.local/share/argbuilder/completions/mycli.ps1"
```

Do **not** append these lines automatically. A future `--install-completion`
flag can do that as a separate, explicit opt-in.

## Suggested API

Keep the logic out of `Command` so it stays testable:

```python
# _completion.py
@dataclass(frozen=True, slots=True)
class CompletionInstall:
    path: Path
    script: str
    hint: str | None


def completion_install_path(cmd_name: str, shell: Shell, env: Mapping[str, str]) -> Path: ...
def install_completion(
    cmd: ResolvedCommand,
    shell: Shell,
    *,
    env: Mapping[str, str],
    dry_run: bool = False,
) -> CompletionInstall: ...
```

`install_completion` should:

- choose the path from XDG env vars,
- create parent directories,
- write atomically (temporary file in the same directory, then `replace`),
- skip the write when the file already has identical content,
- never overwrite an unrelated file with a different command name,
- raise/return a clear error on permission failure.

The `completion` subcommand spec gets:

```python
ArgSpec(id="install", long="install", action="set_true", help="Install the script")
ArgSpec(id="dry_run", long="dry-run", action="set_true", help="Show the target without writing")
```

`_write_completion_command` branches:

- `install` false → print script (current behavior)
- `install` true → call `install_completion` and print the result
- `dry_run` true → print the target and a preview, no writes

## Implementation steps

1. Add the two boolean args to `_COMPLETION_SUBCOMMAND` in `_build.py`.
2. Add `CompletionInstall`, path selection and atomic write in `_completion.py`.
3. Extend `_write_completion_command` in `_command.py` to read `install` /
   `dry_run` from the subcommand matches.
4. Print path and hint to stdout; exit 0.
5. On `OSError`, print a clear error to stderr and exit 1 (I/O failure, not a
   user typo). Do not turn it into an `AssertionError`.
6. Add docs and CHANGELOG.

## Validation / edge cases

- Reject command names containing `/`, `\`, `..` or path separators when
  constructing the target filename. `_check_name` does not currently reject
  `/`.
- If `XDG_DATA_HOME` is relative, ignore it and use the home fallback.
- If `XDG_CONFIG_HOME` is set, use it for fish.
- Windows: use `LOCALAPPDATA` for the PowerShell data directory.
- Ensure `--dry-run` never creates directories.
- Ensure `--install` is idempotent and does not rewrite identical content
  (or at least produces the same bytes).
- Do not overwrite a file that contains a script for a different command.
- Preserve a user's existing file permissions when replacing.

## Tests

Use `tmp_path` and monkeypatch `HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`.
Never touch the real home directory.

- bash/fish/zsh/powershell target paths with and without XDG vars.
- `--install` writes the identical script to the target.
- `--install` twice is idempotent.
- `--dry-run` writes nothing and prints the path.
- default `completion bash` still prints to stdout and writes nothing.
- `--install` with a permission error prints an error and exits 1.
- zsh/powershell print the correct one-time hint.
- command name with a path separator is rejected before writing.
- `get_matches()` and `get_matches_from()` both handle install.
- `try_get_matches_from()` remains pure.

## Acceptance criteria

- [ ] `mycli completion bash --install` makes completion survive a new shell
      after the shell's normal completion directory is loaded.
- [ ] fish install requires no config edit.
- [ ] zsh/PowerShell print the exact one-time setup line if needed.
- [ ] No automatic edits to shell startup files.
- [ ] No writes outside the chosen XDG/user directory.
- [ ] 100% branch coverage.
- [ ] README and CHANGELOG updated.

## Non-goals

- `--install-completion` that edits startup files
- system-wide installation (needs root/packaging)
- Homebrew/RPM/DEB packaging
- installing completions for multiple shells in one command
