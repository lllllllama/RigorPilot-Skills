# Real-client acceptance: explicit Fast Path and fresh-client AUTO pass

[简体中文](REAL_CLIENT_ACCEPTANCE.zh-CN.md) · [Home](../README.md) · [Latest machine report](../benchmark_outputs/real_client/20260922/REPORT.json) · [2026-09-21 report](../benchmark_outputs/real_client/20260921/REPORT.json) · [2026-09-20 report](../benchmark_outputs/real_client/20260920/REPORT.json) · [Historical 2026-09-13 report](../benchmark_outputs/real_client/20260913/REPORT.json)

## 2026-09-22 AUTO acceptance

One fresh natural-language AUTO canary was run on skill commit `7590f36` and the
same pinned micrograd commit `7bc720e`, Codex `0.154.0-alpha.6.2`,
`gpt-6-astra` / high, existing CPU Python/PyTorch/pytest environment, 30-second
target-command bound, 240-second outer watchdog and 16 tool-start cap. The user
explicitly kept the prior quota-percentage override, so quota readings were
observation-only and are not a same-budget model comparison.

**This AUTO gate passed end to end.** The prompt did not name the skill; the trace
shows project-local skill discovery and use of the reviewed README target. The
client returned 0 with `turn.completed` after 104.469 seconds and 5 tool starts.
The selected `python -m pytest` runtime succeeded in 15.313 seconds, source
integrity stayed unchanged, the independent first-use grader passed, the retained
bundle passed `--verify-output`, and the source-adjacent README was delivered.

| Check | Result | Evidence |
|---|---|---|
| Natural-language skill loading | **Passed**; prompt omitted skill name/path and trace references the project skill | [AUTO report](../benchmark_outputs/real_client/20260922/AUTO/REPORT.json) · [prompt](../benchmark_outputs/real_client/20260922/AUTO/client/PROMPT.txt) |
| Client completion | **Passed**; return code 0, `turn.completed`, no watchdog stop | [client end](../benchmark_outputs/real_client/20260922/AUTO/client/END.public.json) · [trace](../benchmark_outputs/real_client/20260922/AUTO/client/TRACE.jsonl) |
| Target execution | **Passed**; README-backed `python -m pytest`, runtime `success` | [status](../benchmark_outputs/real_client/20260922/AUTO/repo/repro_outputs/status.json) · [runtime stdout](../benchmark_outputs/real_client/20260922/AUTO/repo/repro_outputs/_runtime/20260922T114013Z-7a4eccf7/stdout.log) |
| Source/evidence acceptance | **Passed**; source unchanged, independent grader and `--verify-output` pass | [independent grader](../benchmark_outputs/real_client/20260922/AUTO/EVIDENCE_CHECK.json) · [verify](../benchmark_outputs/real_client/20260922/AUTO/VERIFY.json) |
| Execution path | Model used the synchronous orchestrator **without** an equal external timeout wrapper; it did not select `repro_job.py` in this turn | [machine report](../benchmark_outputs/real_client/20260922/REPORT.json) |
| Usage / model effect | 141,255 input tokens (90,880 cached), 1,983 output tokens; provider cost unknown. A/B remains unrun and `model_uplift=null` | [AUTO report](../benchmark_outputs/real_client/20260922/AUTO/REPORT.json) |

This closes the fresh-client AUTO **acceptance** gate; it does not prove that the
skill improves model quality. The optional `repro_job.py` short-call handoff was
not selected by the model in this successful turn, so its usefulness remains
grounded in the separate real bridge/fault evidence rather than attributed to
this AUTO pass. A/B evaluation is now unblocked by client acceptance but remains
a separate experiment with frozen tasks, budgets and independent grading.

## 2026-09-21 AUTO follow-up

The user explicitly authorized one new AUTO canary without waiting for the
historical 70% quota-start threshold. Quota readings were therefore observation
only for this run; all other bounds stayed fixed: pinned micrograd `7bc720e`,
skill commit `9a86470`, Codex `0.154.0-alpha.6.2`, `gpt-6-astra` / high,
30 seconds per target command, 240 seconds outer wall time, 16 tool starts,
no automatic retry, no A/B expansion.

The fresh prompt again did not name the skill. Trace evidence again shows
project-local `ai-research-reproduction` discovery and use of
`orchestrate_repro.py`. The earlier 20-second problem was corrected: the agent
selected the full 30-second target timeout. **End-to-end acceptance still failed.**

This time the agent wrapped the entire orchestrator in another 30-second
`subprocess` timeout. The external wrapper expired at about 30.047 seconds before
the orchestrator could complete its own child-process timeout cleanup and terminal
evidence finalization. The retained runtime state therefore remained `running`,
`status.json` was never written, the independent first-use grader could not pass,
and the outer Codex client later hit its 240-second watchdog after 9 tool starts
without `turn.completed`.

| Check | Result | Evidence |
|---|---|---|
| Natural-language auto-loading | **Observed again**; prompt did not name the skill and trace references the project skill/orchestrator | [AUTO report](../benchmark_outputs/real_client/20260921/AUTO/REPORT.json) · [client end](../benchmark_outputs/real_client/20260921/AUTO/client/END.public.json) |
| User command-time bound | **Preserved** at 30 s | [orchestrator command](../benchmark_outputs/real_client/20260921/AUTO/repo/repro_outputs/orchestrator.command.json) |
| Orchestrator finalization | **Failed**; equal external timeout killed the orchestrator before terminal evidence | [runtime state](../benchmark_outputs/real_client/20260921/AUTO/repo/repro_outputs/_runtime/20260921T025519Z-09a06136/state.json) |
| Postmortem verification | **Failed closed** as `runtime_incomplete_without_status`; no automatic replay | [postmortem verifier](../benchmark_outputs/real_client/20260921/AUTO/POSTMORTEM_VERIFY.json) |
| Source originals | 13 baseline files still matched; this does not establish task success | [independent check](../benchmark_outputs/real_client/20260921/AUTO/EVIDENCE_CHECK.json) |
| Model usage / uplift | Usage unavailable because no `turn.completed`; cost unknown; A/B not run and `model_uplift` remains `null` | [machine summary](../benchmark_outputs/real_client/20260921/REPORT.json) |

