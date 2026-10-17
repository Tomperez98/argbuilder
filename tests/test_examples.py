"""The shipped example, exercised end to end.

`examples/git.py` is what users copy, so its help and errors are pinned as
goldens and its dispatch is checked directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from argbuilder import ArgMatches, Error

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


@pytest.fixture
def git(example: Callable[[str], ModuleType]) -> Any:
    return example("git")


def test_example_git_help(git: Any, golden: Callable[[str, str], None]) -> None:
    golden("example_git_help", git.cli().render_help())


def test_example_git_markdown(git: Any, golden: Callable[[str, str], None]) -> None:
    golden("markdown_example_git", git.cli().render_markdown())


def test_example_git_subcommand_help(git: Any, golden: Callable[[str, str], None]) -> None:
    result = git.cli().try_get_matches_from(["git", "help", "clone"])
    assert isinstance(result, Error)
    golden("example_git_help_clone", result.render())


def test_example_git_unknown_argument(git: Any, golden: Callable[[str, str], None]) -> None:
    result = git.cli().try_get_matches_from(["git", "--colourr", "clone", "x"])
    assert isinstance(result, Error)
    golden("example_git_error_unknown", result.render())


def test_example_git_definition_is_valid(git: Any) -> None:
    git.cli().debug_assert()


def test_example_git_clone_dispatch(git: Any) -> None:
    matches = git.cli().try_get_matches_from(["git", "clone", "https://example.com/x", "dest"])
    assert isinstance(matches, ArgMatches)
    assert git.run(matches) == "cloning https://example.com/x into dest"


def test_example_git_clone_rejects_a_non_url_as_a_value(
    git: Any,
    golden: Callable[[str, str], None],
) -> None:
    matches = git.cli().try_get_matches_from(["git", "clone", "not-a-url"])
    assert isinstance(matches, ArgMatches)
    result = git.run(matches)
    assert isinstance(result, Error)
    assert result.exit_code == 2
    golden("example_git_error_bad_remote", result.render())


def test_example_git_push_reads_the_environment_by_value(git: Any) -> None:
    # No os.environ mutation: the environment is an argument to the parser.
    matches = git.cli().try_get_matches_from(["git", "push"], {"GIT_PORT": "2222"})
    assert isinstance(matches, ArgMatches)
    assert git.run(matches) == "pushing to None:2222 [v=0, auto]"


def test_example_git_global_count_reaches_dispatch(git: Any) -> None:
    matches = git.cli().try_get_matches_from(["git", "-vv", "add", "a", "b"])
    assert isinstance(matches, ArgMatches)
    assert matches.get_count("verbose") == 2
    assert git.run(matches) == "adding a, b"
