"""The derive API: classes describe a `Command`, parse results come back as instances."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Union

import pytest

from argbuilder import (
    Arg,
    ArgumentConflict,
    Command,
    Error,
    InvalidValue,
    MissingRequiredArgument,
    MissingSubcommand,
    arg,
    args,
    from_arg_matches,
    parse,
    parse_from,
    parser as parser_deco,
    to_command,
    try_parse_from,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


def panics(match: str) -> pytest.RaisesExc[AssertionError]:
    return pytest.raises(AssertionError, match=match)


type Mode = Literal["fast", "safe"]


@parser_deco(name="tool", version="0.1.0")
class Tool:
    """Does things.

    More detail that stays out of `about`.
    """

    input: Path
    extra: tuple[str, ...]
    output: Path | None = arg(short=True, long=True)
    level: int = arg(short=True, long=True, default=3, env=True)
    mode: Mode = arg(long=True, default="safe")
    dry_run: bool = arg(long=True, help="Do nothing")
    keep: bool = arg(long="no-cleanup", action="set_false")
    verbose: int = arg(short=True, action="count")
    tag: tuple[str, ...] = arg(short=True, long=True)
    ratio: float = arg(long=True, default=0.5)


def parse_ok[T](cls: type[T], *argv: str, env: dict[str, str] | None = None) -> T:
    result = try_parse_from(cls, [to_command(cls).get_name(), *argv], env or {})
    assert not isinstance(result, Error), result.render()
    return result


def fail(cls: type, *argv: str) -> Error:
    result = try_parse_from(cls, [to_command(cls).get_name(), *argv])
    assert isinstance(result, Error), result
    return result


def test_defaults_and_absent_values() -> None:
    assert parse_ok(Tool, "in.txt") == Tool(
        input=Path("in.txt"),
        extra=(),
        output=None,
        level=3,
        mode="safe",
        dry_run=False,
        keep=True,
        verbose=0,
        tag=(),
        ratio=0.5,
    )


def test_every_field_kind() -> None:
    tool = parse_ok(
        Tool,
        *("in.txt", "a", "b", "-o", "out.txt", "--level", "7", "--mode", "fast"),
        *("--dry-run", "--no-cleanup", "-vv", "-t", "x", "--tag", "y", "--ratio", "2"),
    )
    assert tool.input == Path("in.txt")
    assert tool.extra == ("a", "b")
    assert tool.output == Path("out.txt")
    assert (tool.level, tool.mode, tool.ratio) == (7, "fast", 2.0)
    assert (tool.dry_run, tool.keep, tool.verbose) == (True, False, 2)
    assert tool.tag == ("x", "y")


def test_env_true_reads_the_uppercased_field_name() -> None:
    assert parse_ok(Tool, "in", env={"LEVEL": "9"}).level == 9


def test_instances_are_frozen() -> None:
    tool = parse_ok(Tool, "in")
    with pytest.raises(dataclasses.FrozenInstanceError):
        tool.level = 1  # ty: ignore[invalid-assignment]


def test_user_mistakes_are_error_values() -> None:
    assert isinstance(fail(Tool).kind, MissingRequiredArgument)
    assert isinstance(fail(Tool, "in", "--level", "x").kind, InvalidValue)
    assert isinstance(fail(Tool, "in", "--mode", "slow").kind, InvalidValue)
    assert isinstance(fail(Tool, "in", "-o", "a", "-o", "b").kind, ArgumentConflict)


def test_help_is_derived() -> None:
    assert to_command(Tool).render_help() == (
        "Does things\n"
        "\n"
        "Usage: tool [OPTIONS] <INPUT> [EXTRA]...\n"
        "\n"
        "Arguments:\n"
        "  <INPUT>\n"
        "  [EXTRA]...\n"
        "\n"
        "Options:\n"
        "  -o, --output <OUTPUT>\n"
        "  -l, --level <LEVEL>    [default: 3] [env: LEVEL]\n"
        "      --mode <MODE>      [default: safe] [possible values: fast, safe]\n"
        "      --dry-run          Do nothing\n"
        "      --no-cleanup\n"
        "  -v...\n"
        "  -t, --tag <TAG>\n"
        "      --ratio <RATIO>    [default: 0.5]\n"
        "  -h, --help             Print help\n"
        "  -V, --version          Print version\n"
    )


def test_debug_assert() -> None:
    to_command(Tool).debug_assert()


# -- subcommands ----------------------------------------------------------------


@args
class Shared:
    json: bool = arg(long=True)


@parser_deco
class Git:
    verbose: int = arg(short=True, action="count", global_=True)
    command: Clone | RemoteAdd


@parser_deco(visible_aliases=["cl"])
class Clone:
    """Clones."""

    remote: str
    shared: Shared


@parser_deco
class RemoteAdd:
    name: str


@parser_deco
class Maybe:
    command: Clone | None = None


def test_subcommand_is_an_instance_of_its_class() -> None:
    git = parse_ok(Git, "-v", "clone", "origin", "--json", "-v")
    assert git == Git(verbose=2, command=Clone(remote="origin", shared=Shared(json=True)))


def test_subcommand_names_are_kebab_case_with_aliases() -> None:
    assert parse_ok(Git, "remote-add", "x").command == RemoteAdd(name="x")
    assert isinstance(parse_ok(Git, "cl", "x").command, Clone)


def test_union_subcommand_is_required_and_none_makes_it_optional() -> None:
    assert isinstance(fail(Git).kind, MissingSubcommand)
    assert parse_ok(Maybe).command is None
    assert parse_ok(Maybe, "clone", "x").command == Clone(remote="x", shared=Shared(json=False))


def test_from_arg_matches_reads_an_extended_command() -> None:
    cmd = to_command(Git).arg(Arg("extra").long("extra").action("set_true"))
    matches = cmd.try_get_matches_from(["git", "--extra", "remote-add", "x"])
    assert not isinstance(matches, Error)
    assert matches.get_flag("extra")
    assert from_arg_matches(Git, matches) == Git(verbose=0, command=RemoteAdd(name="x"))


def test_to_command_is_cached() -> None:
    assert to_command(Git) is to_command(Git)


@pytest.mark.parametrize("sub", [[], ["clone"], ["push"], ["add"]])
def test_derived_example_matches_the_builder_example(
    sub: list[str],
    example: Callable[[str], ModuleType],
) -> None:
    built: Command = example("git").cli()
    derived_module = example("git_derive")
    derived: Command = derived_module.to_command(derived_module.Git)
    argv = ["git", *(["help", *sub] if sub else ["--help"])]
    built_help = built.try_get_matches_from(argv)
    derived_help = derived.try_get_matches_from(argv)
    assert isinstance(built_help, Error) and isinstance(derived_help, Error)
    assert derived_help.render() == built_help.render()


# -- definition bugs ------------------------------------------------------------


@parser_deco
class Cycle:
    command: Cycle


@args
class Flat:
    again: Flat


@parser_deco
class HoldsFlat:
    flat: Flat


@args
class Holder:
    command: Clone


@parser_deco
class HoldsHolder:
    holder: Holder


@parser_deco(name="clone")
class Dupe:
    pass


@parser_deco
class DuplicateNames:
    command: Clone | Dupe


def test_subcommand_cycle_panics() -> None:
    with panics("subcommands form a cycle: Cycle -> Cycle"):
        to_command(Cycle)


def test_flatten_cycle_panics() -> None:
    with panics("flattened @args form a cycle"):
        to_command(HoldsFlat)


def test_args_cannot_hold_a_subcommand() -> None:
    with panics("an @args class cannot hold a subcommand"):
        to_command(HoldsHolder)


def test_duplicate_subcommand_names_panic() -> None:
    with panics("are both named 'clone'"):
        to_command(DuplicateNames)


def test_a_class_cannot_be_decorated_with_both_parser_and_args() -> None:
    with panics("decorate with exactly one of @parser or @args"):

        @args
        @parser_deco
        class BadBoth:
            pass

    with panics("decorate with exactly one of @parser or @args"):

        @parser_deco
        @args
        class BadBothOther:
            pass


def test_bad_class_option_panics_at_decoration() -> None:
    with panics("Command name must be a non-empty str"):

        @parser_deco(name="has space")
        class Bad:
            pass


def test_default_factory_panics() -> None:
    with panics("default_factory is not supported"):

        @parser_deco
        class Bad:
            tags: tuple[str, ...] = dataclasses.field(default_factory=tuple)


def _bad_field(annotation: str, default: str = "") -> type:
    """A one-field @parser class, defined at module scope so its annotation resolves."""
    namespace: dict[str, object] = {}
    source = f"@parser_deco\nclass Bad:\n    x: {annotation}{f' = {default}' if default else ''}\n"
    exec(source, globals(), namespace)  # noqa: S102
    bad = namespace["Bad"]
    assert isinstance(bad, type)
    return bad


FIELD_BUGS: list[tuple[str, str, str]] = [
    ("list[str]", "", r"use tuple\[T, ...\] instead of list\[T\]"),
    ("tuple[str, str]", "", "a fixed-size tuple is not supported"),
    ("tuple[str, ...] | None", "", "drop '| None'"),
    ("int | str", "", "a union of"),
    ("Clone | int", "", "a union of @parser classes"),
    ("bool", "arg(long=True, default=True)", "use arg\\(action='set_false'\\)"),
    ("bool | None", "arg(long=True)", "action 'set_true' needs a 'bool' field"),
    ("str", "arg(long=True, action='count')", "action 'count' needs an 'int' field"),
    ("str", "arg(long=True, action='append')", r"annotate it tuple\[T, ...\]"),
    ("str", "arg(long=True, action='help')", "is not for fields"),
    ("str", "arg(long=True, action='cout')", "did you mean 'count'"),
    ("str", "arg(long=True, required=True)", "required=True is only for tuple"),
    ("int | None", "5", "a default of 5 means it is never None"),
    ("int", "arg(long=True, default='x')", "rejected by its value parser"),
    ("str", "arg(long=True, default=5)", "parses back as '5'"),
    ("int", "arg(long=True, value_parser=range(1, 5), default=9)", "9 is not in 1..=4"),
    ("tuple[int, ...]", "arg(long=True, default=1)", "must be a tuple"),
    ("Clone", "arg(long=True)", "arg\\(\\) does not apply to a subcommand"),
    ("Shared", "arg(long=True)", "takes no arg\\(\\) or default"),
    ("dict[str, int]", "arg(long=True)", "cannot infer a value parser"),
    ("str", "arg(short='xy')", "takes one character"),
]


@pytest.mark.parametrize(("annotation", "default", "message"), FIELD_BUGS)
def test_field_bugs_panic_naming_the_field(annotation: str, default: str, message: str) -> None:
    bad = _bad_field(annotation, default)
    with panics(message) as caught:
        to_command(bad)
    assert "Bad.x" in f"{caught.value} {getattr(caught.value, '__notes__', [])}"


def test_bool_positional_panics_at_build() -> None:
    with panics("action 'set_true' needs short\\(\\) or long\\(\\)"):
        to_command(_bad_field("bool")).debug_assert()


def test_two_subcommand_fields_panic() -> None:
    namespace: dict[str, object] = {}
    source = "@parser_deco\nclass Bad:\n    a: Clone\n    b: RemoteAdd\n"
    exec(source, globals(), namespace)  # noqa: S102
    bad = namespace["Bad"]
    assert isinstance(bad, type)
    with panics("already has subcommand field 'a'"):
        to_command(bad)


# -- remaining derive paths -----------------------------------------------------

from argbuilder._field import _check_type  # noqa: E402


@parser_deco(aliases=["al", "als"])
class Aliased:
    pass


@parser_deco
class HasAliased:
    command: Aliased


@parser_deco
class Configured:
    point: tuple[int, ...] = arg(long=True, num_args=(2, 2), value_parser=int, default=(1, 2))
    single: tuple[str, ...] = arg(long=True, num_args=1, default=("a",))
    empty: tuple[str, ...] = arg(long=True, default=())
    color: str = arg(long=True, num_args=(0, 1), default="auto", default_missing_value="always")
    tags: tuple[str, ...] = arg(long=True, num_args=(1, None), value_delimiter=",")
    mode: str = arg(
        long=True,
        visible_aliases=["m"],
        short_aliases=["M"],
        visible_short_aliases=["N"],
        requires=["on"],
    )
    on: bool = arg(long=True, action="set", default=True)
    mapping: dict[str, int] = arg(long=True, value_parser=lambda raw: {raw: len(raw)})
    maybe: int | None = None


def test_class_level_aliases_are_registered() -> None:
    assert isinstance(parse_ok(HasAliased, "als").command, Aliased)


CONFIGURED_ARGV = [
    "configured",
    "--point",
    "3",
    "4",
    "--single=z",
    "--mode",
    "x",
    "--on",
    "false",
    "--mapping",
    "ab",
]


def test_configured_fields_build() -> None:
    cmd = to_command(Configured)
    cmd.debug_assert()
    matches = try_parse_from(Configured, CONFIGURED_ARGV)
    assert isinstance(matches, Configured)
    assert (matches.point, matches.single, matches.empty) == ((3, 4), ("z",), ())
    assert matches.color == "auto"
    assert matches.on is False
    assert matches.mapping == {"ab": 2}
    tagged = try_parse_from(Configured, [*CONFIGURED_ARGV, "--tags", "a,b"])
    assert isinstance(tagged, Configured) and tagged.tags == ("a", "b")
    colored = try_parse_from(Configured, [*CONFIGURED_ARGV, "--color"])
    assert isinstance(colored, Configured) and colored.color == "always"


@parser_deco
class Wired:
    """Every arg() option the other fixtures do not name."""

    hidden: str | None = arg(long=True, hide=True)
    hyphen: str | None = arg(long=True, allow_hyphen_values=True)
    named: str | None = arg(long=True, value_name="THING", aliases=["n"])
    toggle: bool = arg(long=True, conflicts_with=["hyphen"])
    needs: str | None = arg(long=True, requires="hyphen")
    rest: tuple[str, ...] = arg(last=True)


def test_configured_fields_wire_every_builder_option() -> None:
    # Each option must survive `arg()` -> `_ArgOptions` -> the builder chain,
    # and `hide`, `aliases`, `conflicts_with`, `requires`, `allow_hyphen_values`
    # and `last` must reach parse behavior, not just the metadata.
    cmd = to_command(Wired)
    cmd.debug_assert()
    help_text = cmd.render_help()
    assert "--hidden" not in help_text
    assert "--named <THING>" in help_text
    parsed = parse_ok(Wired, "--n", "v", "--", "a", "b")
    assert (parsed.named, parsed.rest) == ("v", ("a", "b"))
    assert parse_ok(Wired, "--hyphen", "-5").hyphen == "-5"
    assert isinstance(fail(Wired, "--hyphen", "x", "--toggle").kind, ArgumentConflict)
    assert isinstance(fail(Wired, "--needs", "y").kind, MissingRequiredArgument)


def test_parse_from_exits_on_error() -> None:
    with pytest.raises(SystemExit) as exited:
        parse_from(Git, ["git"])
    assert exited.value.code == 2


def test_parse_reads_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["git", "remote-add", "x"])
    assert parse(Git).command == RemoteAdd(name="x")


def test_unresolvable_annotation_panics() -> None:
    namespace: dict[str, object] = {}
    exec("@parser_deco\nclass Bad:\n    x: MissingName\n", globals(), namespace)  # noqa: S102
    bad = namespace["Bad"]
    with pytest.raises(AssertionError, match="must be defined at module level"):
        to_command(bad)  # ty: ignore[invalid-argument-type]


def test_check_type_without_an_explicit_parser_panics() -> None:
    with panics("unsupported field type"):
        _check_type("Bad.x", dict[str, int], explicit=False)
    assert _check_type("Bad.x", dict[str, int], explicit=True) is object


@parser_deco
class TypingOptional:
    # `typing.Optional` / `typing.Union` resolve to `typing.Union` at runtime,
    # while `X | None` resolves to `types.UnionType`: two distinct code paths,
    # both of which must produce an optional field.
    count: Optional[int] = arg(long=True)  # noqa: UP045
    label: Union[str, None] = arg(long=True)  # noqa: UP007


@parser_deco
class HTTPServer:
    pass


@parser_deco
class MultiSentence:
    """Does one thing. And then another."""


def test_typing_optional_and_union_are_optional_fields() -> None:
    assert parse_ok(TypingOptional) == TypingOptional(count=None, label=None)
    parsed = parse_ok(TypingOptional, "--count", "3", "--label", "x")
    assert (parsed.count, parsed.label) == (3, "x")


def test_kebab_case_handles_acronyms() -> None:
    assert to_command(HTTPServer).get_name() == "http-server"


def test_about_keeps_the_period_of_a_multi_sentence_docstring() -> None:
    # A lone trailing period is dropped, but a docstring with a sentence break
    # keeps it (`_about` must not truncate the second sentence).
    assert to_command(MultiSentence).render_help().startswith("Does one thing. And then another.\n")


def test_undecorated_class_panics_on_the_entry_points() -> None:
    class Bad:
        pass

    with panics(r"to_command\(\): .* is not decorated with @parser"):
        to_command(Bad)
    with panics(r"from_arg_matches\(\): .* is not decorated with @parser"):
        from_arg_matches(Bad, None)  # ty: ignore[invalid-argument-type]
