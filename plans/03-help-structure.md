# 03 — Help structure and long help

## Goal

Make help output comparable to clap for real CLIs:

- short `-h` vs long `--help`
- `before_help`, `after_help`
- `long_about`, `Arg.long_help`
- option headings and display order
- hiding noisy defaults, env names and possible values

## Current state

`_help.py` renders one `Options:` table and one `Arguments:` table, with
insertion order. `-h` and `--help` share the same help action, so the parser
cannot distinguish them.

## Proposed API

```python
Command("git")
.about("A versioning CLI")
.long_about("A longer description shown by --help")
.before_help("Examples live below the options.")
.after_help("See https://example.invalid/docs")

Arg("json")
.long("json")
.help("Machine-readable output")
.long_help("Emit JSON. This is intended for scripts; fields may change.")
.help_heading("Output")
.display_order(10)
.hide_default_value(True)
.hide_env_values(True)
.hide_possible_values(True)
```

### Short vs long help

- `-h` uses `about` and each argument's `help`.
- `--help` uses `long_about` when present, otherwise `about`.
- `--help` uses `long_help` when present, otherwise `help`.
- `help <command>` should use long help (same as `--help`).
- Missing-argument / `arg_required_else_help` help should use short help
  unless a separate decision is made.

Implementation catch: `_HELP_SPEC` currently has one `action="help"` used by
both `-h` and `--help`. The parser must know which spelling was used.

Suggested change:

```python
@dataclass(frozen=True, slots=True)
class DisplayHelp:
    long: bool = False
```

- `_parser._flag` receives a `long: bool` from `_long()` / `_short()`.
- `_help_error(DisplayHelp(long=...), cmd)` calls `render_help(..., long=...)`.
- `Error.restyle` must preserve the long flag.
- The auto `help` subcommand uses `long=True`.
- Existing tests compare `DisplayHelp()` exactly; update them deliberately.

### Headings and order

Add:

- `ArgSpec.help_heading: str | None`
- `ArgSpec.display_order: int | None`
- `CommandSpec.subcommand_help_heading`? Start with argument headings only;
  the `Commands:` section can stay fixed until needed.

Render:

1. Arguments, grouped by heading.
2. Options, grouped by heading.
3. Default heading remains `Arguments:` / `Options:`.
4. Within a heading, sort by `display_order`, then insertion order.
5. A heading appears once; empty headings do not appear.
6. `render_markdown` reuses the same grouping so help and docs cannot drift.

Validate at build:

- heading is a non-empty string if set
- display_order is an int (bool is not an int here)
- hidden args never create a heading

### Hide metadata

Add boolean fields/options:

- `hide_default_value` — `arg_details` omits `[default: ...]`
- `hide_env_values` — omit `[env: ...]`
- `hide_possible_values` — omit `[possible values: ...]`

Defaults are `False`, so existing output is unchanged.

## Implementation steps

1. Extend `ArgSpec`, `CommandSpec`, `ResolvedArg`, `ResolvedCommand`.
2. Add builder methods in `_arg.py` / `_command.py` with validation.
3. Resolve fields in `_build.py`.
4. Change `_help.render_help` to accept `long: bool`; add section grouping.
5. Add `_help.arg_details` hide switches.
6. Change `_parser` help calls to carry `long`.
7. Update `_docs` to reuse the new grouping and long text.
8. Update README/CHANGELOG.
9. Regenerate goldens and review diffs.

## Tests

- `-h` vs `--help` output differs only where long text is set.
- `help <cmd>` equals `--help` for that command.
- `before_help` appears before usage/options and `after_help` after them.
- Headings render in definition order; display order sorts within a heading.
- Hidden args do not create or leak into headings.
- `hide_default_value`, `hide_env_values`, `hide_possible_values` each work.
- Markdown and help use the same headings and visibility.
- Width wrapping and color still preserve layout (reuse render properties).
- Golden files for a rich CLI: short help, long help, headings, hidden
  metadata.
- Build errors for empty heading / non-int display order.

## Acceptance criteria

- [ ] `-h` and `--help` can produce different content.
- [ ] `help cmd` shows long help.
- [ ] Option headings and display order are supported.
- [ ] Hidden metadata options work in help and Markdown.
- [ ] Existing help output is unchanged when the new features are unused.
- [ ] 100% branch coverage.
- [ ] No external dependencies.

## Risks

- `DisplayHelp` is public and compared in tests/examples; update carefully.
- `Error.restyle` must know whether help was long.
- Help and docs can drift if Markdown keeps its own grouping logic; share the
  section-building code.
- Goldens will churn; review them rather than blindly accepting updates.

## Non-goals

- `help_template`
- author/long_version
- next-line-help toggles (current automatic layout stays)
- custom usage strings
