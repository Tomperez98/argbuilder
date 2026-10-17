# AGENTS.md

Guidance for coding agents working on or with argbuilder.

## The contract

- A broken **definition** raises `AssertionError` at the builder call, or at
  build for rules that span arguments. It is raised explicitly, so
  `python -O` does not strip it.
- A bad **command line** is a value: `try_get_matches_from(argv, env=...)`
  returns `ArgMatches | Error`. `get_matches()` prints the error and exits
  (0 for help/version, 2 otherwise).
- Reading matches is typed at the call site. A wrong id, wrong type, or wrong
  getter is an `AssertionError` at the read.

## Purity

- Pure: `try_get_matches_from`, `render_help`, `render_markdown`,
  `render_completion`, `complete`, `debug_assert`. No process, terminal, or
  filesystem dependency.
- Process edges: `get_matches()` reads `sys.argv` and `os.environ`;
  `get_matches_from()` prints and exits on a user error; `Error.exit()` writes
  to a stream. The parse itself is still pure.
- Test with `try_get_matches_from(argv, env={...})`. Never spawn a subprocess
  or monkeypatch `sys.argv` for parser tests.

## Changing a CLI

1. Edit the `Command` / `Arg` builder.
2. Run `cli().debug_assert()`.
3. Add or update a parse test:

   ```python
   from argbuilder import ArgMatches

   matches = cli().try_get_matches_from(["tool", "sub", "value"], env={"TOOL_VALUE": "x"})
   assert isinstance(matches, ArgMatches)
   assert matches.get_required("value", str) == "x"
   ```

4. Run `uv run pytest -q`. The suite is held at 100% branch coverage.
5. If help, Markdown docs or completion changed, update the golden assertions;
   they all render from the same command tree.

## Getters

| Call | Returns | Use for |
|---|---|---|
| `get_required(id, T)` | `T` | `required(True)` or defaulted single-value args |
| `get_one(id, T)` | `T \| None` | optional single-value args |
| `get_many(id, T)` | `tuple[T, ...]` | `append` / multi-value args; empty when absent |
| `get_flag(id)` | `bool` | `set_true` / `set_false` |
| `get_count(id)` | `int` | `count` |
| `contains_id(id)` | `bool` | whether any source provided a value |
| `value_source(id)` | `"default_value" \| "env_variable" \| "command_line"` | where the value came from |

## Errors

`ErrorKind` is a union of frozen dataclasses. Match it; do not parse
`Error.message`:

```python
match error.kind:
    case DisplayHelp() | DisplayVersion():
        ...
    case InvalidValue(argument=argument, value=value):
        ...
    case UnknownArgument(argument=typed, suggestion=closest):
        ...
```

## Invariants

- Python 3.12+, no runtime dependencies.
- Builders are immutable: every method returns a new value.
- New public API needs README, CHANGELOG, tests and 100% branch coverage.
- Definition mistakes panic (`AssertionError`); user mistakes return values.
- Keep the parser pure. Process and filesystem edges belong in `get_matches` /
  `get_matches_from` or explicitly injected helpers.
- Do not add a derive/decorator API, config-file parsing, prompting, i18n, a
  `help_template` DSL, or alternate option prefixes. See `plans/README.md` for
  the full non-goals list.

## Where to look

- `README.md` — public behavior and examples.
- `examples/git.py` — a fuller CLI with subcommands.
- `src/argbuilder/` — implementation.
- `tests/` — the suite; `tests/test_parse.py`, `tests/test_validation_matrix.py`
  and `tests/test_output.py` are good starting points.
- `plans/README.md` — feature order, non-goals and working rules.
- `CHANGELOG.md` — write the entry in the same commit as the change.

## Using argbuilder in another project

- Read `llms.txt` first for a compact API index.
- Put `cli().debug_assert()` in a test, not in `main`.
- Test through `try_get_matches_from(argv, env=...)`; keep `get_matches()` for
  the real entry point.
- The CLI boundary is checked; business logic still needs its own tests.
