"""Properties that hold for every completion request, not one example per case."""

from __future__ import annotations

import runpy
from pathlib import Path

from hypothesis import given, settings, strategies as st

from argbuilder import (
    Arg,
    ArgMatches,
    Command,
    CompletionResult,
    Error,
    InvalidSubcommand,
    UnknownArgument,
)

CLI = runpy.run_path(str(Path(__file__).with_name("completion_cli.py")))["cli"]()
SETTINGS = settings(max_examples=50, deadline=None)


@SETTINGS
@given(st.text(max_size=20))
def test_completion_never_raises(prefix: str) -> None:
    assert isinstance(CLI.complete(["tool", prefix]), CompletionResult)


@SETTINGS
@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz-_", max_size=10))
def test_root_candidates_match_the_prefix(prefix: str) -> None:
    assert all(
        candidate.value.startswith(prefix)
        for candidate in CLI.complete(["tool", prefix]).candidates
    )


@SETTINGS
@given(st.text(max_size=20))
def test_hidden_things_never_leak(prefix: str) -> None:
    for candidate in CLI.complete(["tool", prefix]).candidates:
        assert candidate.value not in {"__internal", "--secret"}


@SETTINGS
@given(st.sampled_from(["", "a", "ad", "r", "re", "rem", "m", "h", "he"]))
def test_every_visible_subcommand_candidate_parses(prefix: str) -> None:
    for candidate in CLI.complete(["tool", prefix]).candidates:
        if candidate.kind != "command" or candidate.value == "help":
            continue
        parsed = CLI.try_get_matches_from(["tool", candidate.value])
        if isinstance(parsed, Error):
            assert not isinstance(parsed.kind, (InvalidSubcommand, UnknownArgument))
        else:
            assert isinstance(parsed, ArgMatches)


@SETTINGS
@given(st.sampled_from(["always", "auto", "never"]))
def test_every_choice_candidate_parses(value: str) -> None:
    candidate = f"--color={value}"
    assert candidate in {item.value for item in CLI.complete(["tool", "--color="]).candidates}
    assert isinstance(CLI.try_get_matches_from(["tool", candidate]), ArgMatches)


@SETTINGS
@given(
    st.sampled_from(
        [
            ["tool", ""],
            ["tool", "--color", ""],
            ["tool", "--color="],
            ["tool", "mode", ""],
            ["tool", "add", ""],
        ],
    ),
)
def test_protocol_is_one_candidate_per_line_plus_a_directive(words: list[str]) -> None:
    result = CLI.complete(words)
    rendered = CLI.complete(words)
    assert rendered == result
    from argbuilder._completion import _format_result

    lines = _format_result(result).splitlines()
    assert len(lines) == len(result.candidates) + 1
    assert lines[-1].startswith("D\t")
    assert all(line.startswith("C\t") for line in lines[:-1])
    assert all(line.count("\t") <= 2 for line in lines[:-1])


def test_a_choice_value_never_offers_a_file() -> None:
    cmd = Command("p").arg(Arg("mode").long("mode").value_parser(["a", "b"]))
    assert cmd.complete(["p", "--mode", ""]).directive.no_file
    assert cmd.complete(["p", "--mode="]).directive.no_file
