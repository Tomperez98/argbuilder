"""Test configuration: the golden-file harness.

Complex rendered output (help, errors, wrapped/colored layouts) is compared
against a committed whole file rather than hand-written per-line strings, so
a layout change shows up as a reviewable diff. Add `--update-golden` to
rewrite the files, then read the diff before committing it.
"""

from __future__ import annotations

import difflib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

GOLDEN_DIR = Path(__file__).parent / "golden"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

_EXAMPLES: dict[str, ModuleType] = {}


def _import_example(name: str) -> ModuleType:
    """Import `examples/<name>.py` once per session, under a unique module name.

    Registering in `sys.modules` lets dataclasses resolve their annotations;
    caching keeps one class identity per example, so identity checks and
    `match` statements over derived subcommands hold.
    """
    if name in _EXAMPLES:
        return _EXAMPLES[name]
    spec = importlib.util.spec_from_file_location(
        f"argbuilder_example_{name}", EXAMPLES_DIR / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _EXAMPLES[name] = module
    return module


@pytest.fixture(scope="session")
def example() -> Callable[[str], ModuleType]:
    """Load a shipped example by name; see `_import_example`."""
    return _import_example


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="rewrite golden files instead of comparing against them",
    )


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Callable[[str, str], None]:
    """Compare rendered output with `tests/golden/<name>.txt`.

    Narrowing first: call it after asserting the value is the shape you
    expect, so a wrong variant never reads as a golden mismatch.
    """
    updating = request.config.getoption("--update-golden")

    def check(name: str, actual: str) -> None:
        path = GOLDEN_DIR / f"{name}.txt"
        if updating:
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8")
            return
        if not path.exists():
            pytest.fail(
                f"missing golden file 'golden/{name}.txt'; "
                "run `pytest --update-golden` to create it",
                pytrace=False,
            )
        expected = path.read_text(encoding="utf-8")
        if actual != expected:
            diff = "\n".join(
                difflib.unified_diff(
                    expected.splitlines(),
                    actual.splitlines(),
                    fromfile=f"golden/{name}.txt",
                    tofile="rendered now",
                    lineterm="",
                )
            )
            pytest.fail(
                f"golden mismatch for {name!r}:\n{diff}\n"
                "(run `pytest --update-golden` to accept the new output)",
                pytrace=False,
            )

    return check
