"""Compile-time pins for the public surface, enforced by `ty check`.

Runtime tests can pass while a signature drifts (a return type widens, a
generic collapses to `Any`), because nothing asserts the static type. This file
uses `typing.assert_type` — a no-op at runtime, a hard error under `ty check` in
CI — so the builder returns, the typed getters, and the derive entry points
cannot silently change shape. TEST.md, "Pin the important unions at compile
time".
"""

from __future__ import annotations

from typing import assert_type

from argbuilder import (
    Arg,
    ArgMatches,
    Command,
    Error,
    Parser,
    ValueParser,
    ValueSource,
)


class _Cli(Parser):
    name: str = "x"
    tag: tuple[str, ...] = ()


_CMD = (
    Command("p")
    .arg(Arg("name").long("name").default_value("x"))
    .arg(Arg("tag").short("t").action("append"))
    .arg(Arg("flag").long("flag").action("set_true"))
    .arg(Arg("v").short("v").action("count"))
)


def _matches() -> ArgMatches:
    result = _CMD.try_get_matches_from(["p"])
    assert isinstance(result, ArgMatches), result
    return result


def test_getter_signatures_are_pinned() -> None:
    matches = _matches()
    assert_type(matches.get_one("name", str), str | None)
    assert_type(matches.get_required("name", str), str)
    assert_type(matches.get_many("tag", str), tuple[str, ...])
    assert_type(matches.get_flag("flag"), bool)
    assert_type(matches.get_count("v"), int)
    assert_type(matches.value_source("name"), ValueSource | None)
    assert_type(matches.subcommand_name(), str | None)
    assert_type(matches.subcommand(), tuple[str, ArgMatches] | None)
    assert_type(matches.contains_id("name"), bool)


def test_builder_signatures_are_pinned() -> None:
    assert_type(Arg("x").short("x"), Arg)
    assert_type(Arg("x").long("x"), Arg)
    assert_type(Arg("x").action("count"), Arg)
    assert_type(Arg("x").value_parser(int), Arg)
    assert_type(Arg("x").required(True), Arg)
    assert_type(Command("p").arg(Arg("x")), Command)
    assert_type(Command("p").subcommand(Command("s")), Command)
    assert_type(Command("p").version("1"), Command)


def test_value_parser_signatures_are_pinned() -> None:
    assert_type(ValueParser.integer(), ValueParser[int])
    assert_type(ValueParser.integer(1, 2), ValueParser[int])
    assert_type(ValueParser.floating(), ValueParser[float])
    assert_type(ValueParser.boolean(), ValueParser[bool])
    assert_type(ValueParser.choices("a", "b"), ValueParser[str])
    assert_type(ValueParser.from_fn(int), ValueParser[int])


def test_derived_entry_points_are_pinned() -> None:
    assert_type(_Cli.try_parse_from(["p", "x"]), _Cli | Error)
    assert_type(_Cli.to_command(), Command)
