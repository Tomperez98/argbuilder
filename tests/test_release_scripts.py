"""Unit tests for the changelog parsing in `scripts/release.py`.

The release tooling is stdlib-only and runs as `python scripts/release.py`
(both by hand and from the release workflow), so it is loaded here by path
rather than imported from the installed package.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"

SAMPLE = """\
# Changelog

## [Unreleased]

## [2.0.0] - 2026-01-02

### Changed (breaking)

- `retry(n)` now takes a policy. Migrate: `retry(3)` becomes `retry(Policy(3))`.

## [1.0.0] - 2025-01-01

### Added

- First release.

[2.0.0]: https://example.com/compare/v1.0.0...v2.0.0
[1.0.0]: https://example.com/releases/tag/v1.0.0
"""


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load("release")


def test_entries_are_split_by_version_heading() -> None:
    assert list(release.changelog_entries(SAMPLE)) == ["Unreleased", "2.0.0", "1.0.0"]


def test_entry_drops_trailing_link_definitions() -> None:
    assert release.changelog_entry(SAMPLE, "1.0.0") == "### Added\n\n- First release."


def test_missing_version_has_no_entry() -> None:
    assert release.changelog_entry(SAMPLE, "3.0.0") is None


def test_breaking_heading_is_recognized() -> None:
    assert release.is_breaking(SAMPLE, "2.0.0")
    assert not release.is_breaking(SAMPLE, "1.0.0")
    assert not release.is_breaking(SAMPLE, "3.0.0")


def test_shipped_changelog_covers_the_current_version() -> None:
    """`release:tag` and `preflight` require this section; keep it true on main."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    source = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release.changelog_entry(source, project["project"]["version"]) is not None
