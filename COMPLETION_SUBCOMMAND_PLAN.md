# Plan: add a standard `completion <shell>` subcommand

Status: implemented. `Command.completion_subcommand(True)` adds the standard
`completion <SHELL>` command, and the generated adapters remain covered by the
shell tests described below.

## Goal

Given a CLI:

```python
def build_cli() -> Command:
    return (
        Command("mycli").completion_subcommand(True)
        # ... existing args/subcommands
    )
```

the following works:

```bash
# bash
eval "$(mycli completion bash)"

# zsh
eval "$(mycli completion zsh)"

# fish
mycli completion fish | source

# PowerShell
mycli completion powershell | Out-String | Invoke-Expression
```

This makes completion **ephemeral, current-shell-only, and copy/paste-free**.
Durable installation (`--install-completion`, package-manager paths) is a
separate feature and is not part of this plan.

## Design decisions

1. **Opt-in.** Do not add a `completion` command to every CLI. It changes help
   output, completion output and dispatch behavior. Add it with
   `Command.completion_subcommand(True)`.
2. **Visible command.** The command is listed in help like any other
   subcommand. It is not hidden.
3. **Root only.** The completion command describes the whole CLI, so allow
   `completion_subcommand(True)` only on the root command. A nested
   `completion` command is usually a mistake and complicates dispatch.
4. **Built at resolve time.** Follow the auto-`help` subcommand pattern in
   `_build.py`: a spec flag causes `_build` to add the command. This keeps
   `Command` immutable and means the command participates in help, Markdown
   docs, completion, suggestions and parsing automatically.
5. **The library prints and exits.** `get_matches_from()` should detect the
   generated command and write the script, like `--help`/`--version` exit
   inside the process edge. `try_get_matches_from()` stays pure and returns
   matches.
6. **No silent rc-file edits.** This plan only prints a script. Editing
   `~/.bashrc`, `~/.zshrc` or `$PROFILE` belongs in a separate, explicit
   `--install-completion` feature.

## Files and changes

### 1. `src/argbuilder/_spec.py`

Add a flag to `CommandSpec`:

```python
completion_subcommand: bool = False
```

No other spec change.

### 2. `src/argbuilder/_build.py`

Add a module-level completion command spec:

```python
_COMPLETION_SUBCOMMAND = CommandSpec(
    name="completion",
    about="Generate a shell completion script",
    args=(
        ArgSpec(
            id="shell",
            value_name="SHELL",
            required=True,
            value_parser=ValueParser.choices(*SHELLS),
            help="Shell to generate completions for",
        ),
    ),
)
```

`SHELLS` currently lives in `_completion.py`. Importing it from `_build` is safe
at runtime because `_completion` only imports `_build` under `TYPE_CHECKING`.
Alternatively move `Shell`/`SHELLS` into `_spec.py` and re-export from
`_completion.py`; either is fine. Pick one and keep one source of truth.

In `_resolve_subcommands()`:

- If `spec.completion_subcommand`:
  - enforce root-only: `depth` is available; panic on a subcommand:
    `"{where}: completion_subcommand(True) only applies to the root command"`
  - enforce no collision: if a user subcommand is already named `completion`,
    panic with a clear message.
  - build and insert `completion` before the auto `help` subcommand.
- Add `completion` to `subcommand_names`.

Add a field to `ResolvedCommand`:

```python
completion_subcommand: bool
```

Set it from `spec.completion_subcommand`. This lets the process edge detect
the opt-in without guessing from the subcommand name.

### 3. `src/argbuilder/_command.py`

Add a builder method:

```python
def completion_subcommand(self, yes: bool) -> Command:
    """Add a `completion <SHELL>` subcommand that prints a completion script.

    Root commands only. The script is meant to be evaluated or sourced by the
    shell; see the README.
    """
    return self._with(
        completion_subcommand=_check_bool(repr(self), "completion_subcommand", yes),
    )
```

Update `get_matches_from()`:

