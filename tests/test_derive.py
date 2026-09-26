"""The derive API: classes describe a `Command`, parse results come back as instances."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Union

import pytest

from argbuilder import (
    Arg,
    Args,
    ArgumentConflict,
    Command,
    Error,
    InvalidValue,
    MissingRequiredArgument,
    MissingSubcommand,
    Parser,
    arg,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


def panics(match: str) -> pytest.RaisesExc[AssertionError]:
    return pytest.raises(AssertionError, match=match)


type Mode = Literal["fast", "safe"]


class Tool(Parser, name="tool", version="0.1.0"):
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


def parse[T: Parser](cls: type[T], *argv: str, env: dict[str, str] | None = None) -> T:
    result = cls.try_parse_from([cls.to_command().get_name(), *argv], env or {})
    assert not isinstance(result, Error), result.render()
    return result


def fail(cls: type[Parser], *argv: str) -> Error:
    result = cls.try_parse_from([cls.to_command().get_name(), *argv])
    assert isinstance(result, Error), result
    return result


def test_defaults_and_absent_values() -> None:
    assert parse(Tool, "in.txt") == Tool(
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
    tool = parse(
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
    assert parse(Tool, "in", env={"LEVEL": "9"}).level == 9


def test_instances_are_frozen() -> None:
    tool = parse(Tool, "in")
    with pytest.raises(dataclasses.FrozenInstanceError):
        tool.level = 1  # ty: ignore[invalid-assignment]


def test_user_mistakes_are_error_values() -> None:
    assert isinstance(fail(Tool).kind, MissingRequiredArgument)
    assert isinstance(fail(Tool, "in", "--level", "x").kind, InvalidValue)
    assert isinstance(fail(Tool, "in", "--mode", "slow").kind, InvalidValue)
    assert isinstance(fail(Tool, "in", "-o", "a", "-o", "b").kind, ArgumentConflict)


def test_help_is_derived() -> None:
    assert Tool.to_command().render_help() == (
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
    Tool.to_command().debug_assert()


# -- subcommands ----------------------------------------------------------------


class Shared(Args):
    json: bool = arg(long=True)


class Git(Parser):
    verbose: int = arg(short=True, action="count", global_=True)
    command: Clone | RemoteAdd


class Clone(Parser, visible_aliases=["cl"]):
    """Clones."""

    remote: str
    shared: Shared


class RemoteAdd(Parser):
    name: str


class Maybe(Parser):
    command: Clone | None = None


def test_subcommand_is_an_instance_of_its_class() -> None:
    git = parse(Git, "-v", "clone", "origin", "--json", "-v")
    assert git == Git(verbose=2, command=Clone(remote="origin", shared=Shared(json=True)))


def test_subcommand_names_are_kebab_case_with_aliases() -> None:
    assert parse(Git, "remote-add", "x").command == RemoteAdd(name="x")
    assert isinstance(parse(Git, "cl", "x").command, Clone)


def test_union_subcommand_is_required_and_none_makes_it_optional() -> None:
    assert isinstance(fail(Git).kind, MissingSubcommand)
    assert parse(Maybe).command is None
    assert parse(Maybe, "clone", "x").command == Clone(remote="x", shared=Shared(json=False))


def test_from_arg_matches_reads_an_extended_command() -> None:
    cmd = Git.to_command().arg(Arg("extra").long("extra").action("set_true"))
    matches = cmd.try_get_matches_from(["git", "--extra", "remote-add", "x"])
    assert not isinstance(matches, Error)
    assert matches.get_flag("extra")
    assert Git.from_arg_matches(matches) == Git(verbose=0, command=RemoteAdd(name="x"))


def test_to_command_is_cached() -> None:
    assert Git.to_command() is Git.to_command()


@pytest.mark.parametrize("sub", [[], ["clone"], ["push"], ["add"]])
def test_derived_example_matches_the_builder_example(
    sub: list[str], example: Callable[[str], ModuleType]
) -> None:
    built: Command = example("git").cli()
    derived: Command = example("git_derive").Git.to_command()
    argv = ["git", *(["help", *sub] if sub else ["--help"])]
    built_help = built.try_get_matches_from(argv)
    derived_help = derived.try_get_matches_from(argv)
    assert isinstance(built_help, Error) and isinstance(derived_help, Error)
    assert derived_help.render() == built_help.render()


# -- definition bugs ------------------------------------------------------------


class Cycle(Parser):
    command: Cycle


class Flat(Args):
    again: Flat


class HoldsFlat(Parser):
    flat: Flat


class Holder(Args):
    command: Clone


class HoldsHolder(Parser):
    holder: Holder


class Dupe(Parser, name="clone"):
    pass


class DuplicateNames(Parser):
    command: Clone | Dupe


def test_subcommand_cycle_panics() -> None:
    with panics("subcommands form a cycle: Cycle -> Cycle"):
        Cycle.to_command()


def test_flatten_cycle_panics() -> None:
    with panics("flattened Args form a cycle"):
        HoldsFlat.to_command()


def test_args_cannot_hold_a_subcommand() -> None:
    with panics("an Args class cannot hold a subcommand"):
        HoldsHolder.to_command()


def test_duplicate_subcommand_names_panic() -> None:
    with panics("are both named 'clone'"):
        DuplicateNames.to_command()


def test_field_hiding_a_method_panics_at_the_class_statement() -> None:
    with panics(r"field 'parse' would hide Parser.parse\(\)"):

        class Bad(Parser):
            parse: bool = arg(long=True)


def test_bad_class_option_panics_at_the_class_statement() -> None:
    with panics("Command name must be a non-empty str"):

        class Bad(Parser, name="has space"):
            pass


def test_default_factory_panics() -> None:
    with panics("default_factory is not supported"):

        class Bad(Parser):
            tags: tuple[str, ...] = dataclasses.field(default_factory=tuple)


def _bad_field(annotation: str, default: str = "") -> type[Parser]:
    """A one-field Parser, defined at module scope so its annotation resolves."""
    namespace: dict[str, object] = {}
    source = f"class Bad(Parser):\n    x: {annotation}{f' = {default}' if default else ''}\n"
    exec(source, globals(), namespace)  # noqa: S102
    bad = namespace["Bad"]
    assert isinstance(bad, type) and issubclass(bad, Parser)
    return bad


FIELD_BUGS: list[tuple[str, str, str]] = [
    ("list[str]", "", r"use tuple\[T, ...\] instead of list\[T\]"),
    ("tuple[str, str]", "", "a fixed-size tuple is not supported"),
    ("tuple[str, ...] | None", "", "drop '| None'"),
    ("int | str", "", "a union of"),
    ("Clone | int", "", "a union of Parser classes"),
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
        bad.to_command()
    assert "Bad.x" in f"{caught.value} {getattr(caught.value, '__notes__', [])}"


def test_bool_positional_panics_at_build() -> None:
    with panics("action 'set_true' needs short\\(\\) or long\\(\\)"):
        _bad_field("bool").to_command().debug_assert()


def test_two_subcommand_fields_panic() -> None:
    namespace: dict[str, object] = {}
    source = "class Bad(Parser):\n    a: Clone\n    b: RemoteAdd\n"
    exec(source, globals(), namespace)  # noqa: S102
    bad = namespace["Bad"]
    assert isinstance(bad, type) and issubclass(bad, Parser)
    with panics("already has subcommand field 'a'"):
        bad.to_command()


# -- remaining derive paths -----------------------------------------------------

from argbuilder._derive import _check_type  # noqa: E402


class Aliased(Parser, aliases=["al", "als"]):
    pass


class HasAliased(Parser):
    command: Aliased


class Configured(Parser):
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
    assert isinstance(parse(HasAliased, "als").command, Aliased)


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
    cmd = Configured.to_command()
    cmd.debug_assert()
    matches = Configured.try_parse_from(CONFIGURED_ARGV)
    assert isinstance(matches, Configured)
    assert (matches.point, matches.single, matches.empty) == ((3, 4), ("z",), ())
    assert matches.color == "auto"
    assert matches.on is False
    assert matches.mapping == {"ab": 2}
    tagged = Configured.try_parse_from([*CONFIGURED_ARGV, "--tags", "a,b"])
    assert isinstance(tagged, Configured) and tagged.tags == ("a", "b")
    colored = Configured.try_parse_from([*CONFIGURED_ARGV, "--color"])
    assert isinstance(colored, Configured) and colored.color == "always"


class Wired(Parser):
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
    cmd = Wired.to_command()
    cmd.debug_assert()
    help_text = cmd.render_help()
    assert "--hidden" not in help_text
    assert "--named <THING>" in help_text
    parsed = parse(Wired, "--n", "v", "--", "a", "b")
    assert (parsed.named, parsed.rest) == ("v", ("a", "b"))
    assert parse(Wired, "--hyphen", "-5").hyphen == "-5"
    assert isinstance(fail(Wired, "--hyphen", "x", "--toggle").kind, ArgumentConflict)
    assert isinstance(fail(Wired, "--needs", "y").kind, MissingRequiredArgument)


def test_parse_from_exits_on_error() -> None:
    with pytest.raises(SystemExit) as exited:
        Git.parse_from(["git"])
    assert exited.value.code == 2


def test_parse_reads_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["git", "remote-add", "x"])
    assert Git.parse().command == RemoteAdd(name="x")


def test_unresolvable_annotation_panics_with_a_note() -> None:
    namespace: dict[str, object] = {}
    exec("class Bad(Parser):\n    x: MissingName\n", globals(), namespace)  # noqa: S102
    bad = namespace["Bad"]
    with pytest.raises(NameError) as caught:
        bad.to_command()  # ty: ignore[unresolved-attribute]
    notes = " ".join(getattr(caught.value, "__notes__", []))
    assert "must be defined at module level" in notes


def test_check_type_without_an_explicit_parser_panics() -> None:
    with panics("unsupported field type"):
        _check_type("Bad.x", dict[str, int], explicit=False)
    assert _check_type("Bad.x", dict[str, int], explicit=True) is object


class TypingOptional(Parser):
    # `typing.Optional` / `typing.Union` resolve to `typing.Union` at runtime,
    # while `X | None` resolves to `types.UnionType`: two distinct code paths,
    # both of which must produce an optional field.
    count: Optional[int] = arg(long=True)  # noqa: UP045
    label: Union[str, None] = arg(long=True)  # noqa: UP007


class HTTPServer(Parser):
    pass


class MultiSentence(Parser):
    """Does one thing. And then another."""


def test_typing_optional_and_union_are_optional_fields() -> None:
    assert parse(TypingOptional) == TypingOptional(count=None, label=None)
    parsed = parse(TypingOptional, "--count", "3", "--label", "x")
    assert (parsed.count, parsed.label) == (3, "x")


def test_kebab_case_handles_acronyms() -> None:
    assert HTTPServer.to_command().get_name() == "http-server"


def test_about_keeps_the_period_of_a_multi_sentence_docstring() -> None:
    # A lone trailing period is dropped, but a docstring with a sentence break
    # keeps it (`_about` must not truncate the second sentence).
    assert (
        MultiSentence.to_command().render_help().startswith("Does one thing. And then another.\n")
    )


def test_parser_base_methods_panic() -> None:
    with panics("call it on a subclass"):
        Parser.to_command()
    with panics("call it on a subclass"):
        Parser.from_arg_matches(None)  # ty: ignore[invalid-argument-type]
