"""Shell completion: the pure engine, the protocol, and the rendered scripts."""

from __future__ import annotations

import io
import runpy
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from argbuilder import (
    Arg,
    ArgMatches,
    Command,
    Completion,
    CompletionDirective,
    CompletionResult,
    Error,
    InvalidSubcommand,
)
from argbuilder._completion import (
    _completion_request,
    _directive_bits,
    _format_result,
    _without_duplicates,
    write_completion,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CLI = runpy.run_path(str(Path(__file__).with_name("completion_cli.py")))["cli"]()


def values(result: CompletionResult) -> tuple[str, ...]:
    return tuple(candidate.value for candidate in result.candidates)


def result(*words: str) -> CompletionResult:
    return CLI.complete(["tool", *words])


# -- the candidate engine -------------------------------------------------------


def test_root_offers_visible_commands_and_options() -> None:
    candidates = result("")
    assert values(candidates) == (
        "add",
        "remote",
        "mode",
        "help",
        "--verbose",
        "--color",
        "--colour",
        "--config",
        "--workdir",
        "--help",
        "--version",
        "-v",
        "-w",
        "-h",
        "-V",
    )
    assert candidates.directive == CompletionDirective(no_file=True)


def test_root_hidden_subcommand_never_appears() -> None:
    assert "__internal" not in values(result(""))
    assert "__internal" not in values(result("__"))


def test_hidden_argument_never_appears() -> None:
    assert "--secret" not in values(result(""))
    assert not result("--secret").candidates


def test_prefix_filters_commands_and_flags() -> None:
    assert values(result("re")) == ("remote",)
    assert values(result("--col")) == ("--color", "--colour")
    assert values(result("--ver")) == ("--verbose", "--version")


def test_visible_alias_is_offered_but_hidden_alias_is_not() -> None:
    assert "--colour" in values(result("--col"))
    assert "--delete" not in values(result(""))


def test_command_aliases_are_offered_and_resolve() -> None:
    assert values(result("remote", "r")) == ("remove", "rm")
    assert values(result("remote", "rm", "")) == ("--verbose", "--help", "-v", "-h")


def test_subcommand_alias_can_be_completed() -> None:
    assert values(result("remote", "re")) == ("remove",)
    assert values(result("remote", "rm")) == ("rm",)


def test_short_flags_and_clusters() -> None:
    assert values(result("-")) == ("-v", "-w", "-h", "-V")
    assert values(result("-v")) == ("-v",)


def test_short_option_value_uses_the_same_parser() -> None:
    cmd = Command("p").arg(Arg("mode").short("m").value_parser(["a", "b"]))
    assert values(cmd.complete(["p", "-m", ""])) == ("a", "b")
    assert values(cmd.complete(["p", "-m="])) == ("-m=a", "-m=b")


def test_long_option_value_is_offered_with_the_flag_prefix() -> None:
    assert values(result("--color", "")) == ("always", "auto", "never")
    assert values(result("--color=a")) == ("--color=always", "--color=auto")
    assert values(result("--color=")) == ("--color=always", "--color=auto", "--color=never")


def test_unknown_value_after_equals_does_not_offer_files() -> None:
    cmd = Command("p").arg(Arg("name").long("name"))
    answer = cmd.complete(["p", "--name="])
    assert answer.candidates == ()
    assert answer.directive == CompletionDirective(no_file=True)


def test_path_hints_leave_completion_to_the_shell() -> None:
    file_answer = result("add", "")
    assert file_answer.candidates == ()
    assert file_answer.directive == CompletionDirective(filter_files=True)

    dir_answer = result("--workdir", "")
    assert dir_answer.candidates == ()
    assert dir_answer.directive == CompletionDirective(filter_dirs=True)

    executable = Command("p").arg(Arg("run").long("run").value_hint("executable"))
    executable_answer = executable.complete(["p", "--run", ""])
    assert executable_answer.directive == CompletionDirective(filter_files=True)

    config_equals = result("--config=")
    assert config_equals.candidates == ()
    assert config_equals.directive == CompletionDirective(no_file=True, filter_files=True)


def test_hint_dir_uses_the_directory_directive() -> None:
    cmd = Command("p").arg(Arg("where").long("where").value_hint("dir"))
    answer = cmd.complete(["p", "--where", ""])
    assert answer.directive == CompletionDirective(filter_dirs=True)


def test_a_required_value_consumes_the_next_word() -> None:
    assert set(values(result("--color", "auto", ""))) == {
        "add",
        "remote",
        "mode",
        "help",
        "--verbose",
        "--color",
        "--colour",
        "--config",
        "--workdir",
        "--help",
        "--version",
        "-v",
        "-w",
        "-h",
        "-V",
    }


def test_double_dash_stops_flag_and_command_completion() -> None:
    assert result("--", "--v").candidates == ()
    assert result("--", "--v").directive == CompletionDirective()
    assert result("add", "--", "").directive == CompletionDirective(filter_files=True)


def test_last_positional_is_not_offered_before_double_dash() -> None:
    cmd = Command("p").arg(Arg("before")).arg(Arg("after").last(True).value_parser(["x"]))
    before_dash = values(cmd.complete(["p", ""]))
    assert "x" not in before_dash
    assert values(cmd.complete(["p", "before", "--", ""])) == ("x",)


def test_help_subcommand_offers_the_parent_commands() -> None:
    assert values(result("help", "")) == ("add", "remote", "mode", "help")
    assert values(result("help", "re")) == ("remote",)
    assert result("help", "add", "").directive == CompletionDirective(filter_files=True)


def test_help_target_switches_to_the_target_command() -> None:
    assert set(values(result("help", "mode", ""))) == {
        "--verbose",
        "--help",
        "-v",
        "-h",
        "fast",
        "safe",
    }


def test_global_argument_is_offered_in_subcommands() -> None:
    assert "--verbose" in values(result("remote", ""))
    assert "-v" in values(result("remote", ""))


def test_option_aliases_work_for_values() -> None:
    assert values(result("--colour", "")) == ("always", "auto", "never")


def test_repeated_append_values_keep_the_value_context() -> None:
    cmd = Command("p").arg(Arg("tag").long("tag").action("append").value_parser(["a", "b"]))
    assert values(cmd.complete(["p", "--tag", "a", "--tag", ""])) == ("a", "b")


def test_a_variadic_option_keeps_the_value_context() -> None:
    cmd = Command("p").arg(
        Arg("tag").long("tag").num_args(1, None).value_parser(["a", "b"]),
    )
    assert values(cmd.complete(["p", "--tag", "a", ""])) == ("a", "b")


def test_optional_value_does_not_swallow_a_flag() -> None:
    cmd = Command("p").arg(
        Arg("color").long("color").num_args(0, 1).value_parser(["always", "never"]),
    )
    assert values(cmd.complete(["p", "--color", "--"])) == ("--color", "--help")


def test_short_cluster_with_inline_value_is_consumed() -> None:
    cmd = Command("p").arg(Arg("name").short("n")).arg(Arg("force").short("f").action("set_true"))
    answer = set(values(cmd.complete(["p", "-fn", "x", ""])))
    assert answer == {"-n", "-f", "-h", "--help"}


def test_escaped_hyphenated_value_is_a_value() -> None:
    cmd = Command("p").arg(Arg("value").allow_hyphen_values(True))
    assert cmd.complete(["p", "--", "-x", ""]).candidates == ()


def test_short_value_with_plain_equals_prefix() -> None:
    cmd = Command("p").arg(Arg("mode").short("m").value_parser(["a", "b"]))
    answer = cmd.complete(["p", "-m="])
    assert values(answer) == ("-m=a", "-m=b")


def test_option_without_a_parser_offers_no_values() -> None:
    answer = result("--config", "x", "")
    assert answer.directive == CompletionDirective(no_file=True)
    assert "add" in values(answer)
    assert not any(candidate.kind == "value" for candidate in answer.candidates)


def test_option_with_no_subcommands_and_no_positionals_still_disables_files() -> None:
    cmd = Command("p").arg(Arg("flag").short("f").action("set_true"))
    answer = cmd.complete(["p", ""])
    assert set(values(answer)) == {"-f", "-h", "--help"}
    assert answer.directive == CompletionDirective(no_file=True)


def test_an_inline_value_does_not_swallow_the_next_word() -> None:
    cmd = Command("p").arg(Arg("files").long("files").num_args(1, None)).subcommand(Command("sub"))
    assert "sub" in values(cmd.complete(["p", "--files=a", "sub"], cursor=2))
    assert "sub" in values(cmd.complete(["p", "--files=", "sub"], cursor=2))

    short = Command("p").arg(Arg("files").short("f").num_args(1, None)).subcommand(Command("sub"))
    assert "sub" in values(short.complete(["p", "-fa", "sub"], cursor=2))
    assert "sub" in values(short.complete(["p", "-f=", "sub"], cursor=2))


def test_double_dash_stops_a_pending_hyphen_value() -> None:
    cmd = (
        Command("p")
        .arg(Arg("values").long("values").num_args(0, None).allow_hyphen_values(True))
        .arg(Arg("first").value_parser(["x"]))
        .arg(Arg("second").value_parser(["y"]))
    )
    assert values(cmd.complete(["p", "--values", "--", "x", ""], cursor=4)) == ("y",)


def test_an_unknown_hyphen_word_starts_an_allow_hyphen_positional() -> None:
    cmd = (
        Command("p")
        .arg(Arg("first").allow_hyphen_values(True))
        .arg(Arg("second").value_parser(["a", "b"]))
    )
    assert {"a", "b"} <= set(values(cmd.complete(["p", "-x", ""], cursor=2)))
    assert {"a", "b"} <= set(values(cmd.complete(["p", "--foo", ""], cursor=2)))


def test_a_known_option_does_not_start_an_allow_hyphen_positional() -> None:
    cmd = (
        Command("p")
        .arg(Arg("verbose").short("v").long("verbose").action("set_true"))
        .arg(Arg("first").allow_hyphen_values(True))
        .arg(Arg("second").value_parser(["a", "b"]))
    )
    assert "a" not in values(cmd.complete(["p", "-v", ""], cursor=2))
    assert "a" not in values(cmd.complete(["p", "--verbose", ""], cursor=2))


def test_an_unknown_hyphen_word_is_a_positional_value_while_completing() -> None:
    cmd = Command("p").arg(Arg("path").allow_hyphen_values(True).value_hint("file"))
    assert cmd.complete(["p", "-x"], cursor=1).directive.filter_files
    assert cmd.complete(["p", "--foo"], cursor=1).directive.filter_files

    known = (
        Command("p")
        .arg(Arg("verbose").short("v").long("verbose").action("set_true"))
        .arg(Arg("path").allow_hyphen_values(True).value_hint("file"))
    )
    assert "-v" in values(known.complete(["p", "-v"], cursor=1))
    assert "--verbose" in values(known.complete(["p", "--verbose"], cursor=1))


def test_trailing_var_arg_with_allow_hyphen_consumes_a_hyphen_word() -> None:
    cmd = (
        Command("p")
        .arg(
            Arg("args").trailing_var_arg(True).num_args(0, None).allow_hyphen_values(True),
        )
        .subcommand(Command("sub"))
    )
    answer = cmd.complete(["p", "-x", ""], cursor=2)
    assert "sub" not in values(answer)
    assert answer.directive == CompletionDirective()


def test_words_after_the_cursor_are_ignored() -> None:
    cmd = Command("p").arg(Arg("mode").long("mode").value_parser(["a", "b"]))
    assert values(cmd.complete(["p", "--mode", "", "ignored"], cursor=2)) == ("a", "b")


def test_cursor_on_the_binary_name_has_no_candidates() -> None:
    assert CLI.complete(["tool", ""], cursor=0) == CompletionResult()


def test_default_cursor_is_the_last_word() -> None:
    assert values(CLI.complete(["tool", "re"])) == ("remote",)


def test_completion_invariants() -> None:
    with pytest.raises(AssertionError, match="not one str"):
        CLI.complete("tool")
    with pytest.raises(AssertionError, match="binary name"):
        CLI.complete([])
    with pytest.raises(AssertionError, match="must hold str"):
        CLI.complete(["tool", 1])
    with pytest.raises(AssertionError, match="cursor must be an int"):
        CLI.complete(["tool"], cursor=True)
    with pytest.raises(AssertionError, match="outside argv"):
        CLI.complete(["tool"], cursor=2)


def test_hint_validation_and_placement() -> None:
    for hint in ("any_path", "file", "dir", "executable"):
        Arg("x").value_hint(hint)  # type: ignore[arg-type]
    for hint in ("fil", "command", "username", "hostname", "env_var"):
        with pytest.raises(AssertionError, match="value_hint"):
            Arg("x").value_hint(hint)  # ty: ignore[invalid-argument-type]
    cmd = Command("p").arg(Arg("flag").long("flag").action("set_true").value_hint("file"))
    with pytest.raises(AssertionError, match="value_hint"):
        cmd.debug_assert()


def test_completion_result_helpers() -> None:
    assert Completion("x").help is None
    assert Completion("x", "help", "command").kind == "command"
    assert CompletionDirective() == CompletionDirective()


# -- the process protocol -------------------------------------------------------


def test_protocol_renders_candidates_and_directive() -> None:
    answer = CompletionResult(
        (
            Completion("alpha", "first\nline", "value"),
            Completion(":colon"),
            Completion("beta"),
        ),
        CompletionDirective(no_file=True, filter_dirs=True),
    )
    assert _format_result(answer) == ("C\talpha\tfirst line\nC\t:colon\nC\tbeta\nD\t3\n")


def test_write_completion_ignores_non_requests() -> None:
    stream = io.StringIO()
    assert not write_completion(CLI._resolved(), ["tool", "--help"], stream)  # noqa: SLF001
    assert stream.getvalue() == ""


def test_completion_request_rejects_bad_shapes() -> None:
    resolved = CLI._resolved()  # noqa: SLF001
    assert _completion_request(resolved, ["tool"]) is None
    assert _completion_request(resolved, ["tool", "other"]) is None
    assert _completion_request(resolved, ["tool", "__complete", "x", "tool"]) is None
    assert _completion_request(resolved, ["tool", "__complete", "3", "tool"]) is None


def test_a_real_complete_subcommand_disables_the_protocol() -> None:
    cmd = Command("p").subcommand(Command("__complete"))
    resolved = cmd._resolved()  # noqa: SLF001
    assert _completion_request(resolved, ["p", "__complete", "1", "p", ""]) is None


def test_get_matches_answers_completion_and_exits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["tool", "__complete", "1", "tool", ""])
    with pytest.raises(SystemExit) as exited:
        CLI.get_matches()
    assert exited.value.code == 0
    out = capsys.readouterr().out
    assert "C\tadd\tAdd files\n" in out
    assert out.endswith("D\t1\n")


