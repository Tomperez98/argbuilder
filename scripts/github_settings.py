"""Apply and check the GitHub settings this repository depends on.

The desired state lives in `.github/settings.json`; this script makes the live
repository match it. `apply` is idempotent, and `check` exits non-zero when
anything has drifted. Requires `gh` authenticated as a repository admin.

    python scripts/github_settings.py apply
    python scripts/github_settings.py apply --dry-run
    python scripts/github_settings.py check

The script never prints a token. GitHub's ruleset and environment reads are
public for a public repository, but `actions/permissions` needs admin auth, so
the release checklist runs `check` with the maintainer's `gh` login.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / ".github" / "settings.json"


class GhError(RuntimeError):
    """`gh api` refused or failed; the message names the call and its stderr."""


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(1)


def gh(method: str, path: str, body: object | None = None) -> Any:
    """One `gh api` call. JSON in, parsed JSON out (or None for an empty body)."""
    command = ["gh", "api", "--method", method, path]
    input_text = None
    if body is not None:
        command.extend(["--input", "-"])
        input_text = json.dumps(body)
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        message = f"{method} {path}: {detail}"
        raise GhError(message)
    text = result.stdout.strip()
    return json.loads(text) if text else None


def load_settings(path: Path = SETTINGS) -> dict[str, Any]:
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {path}: {error}")
    if not isinstance(settings, dict):
        fail(f"{path} must hold a JSON object")
    return settings


def contains(actual: object, desired: object) -> bool:
    """Whether `actual` already has every value in `desired` (lists as unordered sets)."""
    if isinstance(desired, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(actual[key], value) for key, value in desired.items()
        )
    if isinstance(desired, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(desired)
            and all(any(contains(item, wanted) for item in actual) for wanted in desired)
        )
    return actual == desired


def desired_rulesets(settings: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every named ruleset in the file, branch first, preserving its rules."""
    rulesets: list[tuple[str, dict[str, Any]]] = []
    for group in ("branch_rulesets", "tag_rulesets"):
        entries = settings.get(group, {})
        if not isinstance(entries, dict):
            fail(f"{group} must be an object")
        for name, spec in entries.items():
            if not isinstance(spec, dict):
                fail(f"{group}.{name} must be an object")
            rulesets.append((name, spec))
    return rulesets


