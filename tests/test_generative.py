"""Properties checked against generated inputs, not just hand-picked ones.

The example tests pin specific renderings; these state the *rules* once and let
Hypothesis search hundreds of command shapes and values (TEST.md, "Test the
contract as properties"). The generated commands come from a fixed menu with
unique ids, so every draw is a valid definition — the search varies structure
and values, not validity.

If a property fails, keep the shrunk counterexample as a plain example test so
it stays pinned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypothesis import given, settings, strategies as st

from argbuilder import Arg, ArgMatches, Command, Style
from argbuilder._help import option_label, positional_label
from argbuilder._style import MAX_WIDTH, MIN_WIDTH, style_for

if TYPE_CHECKING:
    from collections.abc import Callable

SETTINGS = settings(max_examples=40, deadline=None)


def _input() -> Arg:
    return Arg("input").required(True).help("The input file")


def _rest() -> Arg:
    return Arg("rest").action("append").help("Extra values, any number")


def _level() -> Arg:
    return Arg("level").short("l").long("level").value_parser(["low", "high"]).help("How hard")


def _tag() -> Arg:
    return Arg("tag").short("t").long("tag").action("append")


def _force() -> Arg:
    return Arg("force").short("f").long("force").action("set_true").help("Force it")


def _verbose() -> Arg:
    return Arg("verbose").short("v").action("count")


def _secret() -> Arg:
    return Arg("secret").long("secret").hide(True)


def _mode() -> Arg:
    return Arg("mode").long("mode").default_value("auto")


# Insertion order matters: `rest` is variadic, so it must stay after `input`.
# Positional args are emitted in menu order regardless of the draw order.
_MENU: dict[str, Callable[[], Arg]] = {
    "input": _input,
    "rest": _rest,
    "level": _level,
    "tag": _tag,
    "force": _force,
    "verbose": _verbose,
    "secret": _secret,
    "mode": _mode,
}
_ORDER = list(_MENU)


@st.composite
def commands(draw: st.DrawFn) -> Command:
    keys = sorted(
        draw(st.lists(st.sampled_from(_ORDER), unique=True, max_size=5)),
        key=_ORDER.index,
    )
    cmd = Command("tool").about("A generated tool used to check rendering properties")
    for key in keys:
        cmd = cmd.arg(_MENU[key]())
    if draw(st.booleans()):
        cmd = cmd.subcommand(
            Command("run").about("Runs it").arg(Arg("target").required(True).help("What to run")),
        )
    return cmd


@SETTINGS
@given(commands())
def test_help_and_markdown_document_the_same_labels(cmd: Command) -> None:
    # `_docs` reuses `_help`'s labels verbatim; this pins that they can never
    # drift: every visible argument appears in both, every hidden one in neither.
    resolved = cmd._resolved()  # noqa: SLF001
    help_text = cmd.render_help()
    markdown = cmd.render_markdown()
    for arg in resolved.args:
        label = option_label(arg) if not arg.is_positional else positional_label(arg)
        label = label.strip()
        if arg.hide:
            assert label not in help_text, (label, help_text)
            assert label not in markdown, (label, markdown)
        else:
            assert label in help_text, (label, help_text)
            assert label in markdown, (label, markdown)
    for sub in resolved.subcommands.values():
        assert sub.name in help_text
        assert sub.name in markdown


@SETTINGS
@given(commands())
def test_wrapping_only_moves_whitespace(cmd: Command) -> None:
    wide = cmd.render_help().split()
    for width in (MIN_WIDTH, 30, 50, MAX_WIDTH):
        assert cmd.render_help(Style(width=width)).split() == wide, width


@SETTINGS
@given(commands())
def test_color_only_adds_escape_codes(cmd: Command) -> None:
    colored = cmd.render_help(Style(color=True, width=50))
    plain = cmd.render_help(Style(width=50))
    assert _strip_ansi(colored) == plain


def _strip_ansi(text: str) -> str:
    for code in ("\x1b[1m", "\x1b[4m", "\x1b[31m", "\x1b[32m", "\x1b[0m"):
        text = text.replace(code, "")
    return text


@SETTINGS
@given(
    is_tty=st.booleans(),
    columns=st.one_of(st.none(), st.integers(min_value=-5, max_value=500)),
    no_color=st.one_of(st.none(), st.text(max_size=4)),
    term=st.one_of(st.none(), st.text(max_size=6)),
    override=st.one_of(st.none(), st.text(max_size=4)),
)
def test_style_for_always_respects_its_bounds(
    is_tty: bool,
    columns: int | None,
    no_color: str | None,
    term: str | None,
    override: str | None,
) -> None:
    env: dict[str, str] = {}
    if no_color is not None:
        env["NO_COLOR"] = no_color
    if term is not None:
        env["TERM"] = term
    if override is not None:
        env["COLUMNS"] = override
    style = style_for(is_tty=is_tty, columns=columns, env=env)
    assert style.width is not None
    assert MIN_WIDTH <= style.width <= MAX_WIDTH
    if style.color:
        # Color requires a terminal and passes both opt-outs.
        assert is_tty
        assert env.get("NO_COLOR", "") == ""
        assert env.get("TERM") != "dumb"


_SAFE_VALUE = st.text(alphabet=st.characters(blacklist_characters="=-"), min_size=1)


@SETTINGS
@given(_SAFE_VALUE)
def test_every_option_spelling_parses_to_the_same_value(value: str) -> None:
    cmd = Command("p").arg(Arg("name").short("n").long("name"))
    spellings = [
        ["--name", value],
        [f"--name={value}"],
        ["-n", value],
        [f"-n{value}"],
        [f"-n={value}"],
    ]
    results = []
    for argv in spellings:
        matches = cmd.try_get_matches_from(["p", *argv])
        assert isinstance(matches, ArgMatches), (argv, matches)
        results.append(matches.get_one("name", str))
    assert results == [value] * len(spellings), results