def test_get_matches_answers_invalid_cursor_with_parser_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["tool", "__complete", "9", "tool", ""])
    with pytest.raises(SystemExit) as exited:
        CLI.get_matches()
    assert exited.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_render_completion_rejects_unknown_shells() -> None:
    with pytest.raises(AssertionError, match="render_completion"):
        CLI.render_completion("tcsh")  # type: ignore[arg-type]


def test_rendered_scripts_are_deterministic() -> None:
    for shell in ("bash", "zsh", "fish", "powershell"):
        assert CLI.render_completion(shell) == CLI.render_completion(shell)  # type: ignore[arg-type]


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
def test_rendered_scripts_use_the_command_name(
    shell: str,
    golden: Callable[[str, str], None],
) -> None:
    golden(f"completion_tool_{shell}", CLI.render_completion(shell))  # type: ignore[arg-type]


# -- hidden commands in the rest of the surface ---------------------------------


def test_hidden_subcommands_stay_out_of_help_and_markdown() -> None:
    assert "__internal" not in CLI.render_help()
    assert "__internal" not in CLI.render_markdown()
    assert "Internal command" not in CLI.render_help()


def test_hidden_subcommands_are_still_parseable() -> None:
    matches = CLI.try_get_matches_from(["tool", "__internal"])
    assert isinstance(matches, ArgMatches)
    assert matches.subcommand_name() == "__internal"


