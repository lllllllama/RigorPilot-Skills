# Real-client first use: tests passed, client timed out

[简体中文](REAL_CLIENT_ACCEPTANCE.zh-CN.md) · [Home](../README.md) · [Machine report](../benchmark_outputs/real_client/20260913/REPORT.json)

2026-09-13: install a pinned public skill and run micrograd in a fresh Codex session.
**Original tests and independent evidence checks passed, but the client did not finish
within 240 seconds. Overall acceptance failed.** This is a real model/tool trace,
not a scripted model substitute, measured model uplift, or paper-result reproduction.

## Inspect the actual outputs

| Check | Observed result | Evidence |
|---|---|---|
| Public installation | TLS verification enabled; 46 installed files match pinned source content | [Installation hashes](../benchmark_outputs/real_client/20260913/INSTALL-secure.json) · [Installer log](../benchmark_outputs/real_client/20260913/setup/public-npx-install-verified/stdout.log) |
| Execution | Model selected `python -m pytest`; 2 original tests passed, pytest reported 14.45 s | [Full test output](../benchmark_outputs/real_client/20260913/B/repo/repro_outputs/_runtime/20260913T125713Z-fd901d8d/stdout.log) · [Invocation](../benchmark_outputs/real_client/20260913/B/repo/repro_outputs/invocation.json) |
| Source and media | All 13 originals retained; 8 heading annotations plus one summary insertion | [Original README](../benchmark_outputs/real_client/20260913/B/repo/README.md) · [Full annotated README](../benchmark_outputs/real_client/20260913/B/repo/RIGORPILOT_README.md) |
| Independent evidence | Original hashes, insertion positions, byte restoration, inserted links and runtime/log consistency pass | [Independent check](../benchmark_outputs/real_client/20260913/B/EVIDENCE_CHECK.json) |
| Client completion | **Failed**; stopped at 241.516 s, no `turn.completed` | [End receipt](../benchmark_outputs/real_client/20260913/B/client/END.public.json) · [Full action trace](../benchmark_outputs/real_client/20260913/B/client/TRACE.jsonl) |

Green `success` in the annotated README describes the selected command, not outer-client
completion. Its internal reproduction score is not a paper metric, model uplift, or
this trial's end-to-end grade. Generated artifacts remain unchanged, including the
Chinese output requested for this run; the timeout is not repackaged as a passing trial.

## Protocol

- Skill pinned to [`3f4ff41`](https://github.com/lllllllama/RigorPilot-Skills/commit/3f4ff415bc678fc83db673288d33b1a8fb5458aa);
  its [Windows / Linux / macOS CI](https://github.com/lllllllama/RigorPilot-Skills/actions/runs/34757822033) passed.
- Fresh fetch of [pinned micrograd](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c), not a reconstructed README or reduced surrogate.
- Public `skills@1.5.26`, temporary portable Node 22.20.0, project-local single-skill install; global installation unchanged.
- Explicit installed-skill invocation in a fresh session with user configuration,
  memory, other global skills and multi-agent disabled. Requested `gpt-6-astra` / `high`,
  using existing Codex authentication, not converting subscription access into API credit.
- Task and bounds supplied, **no preselected test command or reference answer**.
  The model read the skill and README, made 8 shell calls and 1 file-change call,
  and wrote its evidence helper inside the output directory; originals remained unchanged.
- Existing Python / PyTorch / pytest environment, CPU only; no task installs, downloads
  or training. This does not establish clean dependency bootstrap or held-out task performance.

[Frozen launch](../benchmark_outputs/real_client/20260913/B/client/START.json) ·
[Exact prompt](../benchmark_outputs/real_client/20260913/B/client/PROMPT.txt) ·
[Frozen collector](../benchmark_outputs/real_client/20260913/B/client/COLLECTOR.py)

The collector is an archived, host-specific Windows experiment, not a general product
entrypoint. Its 240 s watchdog terminated the client process tree. The implemented
16-call counter tracks shell execution; file changes are separate. Native token budgeting
was experimental, not a proven hard limit. Quota snapshots cover only returned windows;
missing final token usage and cost remain unknown, never inferred from percentage deltas.

## Retained failures

1. Initial installation inherited `NODE_TLS_REJECT_UNAUTHORIZED=0`; it was not accepted
   as secure installation. The [warning](../benchmark_outputs/real_client/20260913/setup/public-npx-install/stderr.log)
   is retained. The secure retry used child-only verification settings, a fresh cache and a new target directory.
2. Codex `0.150.1` received an explicit HTTP 400 requiring a newer client for this model.
   Its [trace](../benchmark_outputs/real_client/20260913/B/client-cli-0.150.1-rejected/TRACE.jsonl) is retained;
   no repository command ran. The next attempt used already-installed `0.154.0-alpha.6.1`,
   without a global CLI update or model change.
3. The newer client ran the tests and generated evidence but did not finish on time.
   Final usage is unknown. **No further model retry or no-Skill baseline A was run;
   model uplift remains `null`.**

The trace shows repeated implementation reading and large tool outputs before execution.
It does not expose private reasoning or per-request latency, so it cannot assign the
entire timeout to the skill, model reasoning, or service delay. Startup telemetry and
remote MCP connection warnings are retained, not treated as proof of an outage or offline operation.

## Evidence-driven correction

Successful reports previously suggested continuing to the next verification step.
They now direct the agent to inspect existing evidence, deliver the bounded result,
and stop without unrequested experiments. Skill guidance clarifies this finish boundary
and starts routine use from the entrypoint/help, with implementation inspection for concrete issues.
Regression covers English/Chinese success, dry runs and actual failures; metric-mismatch
and training-authorization boundaries remain intact.
**A new live run has not yet established whether this correction reduces timeout risk.**

Next, when budget permits, retry only this task in a fresh directory with the corrected
version. Require command success, source fidelity, independent evidence acceptance **and**
normal client completion before running a same-condition A baseline; artifact count is not task quality.

The public snapshot is about 0.5 MB, retaining source, media and notebooks.
[File hashes](../benchmark_outputs/real_client/20260913/FILES.json) cover unchanged copied files.
Omitted: Node binaries, npm caches, Git metadata, duplicate installed skill, test cache and
private quota snapshots. Public end receipts name omitted fields and hash the local originals;
credentials and the full host environment were never collected. Historical absolute paths
remain unchanged; this is an inspection snapshot, not an in-place resumable run.
