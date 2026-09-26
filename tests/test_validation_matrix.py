"""The validation order, proven total and unambiguous over every combination.

`_validate` checks relationships in a fixed order and returns the *first*
failure it finds. `test_the_first_failure_wins` in `test_properties.py` pins
that order with a handful of stacked pairs. This file treats the same rules as
a decision table (TEST.md, "Test every row of the decision table"): five
independent failure sources, all `2**5` combinations enumerated, and exactly
one expected winner per combination. A gap (some combination reports the wrong
failure) or an overlap (the order stops being total) fails at the input that
causes it.
"""

from __future__ import annotations

from itertools import product

import pytest

from argbuilder import (
    Arg,
    ArgGroup,
    ArgMatches,
    ArgumentConflict,
    Command,
    Error,
    MissingRequiredArgument,
    MissingSubcommand,
    TooFewValues,
)

# The failure sources, in the order `_validate` checks them. Each key names
# one independent condition; each value is the error kind it produces.
SOURCES: list[tuple[str, type[object]]] = [
    ("conflict", ArgumentConflict),
    ("group_conflict", ArgumentConflict),
    ("missing_required", MissingRequiredArgument),
    ("arity", TooFewValues),
    ("missing_subcommand", MissingSubcommand),
]


def _cmd() -> Command:
    """A command whose failures can be switched on independently from argv."""
    return (
        Command("p")
        .arg(Arg("a").long("a").action("set_true").conflicts_with("b"))
        .arg(Arg("b").long("b").action("set_true"))
        .arg(Arg("m").long("m").action("set_true"))
        .arg(Arg("n").long("n").action("set_true"))
        .group(ArgGroup("g").args(["m", "n"]))
        .arg(Arg("z").long("z").required(True))
        .arg(Arg("pair").num_args(2, 2))
        .subcommand(Command("s"))
        .subcommand_required(True)
    )


def _argv(flags: tuple[bool, ...]) -> list[str]:
    conflict, group_conflict, missing_required, arity, missing_subcommand = flags
    argv: list[str] = []
    if conflict:  # `--b` present flips the conflict on
        argv += ["--a", "--b"]
    if group_conflict:  # `--n` present flips the group conflict on
        argv += ["--m", "--n"]
    if not missing_required:  # `--z` is required; omit it to flip the failure on
        argv += ["--z", "Z"]
    argv += ["1"] if arity else ["1", "2"]  # one pair value is too few
    if not missing_subcommand:  # passing `s` satisfies subcommand_required
        argv += ["s"]
    return argv


def _expected(flags: tuple[bool, ...]) -> type[object] | None:
    for (_, kind), present in zip(SOURCES, flags, strict=True):
        if present:
            return kind
    return None


COMBINATIONS = list(product([False, True], repeat=len(SOURCES)))
IDS = [
    "+".join(name for (name, _), present in zip(SOURCES, combo, strict=True) if present) or "none"
    for combo in COMBINATIONS
]


@pytest.mark.parametrize("flags", COMBINATIONS, ids=IDS)
def test_exactly_the_first_failure_is_reported(flags: tuple[bool, ...]) -> None:
    result = _cmd().try_get_matches_from(["p", *_argv(flags)])
    expected = _expected(flags)
    if expected is None:
        assert isinstance(result, ArgMatches), result
        return
    assert isinstance(result, Error), result
    assert type(result.kind) is expected


def test_failure_sources_are_independent() -> None:
    # Sanity: each flag on its own really does flip exactly its own failure,
    # so a wrong row above is a real ordering gap and not a dead switch.
    for index, (_name, kind) in enumerate(SOURCES):
        flags = [False] * len(SOURCES)
        flags[index] = True
        result = _cmd().try_get_matches_from(["p", *_argv(tuple(flags))])
        assert isinstance(result, Error), (index, result)
        assert type(result.kind) is kind, (index, result.kind)
