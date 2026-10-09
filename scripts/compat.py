"""Compatibility and contract checks: an Accordant spec of the public parsing API judges argbuilder.

Stdlib only, like release.py. Needs uv and the .NET SDK on PATH; `compat`
also needs the release tags (`git fetch --tags`).

    python scripts/compat.py check     # this build against this spec
    python scripts/compat.py compat    # this build against a release's API and contract

`compat` picks the baseline release, then checks two layers against it:

- Shape: griffe diffs the public API against the baseline tag.
- Behavior: the baseline's spec judges this build. A baseline that shipped
  no contract is bootstrapped instead: today's spec judges its published
  wheel, and green means today's spec describes what users already have.

It labels the change (unchanged / additive / changed / breaking), writes the
label and a summary to .contract-compat/report/ (and the job summary on CI),
and fails only on an undeclared break: the baseline's contract rejects this
build and the major version didn't go up (ship skill, COMPAT.md rule 6).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from release import NETWORK_ATTEMPTS, ROOT, fail, git, parse_version, say

type Label = Literal["unchanged", "additive", "changed", "breaking"]
type Severity = Literal["error", "warning", "notice"]

CONTRACT = ROOT / "contract"
SPEC = "contract/Contract/GitSpec.cs"
WORK = ROOT / ".contract-compat"
REPORT = WORK / "report"

# A C# string literal (plain or interpolated) holding a promise: the spec's
# explanation strings read "<situation> → <outcome>".
LITERAL = re.compile(r'\$?"((?:[^"\\\n]|\\.)*)"')


# -- decisions (pure) ----------------------------------------------------------


def baseline_tag(merged: list[str], at_head: list[str], *, release: bool) -> str | None:
    """The release to judge against, from the release tags merged into HEAD (newest first).

    A release is judged against the release before it: that's where a break
    gets decided. Everything else (pull requests, main, scheduled runs) is
    judged against the latest release at or before HEAD, so a break that
    already shipped isn't re-reported on every run: a published version can't
    be fixed, only superseded (RELEASE.md rule 7).
    """
    skip = set(at_head) if release else set()
    return next((tag for tag in merged if tag not in skip), None)


def promises(source: str) -> set[str]:
    return {text for text in LITERAL.findall(source) if "→" in text}


def label_for(*, shape_ok: bool, behavior_ok: bool, added: set[str], removed: set[str]) -> Label:
    if not (shape_ok and behavior_ok):
        return "breaking"
    if removed:
        return "changed"
    if added:
        return "additive"
    return "unchanged"


def is_declared(version: str, baseline: str) -> bool:
    """A break is declared when the major version went up past the baseline's."""
    return parse_version(version)[0] > parse_version(baseline.removeprefix("v"))[0]


def severity(label: Label, *, declared: bool) -> Severity | None:
    """Only an undeclared break blocks.

    A reworded or removed promise that the old contract still accepts needs a
    reviewer, not a red build; a declared break is a fact for the release notes.
    """
    match label:
        case "breaking":
            return "notice" if declared else "error"
        case "changed":
            return "warning"
        case "unchanged" | "additive":
            return None


@dataclass(frozen=True, slots=True)
class Verdict:
    baseline: str
    mode: str
    shape_ok: bool
    behavior_ok: bool
    added: set[str]
    removed: set[str]
    version: str

    @property
    def label(self) -> Label:
        """What the change does to the contract."""
        return label_for(
            shape_ok=self.shape_ok,
            behavior_ok=self.behavior_ok,
            added=self.added,
            removed=self.removed,
        )

    @property
    def declared(self) -> bool:
        """Whether the version bump declares a break."""
        return is_declared(self.version, self.baseline)

    def summary(self) -> str:
        """The report posted on the pull request and the job summary, in Markdown."""

        def word(ok: bool) -> str:
            return "pass" if ok else "fail"

        lines = [
            f"## Contract: {self.label}",
            "",
            (
                f"Against {self.baseline} — shape: **{word(self.shape_ok)}**, "
                f"behavior: **{word(self.behavior_ok)}** ({self.mode})."
            ),
        ]
        if self.label == "breaking":
            lines.append("")
            lines.append(
                f"Declared break: {self.version} is a major bump over {self.baseline}."
                if self.declared
                else "**Undeclared break.** Fix the regression, or bump the major version "
                "(`uv version --bump major`) and describe the migration in the release notes."
            )
        if self.added or self.removed:
            lines += ["", "```diff"]
            lines += [f'- "{text}"' for text in sorted(self.removed)]
            lines += [f'+ "{text}"' for text in sorted(self.added)]
            lines.append("```")
        return "\n".join(lines) + "\n"


# -- effects ---------------------------------------------------------------------


