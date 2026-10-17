"""A small, feature-rich CLI used by the completion tests.

Kept in its own module so the generated shell scripts can invoke it through a
launcher, exactly as a real installed console script would.
"""

from __future__ import annotations

from argbuilder import Arg, Command


def cli() -> Command:
    return (
        Command("tool")
        .about("A tool for testing completion")
        .version("1.0.0")
        .arg(
            Arg("verbose")
            .short("v")
            .long("verbose")
            .action("count")
            .global_(True)
            .help("More output per occurrence"),
        )
        .arg(
            Arg("color")
            .long("color")
            .visible_alias("colour")
            .value_parser(["always", "auto", "never"])
            .help("Colorize output"),
        )
        .arg(Arg("config").long("config").value_hint("file").help("Config file"))
        .arg(Arg("workdir").short("w").long("workdir").value_hint("dir").help("Working directory"))
        .arg(Arg("secret").long("secret").hide(True).help("Not offered"))
        .subcommand(
            Command("add")
            .about("Add files")
            .arg(
                Arg("paths")
                .action("append")
                .required(True)
                .value_hint("any_path")
                .help("Files to add"),
            ),
        )
        .subcommand(
            Command("remote")
            .about("Manage remotes")
            .subcommand(
                Command("add")
                .about("Add a remote")
                .arg(Arg("name").required(True).help("Remote name")),
            )
            .subcommand(
                Command("remove").about("Remove a remote").visible_alias("rm").alias("delete"),
            ),
        )
        .subcommand(
            Command("mode")
            .about("Set the mode")
            .arg(Arg("value").required(True).value_parser(["fast", "safe"]).help("Mode")),
        )
        .subcommand(Command("__internal").about("Internal command").hide(True))
    )