def ruleset_payload(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    fields = ("target", "enforcement", "conditions", "rules", "bypass_actors")
    return {"name": name, **{field: spec[field] for field in fields if field in spec}}


def ruleset_matches(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    return all(
        contains(current.get(field), value) for field, value in desired.items() if field != "name"
    )


def list_rulesets() -> dict[str, dict[str, Any]]:
    """Every ruleset by name. The list endpoint returns summaries, so fetch details."""
    result: dict[str, dict[str, Any]] = {}
    for summary in gh("GET", "repos/{owner}/{repo}/rulesets"):
        if "rules" in summary and "conditions" in summary:
            result[summary["name"]] = summary
            continue
        detail = gh("GET", f"repos/{{owner}}/{{repo}}/rulesets/{summary['id']}")
        result[detail["name"]] = detail
    return result


def apply_rulesets(settings: dict[str, Any], *, dry_run: bool) -> None:
    existing = list_rulesets()
    for name, spec in desired_rulesets(settings):
        current = existing.get(name)
        payload = ruleset_payload(name, spec)
        if current is not None and ruleset_matches(current, payload):
            say(f"ruleset {name}: unchanged")
            continue
        if current is None:
            say(f"ruleset {name}: create")
            if not dry_run:
                gh("POST", "repos/{owner}/{repo}/rulesets", payload)
        else:
            say(f"ruleset {name}: update")
            if not dry_run:
                gh("PUT", f"repos/{{owner}}/{{repo}}/rulesets/{current['id']}", payload)


def check_rulesets(settings: dict[str, Any]) -> list[str]:
    existing = list_rulesets()
    problems: list[str] = []
    for name, spec in desired_rulesets(settings):
        current = existing.get(name)
        if current is None:
            problems.append(f"ruleset {name}: missing")
        elif not ruleset_matches(current, ruleset_payload(name, spec)):
            problems.append(f"ruleset {name}: differs from .github/settings.json")
    return problems


def apply_repository(settings: dict[str, Any], *, dry_run: bool) -> None:
    desired = settings.get("repository", {})
    if not isinstance(desired, dict):
        fail("repository must be an object")
    current = gh("GET", "repos/{owner}/{repo}")
    for key, value in desired.items():
        if current.get(key) == value:
            say(f"repository {key}: unchanged")
            continue
        say(f"repository {key}: {current.get(key)!r} -> {value!r}")
        if not dry_run:
            gh("PATCH", "repos/{owner}/{repo}", {key: value})


def check_repository(settings: dict[str, Any]) -> list[str]:
    desired = settings.get("repository", {})
    current = gh("GET", "repos/{owner}/{repo}")
    return [
        f"repository {key}: {current.get(key)!r}, expected {value!r}"
        for key, value in desired.items()
        if current.get(key) != value
    ]


def apply_actions(settings: dict[str, Any], *, dry_run: bool) -> None:
    desired = settings.get("actions", {})
    if not isinstance(desired, dict):
        fail("actions must be an object")
    current = gh("GET", "repos/{owner}/{repo}/actions/permissions")
    changes = {key: value for key, value in desired.items() if current.get(key) != value}
    if not changes:
        say("actions: unchanged")
        return
    for key, value in changes.items():
        say(f"actions {key}: {current.get(key)!r} -> {value!r}")
    if not dry_run:
        gh(
            "PUT",
            "repos/{owner}/{repo}/actions/permissions",
            {
                "enabled": current["enabled"],
                "allowed_actions": current["allowed_actions"],
                "sha_pinning_required": changes.get(
                    "sha_pinning_required", current["sha_pinning_required"]
                ),
            },
        )


def check_actions(settings: dict[str, Any]) -> list[str]:
    desired = settings.get("actions", {})
    current = gh("GET", "repos/{owner}/{repo}/actions/permissions")
    return [
        f"actions {key}: {current.get(key)!r}, expected {value!r}"
        for key, value in desired.items()
        if current.get(key) != value
    ]


def reviewer_logins(environment: dict[str, Any]) -> set[str]:
    logins: set[str] = set()
    for rule in environment.get("protection_rules", []):
        if rule.get("type") != "required_reviewers":
            continue
        for reviewer in rule.get("reviewers", []):
            login = reviewer.get("reviewer", {}).get("login")
            if isinstance(login, str):
                logins.add(login)
    return logins


def environment_prevent_self_review(environment: dict[str, Any]) -> bool:
    for rule in environment.get("protection_rules", []):
        if rule.get("type") == "required_reviewers":
            return bool(rule.get("prevent_self_review", False))
    return False


def deployment_policies(name: str) -> list[dict[str, Any]]:
    try:
        body = gh("GET", f"repos/{{owner}}/{{repo}}/environments/{name}/deployment-branch-policies")
    except GhError as error:
        if "Not Found" in str(error):
            return []
        raise
    return body.get("branch_policies", [])


def environment_matches(name: str, spec: dict[str, Any], current: dict[str, Any]) -> bool:
    if reviewer_logins(current) != set(spec.get("reviewers", [])):
        return False
    if environment_prevent_self_review(current) != spec.get("prevent_self_review", False):
        return False
    wanted = {(tag, "tag") for tag in spec.get("deployment_tags", [])}
    have = {(policy["name"], policy["type"]) for policy in deployment_policies(name)}
    return have == wanted


def apply_environment(name: str, spec: dict[str, Any], *, dry_run: bool) -> None:
    current = gh("GET", f"repos/{{owner}}/{{repo}}/environments/{name}")
    reviewer_ids = [gh("GET", f"users/{login}")["id"] for login in spec.get("reviewers", [])]
    payload = {
        "reviewers": [{"type": "User", "id": reviewer_id} for reviewer_id in reviewer_ids],
        "prevent_self_review": spec.get("prevent_self_review", False),
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
    }
    if environment_matches(name, spec, current):
        say(f"environment {name}: unchanged")
        return
    say(f"environment {name}: update reviewers and deployment branches")
    if dry_run:
        return
    gh("PUT", f"repos/{{owner}}/{{repo}}/environments/{name}", payload)
    wanted = {(tag, "tag") for tag in spec.get("deployment_tags", [])}
    existing = deployment_policies(name)
    have = {(policy["name"], policy["type"]) for policy in existing}
    for policy in existing:
        if (policy["name"], policy["type"]) not in wanted:
            gh(
                "DELETE",
                f"repos/{{owner}}/{{repo}}/environments/{name}/deployment-branch-policies/{policy['id']}",
            )
    for tag, kind in sorted(wanted - have):
        gh(
            "POST",
            f"repos/{{owner}}/{{repo}}/environments/{name}/deployment-branch-policies",
            {"name": tag, "type": kind},
        )


def check_environment(name: str, spec: dict[str, Any]) -> list[str]:
    current = gh("GET", f"repos/{{owner}}/{{repo}}/environments/{name}")
    problems: list[str] = []
    if reviewer_logins(current) != set(spec.get("reviewers", [])):
        problems.append(f"environment {name}: reviewers differ")
    if environment_prevent_self_review(current) != spec.get("prevent_self_review", False):
        problems.append(f"environment {name}: prevent_self_review differs")
    wanted = {(tag, "tag") for tag in spec.get("deployment_tags", [])}
    have = {(policy["name"], policy["type"]) for policy in deployment_policies(name)}
    if have != wanted:
        problems.append(
            f"environment {name}: deployment branches {sorted(have)}, expected {sorted(wanted)}"
        )
    return problems


def apply_settings(settings: dict[str, Any], *, dry_run: bool) -> None:
    apply_repository(settings, dry_run=dry_run)
    apply_actions(settings, dry_run=dry_run)
    apply_rulesets(settings, dry_run=dry_run)
    environments = settings.get("environments", {})
    if not isinstance(environments, dict):
        fail("environments must be an object")
    for name, spec in environments.items():
        apply_environment(name, spec, dry_run=dry_run)


def check_settings(settings: dict[str, Any]) -> list[str]:
    problems = check_repository(settings)
    problems.extend(check_actions(settings))
    problems.extend(check_rulesets(settings))
    environments = settings.get("environments", {})
    if not isinstance(environments, dict):
        fail("environments must be an object")
    for name, spec in environments.items():
        problems.extend(check_environment(name, spec))
    return problems


def main(argv: list[str]) -> None:
    try:
        match argv:
            case ["apply"]:
                apply_settings(load_settings(), dry_run=False)
            case ["apply", "--dry-run"]:
                apply_settings(load_settings(), dry_run=True)
            case ["check"]:
                problems = check_settings(load_settings())
                if problems:
                    fail("drift:\n" + "\n".join(f"  {problem}" for problem in problems))
                say("GitHub settings match .github/settings.json")
            case _:
                fail(f"unknown arguments {argv}\n{__doc__}")
    except GhError as error:
        fail(str(error))


if __name__ == "__main__":
    main(sys.argv[1:])