```python
def get_matches_from(self, argv, env=_NO_ENV) -> ArgMatches:
    result = self.try_get_matches_from(argv, env)
    if isinstance(result, Error):
        result.exit()
    self._write_completion_command(result)
    return result
```

Add a private helper:

```python
def _write_completion_command(self, matches: ArgMatches) -> None:
    if not self._resolved().completion_subcommand:
        return
    if matches.subcommand_name() != "completion":
        return
    sub = matches.subcommand_matches("completion")
    if sub is None:
        return
    shell = sub.get_required("shell", str)
    sys.stdout.write(render_completion(self._resolved(), shell))  # cast to Shell
    sys.stdout.flush()
    raise SystemExit(0)
```

Important:

- `get_matches()` already intercepts the hidden `__complete` protocol before
  parsing. Keep that order.
- `get_matches_from()` now answers `completion` too, so apps that use
  `get_matches_from(sys.argv[1:])` also get the standard behavior.
- `try_get_matches_from()` remains pure and returns `ArgMatches` for
  `["mycli", "completion", "bash"]`.
- Use `typing.cast("Shell", shell)` or a validated conversion to keep `ty`.
  `ValueParser.choices` guarantees the value, but the getter is typed `str`.

### 4. `src/argbuilder/_completion.py`

No protocol change needed. The generated shell scripts still call:

```text
mycli __complete <cursor> <argv...>
```

`completion bash` is just a public front door to `render_completion()`.

Optionally expose a small helper to avoid `cast` in `_command.py`:

```python
def render_completion_for(cmd: ResolvedCommand, shell: str) -> str:
    invariant(shell in SHELLS, ...)
    return render_completion(cmd, shell)  # type: ignore[arg-type]
```

Prefer importing `SHELLS` and validating in one place.

### 5. `examples/git.py` (recommended)

Add `.completion_subcommand(True)` to the example root:

```python
Command("git")
.about(...)
.version(...)
.completion_subcommand(True)
```

Then document:

```bash
uv run examples/git.py completion bash
eval "$(uv run examples/git.py completion bash)"   # binary name caveat
```

Caveat: the generated script invokes `git`, while the example is run as
`python examples/git.py`. For a real demo, either install an entry point named
`git` or keep the example's existing name. If adding this changes the
`example_git_help` golden, update it with `pytest --update-golden` and review
the diff.

If the example change is undesirable, leave the example alone and document
the pattern in the README only.

### 6. Documentation

Update the README “Shell completion” section to lead with:

```bash
eval "$(mycli completion bash)"
```

and show all four shell forms. Keep the existing `render_completion()` API as
the lower-level mechanism. Explain:

- `completion` is opt-in via `completion_subcommand(True)`.
- It is visible in help.
- The script is ephemeral unless the user sources it from a startup file or a
  package installs it in a standard completion directory.
- The executable must be named the same as the `Command` and be on `PATH`.
- `get_matches_from()` and `get_matches()` handle printing; a custom parser
  that only calls `try_get_matches_from()` must call `render_completion()`
  itself.

Add a `CHANGELOG.md` entry under Unreleased:

```markdown
- `Command.completion_subcommand(True)` adds a standard `completion <SHELL>`
  command. `mycli completion bash` prints a script suitable for
  `eval "$(mycli completion bash)"`.
```

Add the new API to the `clap → argbuilder` or “Also supported” section if it
fits the table style. `clap` has no built-in equivalent, so a short prose note
is better than a table row.

## Tests

Add to `tests/test_completion.py` or a new `tests/test_completion_command.py`.

### Builder and help

- `Command("p").completion_subcommand(True)` adds a visible `completion`
  subcommand.
- Without the flag, there is no `completion` command.
- Calling `completion_subcommand(True)` twice is idempotent.
- `completion_subcommand(False)` leaves it out.
- Help lists `completion`; Markdown docs list it too.
- `p completion --help` returns `DisplayHelp`, exit 0.
- `p help completion` shows the completion command’s help.
- A nested `completion_subcommand(True)` panics at build.
- A user-defined `Command("completion")` plus the flag panics with a clear
  duplicate-name error.

### Parsing

