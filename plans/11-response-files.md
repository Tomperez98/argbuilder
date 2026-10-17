# 11 — Response files (`@file`)

## Goal

Support long command lines kept in files:

```text
mycli @args.txt
```

where `args.txt` contains additional arguments. This mirrors argparse's
`fromfile_prefix_chars` and picocli's `@-files`.

## Current state

- The parser is pure and token-driven.
- No filesystem access exists in `try_get_matches_from`.
- There is no response-file expansion.

## Design constraint

Keep `try_get_matches_from()` pure. Reading files inside it would break the
current contract and make tests/environment behavior surprising.

Recommended split:

```python
# pure-ish helper, I/O is explicit
expand_response_files(argv, *, read_text=Path.read_text, max_depth=8) -> list[str]

# opt-in process edge
Command("mycli").response_files(prefix="@", max_depth=8)
```

- `try_get_matches_from()` does **not** expand files by default.
- `get_matches()` / `get_matches_from()` expand when enabled.
- Applications that use `try_get_matches_from()` can call the helper themselves.
- Tests can inject a fake `read_text` and stay hermetic.

## Format

Choose one format and document it. Recommended first version:

- one argument per non-empty line
- blank lines ignored
- lines beginning with `#` are comments
- no shell quoting in v1
- `@@` escapes a literal argument beginning with `@`
- recursion allowed with a maximum depth
- paths resolve relative to the current working directory
- an unreadable file is a user-facing error, not a panic

If shell-like quoting is needed later, add an explicit mode rather than
changing the default.

## Behavior

- Expansion happens before parsing and before `--` handling, but after a
  literal `--`? Decide: arguments after `--` are still expanded? Safer:
  response-file syntax applies only before `--`; after `--`, `@file` is a
  literal value. Document and test.
- A missing file: decide whether to treat `@name` literally (argparse does) or
  return an error. Recommended: error, because silently passing `@name` is
  confusing and security-sensitive.
- Cycles: error with the chain or a max-depth message.
- Do not expand `@` inside an option value unless it is a standalone token.
- Respect the prefix setting; `@` is only special when configured.
- Empty file expands to no tokens.

## Implementation steps

1. Add `CommandSpec.response_files` settings (enabled/prefix/max_depth).
2. Add `Command.response_files(...)`.
3. Implement `expand_response_files()` in a new `_response.py` or `_io.py`.
4. Expand in `get_matches` / `get_matches_from` only when enabled.
5. Define the user-facing error kind (or reuse `InvalidValue` on a synthetic
   `@file` argument). Prefer a dedicated `ResponseFileError` only if it carries
   useful path/depth context.
6. README/CHANGELOG/tests.

## Tests

- Simple expansion with spaces in arguments.
- Comments and blank lines.
- Multiple `@file`s, left-to-right order.
- Nested files and max-depth error.
- Missing file error.
- Unreadable file (permission) error.
- `@@literal` escape.
- `@file` after `--` remains literal.
- Prefix disabled means no expansion.
- Injected `read_text` is used (no real filesystem in tests).
- Expansion preserves argument order and does not mutate the input.
- Shell completion is unaffected.

## Acceptance criteria

- [ ] Opt-in response files work for long command lines.
- [ ] `try_get_matches_from` remains pure.
- [ ] Recursion is bounded and errors are clear.
- [ ] No arbitrary file reads beyond explicitly referenced files.
- [ ] 100% branch coverage.

## Risks

- File format/quoting compatibility varies across tools; document precisely.
- Security: avoid expanding inside arbitrary values and enforce a depth bound.
- Path resolution and Windows/backslash behavior need explicit tests.