def test_hidden_subcommands_are_not_suggested() -> None:
    error = CLI.try_get_matches_from(["tool", "inter"])
    assert isinstance(error, Error)
    assert isinstance(error.kind, InvalidSubcommand)
    assert error.kind.name == "inter"


# -- internal branches that are hard to reach through a realistic CLI -----------


@pytest.mark.parametrize(
    ("directive", "bits"),
    [
        (CompletionDirective(), 0),
        (CompletionDirective(no_file=True), 1),
        (CompletionDirective(filter_dirs=True), 2),
        (CompletionDirective(filter_files=True), 4),
        (CompletionDirective(True, True, True), 7),
    ],
)
def test_directive_bits(directive: CompletionDirective, bits: int) -> None:
    assert _directive_bits(directive) == bits


def test_duplicate_candidates_are_removed() -> None:
    assert _without_duplicates([Completion("a"), Completion("a"), Completion("b")]) == [
        Completion("a"),
        Completion("b"),
    ]


def test_pending_value_is_abandoned_for_a_flag() -> None:
    cmd = (
        Command("p").arg(Arg("name").long("name")).arg(Arg("flag").long("flag").action("set_true"))
    )
    assert "--flag" in values(cmd.complete(["p", "--name", "--flag", ""]))


def test_walk_ignores_unknown_and_flag_long_options() -> None:
    cmd = (
        Command("p").arg(Arg("name").long("name")).arg(Arg("flag").long("flag").action("set_true"))
    )
    assert "--name" in values(cmd.complete(["p", "--unknown", ""]))
    assert "--name" in values(cmd.complete(["p", "--flag", ""]))