- `try_get_matches_from(["p", "completion", "bash"])` returns `ArgMatches`,
  `subcommand_name() == "completion"`, and
  `subcommand_matches("completion").get_required("shell", str) == "bash"`.
- Each of `bash`, `zsh`, `fish`, `powershell` is accepted.
- Missing shell returns `MissingRequiredArgument` with usage
  `p completion <SHELL>`.
- Invalid shell returns `InvalidValue` with possible values and a suggestion.
- Pure parsing does **not** print or exit.

### Process edge

Use monkeypatch + capsys:

- `sys.argv = ["p", "completion", "bash"]`; `get_matches()` raises
  `SystemExit(0)` and stdout starts with the bash completion header/script.
- Same for `get_matches_from(["p", "completion", "bash"])`.
- `get_matches()` with `completion` and no shell exits 2 and prints an error.
- `get_matches()` with an invalid shell exits 2 and prints an error.
- The existing hidden `__complete` protocol test still passes.

### Completion of the completion command

The pure completion engine should offer:

- `completion` at the root, when enabled.
- `bash`, `zsh`, `fish`, `powershell` after `p completion `.
- A prefix like `p completion z` returns `zsh`.
- Hidden/filtered behavior remains unchanged.

### Shell integration

Add one shell test that generates the script through the public command:

```python
generated = _run([tool, "completion", "bash"], ...)
assert generated.stdout == cli.render_completion("bash")
```

Keep the existing `render_completion()` shell tests; they cover the script
itself. This new test covers only the command-to-script path.

### Coverage

The project requires 100% branch coverage. New branches to cover:

- flag true/false
- root vs nested rejection
- name collision
- `subcommand_name != "completion"`
- `subcommand_matches is None` defensive branch
- valid/missing/invalid shell
- `get_matches_from` completion path

If a defensive branch is truly unreachable, remove it rather than adding a
coverage pragma (the repo has no `pragma: no cover` convention).

## Acceptance criteria

- [ ] `Command("mycli").completion_subcommand(True)` adds a visible
      `completion` command.
- [ ] `mycli completion bash` prints the same script as
      `mycli.render_completion("bash")`.
- [ ] `eval "$(mycli completion bash)"` enables Tab completion in the current
      bash session.
- [ ] The fish and PowerShell equivalents work in the shell matrix.
- [ ] Missing/invalid shell values produce normal argbuilder errors and exit 2.
- [ ] `completion --help` works and is included in help/Markdown.
- [ ] `try_get_matches_from()` remains pure.
- [ ] No shell config is modified automatically.
- [ ] 100% branch coverage remains.
- [ ] `mise run ci:fast`, `mise run test`, `mise run test:completion`,
      `mise run contract:check` and `mise run smoke` pass.

## Commands

```bash
mise run ci:fast
mise run test
uv run pytest -q
mise run test:completion
mise run contract:check
mise run smoke
```

After changing generated scripts or adding the example command, regenerate
goldens and review the diff:

```bash
uv run pytest -q --update-golden
git diff -- tests/golden
```

## Risks / gotchas

- **Name collision.** `completion` is a common subcommand name. Do not
  auto-add it unless the flag is set; panic clearly if the user already has
  one.
- **Root-only.** Nested completion commands are confusing; reject them at
  build time.
- **Output stream.** Print completion scripts to stdout, not stderr. Exit 0.
- **Binary name.** Generated scripts invoke the command name from
  `Command(...)`. The executable must be on `PATH` under that name. Running
  `python mycli.py completion bash` does not make a `mycli` executable exist.
- **Purity.** Keep `try_get_matches_from()` side-effect free. Only
  `get_matches_from()` / `get_matches()` may print and exit.
- **Hidden protocol.** Do not let the visible `completion` command shadow the
  internal `__complete` protocol. They are separate paths.
- **Example goldens.** Adding the command to `examples/git.py` changes its
  help/Markdown goldens; update and review them, or leave the example alone.
- **No installer.** This plan does not persist anything. It only provides the
  one-command ephemeral path. `--install-completion` is a separate feature.
