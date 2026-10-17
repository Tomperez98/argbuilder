# 14 — Ergonomics: `infer_subcommands` and `ignore_case`

## Goal

Add two opt-in convenience settings:

```python
Command("git").infer_subcommands(True)
Command("git").ignore_case(True)
```

Both are lower priority; they should not change default behavior.

## `infer_subcommands`

Allow unambiguous prefixes:

```text
mycli rem        -> remote
mycli remote ad  -> add
```

Behavior:

- Exact matches always win.
- If a prefix matches exactly one canonical name or visible alias, select it.
- If it matches multiple, return a normal `InvalidSubcommand`/ambiguous error
  listing candidates.
- Hidden subcommands should not make an otherwise unambiguous prefix
  ambiguous, but should they be selectable? Recommendation: preserve current
  behavior for explicit hidden names; prefix inference only considers visible
  names.
- Aliases participate in inference.
- Nested levels apply independently.
- Completion should still offer full names, not inferred prefixes. It may
  highlight the prefix but that is optional.
- Error suggestions should mention the ambiguity.

Implementation:

- Add `infer_subcommands: bool = False` to `CommandSpec` / `ResolvedCommand`.
- Add builder method.
- In `_parser.run`, before unknown-subcommand handling, resolve an
  unambiguous prefix to the canonical name.
- Consider conflicts with external subcommands (plan 12): known prefixes win;
  external capture only applies when no known inference matches.
- Help/usage unchanged except perhaps a note in docs.

Tests:

- unique prefix selects.
- exact name beats prefix.
- visible alias prefix selects.
- ambiguous prefix errors with candidates.
- hidden names/aliases do not create ambiguity.
- disabled by default.
- nested commands.
- completion unaffected.

## `ignore_case`

Case-insensitive matching for option names and subcommands:

```text
MYCLI --COLOR always
MYCLI REMOTE add
```

Behavior:

- Applies to long option names, aliases, subcommand names and aliases.
- Short flags are already case-sensitive (`-v` vs `-V`); do not fold those.
- Exact canonical spelling wins when multiple spellings differ only by case.
- Completion should offer canonical spellings, not mixed-case variants.
- Error suggestions should use the configured matching and still suggest the
  closest canonical spelling.
- Environment variable names and values remain case-sensitive.
- On case-sensitive filesystems, values are unchanged.

Implementation:

- Add `ignore_case: bool = False` to `CommandSpec` / `ResolvedCommand`.
- Add builder method.
- Normalize lookups in `_parser` for long names and subcommand names, while
  preserving the original spelling in help/errors.
- Consider `infer_long_args` as a separate feature; do not merge it into this
  plan.

Tests:

- `--COLOR`, `--Color` match `--color`.
- `REMOTE` matches `remote`.
- Visible aliases match case-insensitively.
- Short flags remain exact.
- Ambiguous case-only definitions are rejected at build time (or document
  first-wins; prefer rejecting).
- Completion offers canonical spelling and filters case-insensitively if
  configured.
- Suggestions still work.

## Acceptance criteria

- [ ] Both settings are opt-in and disabled by default.
- [ ] Exact/canonical matches take precedence.
- [ ] Ambiguity is a normal user error.
- [ ] Hidden entries never become visible through inference.
- [ ] Completion remains predictable.
- [ ] 100% branch coverage.

## Risks

- Prefix inference can hide typos; document it as an opt-in convenience.
- Case folding differs for Unicode; use ASCII case folding for CLI names and
  document it.
- These settings interact with external subcommands, aliases and suggestions;
  test combinations explicitly.
