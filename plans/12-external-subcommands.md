# 12 — External subcommands

## Goal

Support git-style external/plugin commands:

```text
mycli my-plugin --flag value
```

where `my-plugin` is not declared in the command tree but is resolved and
dispatched by the application.

This mirrors clap's `Command::allow_external_subcommands`.

## Current state

- Unknown first positional/subcommand is an `InvalidSubcommand` or
  `UnknownArgument`.
- `ArgMatches` only exposes declared ids and subcommands.
- There is no plugin/extension mechanism.

## Proposed API

```python
Command("git").allow_external_subcommands(True)
```

Matches:

```python
matches.external_subcommand()  # ("my-plugin", ("--flag", "value")) | None
matches.external_subcommand_name()  # "my-plugin" | None
matches.external_subcommand_args()  # ("--flag", "value")
```

Decide whether the external args are returned as raw strings or as a small
`ArgMatches`-like object. Raw strings are simpler and match “everything after
the command name is opaque”.

## Behavior

- Only applies when the token would otherwise be an unknown subcommand/command.
- The first unknown token becomes the external command name.
- Every following token is captured verbatim, including flags, `--`, and
  subcommand-looking names.
- Do not parse external args through the normal option parser.
- If the command has positional arguments, decide precedence:
  - recommended: known positionals are still filled first; external
    subcommands only apply when no positional can take the token
  - document and test `mycli file plugin`
- `subcommand_required(True)` interacts: external subcommands count as a
  subcommand? Decide and test.
- `help` should show `[COMMAND]...` or a note that external commands are
  accepted, but must not enumerate unknown plugins.
- Completion cannot know plugin names; do not invent candidates. For an
  external-command context, return no candidates and allow file/default
  completion or no-file according to the configured behavior.
- Errors: none for the external name; `ArgMatches` signals it instead.

## Implementation steps

1. Add `allow_external_subcommands: bool = False` to `CommandSpec` /
   `ResolvedCommand`.
2. Add the builder method.
3. In `_parser.run`, before the positional/unknown error:
   - if the token is not a known subcommand and external subcommands are
     enabled, capture `(token, remaining_tokens)` and stop parsing this level.
4. Store the external command on `ArgMatches` and add accessors.
5. Ensure global args before the external name are still parsed normally.
6. Decide how a parent command’s `_finish` validation behaves; required args
   still apply unless documented otherwise.
7. Update help/usage/docs/completion.
8. README/CHANGELOG/tests.

## Tests

- `p plugin --x y` returns external name and raw args.
- External args are not parsed as known options.
- Global flags before the external name still work.
- Unknown token without the flag still errors.
- Known subcommands still win over external capture.
- Positional vs external precedence is defined and tested.
- `--` before the external name behaves correctly.
- Required args/`subcommand_required` interactions are defined.
- `ArgMatches` accessors return `None` for normal commands.
- Completion does not offer unknown plugin names and does not crash.
- Help/usage mentions external commands without leaking names.

## Acceptance criteria

- [ ] Plugin-style dispatch is possible without a declared subcommand.
- [ ] External args are returned verbatim.
- [ ] Normal unknown-token errors remain when disabled.
- [ ] No false plugin candidates in completion.
- [ ] 100% branch coverage.

## Risks

- Capturing everything verbatim can hide typos; make it opt-in.
- Interactions with required positionals, `subcommand_required`, and globals
  need explicit tests.
- Security: external command names are application-controlled dispatch keys;
  do not execute anything from the parser.
