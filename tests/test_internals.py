"""Defensive guards inside the parser and derive: unreachable from the public API.

Each of these is a panic meant to catch future misuse of an internal helper,
so the only way to exercise it is to call the helper directly.
"""

from __future__ import annotations

import dataclasses
import inspect
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from argbuilder import Arg, Command, arg, parser
from argbuilder._build import ResolvedArg, build
from argbuilder._derive import _fields, _read_subcommand, _Subcommand
from argbuilder._field import (
    _OPTION_APPLIERS,
    _SPECIAL_OPTIONS,
    FlagReader,
    ValueReader,
    _apply_options,
    _ArgOptions,
)
from argbuilder._parser import _Parser
from argbuilder._suggest import suggest

if TYPE_CHECKING:
    from collections.abc import Callable

    from argbuilder._spec import ArgSpec


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


@parser
class Leaf:
    pass


class _GhostMatches:
    def subcommand(self) -> tuple[str, None]:
        return ("ghost", None)


def test_suggest_is_one_shared_closeness_rule() -> None:
    assert suggest("saf", ["fast", "safe"]) == "safe"
    assert suggest("saf", {"fast", "safe"}) == "safe"
    assert suggest("zzz", ["fast", "safe"]) is None


def test_field_readers_are_inspectable_data() -> None:
    # Readers are descriptors, not closures, so the derivation can be asserted
    # without parsing anything.
    @parser
    class Sample:
        name: str
        tag: tuple[str, ...] = ()
        verbose: int = arg(action="count")

    assert _fields(Sample, ()).readers == (
        ValueReader(field="name", type_=str, getter="get_required"),
        ValueReader(field="tag", type_=str, getter="get_many"),
        FlagReader(field="verbose", counter=True),
    )


def test_subcommand_reader_panics_on_a_name_it_never_defined() -> None:
    sub = _Subcommand(
        where="X.command",
        field="command",
        by_name=MappingProxyType({"leaf": Leaf}),
        optional=False,
    )
    with pytest.raises(AssertionError, match="matched subcommand 'ghost'"):
        _read_subcommand(sub, _GhostMatches())  # ty: ignore[invalid-argument-type]


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


# -- derive option coverage ------------------------------------------------------
# `arg()`'s keywords, `_ArgOptions`'s fields and the appliers in `_value_field`
# must stay in lockstep. These tests turn "an option was added and forgotten"
# from a silent behavior bug into a failure.


def _option_cases() -> dict[str, tuple[_ArgOptions, Callable[[ArgSpec], bool]]]:
    """One non-default setting per applier, and what it must change in the spec."""
    return {
        "short": (_ArgOptions(short="s"), lambda spec: spec.short == "s"),
        "long": (_ArgOptions(long=True), lambda spec: spec.long == "dry-run"),
        "env": (_ArgOptions(env=True), lambda spec: spec.env == "DRY_RUN"),
        "help": (_ArgOptions(help="h"), lambda spec: spec.help == "h"),
        "value_name": (_ArgOptions(value_name="V"), lambda spec: spec.value_name == "V"),
        "num_args": (_ArgOptions(num_args=(0, 2)), lambda spec: spec.num_args == (0, 2)),
        "default_missing_value": (
            _ArgOptions(default_missing_value="d"),
            lambda spec: spec.default_missing_values == ("d",),
        ),
        "value_delimiter": (
            _ArgOptions(value_delimiter=","),
            lambda spec: spec.value_delimiter == ",",
        ),
        "aliases": (_ArgOptions(aliases=("hidden",)), lambda spec: spec.aliases == ("hidden",)),
        "visible_aliases": (
            _ArgOptions(visible_aliases=("shown",)),
            lambda spec: spec.visible_aliases == ("shown",),
        ),
        "short_aliases": (
            _ArgOptions(short_aliases=("q",)),
            lambda spec: spec.short_aliases == ("q",),
        ),
        "visible_short_aliases": (
            _ArgOptions(visible_short_aliases=("Q",)),
            lambda spec: spec.visible_short_aliases == ("Q",),
        ),
        "global_": (_ArgOptions(global_=True), lambda spec: spec.global_ is True),
        "hide": (_ArgOptions(hide=True), lambda spec: spec.hide is True),
        "allow_hyphen_values": (
            _ArgOptions(allow_hyphen_values=True),
            lambda spec: spec.allow_hyphen_values is True,
        ),
        "last": (_ArgOptions(last=True), lambda spec: spec.last is True),
        "conflicts_with": (
            _ArgOptions(conflicts_with=("other",)),
            lambda spec: spec.conflicts_with == frozenset({"other"}),
        ),
        "requires": (
            _ArgOptions(requires=("other",)),
            lambda spec: spec.requires == frozenset({"other"}),
        ),
    }


def test_arg_signature_matches_argoptions() -> None:
    signature = {name for name in inspect.signature(arg).parameters if name != "default"}
    fields = {field.name for field in dataclasses.fields(_ArgOptions)}
    assert signature == fields


def test_every_argoptions_field_is_applied_or_special() -> None:
    fields = {field.name for field in dataclasses.fields(_ArgOptions)}
    assert set(_OPTION_APPLIERS) | _SPECIAL_OPTIONS == fields
    assert not set(_OPTION_APPLIERS) & _SPECIAL_OPTIONS


def test_every_applier_has_a_behavioral_case() -> None:
    assert set(_option_cases()) == set(_OPTION_APPLIERS)


@pytest.mark.parametrize("option", sorted(_option_cases()))
def test_each_applier_changes_the_arg(option: str) -> None:
    options, changed = _option_cases()[option]
    built = _apply_options(Arg("dry_run").long("dry-run"), options, "dry_run")
    assert changed(built._spec)  # noqa: SLF001
