# 10 — Man page generation

## Goal

Add a pure renderer:

```python
Command("git").render_man_page()
```

that emits roff suitable for `man 1 git`, alongside the existing
`render_help`, `render_markdown` and `render_completion`.

## Current state

- `_help.py` renders help/usage.
- `_docs.py` renders Markdown.
- `_completion.py` renders shell adapters.
- No man page renderer or roff escaping helper.

## Proposed API

```python
Command("git").render_man_page(
    section=1,
    date=None,       # None means omit the date field; never call datetime.now()
    source="git 2.0.0",
    manual="Git Manual",
) -> str
```

Defaults should be deterministic:

- `section=1`
- `date=None` (or a caller-provided string)
- `source` defaults to the command name
- `manual` defaults to `"General Commands Manual"` or omitted

Add a `ManPage`/`ManOptions` dataclass only if the parameter list grows.

## Content

Use the same resolved tree and visibility rules as help/docs:

- `.TH` with name, section, date/source/manual
- `.SH NAME` — `name \- about`
- `.SH SYNOPSIS` — `render_usage`
- `.SH DESCRIPTION` — `about` / `long_about` if available
- `.SH OPTIONS` — visible options, grouped by help headings if implemented
- `.SH ARGUMENTS` — visible positionals
- `.SH COMMANDS` — visible subcommands, with their paths
- `.SH EXAMPLES` — `after_help` or a dedicated `examples` field if added
- One section per subcommand or a nested `.SS` structure; choose and document.
  A flat `.SS` per command path is easiest to generate and read.

Hidden args/subcommands stay out. Inherited globals appear on each subcommand,
matching help/docs.

## Roff escaping

Add a focused helper:

- escape leading `.` and `'` at the start of a line (`\&.`)
- escape backslashes (`\\`)
- represent literal hyphens in option names as `\-`
- avoid accidental roff macros from user help text
- preserve line wrapping deliberately; do not blindly inject ANSI/color
- handle empty help text
- normalize tabs/newlines in one-line headings

Do not shell out to `groff` from the library. Rendering stays pure.

## Implementation steps

1. Add `src/argbuilder/_man.py` with `render_man_page(cmd, ...)`.
2. Add `Command.render_man_page(...)`.
3. Reuse `_help` labels/visibility/usage.
4. Add roff escaping tests.
5. Add a golden per representative CLI.
6. Optionally add a CI check using `groff -man -Tutf8` if installed; skip if
   absent, but fail in the dedicated docs job if the project requires it.
7. README/CHANGELOG.

## Tests

Golden files:

- basic command with arguments/options
- nested subcommands
- hidden args/subcommands
- choices/defaults/env
- help text with `.`, `'`, `\`, hyphens and quotes
- no date vs explicit date
- section/source/manual overrides

Structural tests:

- `.TH` line is well-formed
- hidden items absent
- every visible option/command appears
- output ends with one newline, no trailing whitespace
- rendering twice is identical
- roff escaping round-trips through `groff` if available

## Acceptance criteria

- [ ] `render_man_page()` produces valid roff for a rich CLI.
- [ ] Output is deterministic and dependency-free.
- [ ] Hidden items and aliases follow existing visibility rules.
- [ ] Goldens and optional `groff` validation pass.
- [ ] 100% branch coverage.

## Risks

- Roff escaping is fiddly; test hostile help text.
- Subcommand layout can become huge; start with `.SS` sections and document.
- Do not introduce non-determinism through dates or environment inspection.

## Non-goals

- installing man pages
- man page compression/packaging
- a generic roff template language