The new correction is narrower than adding another retry: Fast Path and CLI help
now state that `--timeout` limits the **target command**, not the full orchestrator
lifecycle. `plan-only` exposes `timeout_scope=target_command_only`,
`orchestrator_must_reach_terminal_state=true`, and
`external_timeout_wrapper_allowed=false`. If a host needs an outer watchdog it
must be comfortably longer than the target timeout. `--verify-output` now also
distinguishes an incomplete nonterminal runtime from evidence that never existed,
returning `runtime_incomplete_without_status` without replaying the command.

This 2026-09-21 run used a user-authorized quota-protocol deviation, so it is not
a same-budget replacement for the earlier runs. It remains a retained failure;
the later 2026-09-22 run above closes the AUTO acceptance gate without rewriting it.

## 2026-09-20 follow-up

The corrected Fast Path was exercised again on pinned micrograd commit `7bc720e`
with current skill commit `184b163`, Codex `0.154.0-alpha.6.2`, `gpt-6-astra`
at high reasoning, the existing Python/PyTorch/pytest environment, CPU only, and
the same 240-second outer watchdog. The skill was copied from the local Git commit
into the fresh project's `.agents/skills/`; this run tests real-client behavior,
not the remote installer.

| Gate | Observed result | Evidence |
|---|---|---|
| Explicit named-skill Fast Path | **Passed**. Client returned 0 with `turn.completed`; 6 tool starts, 128.094 s. `python -m pytest` passed both original tests, source integrity stayed unchanged, the independent first-use grader passed, and `--verify-output` accepted the bundle. | [B report](../benchmark_outputs/real_client/20260920/B/REPORT.json) · [client end](../benchmark_outputs/real_client/20260920/B/client/END.public.json) · [independent check](../benchmark_outputs/real_client/20260920/B/EVIDENCE_CHECK.json) |
| Fresh-client natural-language auto-loading | **Skill discovery passed, end-to-end task acceptance failed.** The prompt did not name a skill; the trace references the project skill and `orchestrate_repro.py`, and the client completed normally with 8 tool starts in 157.281 s. The agent nevertheless chose `--timeout 20` even though the task allowed up to 30 s; pytest remained at `collecting ...` and the run was truthfully recorded `partial` / `timeout`. | [AUTO report](../benchmark_outputs/real_client/20260920/AUTO/REPORT.json) · [client end](../benchmark_outputs/real_client/20260920/AUTO/client/END.public.json) · [status](../benchmark_outputs/real_client/20260920/AUTO/repo/repro_outputs/status.json) |
| 30-second no-model diagnostic | **Passed** on a fresh checkout: both tests completed in 10.61 s. This supports treating the AUTO failure as a too-strict selected timeout on this attempt; it is not a retroactive pass or a model retry. | [diagnostic](../benchmark_outputs/real_client/20260920/TIMEOUT_DIAGNOSTIC.json) |
| A/B model comparison | **Not run.** The protocol stops expansion after the AUTO gate fails; `model_uplift` remains `null`. | [sequence report](../benchmark_outputs/real_client/20260920/REPORT.json) |

Both real turns have complete returned usage records in their reports. The explicit
run reported 145,689 input tokens (116,224 cached) and 3,087 output tokens; AUTO
reported 222,679 input tokens (189,952 cached) and 3,337 output tokens. Provider
cost remains unknown. Private quota percentages are not published and are not
treated as token accounting or a billing cap.

The live failure produced one concrete correction: Fast Path guidance now says
to preserve an explicit user command-timeout bound instead of silently making it
stricter. A non-training timeout now tells the agent to keep the reviewed command
and protocol unchanged and, only when the existing user budget permits, increase
`--timeout` rather than changing dependencies, inputs, or evaluation semantics.

The 2026-09-21 run above tested that timeout correction and exposed a separate
outer-wrapper timeout race. Both failed AUTO attempts remain in the evidence set;
the 2026-09-22 run closes AUTO acceptance, while A/B/model uplift remain unrun.

## Historical 2026-09-13 trial

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
and stop without unrequested experiments. The 2026-09-20 explicit named-skill run
above established normal client completion for that corrected Fast Path. The
natural-language AUTO run separately exposed the stricter-than-requested timeout
issue. The retained 2026-09-21 failure then exposed the equal outer-wrapper race;
the 2026-09-22 fresh-client AUTO pass closes that client-acceptance gate. A/B
remains a separate, still-unrun effectiveness experiment.

The public snapshot is about 0.5 MB, retaining source, media and notebooks.
[File hashes](../benchmark_outputs/real_client/20260913/FILES.json) cover unchanged copied files.
Omitted: Node binaries, npm caches, Git metadata, duplicate installed skill, test cache and
private quota snapshots. Public end receipts name omitted fields and hash the local originals;
credentials and the full host environment were never collected. Historical absolute paths
remain unchanged; this is an inspection snapshot, not an in-place resumable run.
