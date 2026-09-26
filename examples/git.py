"""A git-like CLI. Try: uv run examples/git.py --help, help clone, push -v --port 0, stage x."""

from pathlib import Path
from typing import Literal

from argbuilder import Arg, ArgMatches, Command, Error, ValueValidation

type Color = Literal["always", "auto", "never"]


def cli() -> Command:
    return (
        Command("git")
        .about("A fictional versioning CLI")
        .version("1.0.0")
        .subcommand_required(True)
        .arg(
            Arg("verbose")
            .short("v")
            .long("verbose")
            .action("count")
            .global_(True)
            .help("More output per occurrence")
        )
        .arg(
            Arg("color")
            .long("color")
            .value_name("WHEN")
            .value_parser(Color)
            .default_value("auto")
            .alias("colour")
            .global_(True)
            .help("Colorize output")
        )
        .subcommand(
            Command("clone")
            .about("Clones repos")
            .arg(Arg("remote").required(True).help("The remote to clone"))
            .arg(Arg("dir").value_parser(Path).help("Where to clone into"))
        )
        .subcommand(
            Command("push")
            .about("Pushes things")
            .arg(Arg("remote").help("The remote to target"))
            .arg(
                Arg("port")
                .short("p")
                .long("port")
                .value_parser(range(1, 65536))
                .env("GIT_PORT")
                .default_value("22")
            )
            .arg(Arg("force").short("f").long("force").action("set_true"))
        )
        .subcommand(
            Command("add")
            .about("Adds things")
            .visible_alias("stage")
            .arg(Arg("paths").action("append").required(True).value_parser(Path))
        )
    )


def run(matches: ArgMatches) -> str | Error:
    """Pure dispatch: matches in, output or an `Error` out. Easy to test without a process."""
    verbose = matches.get_count("verbose")
    color = matches.get_required("color", str)
    match matches.subcommand():
        case ("clone", sub):
            remote = sub.get_required("remote", str)
            if "://" not in remote and not remote.startswith("git@"):
                return sub.error(ValueValidation(), f"'{remote}' is not a remote URL")
            return f"cloning {remote} into {sub.get_one('dir', Path)}"
        case ("push", sub):
            force = " (forced)" if sub.get_flag("force") else ""
            port = sub.get_required("port", int)
            return f"pushing to {sub.get_one('remote', str)}:{port}{force} [v={verbose}, {color}]"
        case ("add", sub):
            return "adding " + ", ".join(str(path) for path in sub.get_many("paths", Path))
        case other:
            raise AssertionError(f"subcommand_required(True) guarantees a match, got {other!r}")


if __name__ == "__main__":
    result = run(cli().get_matches())
    if isinstance(result, Error):
        result.exit()
    print(result)
