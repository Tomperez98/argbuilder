"""Release checks, run by the release workflows and by hand.

Stdlib only, so it runs in any interpreter, including a clean venv that has
nothing but the published wheel. Every check that fails is a broken
precondition: it exits non-zero with the artifact name and both values.

    python scripts/release.py tag                       # tag origin/main and push the tag
    python scripts/release.py check-dist VERSION        # dist/ holds exactly this release
    python scripts/release.py smoke VERSION EXAMPLES    # the installed package works
    python scripts/release.py preflight VERSION         # safe to publish dist/ to PyPI
    python scripts/release.py verify-pypi VERSION       # PyPI serves exactly dist/
    python scripts/release.py notes VERSION             # the mechanical part of the notes
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

PACKAGE = "argbuilder"
ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PYPI = "https://pypi.org/pypi"

# Network calls are expected to fail sometimes: retry a bounded number of
# times, then fail with the URL. PyPI's JSON API is cached, so a release can
# take a few minutes to appear after upload.
NETWORK_ATTEMPTS = 4
PROPAGATION_TIMEOUT_S = 600
POLL_INTERVAL_S = 20


def fail(message: str) -> NoReturn:
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "error: "
    sys.stderr.write(f"{prefix}{message}\n")
    raise SystemExit(1)


def say(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def parse_version(version: str) -> tuple[int, int, int]:
    """Only plain X.Y.Z releases: anything else is a mistake in the tag or pyproject."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        fail(f"version {version!r} is not X.Y.Z")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def expected_files(version: str) -> set[str]:
    return {f"{PACKAGE}-{version}-py3-none-any.whl", f"{PACKAGE}-{version}.tar.gz"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dist_digests() -> dict[str, str]:
    """Name -> sha256 for everything in dist/, ignoring the .gitignore uv writes."""
    if not DIST.is_dir():
        fail(f"{DIST} does not exist; run `mise run build` first")
    return {p.name: sha256(p) for p in sorted(DIST.iterdir()) if not p.name.startswith(".")}


def fetch_json(url: str) -> dict[str, object] | None:
    """The parsed body, or None on 404. Other failures retry, then fail."""
    if not url.startswith("https://"):
        fail(f"refusing to fetch non-https URL {url}")
    for attempt in range(1, NETWORK_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - https only, checked above
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            reason = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError) as error:
            reason = str(error)
        if attempt < NETWORK_ATTEMPTS:
            time.sleep(2**attempt)
    fail(f"GET {url} failed after {NETWORK_ATTEMPTS} attempts: {reason}")


def pypi_release(version: str) -> dict[str, str] | None:
    """Filename -> sha256 of the files PyPI has for `version`, or None if it has none."""
    body = fetch_json(f"{PYPI}/{PACKAGE}/{version}/json")
    if body is None:
        return None
    urls = body["urls"]
    assert isinstance(urls, list)
    return {file["filename"]: file["digests"]["sha256"] for file in urls}


def pypi_latest() -> str | None:
    body = fetch_json(f"{PYPI}/{PACKAGE}/json")
    if body is None:
        return None
    info = body["info"]
    assert isinstance(info, dict)
    return info["version"]


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S607 - fixed git argv
    if result.returncode != 0:
        fail(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def cmd_tag() -> None:
    """Tag the version on origin/main (never the local HEAD) and push the tag."""
    git("fetch", "--quiet", "--tags", "origin", "main")
    pyproject = tomllib.loads(git("show", "origin/main:pyproject.toml"))
    version = pyproject["project"]["version"]
    parse_version(version)
    tag = f"v{version}"
    if git("tag", "--list", tag):
        fail(
            f"tag {tag} already exists; bump the version in a PR first (`uv version --bump patch`)",
        )
    if git("ls-remote", "--tags", "origin", f"refs/tags/{tag}"):
        fail(f"tag {tag} already exists on origin")
    latest = pypi_latest()
    if latest is not None and parse_version(version) <= parse_version(latest):
        fail(f"version {version} on origin/main is not newer than {latest} on PyPI")
    commit = git("rev-parse", "origin/main")
    git("tag", "--annotate", tag, commit, "--message", f"{PACKAGE} {version}")
    git("push", "origin", f"refs/tags/{tag}")
    say(f"pushed {tag} -> {commit[:12]}; the Release workflow takes it from here")


def cmd_check_dist(version: str) -> None:
    parse_version(version)
    found = dist_digests()
    if set(found) != expected_files(version):
        fail(f"dist/ holds {sorted(found)}, expected {sorted(expected_files(version))}")
    for name, digest in found.items():
        say(f"{digest}  {name}")


def cmd_smoke(version: str, examples: str) -> None:
    """Check the installed package from the outside: version, location, examples."""
    installed = importlib.metadata.version(PACKAGE)
    if installed != version:
        fail(f"installed {PACKAGE} is {installed}, expected {version}")
    module = __import__(PACKAGE)
    location = Path(module.__file__).resolve()
    if ROOT / "src" in location.parents:
        fail(f"{PACKAGE} imported from the source tree ({location}), not an installed wheel")
    scripts = sorted(Path(examples).glob("*.py"))
    if not scripts:
        fail(f"no examples found in {examples}")
    for script in scripts:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or "Usage:" not in result.stdout:
            fail(
                f"{script.name} --help exited {result.returncode}:\n{result.stdout}{result.stderr}",
            )
    say(f"{PACKAGE} {installed} from {location.parent}: {len(scripts)} examples ran")


def cmd_preflight(version: str) -> None:
    """Safe to publish when the version is new, or is a partial upload of these exact bytes."""
    cmd_check_dist(version)
    local = dist_digests()
    published = pypi_release(version)
    if published is None:
        latest = pypi_latest()
        if latest is not None and parse_version(version) <= parse_version(latest):
            fail(f"version {version} is not newer than {latest} on PyPI; versions only go up")
        say(f"{version} is new on PyPI (latest: {latest})")
        return
    for name, digest in published.items():
        if local.get(name) != digest:
            fail(
                f"{name} on PyPI has sha256 {digest}, dist/ has {local.get(name)}; "
                f"{version} is taken, bump the version",
            )
    missing = sorted(set(local) - set(published))
    say(f"{version} is already on PyPI with the same bytes; still to upload: {missing or 'none'}")


def cmd_verify_pypi(version: str) -> None:
    """PyPI serves exactly dist/, and `latest` is this version. Waits for the CDN."""
    cmd_check_dist(version)
    local = dist_digests()
    deadline = time.monotonic() + PROPAGATION_TIMEOUT_S
    while True:
        published = pypi_release(version) or {}
        latest = pypi_latest()
        if set(published) == set(local) and latest == version:
            break
        if time.monotonic() > deadline:
            fail(
                f"after {PROPAGATION_TIMEOUT_S}s PyPI has {sorted(published)} for {version} "
                f"(expected {sorted(local)}) and latest={latest} (expected {version})",
            )
        time.sleep(POLL_INTERVAL_S)
    for name, digest in local.items():
        if published[name] != digest:
            fail(f"{name}: PyPI sha256 {published[name]}, built sha256 {digest}")
    say(f"PyPI serves {PACKAGE} {version} byte-for-byte, and it is the latest")


def cmd_notes(version: str) -> None:
    """Install and compatibility facts, from pyproject: people write the story."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    if project["version"] != version:
        fail(f"pyproject version is {project['version']}, expected {version}")
    say(
        f"Requires Python {project['requires-python']}. No dependencies.\n\n"
        f"```\npip install {PACKAGE}=={version}\n```\n\n"
        f"PyPI: https://pypi.org/project/{PACKAGE}/{version}/",
    )


def main(argv: list[str]) -> None:
    match argv:
        case ["tag"]:
            cmd_tag()
        case ["check-dist", version]:
            cmd_check_dist(version)
        case ["smoke", version, examples]:
            cmd_smoke(version, examples)
        case ["preflight", version]:
            cmd_preflight(version)
        case ["verify-pypi", version]:
            cmd_verify_pypi(version)
        case ["notes", version]:
            cmd_notes(version)
        case _:
            fail(f"unknown arguments {argv}\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
