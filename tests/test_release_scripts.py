"""Unit tests for the changelog parsing in `scripts/release.py`.

The release tooling is stdlib-only and runs as `python scripts/release.py`
(both by hand and from the release workflow), so it is loaded here by path
rather than imported from the installed package.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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
compat = _load("compat")


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


def test_manifest_records_checksums_and_the_commit(tmp_path: Path) -> None:
    wheel = tmp_path / "argbuilder-2.0.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    spec = tmp_path / "GitSpec.cs"
    spec.write_bytes(b"spec")
    record = release.manifest("2.0.0", "0" * 40, {"dist/wheel": wheel, "contract/spec": spec})
    assert record["package"] == "argbuilder"
    assert record["version"] == "2.0.0"
    assert record["commit"] == "0" * 40
    assert record["files"] == [
        {
            "path": "contract/spec",
            "sha256": hashlib.sha256(b"spec").hexdigest(),
            "size": 4,
        },
        {
            "path": "dist/wheel",
            "sha256": hashlib.sha256(b"wheel").hexdigest(),
            "size": 5,
        },
    ]


def test_verify_manifest_checks_downloaded_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "dist" / "argbuilder-2.0.0-py3-none-any.whl"
    artifact.parent.mkdir()
    artifact.write_bytes(b"wheel")
    record = release.manifest(
        "2.0.0", "0" * 40, {"dist/argbuilder-2.0.0-py3-none-any.whl": artifact}
    )
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(json.dumps(record), encoding="utf-8")

    release.verify_manifest(manifest, tmp_path, "dist/")

    artifact.write_bytes(b"tampered")
    with pytest.raises(SystemExit):
        release.verify_manifest(manifest, tmp_path, "dist/")


def test_diff_base_is_shortened_for_display() -> None:
    assert compat.short_ref("0123456789abcdef0123456789abcdef01234567") == "0123456"
    assert compat.short_ref("v1.1.1") == "v1.1.1"


def test_no_previous_contract_is_baseline_not_additive() -> None:
    label = compat.label_for(
        shape_ok=True, behavior_ok=True, added=set(), removed=set(), has_previous=False
    )
    assert label == "baseline"


def test_promises_added_by_this_change_are_additive() -> None:
    label = compat.label_for(
        shape_ok=True, behavior_ok=True, added={"p"}, removed=set(), has_previous=True
    )
    assert label == "additive"


def test_a_failing_check_beats_baseline() -> None:
    label = compat.label_for(
        shape_ok=False, behavior_ok=True, added=set(), removed=set(), has_previous=False
    )
    assert label == "breaking"


def test_baseline_does_not_block() -> None:
    assert compat.severity("baseline", declared=False) is None


def test_baseline_summary_names_the_diff_base() -> None:
    verdict = compat.Verdict(
        baseline="v1.1.0",
        diff_base="0123456789abcdef0123456789abcdef01234567",
        mode="v1.1.0 shipped no contract; today's spec judged its PyPI wheel (bootstrap)",
        shape_ok=True,
        behavior_ok=True,
        has_previous=False,
        added=set(),
        removed=set(),
        version="1.1.1",
    )
    text = verdict.summary()
    assert text.startswith("## Contract: baseline")
    assert "No contract at 0123456" in text
