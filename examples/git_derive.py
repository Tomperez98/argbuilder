"""`examples/git.py`, derived from classes. Try: uv run examples/git_derive.py --help."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from argbuilder import Error, ValueValidation, arg, parse, parser, to_command

type Color = Literal["always", "auto", "never"]


@parser(version="1.0.0")
class Git:
    """A fictional versioning CLI."""

    verbose: int = arg(
        short=True,
        long=True,
        action="count",
        global_=True,
        help="More output per occurrence",
    )
    color: Color = arg(
        long=True,
        default="auto",
        value_name="WHEN",
        aliases="colour",
        global_=True,
        help="Colorize output",
    )
    command: Clone | Push | Add


@parser
class Clone:
    """Clones repos."""

    remote: str = arg(help="The remote to clone")
    dir: Path | None = arg(help="Where to clone into")


@parser
class Push:
    """Pushes things."""

    remote: str | None = arg(help="The remote to target")
    port: int = arg(
        short=True,
        long=True,
        value_parser=range(1, 65536),
        env="GIT_PORT",
        default=22,
    )
    force: bool = arg(short=True, long=True)


@parser(visible_aliases=["stage"])
class Add:
    """Adds things."""

    paths: tuple[Path, ...] = arg(required=True)


def run(git: Git) -> str | Error:
    """Pure dispatch: a `Git` in, output or an `Error` out."""
    match git.command:
        case Clone(remote=remote, dir=dir):
            if "://" not in remote and not remote.startswith("git@"):
                return to_command(Git).error(ValueValidation(), f"'{remote}' is not a remote URL")
            return f"cloning {remote} into {dir}"
        case Push(remote=remote, port=port, force=force):
            forced = " (forced)" if force else ""
            return f"pushing to {remote}:{port}{forced} [v={git.verbose}, {git.color}]"
        case Add(paths=paths):
            return "adding " + ", ".join(str(path) for path in paths)


if __name__ == "__main__":
    result = run(parse(Git))
    if isinstance(result, Error):
        result.exit()
    print(result)  # noqa: T201