def test_walk_consumes_inline_long_and_short_values() -> None:
    cmd = (
        Command("p")
        .arg(Arg("name").long("name").short("n"))
        .arg(Arg("pair").long("pair").short("p").num_args(2, 2))
        .arg(Arg("flag").short("f").action("set_true"))
    )
    assert "--name" in values(cmd.complete(["p", "--name=x", ""]))
    assert "--pair" in values(cmd.complete(["p", "--pair=x", ""]))
    assert "-n" in values(cmd.complete(["p", "-nX", ""]))
    assert "-p" in values(cmd.complete(["p", "-p=x", ""]))
    assert "-f" in values(cmd.complete(["p", "-ff", ""]))


def test_unknown_short_in_a_cluster_is_ignored() -> None:
    cmd = Command("p").arg(Arg("flag").short("f").action("set_true"))
    assert "-f" in values(cmd.complete(["p", "-fz", ""]))


def test_extra_positionals_do_not_break_the_walk() -> None:
    cmd = Command("p").arg(Arg("one"))
    assert values(cmd.complete(["p", "a", "b", ""])) == ("--help", "-h")


def test_unknown_value_after_equals_on_long_and_short_flags() -> None:
    cmd = Command("p").arg(Arg("flag").long("flag").short("f").action("set_true"))
    assert cmd.complete(["p", "--flag=x"]).candidates == ()
    assert cmd.complete(["p", "-f=x"]).candidates == ()


