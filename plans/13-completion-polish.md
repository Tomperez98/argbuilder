# 13 — Completion polish

## Goal

Close the remaining completion gaps after the core feature ships:

1. `ValueHint` beyond paths
2. path completion after `--opt=`
3. fish directory-only filtering
4. `no_space` emission
5. shell descriptions consistency

Each item is small and independent; ship them in the order listed.

## 1. `ValueHint` scope

Current type accepts:

`any_path`, `file`, `dir`, `executable`, `command`, `username`, `hostname`,
`env_var`.

Only the path-ish hints affect candidates. The others fall back to default
shell completion.

Options:

- **Narrow** the public literal to the implemented path hints and document the
  rest as future work.
- **Implement** the missing hints:
  - `command`: shell command names
  - `username`: platform user names
  - `hostname`: known hosts/SSH config
  - `env_var`: environment variable names

Recommendation: narrow now, implement later. Do not expose hints that do
nothing. If keeping them, README must say they are accepted but currently fall
back to the shell default.

## 2. Path completion after `--opt=`

Current behavior:

- `--config ` → file fallback works
- `--config=` → no candidates + `no_file`

Problem: the shell’s native path completion does not handle the `=` prefix.

Options:

- Add a `path_prefix` to `CompletionResult` so the shell adapter can invoke
  native path completion with the prefix.
- Or add path candidates in Python for `=` values. This requires I/O and
  cross-platform path handling; keep it in a helper, not the pure engine.
- Or document the limitation and keep `no_file`.

Recommendation: implement a small `completion_value_prefix` field and have
each shell adapter use its native file completion with the prefix where
possible. If that is too shell-specific, add a `PathCompleter` helper with
injected `scandir`.

## 3. fish directory-only filtering

Current fish adapter treats `filter_dirs` like default file completion, so it
offers both files and directories.

Options:

- Use fish’s `__fish_complete_directories` helper when the directive asks for
  directories.
- Or let fish do full file completion and document the limitation.

Recommendation: use the fish helper if it is stable across the supported fish
versions; otherwise document the limitation.

## 4. `no_space`

The model and protocol support `no_space` (bit 2), but the engine never emits
it.

Decide:

- Remove the field if it has no use, or
- Emit it for candidates that end in `=` (for example, a `--opt=` completion)
  and test Bash/Zsh behavior.

Do not ship a public directive that can never occur without a test and a use
case.

## 5. Descriptions

Current behavior:

- zsh: descriptions passed through `compadd -d`
- fish: tab-separated values/help
- PowerShell: `CompletionResult` tooltips
- bash: no descriptions

Add a shared protocol test with a candidate that has a tab/newline in its help
to ensure `_one_line` sanitation remains correct. Do not attempt multi-line
descriptions.

## Tests

- ValueHint path matrix for file/dir/any_path/executable.
- `--config=` prefix behavior on bash/zsh/fish/powershell.
- fish dir-only behavior.
- no-space candidate behavior per shell.
- descriptions with spaces/quotes/tabs.
- candidates starting with `:`/`C`/`D` remain safe (protocol prefixes).
- generated script goldens update only when intended.

## Acceptance criteria

- [ ] Documented hints match implemented behavior.
- [ ] `--opt=` path completion is either supported or clearly documented.
- [ ] fish directory filtering is supported or documented.
- [ ] `no_space` has a real use case and test, or is removed.
- [ ] 100% branch coverage.

## Risks

- Native path completion differs across shells; keep the pure engine free of
  filesystem assumptions.
- A protocol change requires updating all four adapters and goldens.
