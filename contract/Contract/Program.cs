using System.Text.Json;
using Contract;
using Microsoft.Accordant;

// export <plan.json>           write the sequences the spec picks (ORACLE.md rule 5)
// check  <plan.json> <trace>   judge a trace the Python driver recorded (ORACLE.md rule 3)
var spec = GitSpec.Create();
var context = spec.CreateTestingContext("contract");

switch (args)
{
    case ["export", var planPath]:
        // Parsing has no state, so the graph is one node with a self-loop per
        // input and the coverage algorithms find nothing to walk. One case per
        // input is the whole plan.
        var inputs = Inputs(spec);
        var tests = inputs.Select(input => TestCaseGenerator.CreateManualSequentialTestCase(
            context, inputs, [input.Name])).ToList();
        TestCaseGenerator.SaveSequentialTestCases(context, planPath, tests);
        Console.WriteLine($"{tests.Count} sequences → {planPath}");
        return 0;

    case ["check", var tracePath]:
        return Check(spec, tracePath);

    default:
        Console.Error.WriteLine("usage: export <plan.json> | check <trace.json>");
        return 2;
}

static InputSet Inputs(Spec<CliState> spec)
{
    var parse = spec.GetOperation<ParseRequest, ParseResponse>("Parse");
    var none = new Dictionary<string, string>();
    ParseRequest R(Dictionary<string, string> env, params string[] argv) => new(["git", .. argv], env);

    return new InputSet
    {
        parse.With(R(none, "push", "origin"), "push, default port"),
        parse.With(R(none, "push", "origin", "-p", "2222"), "push -p 2222"),
        parse.With(R(none, "push", "origin", "--port=8080", "-f"), "push --port=8080 -f"),
        parse.With(R(none, "-v", "-v", "push", "origin"), "-v -v push"),
        parse.With(R(none, "push", "origin", "-p", "99999"), "port out of range"),
        parse.With(R(none, "push", "origin", "-p", "abc"), "port not a number"),
        parse.With(R(new() { ["GIT_PORT"] = "2200" }, "push", "origin"), "port from env"),
        parse.With(R(new() { ["GIT_PORT"] = "0" }, "push", "origin"), "invalid port from env"),
        parse.With(R(new() { ["GIT_PORT"] = "2200" }, "push", "origin", "-p", "23"), "command line beats env"),
        parse.With(R(new() { ["GIT_PORT"] = "" }, "push", "origin"), "empty env var"),
        parse.With(R(none, "push"), "push without remote"),
        parse.With(R(none, "push", "-p", "99999"), "bad port and no remote"),
        parse.With(R(new() { ["GIT_PORT"] = "0" }, "push"), "bad env port and no remote"),
        parse.With(R(none), "no subcommand"),
        parse.With(R(none, "pull"), "unknown subcommand"),
        parse.With(R(none, "--prot"), "unknown top-level option"),
        parse.With(R(none, "push", "origin", "--prot", "1"), "unknown push option"),
        parse.With(R(none, "push", "origin", "extra"), "extra positional"),
        parse.With(R(none, "push", "--help"), "push --help without remote"),
        parse.With(R(none, "--version"), "--version"),
    };
}

// The trace is what contract/driver.py writes: one entry per test case, each with
// the calls it made. Every case starts from the initial state (parsing remembers
// nothing), and every step's response is judged by the spec.
static int Check(Spec<CliState> spec, string tracePath)
{
    var json = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
    var cases = JsonSerializer.Deserialize<List<TraceCase>>(File.ReadAllText(tracePath), json)!;
    var failures = 0;
    foreach (var testCase in cases)
    {
        var profile = new StateProfile(new CliState());
        foreach (var (step, i) in testCase.Steps.Select((s, i) => (s, i)))
        {
            var op = spec.GetOperation(step.Operation);
            var request = step.Request.Deserialize<ParseRequest>(json)!;
            var response = step.Response.Deserialize<ParseResponse>(json)!;
            var (ok, message, next) = spec.Allows(op, request, response, profile);
            if (!ok)
            {
                failures++;
                Console.WriteLine($"✗ {testCase.Name} (step {i}, {step.Operation})");
                Console.WriteLine($"    argv:     {string.Join(' ', request.Argv)}  env: {JsonSerializer.Serialize(request.Env)}");
                Console.WriteLine($"    response: {step.Response.GetRawText()}");
                Console.WriteLine($"    {message.Replace("\n", "\n    ")}");
                break;
            }
            profile = next;
        }
    }
    Console.WriteLine(failures == 0
        ? $"✓ {cases.Count} cases, every response allowed by the spec"
        : $"{failures} of {cases.Count} cases violate the spec");
    return failures == 0 ? 0 : 1;
}

record TraceCase(string Name, List<TraceStep> Steps);
record TraceStep(string Operation, JsonElement Request, JsonElement Response);