def test_no_arguments_means_no_file_completion() -> None:
    cmd = Command("bare").disable_help_flag(True)
    answer = cmd.complete(["bare", ""])
    assert answer.candidates == ()
    assert answer.directive == CompletionDirective()


def test_choices_with_no_match_still_disable_files() -> None:
    answer = CLI.complete(["tool", "--color=zzz"])
    assert answer.candidates == ()
    assert answer.directive == CompletionDirective(no_file=True)


def test_allow_hyphen_value_stays_a_value() -> None:
    cmd = Command("p").arg(Arg("name").long("name").allow_hyphen_values(True))
    assert cmd.complete(["p", "--name", "-x"]).directive == CompletionDirective()


def test_allow_negative_numbers_treats_a_numeric_token_as_a_value() -> None:
    option = Command("p").arg(
        Arg("offset").long("offset").value_parser(int).allow_negative_numbers(True),
    )
    # A negative partial still gets value completion, not flag completion.
    assert option.complete(["p", "--offset", "-5"]).directive == CompletionDirective()

    positional = Command("p").arg(
        Arg("n").value_parser(["-5", "-6"]).allow_negative_numbers(True),
    )
    assert values(positional.complete(["p", "-5"])) == ("-5",)
    assert values(positional.complete(["p", "-5", ""])) == ("--help", "-h")


def test_allow_negative_numbers_completion_accepts_partial_numerics() -> None:
    option = Command("p").arg(
        Arg("offset").long("offset").allow_negative_numbers(True).value_parser(float),
    )
    assert option.complete(["p", "--offset", "-1."]).directive == CompletionDirective()
    assert option.complete(["p", "--offset", "-1e"]).directive == CompletionDirective()

    positional = Command("p").arg(
        Arg("n").allow_negative_numbers(True).value_hint("file"),
    )
    assert positional.complete(["p", "-1."]).directive == CompletionDirective(filter_files=True)


