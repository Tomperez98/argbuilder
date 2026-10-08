using Microsoft.Accordant;

namespace Contract;

// The contract for argbuilder's public parsing API, judged through one fixture
// CLI (contract/driver.py builds the same definition):
//
//   git [-v|--verbose]... [--version] [-h|--help] <SUBCOMMAND>
//     push <REMOTE> [-p|--port <PORT> (1..=65535, env GIT_PORT, default 22)] [-f|--force]
//
// Parsing is pure: the request is (argv, env) and nothing is remembered between
// calls, so the state is empty. The spec covers only what a caller can observe
// from `Command.try_get_matches_from`: the matches, or the error's kind, the
// fields it carries, and its exit code.

[State]
public partial class CliState
{
}

public record ParseRequest(List<string> Argv, Dictionary<string, string> Env);

public record ParseResponse(
    string Outcome,          // "Matches", or the ErrorKind class name
    int ExitCode,
    string? Subcommand = null,
    string? Remote = null,
    long? Port = null,
    string? PortSource = null,
    bool? Force = null,
    long? Verbose = null,
    string? Argument = null, // the argument (or subcommand name) the error is about
    string? Value = null,
    string? FromEnv = null);

public static class GitSpec
{
    const string Port = "--port <PORT>";

    public static Spec<CliState> Create()
    {
        var spec = new Spec<CliState>();
        spec.Operation<ParseRequest, ParseResponse>("Parse", (request, _) => Parse(request));
        return spec.WithJsonPrinters();
    }

    static ExpectedOutcomes Parse(ParseRequest request)
    {
        var tokens = request.Argv.Skip(1).ToList();
        var verbose = 0;
        for (var i = 0; i < tokens.Count; i++)
        {
            var token = tokens[i];
            if (token is "-h" or "--help")
                return Exit("DisplayHelp", 0, "--help → help, exit 0");
            if (token == "--version")
                return Exit("DisplayVersion", 0, "--version → version, exit 0");
            if (token is "-v" or "--verbose")
            {
                verbose++;
                continue;
            }
            if (token.StartsWith('-'))
                return Error("UnknownArgument", token, $"'{token}' is not an option of git → UnknownArgument");
            if (token == "push")
                return Push(tokens.Skip(i + 1).ToList(), request.Env, verbose);
            return Error("InvalidSubcommand", token, $"'{token}' is not a subcommand → InvalidSubcommand");
        }
        return Exit("MissingSubcommand", 2, "no subcommand → MissingSubcommand, exit 2");
    }

    static ExpectedOutcomes Push(List<string> tokens, Dictionary<string, string> env, int verbose)
    {
        string? remote = null;
        string? cliPort = null;
        var force = false;
        for (var i = 0; i < tokens.Count; i++)
        {
            var token = tokens[i];
            if (token is "-h" or "--help")
                return Exit("DisplayHelp", 0, "push --help → help, exit 0");
            if (token is "-f" or "--force")
            {
                force = true;
                continue;
            }
            if (token is "-p" or "--port" || token.StartsWith("--port="))
            {
                cliPort = token.StartsWith("--port=") ? token["--port=".Length..] : tokens[++i];
                if (!ValidPort(cliPort))
                    return Error("InvalidValue", Port, $"--port {cliPort} is not in 1..=65535 → InvalidValue", cliPort);
                continue;
            }
            if (token.StartsWith('-') || remote != null)
                return Error("UnknownArgument", token, $"'{token}' is not an argument of push → UnknownArgument");
            remote = token;
        }

        long port;
        string source;
        if (cliPort != null)
            (port, source) = (long.Parse(cliPort), "command_line");
        // An empty value counts as unset (Arg.env's documented rule).
        else if (env.TryGetValue("GIT_PORT", out var envPort) && envPort != "")
        {
            if (!ValidPort(envPort))
                return Error("InvalidValue", Port, $"GIT_PORT={envPort} is not in 1..=65535 → InvalidValue from env",
                    envPort, fromEnv: "GIT_PORT");
            (port, source) = (long.Parse(envPort), "env_variable");
        }
        else
            (port, source) = (22, "default_value");

        // Values from the environment are validated before required arguments
        // are checked, as in clap: a bad GIT_PORT wins over a missing remote.
        if (remote == null)
            return Error("MissingRequiredArgument", "<REMOTE>", "push without a remote → MissingRequiredArgument");

        return Expect.That<ParseResponse>(r =>
                    r.Outcome == "Matches" && r.ExitCode == 0 && r.Subcommand == "push" &&
                    r.Remote == remote && r.Port == port && r.PortSource == source &&
                    r.Force == force && r.Verbose == verbose,
                $"push {remote} → port {port} from {source}, force={force}, verbose={verbose}")
            .SameState();
    }

    static bool ValidPort(string value) => long.TryParse(value, out var n) && n is >= 1 and <= 65535;

    static ExpectedOutcomes Exit(string kind, int exitCode, string explanation) =>
        Expect.That<ParseResponse>(r => r.Outcome == kind && r.ExitCode == exitCode, explanation).SameState();

    static ExpectedOutcomes Error(string kind, string argument, string explanation,
        string? value = null, string? fromEnv = null) =>
        Expect.That<ParseResponse>(r =>
                r.Outcome == kind && r.ExitCode == 2 && r.Argument == argument &&
                (value == null || r.Value == value) && r.FromEnv == fromEnv,
            explanation).SameState();
}
