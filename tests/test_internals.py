"""Defensive guards inside the parser: unreachable from the public API.

Each of these is a panic meant to catch future misuse of an internal helper,
so the only way to exercise it is to call the helper directly.
"""

from __future__ import annotations

import dataclasses

import pytest

from argbuilder import Arg, Command
from argbuilder._build import ResolvedArg, build
from argbuilder._completion import _State
from argbuilder._invariant import bug
from argbuilder._parser import _Parser
from argbuilder._suggest import suggest


def _resolved() -> tuple[_Parser, ResolvedArg]:
    cmd = Command("x").arg(Arg("a").long("a"))
    resolved = build(cmd._spec)  # noqa: SLF001
    parser = _Parser(resolved, {}, (), {}, given_globals=set(), raw_globals={})
    return parser, resolved.by_long["a"]


def test_flag_panics_for_a_value_taking_argument() -> None:
    parser, arg = _resolved()
    with pytest.raises(AssertionError, match="value-taking argument 'a'"):
        parser._flag(arg, 0)  # noqa: SLF001


def test_trailing_values_without_a_trailing_positional_panics() -> None:
    parser, _ = _resolved()
    with pytest.raises(AssertionError, match="trailing mode without a trailing positional"):
        parser._trailing_values(["x"], 0)  # noqa: SLF001


def test_parse_values_panics_without_a_parser() -> None:
    parser, arg = _resolved()
    broken = dataclasses.replace(arg, parser=None)
    with pytest.raises(AssertionError, match="takes values but has no parser"):
        parser._parse_values(broken, ["x"], None)  # noqa: SLF001


def test_consume_pending_without_a_pending_argument_panics() -> None:
    state = _State(build(Command("x")._spec))  # noqa: SLF001
    with pytest.raises(AssertionError, match="pending argument disappeared"):
        state._consume_pending()  # noqa: SLF001


def test_bug_chains_the_underlying_cause() -> None:
    cause = ValueError("boom")
    with pytest.raises(AssertionError, match="wrapped") as raised:
        bug("wrapped", cause)
    assert raised.value.__cause__ is cause


def test_suggest_is_one_shared_closeness_rule() -> None:
    assert suggest("saf", ["fast", "safe"]) == "safe"
    assert suggest("saf", {"fast", "safe"}) == "safe"
    assert suggest("zzz", ["fast", "safe"]) is None


def test_build_is_cached_for_an_immutable_spec() -> None:
    spec = Command("x").arg(Arg("a").long("a"))._spec  # noqa: SLF001
    assert build(spec) is build(spec)


def test_a_broken_spec_is_not_cached() -> None:
    spec = Command("x").arg(Arg("a")).arg(Arg("a"))._spec  # noqa: SLF001
    with pytest.raises(AssertionError, match="defined more than once"):
        build(spec)
    with pytest.raises(AssertionError, match="defined more than once"):
        build(spec)