def test_a_numeric_token_still_completes_as_a_short_option_when_not_opted_in() -> None:
    cmd = Command("p").arg(Arg("five").short("5").action("set_true"))
    assert values(cmd.complete(["p", "-5"])) == ("-5",)


def test_allow_negative_numbers_does_not_claim_other_hyphen_tokens() -> None:
    cmd = Command("p").arg(
        Arg("n").allow_negative_numbers(True).value_hint("file"),
    )
    # `-x` is a flag-shaped token, so it gets option completion, not file values.
    assert cmd.complete(["p", "-x"]).directive == CompletionDirective(no_file=True)
    assert cmd.complete(["p", "-5"]).directive == CompletionDirective(filter_files=True)


def test_trailing_var_arg_completion_switches_after_the_first_value() -> None:
    cmd = (
        Command("p")
        .arg(Arg("verbose").long("verbose").action("set_true"))
        .arg(
            Arg("cmd").num_args(1, None).trailing_var_arg(True).value_parser(["cargo", "rustc"]),
        )
    )
    # Before the trailing positional starts, flags and its choices are offered.
    before = values(cmd.complete(["p", ""]))
    assert "--verbose" in before
    assert "cargo" in before

    # After it starts, only values remain: no flags, no `--` separator.
    after = values(cmd.complete(["p", "cargo", ""]))
    assert after == ("cargo", "rustc")
    assert values(cmd.complete(["p", "cargo", "build", ""])) == ("cargo", "rustc")
    assert "--verbose" not in after
    assert "--verbose" not in values(cmd.complete(["p", "cargo", "--v"]))
    assert "--help" not in values(cmd.complete(["p", "cargo", "--"]))


def test_trailing_var_arg_completion_keeps_path_hints() -> None:
    cmd = Command("p").arg(
        Arg("cmd").num_args(1, None).trailing_var_arg(True).value_hint("file"),
    )
    assert cmd.complete(["p", "cargo", ""]).directive == CompletionDirective(filter_files=True)


def test_require_equals_does_not_treat_the_next_word_as_a_value() -> None:
    cmd = (
        Command("p")
        .arg(
            Arg("color").long("color").num_args(0, 1).value_parser(["always"]).require_equals(True),
        )
        .arg(Arg("rest"))
    )
    # `--color` is complete; `always` is not a value the user can type next.
    assert "always" not in values(cmd.complete(["p", "--color", ""]))
    assert "always" not in values(cmd.complete(["p", "--color", "a"]))
    # The `=` spelling still offers choices while the `=` word is being typed.
    assert "--color=always" in values(cmd.complete(["p", "--color="]))

    short = (
        Command("p")
        .arg(
            Arg("color").short("c").num_args(0, 1).value_parser(["always"]).require_equals(True),
        )
        .arg(Arg("rest"))
    )
    assert "always" not in values(short.complete(["p", "-c", ""]))
    assert "-c=always" in values(short.complete(["p", "-c="]))


def test_root_cannot_be_hidden() -> None:
    with pytest.raises(AssertionError, match=r"hide\(\) only applies to subcommands"):
        Command("p").hide(True).debug_assert()


def test_only_hidden_subcommands_are_not_a_help_section() -> None:
    cmd = (
        Command("p")
        .disable_help_subcommand(True)
        .subcommand(Command("secret").hide(True).subcommand(Command("child")))
    )
    assert "Commands:" not in cmd.render_help()
    assert "secret" not in cmd.render_markdown()
    assert "child" not in cmd.render_markdown()
    assert "[COMMAND]" not in cmd.render_usage()


def test_last_only_positional_is_not_offered_before_double_dash() -> None:
    cmd = Command("p").arg(Arg("last").last(True).value_parser(["x"]))
    assert "x" not in values(cmd.complete(["p", ""]))
    assert values(cmd.complete(["p", "--", ""])) == ("x",)


def test_variadic_positional_keeps_the_positional_context() -> None:
    cmd = Command("p").arg(Arg("many").num_args(1, None).value_parser(["x"]))
    assert "x" in values(cmd.complete(["p", "a", "b", ""]))
