"""Defensive guards inside the parser and derive: unreachable from the public API.

Each of these is a panic meant to catch future misuse of an internal helper,
so the only way to exercise it is to call the helper directly.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from argbuilder import Arg, Command, Parser
from argbuilder._build import ResolvedArg, build
from argbuilder._derive import _Subcommand, _subcommand_reader
from argbuilder._parser import _Parser


def _resolved() -> tuple[_Parser, ResolvedArg]:
    cmd = Command("x").arg(Arg("a").long("a"))
    resolved = build(cmd._spec)  # noqa: SLF001
    parser = _Parser(resolved, {}, (), {})
    return parser, resolved.by_long["a"]


def test_flag_panics_for_a_value_taking_argument() -> None:
    parser, arg = _resolved()
    with pytest.raises(AssertionError, match="value-taking argument 'a'"):
        parser._flag(arg, 0)  # noqa: SLF001


def test_parse_values_panics_without_a_parser() -> None:
    parser, arg = _resolved()
    broken = dataclasses.replace(arg, parser=None)
    with pytest.raises(AssertionError, match="takes values but has no parser"):
        parser._parse_values(broken, ["x"], None)  # noqa: SLF001


class Leaf(Parser):
    pass


class _GhostMatches:
    def subcommand(self) -> tuple[str, None]:
        return ("ghost", None)


def test_subcommand_reader_panics_on_a_name_it_never_defined() -> None:
    sub = _Subcommand(field="command", by_name=MappingProxyType({"leaf": Leaf}), optional=False)
    reader = _subcommand_reader("X.command", sub)
    with pytest.raises(AssertionError, match="matched subcommand 'ghost'"):
        reader(_GhostMatches())  # ty: ignore[invalid-argument-type]


# -- build caching ---------------------------------------------------------------


def test_build_is_cached_for_an_immutable_spec() -> None:
    spec = Command("x").arg(Arg("a").long("a"))._spec  # noqa: SLF001
    assert build(spec) is build(spec)


def test_a_broken_spec_is_not_cached() -> None:
    spec = Command("x").arg(Arg("a")).arg(Arg("a"))._spec  # noqa: SLF001
    with pytest.raises(AssertionError, match="defined more than once"):
        build(spec)
    with pytest.raises(AssertionError, match="defined more than once"):
        build(spec)