def annotate(level: Severity, message: str) -> None:
    on_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    sys.stderr.write(f"::{level}::{message}\n" if on_ci else f"{level}: {message}\n")


def run(*argv: str, cwd: Path = ROOT) -> bool:
    """Run a command, streaming its output. False when it fails: that's a check's verdict."""
    if shutil.which(argv[0]) is None:
        fail(f"{argv[0]} is not on PATH")
    return subprocess.run(argv, cwd=cwd, check=False).returncode == 0


def judge(contract: Path, python: list[str], work: Path) -> bool:
    """The spec in `contract` picks the calls, `python` makes them, the spec judges the trace."""
    project = str(contract / "Contract")
    plan, trace = str(work / "plan.json"), str(work / "trace.json")
    return (
        run("dotnet", "run", "--project", project, "--", "export", plan)
        and run(*python, str(contract / "driver.py"), plan, trace)
        and run("dotnet", "run", "--project", project, "--", "check", trace)
    )


def install_release(version: str, venv: Path) -> list[str]:
    """A clean venv holding only the published wheel. PyPI is retried, then fails."""
    if not run("uv", "venv", "--quiet", "--python", "3.12", str(venv)):
        fail(f"could not create {venv}")
    python = str(venv / "bin" / "python")
    for attempt in range(1, NETWORK_ATTEMPTS + 1):
        if run("uv", "pip", "install", "--quiet", "--python", python, f"argbuilder=={version}"):
            return [python]
        if attempt < NETWORK_ATTEMPTS:
            time.sleep(2**attempt)
    fail(f"installing argbuilder=={version} from PyPI failed after {NETWORK_ATTEMPTS} attempts")


def cmd_check() -> None:
    if not judge(CONTRACT, ["uv", "run", "--no-sync", "python"], CONTRACT):
        fail("this build violates its own spec")


def cmd_compat() -> None:
    release = (
        os.environ.get("GITHUB_REF_TYPE") == "tag"
        or os.environ.get("CONTRACT_BASELINE") == "previous"
    )
    merged = git("tag", "--merged", "HEAD", "--list", "v[0-9]*", "--sort=-v:refname").split()
    at_head = git("tag", "--points-at", "HEAD", "--list", "v[0-9]*").split()
    baseline = baseline_tag(merged, at_head, release=release)
    if baseline is None:
        fail("no release tag before HEAD; fetch them with `git fetch --tags`")

    shutil.rmtree(WORK, ignore_errors=True)
    REPORT.mkdir(parents=True)

    say(f"== shape: public API against {baseline}")
    shape_ok = run(
        "uv", "run", "--no-sync", "griffe", "check", "argbuilder",
        "--search", "src", "--against", baseline,
    )  # fmt: skip

    old_spec = subprocess.run(
        ["git", "show", f"{baseline}:{SPEC}"],  # noqa: S607 - fixed git argv
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if old_spec.returncode == 0:
        mode = f"{baseline}'s contract judged this build"
        say(f"== behavior: {mode}")
        tree = WORK / "baseline"
        git("worktree", "add", "--quiet", "--detach", str(tree), baseline)
        try:
            behavior_ok = judge(tree / "contract", ["uv", "run", "--no-sync", "python"], WORK)
        finally:
            git("worktree", "remove", "--force", str(tree))
    else:
        mode = f"{baseline} shipped no contract; today's spec judged its PyPI wheel (bootstrap)"
        say(f"== behavior: {mode}")
        python = install_release(baseline.removeprefix("v"), WORK / "venv")
        behavior_ok = judge(CONTRACT, python, WORK)

    old = promises(old_spec.stdout) if old_spec.returncode == 0 else set()
    new = promises((ROOT / SPEC).read_text())
    verdict = Verdict(
        baseline=baseline,
        mode=mode,
        shape_ok=shape_ok,
        behavior_ok=behavior_ok,
        added=new - old,
        removed=old - new,
        version=tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
    )

    summary = verdict.summary()
    (REPORT / "summary.md").write_text(summary)
    (REPORT / "label").write_text(verdict.label + "\n")
    job_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if job_summary:
        with Path(job_summary).open("a") as file:
            file.write(summary)
    say(summary)

    match severity(verdict.label, declared=verdict.declared):
        case "error":
            fail(f"the build breaks the {baseline} contract and the version doesn't declare it")
        case "notice":
            annotate("notice", f"declared break against {baseline}: describe the migration")
        case "warning":
            annotate("warning", f"promises changed against {baseline}; a spec owner reviews")
        case None:
            pass


def main(argv: list[str]) -> None:
    match argv:
        case ["check"]:
            cmd_check()
        case ["compat"]:
            cmd_compat()
        case _:
            fail(f"unknown arguments {argv}\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
