"""Unit tests for the GitHub settings sync in `scripts/github_settings.py`.

The script is loaded by path, like the release tooling: it is not part of the
installed package, and its `gh` boundary is replaced with an in-memory fake.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


settings = _load("github_settings")


def _desired() -> dict[str, Any]:
    return json.loads((ROOT / ".github" / "settings.json").read_text(encoding="utf-8"))


def test_shipped_settings_name_all_ci_jobs() -> None:
    rules = _desired()["branch_rulesets"]["main"]["rules"]
    checks = next(rule for rule in rules if rule["type"] == "required_status_checks")
    contexts = {item["context"] for item in checks["parameters"]["required_status_checks"]}
    assert contexts == {
        "Lint, type, build",
        "Python 3.12",
        "Python 3.13",
        "Python 3.14",
        "Python 3.15",
        "Completion",
        "Contract",
    }


def test_contains_ignores_order_and_allows_extra_fields() -> None:
    assert settings.contains(
        {"rules": [{"type": "a", "parameters": {"x": 1}}]}, {"rules": [{"type": "a"}]}
    )
    assert settings.contains({"methods": ["squash", "merge"]}, {"methods": ["merge", "squash"]})
    assert not settings.contains({"methods": ["squash"]}, {"methods": ["merge", "squash"]})
    assert not settings.contains({"value": 1}, {"value": 2})


def test_desired_rulesets_lists_branch_then_tag() -> None:
    names = [name for name, _ in settings.desired_rulesets(_desired())]
    assert names == ["main", "release-tags"]


def test_ruleset_payload_keeps_only_api_fields() -> None:
    payload = settings.ruleset_payload("main", {"target": "branch", "extra": True})
    assert payload == {"name": "main", "target": "branch"}


def test_ruleset_matches_accepts_extra_parameters() -> None:
    desired = {"target": "branch", "rules": [{"type": "deletion"}]}
    current = {"id": 1, "target": "branch", "rules": [{"type": "deletion", "parameters": None}]}
    assert settings.ruleset_matches(current, desired)


def test_list_rulesets_fetches_detail_for_summaries(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake(method: str, path: str, body: object | None = None) -> Any:
        calls.append(path)
        if path == "repos/{owner}/{repo}/rulesets":
            return [{"id": 7, "name": "main"}]
        if path == "repos/{owner}/{repo}/rulesets/7":
            return {"id": 7, "name": "main", "rules": [], "conditions": {}}
        raise AssertionError(path)

    monkeypatch.setattr(settings, "gh", fake)
    assert settings.list_rulesets()["main"]["rules"] == []
    assert calls == ["repos/{owner}/{repo}/rulesets", "repos/{owner}/{repo}/rulesets/7"]


def test_reviewer_logins_reads_the_protection_rule() -> None:
    environment = {
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"reviewer": {"login": "Tomperez98"}}],
            }
        ]
    }
    assert settings.reviewer_logins(environment) == {"Tomperez98"}
    assert settings.environment_prevent_self_review(environment) is False


def _fake_gh(monkeypatch: Any) -> dict[tuple[str, str], Any]:
    wanted = _desired()
    rulesets = [
        {"id": index, **settings.ruleset_payload(name, spec)}
        for index, (name, spec) in enumerate(settings.desired_rulesets(wanted), start=1)
    ]
    responses: dict[tuple[str, str], Any] = {
        ("GET", "repos/{owner}/{repo}"): {"allow_auto_merge": True},
        ("GET", "repos/{owner}/{repo}/actions/permissions"): {
            "enabled": True,
            "allowed_actions": "all",
            "sha_pinning_required": True,
        },
        ("GET", "repos/{owner}/{repo}/rulesets"): rulesets,
        ("GET", "repos/{owner}/{repo}/environments/pypi"): {
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [{"reviewer": {"login": "Tomperez98"}}],
                }
            ]
        },
        (
            "GET",
            "repos/{owner}/{repo}/environments/pypi/deployment-branch-policies",
        ): {"branch_policies": [{"id": 1, "name": "v*", "type": "tag"}]},
    }

    def fake(method: str, path: str, body: object | None = None) -> Any:
        return responses[(method, path)]

    monkeypatch.setattr(settings, "gh", fake)
    return responses


def test_check_reports_no_drift_for_the_shipped_state(monkeypatch: Any) -> None:
    _fake_gh(monkeypatch)
    assert settings.check_settings(_desired()) == []


def test_check_reports_drift(monkeypatch: Any) -> None:
    responses = _fake_gh(monkeypatch)
    responses[("GET", "repos/{owner}/{repo}")] = {"allow_auto_merge": False}
    responses[("GET", "repos/{owner}/{repo}/rulesets")] = []
    responses[("GET", "repos/{owner}/{repo}/actions/permissions")] = {
        "enabled": True,
        "allowed_actions": "all",
        "sha_pinning_required": False,
    }
    responses[("GET", "repos/{owner}/{repo}/environments/pypi")] = {"protection_rules": []}
    problems = settings.check_settings(_desired())
    assert any("allow_auto_merge" in problem for problem in problems)
    assert any("sha_pinning_required" in problem for problem in problems)
    assert any("ruleset main: missing" in problem for problem in problems)
    assert any("reviewers differ" in problem for problem in problems)


def test_apply_dry_run_never_writes(monkeypatch: Any) -> None:
    responses = _fake_gh(monkeypatch)
    responses[("GET", "users/Tomperez98")] = {"id": 72174660}
    calls: list[tuple[str, str]] = []

    def fake(method: str, path: str, body: object | None = None) -> Any:
        calls.append((method, path))
        return responses[(method, path)]

    monkeypatch.setattr(settings, "gh", fake)
    settings.apply_settings(_desired(), dry_run=True)
    assert not [call for call in calls if call[0] != "GET"]
