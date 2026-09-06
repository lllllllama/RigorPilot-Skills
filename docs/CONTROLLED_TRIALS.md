# Controlled trials: executable boundaries before live evaluation

[简体中文](CONTROLLED_TRIALS.zh-CN.md) · [Paired pilot](PAIRED_PILOT.md) · [Benchmarks](../benchmarks/README.md)

The trial core now connects a neutral tool loop, a restricted command broker,
an independent grader, and a durable per-trial budget ledger. The runnable
demonstration uses **scripted transport responses and real local Python
processes**. It tests controller behavior, not model intelligence or skill gains.

## Run and inspect

From the project root, using an existing Python installation:

```bash
python benchmarks/run_controller_smoke.py --output repro_outputs/controller-check
```

Use a fresh output directory for each run. No model API, package installation,
repository download, or model download is required. The tasks use the Python
standard library; they are explicitly synthetic fault-injection cases.

Open the generated `REPORT.json` and the linked per-case evidence. The
[published report](../benchmark_outputs/controller_smoke/REPORT.json) provides
the recorded outcomes and paths; do not infer results from this page's case list.

| Case | What the execution checks |
|---|---|
| Missing asset | First evaluation fails; local preparation and a second evaluation produce MSE 0. Keep the failed attempt and successful commands. |
| Wrong metric | Evaluation exits 0 but produces MSE 1, not the required 0. A truthful `mismatched` claim can pass handling checks without passing the scientific result criterion. |
| Unknown usage | A scripted response lacks acceptable usage. Stop before executing its requested tool; retain the unresolved reservation. |
| Out-of-scope path | Reject a tool read outside its permitted namespace; do not disclose private control files. |

Logs and artifacts come from actual reviewed subprocesses. Claims, tool choices,
model identities, and reported token counts in this demonstration are scripted
fixtures. Neither `accepted` nor a fixture's token count is a live-model result.
Host agents used to develop this project may consume tokens; that usage is not
measured by this command.

Recorded on 2026-09-06: **4/4 controller checks passed**, with four actual command
attempts including one retained failure. The complete snapshot is about 65 KiB:
[first failure](../benchmark_outputs/controller_smoke/missing_asset/evidence/commands/0001/steps/evaluate/stderr.log),
[successful recovery](../benchmark_outputs/controller_smoke/missing_asset/RESULT.json),
[metric mismatch](../benchmark_outputs/controller_smoke/wrong_metric/RESULT.json),
[unknown usage stopped before tools](../benchmark_outputs/controller_smoke/unknown_usage/RESULT.json),
and [denied read trace](../benchmark_outputs/controller_smoke/path_denied/evidence/trace.jsonl).
Historical absolute paths in logs are retained; public files are a browsable
snapshot, not a resumable trial. Validate committed bytes with
`python scripts/check_publication.py`.

## What the core implements

| Component | Responsibility |
|---|---|
| [Trial controller](../benchmarks/trial_controller.py) | Same neutral system prompt and tool schemas; validate each response, account for usage before tool execution, then collect an independent final grade. |
| [Tool broker](../benchmarks/trial_broker.py) | Read bounded repository/skill files; execute frozen command IDs without custom argv or shell tools; keep execution receipts and grader inputs operator-owned. |
| [Budget ledger](../benchmarks/trial_budget.py) | Append and sync reservations, settlements, and stops; enforce per-trial token, call, and elapsed-time gates. |

The exposed tools are `list_files`, `read_file`, `run_command`, and `finish`.
Models cannot submit execution receipts or modify the grader, control files,
original README, media, scientific source, or evaluation criteria through them.
The broker can expose only collected, allowed result files after execution.

For a future comparison, A has repository access; B can additionally read the
frozen skill namespace. The core does **not execute bundled skill helpers**.
This is a *skill-guided constrained trial*, not a complete skill-package A/B,
installation check, client auto-discovery test, or unrestricted agent benchmark.

## Accounting and stopping

The ledger is for **one trial with one exclusive directory owner**. It is not
a campaign-wide accountant or a multiprocess lock. Required positive-integer
limits are `max_total_tokens`, `max_model_calls`, `max_tool_calls`, and
`max_seconds`; no subscription balance or implicit spending allowance is used.

- Reserve before dispatch and sync the event to disk. Request-byte reservations
  are conservative estimates, not proven tokenizer bounds.
- Settle valid input/output/cache usage before acting on a response. If actual
  usage exceeds a cap, retain it and stop subsequent actions. Cache accounting
  requires transport-specific normalization, not copying arbitrary API fields.
- Missing/malformed usage or an uncertain request leaves `tokens_used: null`
  while retaining `known_tokens` and the pending reservation. Do not release
  that reservation, retry the request, or automatically resume a pending run.
- In controller reports, `model_calls` counts actual `complete()` invocations;
  `dispatch_reservations` counts durable reservations separately. Offline runs
  have `live_model_calls: 0`; `fixture_reported_tokens` is fixture data, while
  live `tokens_used` and `cost` remain `null`.
- Any trace-write failure makes completion unaccepted and `trace_complete: false`,
  even if a later final record succeeds. Preserve the independent grade and known
  usage; a correct task result does not repair missing execution evidence.

The declared mode is `reservation_plus_post_response_stop`: a local stop policy,
**not an absolute provider billing guarantee** or a subscription-percentage stop.

## Integration and isolation limits

This is a dependency-injected library. An operator must supply the transport,
explicit provider/model/revision identity, and budgets. The transport contract
normalizes `model`, `content` text/tool-use blocks, and `usage`; it resembles
Anthropic Messages and is **not a raw OpenAI Responses adapter**. Returned model
identity is checked; a configured revision is recorded, not remotely attested.
There is no live API CLI here and no completed live-provider acceptance test.
Traces remain private by default. Model text and tool output are not universally
redacted; inspect them before publishing. Transport exceptions are recorded by
type, not by arbitrary error bodies or authentication headers.

`broker_scoped` controls access through the model's tools; `os_sandbox` is
`false`. Local Python still uses host dependencies and is not strongly isolated
from host files, network access, `PATH`, or `PYTHONPATH`. Reviewed-command
timeouts are propagated, but this does not guarantee OS process-tree cleanup
or cancellation of a remote request. The operator must not run unreviewed or
hostile repositories under this boundary.

Before live trials: choose a model and explicit spending/token limits, audit
the provider's usage/timeout/retry behavior, add a campaign-wide ledger, and
choose appropriate real process/network isolation. Then run one budgeted canary
before a newly frozen comparison. The six historical paired-pilot slots remain
`not_run`; this smoke test does not rewrite their protocol or results.

Design references: application-owned tool execution is described in
[OpenAI's function-calling guide](https://developers.openai.com/api/docs/guides/function-calling),
and response/usage fields in the
[Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
These are design sources, not evidence that an OpenAI adapter or model has been
integrated and validated here.
