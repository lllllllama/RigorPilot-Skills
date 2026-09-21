# Current skill: functional acceptance

[简体中文](SKILL_ACCEPTANCE.zh-CN.md) · [README](../README.md) · [Protocol source](../benchmarks/run_skill_acceptance.py)

2026-09-13: **4/4 functional checks passed** through an installed-layout copy of
the actual reproduction skill. This demonstrates execution, truthful failure
reporting and evidence delivery, not model uplift or paper-level reproduction.

Full local Windows regression: **71/71 scripts passed in 168.3 s**. The public
archive passed byte/link checks and Git publication validation in an isolated
temporary index, without changing the normal staging area. Subsequently published at
[`3f4ff41`](https://github.com/lllllllama/RigorPilot-Skills/commit/3f4ff415bc678fc83db673288d33b1a8fb5458aa),
with [all three CI platforms passing](https://github.com/lllllllama/RigorPilot-Skills/actions/runs/34757822033).
See also the [real-client follow-up](REAL_CLIENT_ACCEPTANCE.md): the corrected
explicit named-skill Fast Path completes and passes independent acceptance;
natural-language auto-loading is repeatedly observed, but AUTO end-to-end remains
failed. The latest run preserved the 30-second target bound but killed the
orchestrator with an equal external timeout before terminal evidence was written.

## Inspect the outcomes

| Case | Actual result | Required skill outcome | Evidence |
|---|---|---|---|
| Missing data (synthetic) | `FileNotFoundError`; nonzero exit | `partial`, no invented metric or changed source | [README](../benchmark_outputs/skill_acceptance/attempt-2/missing_asset/repo/RIGORPILOT_README.md) · [check](../benchmark_outputs/skill_acceptance/attempt-2/missing_asset/ACCEPTANCE.json) |
| Prepared data (synthetic) | Exit 0; independently recomputed MSE = 0 | `success`, metric `matched` | [README](../benchmark_outputs/skill_acceptance/attempt-2/matching_metric/repo/RIGORPILOT_README.md) · [check](../benchmark_outputs/skill_acceptance/attempt-2/matching_metric/ACCEPTANCE.json) |
| Wrong metric (synthetic) | Exit 0; independently recomputed MSE = 1 | `partial`, metric `mismatched`; keep the real result | [README](../benchmark_outputs/skill_acceptance/attempt-2/wrong_metric/repo/RIGORPILOT_README.md) · [check](../benchmark_outputs/skill_acceptance/attempt-2/wrong_metric/ACCEPTANCE.json) |
| micrograd (public repository) | Both unchanged upstream tests passed | `success`; paper metrics `not_evaluated` | [README](../benchmark_outputs/skill_acceptance/attempt-2/micrograd/repo/RIGORPILOT_README.md) · [check](../benchmark_outputs/skill_acceptance/attempt-2/micrograd/ACCEPTANCE.json) |

[Full report](../benchmark_outputs/skill_acceptance/attempt-2/REPORT.json) ·
[Frozen inputs, implementation hashes and environment](../benchmark_outputs/skill_acceptance/attempt-2/START.json)

The three synthetic executions took 0.766 / 0.688 / 0.734 s; the micrograd skill
invocation took 5.968 s (pytest reported 4.18 s). These are single warm-environment
observations, excluding preparation/copying/grading, not speedup measurements.
Both archived attempts total **768,723 bytes**; no model/data downloads or package
installation. The original 13 micrograd files, including media/notebooks, remain
byte-identical. All four annotated READMEs restore exactly after stripping only
RigorPilot insertions; links remain relative to the retained source directory.

## Repeat locally

```bash
python benchmarks/run_skill_acceptance.py --output tmp/skill-check
```

Requires Python 3.11+ and Git. The three default cases use the standard library.
With PyTorch and pytest already installed in the selected environment:

```bash
python benchmarks/run_skill_acceptance.py --output tmp/skill-check-with-micrograd --include-micrograd
```

Use `--python /path/to/python` when the task environment differs. The runner
records it and places it first on the child PATH. Each run requires a new output
directory. Admission checks require 1 GiB free and keep evidence below 32 MiB
between cases; this is not a filesystem quota or a security sandbox.

The expected synthetic metric and tolerance are explicitly supplied by the
operator. The matching case records an operator-executed `prepare_data.py` step;
the missing-data case intentionally omits it. Neither measures autonomous setup.
The public case uses the retained, hash-verified
[micrograd commit](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c),
not a fresh network clone. Installed-layout copying does not test the remote
installer or automatic skill discovery in a new client.

## Grader failures are retained too

The [first attempt](../benchmark_outputs/skill_acceptance/attempt-1/REPORT.json)
reported 3/4: its integration incorrectly required the success-only first-use
grader to accept the deliberately mismatching case. The product already reported
that case correctly. Its report and raw logs are retained unchanged.

The second attempt uses a separate exact-case verifier; the old success-only
grader remains strict and still rejects negative outcomes in `CHECK.json`.
`ACCEPTANCE.json` is the correct verdict for these cases. Regression tests reject
changed predictions/MSE, fabricated success, missing completion events and unrelated
errors disguised as missing assets. Logs/hashes assume a trusted operator and
are not a defence against coordinated forgery.

Archived logs preserve their original execution paths. The copied evidence is
for browsing, not restoring a live task at those paths. The installed package is
not duplicated in the public archive; its per-file hashes are in `START.json`.
No credentials or full host environment are included. Git publication validation
checks the archived files; the corresponding commit's CI is linked above.

## Optional Codex quota snapshot

```bash
python scripts/check_codex_quota.py
```

Requires an already authenticated Codex CLI; on Windows pass
`--codex /path/to/native/codex.exe` rather than a `.cmd` wrapper. The helper uses
the official [app-server `account/rateLimits/read`](https://learn.chatgpt.com/docs/app-server)
interface, starts no model turn and returns only allowlisted usage-window fields.
Missing windows remain unknown. This snapshot neither reserves tokens nor
guarantees a 60% floor after an in-flight request, and is not wired into execution.

There were **zero extra model calls in this functional suite**. Host-assistant
usage is separate and not measured here. Actual model benefit still requires
same-condition A/B trials with real trajectories and independent task grading;
`REPORT.json` therefore keeps `model_effect: null`.
