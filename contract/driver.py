"""Run the contract's test plan against whichever argbuilder is installed.

    python contract/driver.py PLAN TRACE

Reads the sequences the spec exported (`contract/plan.json`), makes each call
through argbuilder's public API, and writes what came back as a trace for the
spec to judge (`dotnet run --project contract/Contract -- check TRACE`).

Stdlib plus argbuilder only, so it runs in a clean venv holding nothing but a
published wheel. That's how one release's contract judges another build.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from argbuilder import (
    Arg,
    ArgMatches,
    Command,
    Error,
    InvalidSubcommand,
    InvalidValue,
    MissingRequiredArgument,
    UnknownArgument,
)


def cli() -> Command:
    """The fixture the spec describes (contract/Contract/GitSpec.cs)."""
    return (
        Command("git")
        .version("1.0.0")
        .subcommand_required(True)
        .arg(Arg("verbose").short("v").long("verbose").action("count"))
        .subcommand(
            Command("push")
            .arg(Arg("remote").required(True))
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
    )


def respond(result: ArgMatches | Error) -> dict[str, Any]:
    """Everything a caller can observe about one parse, as the spec's ParseResponse."""
    if isinstance(result, Error):
        response: dict[str, Any] = {
            "outcome": type(result.kind).__name__,
            "exitCode": result.exit_code,
        }
        match result.kind:
            case InvalidValue(argument=argument, value=value, env=env):
                response |= {"argument": argument, "value": value, "fromEnv": env}
            case UnknownArgument(argument=argument):
                response["argument"] = argument
            case InvalidSubcommand(name=name):
                response["argument"] = name
            case MissingRequiredArgument(arguments=arguments):
                response["argument"] = ", ".join(arguments)
            case _:
                pass
        return response

    response = {"outcome": "Matches", "exitCode": 0, "verbose": result.get_count("verbose")}
    match result.subcommand():
        case ("push", push):
            response |= {
                "subcommand": "push",
                "remote": push.get_required("remote", str),
                "port": push.get_required("port", int),
                "portSource": push.value_source("port"),
                "force": push.get_flag("force"),
            }
        case other:
            response["subcommand"] = None if other is None else other[0]
    return response


def call(operation: str, request: dict[str, Any]) -> dict[str, Any]:
    if operation != "Parse":
        sys.stderr.write(
            f"error: the plan names operation {operation!r}, the driver has only Parse\n"
        )
        raise SystemExit(1)
    return respond(cli().try_get_matches_from(request["Argv"], request["Env"]))


def main(plan_path: str, trace_path: str) -> None:
    plan = json.loads(Path(plan_path).read_text())
    trace = []
    for case in plan:
        steps = []
        for operation_call in case["OperationCalls"]:
            operation = operation_call["Input"]["OperationName"]
            request = json.loads(operation_call["Input"]["SerializedRequest"])
            steps.append(
                {"operation": operation, "request": request, "response": call(operation, request)}
            )
        trace.append({"name": case["Description"], "steps": steps})
    Path(trace_path).write_text(json.dumps(trace, indent=1) + "\n")
    sys.stdout.write(f"{len(trace)} cases → {trace_path}\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__ or "")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
