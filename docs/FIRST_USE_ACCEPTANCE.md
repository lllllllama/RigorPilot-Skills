# Installed-skill first use: micrograd

[简体中文](FIRST_USE_ACCEPTANCE.zh-CN.md) · [Engineering plan](ENGINEERING_ROADMAP.md) · [README](../README.md)

2026-09-06: an independent agent used the installed skill to select and execute
`python -m pytest` from the original README. Both tests passed. After correcting
reporting issues, a fresh-directory replay and an independent pytest rerun passed.
This is small autograd-test acceptance, not paper reproduction, model uplift or client auto-loading evidence.

## Inspect actual results

| Attempt | Actual outcome | Evidence |
|---|---|---|
| Before: independent installed-skill trial | Two tests passed; pytest 2.29 s, runtime 3.437 s | [Annotated README](../benchmark_outputs/showcases/micrograd-first-use-before/repo/RIGORPILOT_README.md) · [Raw trial review, Chinese](../benchmark_outputs/showcases/micrograd-first-use-before/FORWARD_REVIEW.md) · [Checks](../benchmark_outputs/showcases/micrograd-first-use-before/CHECK.json) |
| After: first parent replay | Missing venv PATH selected Python without pytest; correctly recorded `partial` / `failed` | [Status](../benchmark_outputs/showcases/micrograd-first-use-failed/repo/repro_outputs/status.json) · [Raw error](../benchmark_outputs/showcases/micrograd-first-use-failed/repo/repro_outputs/_runtime/20260906T085408Z-0e53ec0f/stderr.log) · [Failed checks](../benchmark_outputs/showcases/micrograd-first-use-failed/CHECK.json) |
| After: corrected deterministic replay | Two tests passed; pytest 1.83 s, runtime 2.640 s | [Annotated README](../benchmark_outputs/showcases/micrograd-first-use-after/repo/RIGORPILOT_README.md) · [Actual command report](../benchmark_outputs/showcases/micrograd-first-use-after/repo/repro_outputs/COMMANDS.md) · [Checks](../benchmark_outputs/showcases/micrograd-first-use-after/CHECK.json) |
| Independent upstream behavior check | Both original tests passed again, with no test or scientific-code edits | [JUnit](../benchmark_outputs/showcases/micrograd-first-use-after/independent/pytest.xml) · [Result](../benchmark_outputs/showcases/micrograd-first-use-after/independent/RESULT.json) |

All three snapshots retain all 13 original files, including images, SVG and notebooks,
with their pre-run SHA-256 values. Both successful attempts produced two README copies,
each with eight correctly positioned inserts and twelve inserted links resolving in
the original workspace. Publication rebases only inserted evidence links. Single-run
timings do not establish a speedup; the parent replay configuration error is not a model failure.

## Changes grounded in use

- Mark setup suggestions unexecuted; missing conventional asset directories no longer invent required preparation.
- Preserve setup discovery gaps as `setup_advisories`, not automatic human decisions; real dependency/asset failures remain visible.
- Record execution separately in `command_reporting`. Missing/out-of-tolerance explicit metrics make overall acceptance `partial` while preserving successful process evidence and clear failed-acceptance guidance.
- Add an independent byte-scanning/log-consistency grader, separating task-log conditions from README presentation. Synthetic negative tests cover wrong/missing metrics and dependencies/assets; they are not external research tasks.

## Installation, environment and cost boundaries

- Upstream: [micrograd commit 7bc720e](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c), freshly fetched into each directory; no source patches.
- Actual installer: `npx skills@1.5.23 add <local skill snapshot> --skill ai-research-reproduction --agent codex --copy --yes`.
  The first snapshot came from product commit `caa9ac6`; later snapshots used the patched working tree. Each `BASELINE.json` records installed file hashes.
  This is not a remote product-release installation test. Installer TLS validation was enabled and telemetry disabled.
- Node 22.17.0 is below the installer's declared 22.20.0 requirement. Installation succeeded with an engine warning, not a supported-version acceptance claim. See [raw setup evidence](../benchmark_outputs/showcases/micrograd-first-use-before/SETUP.json).
- Python 3.12.7; fresh virtualenvs inherited host PyTorch 2.12.1+cu126 and pytest 7.4.4. Tests ran on CPU, without model/data downloads or large dependency installation. This is not a dependency cold start. Child commands resolve via PATH; launching the orchestrator with venv Python alone does not activate the environment.
- The parent prepared installation/environment. The independent agent read, selected and executed without a supplied test command. The skill path was explicit; fresh-client natural-language auto-loading and complete provider trajectories were not tested.
- Published snapshots total about 0.6 MiB including the failure; local workspaces total about 22.3 MiB including installer caches. No separate model API calls; host-agent tokens/cost were unmeasured, not zero. Subscription balance is unavailable.
- Raw logs retain original absolute paths; use the links above for browsing. Relocated snapshots are not live resumable tasks and their old ownership receipts must not be reused. The public replay record omits unrelated inherited PATH entries; the original remains local.

## Repeatable checks and next gate

Local `python scripts/run_all_tests.py`: 63/63 scripts passed in 108.9 s, including the new reporting and grader regressions.
Verify published README/media bytes and inserted evidence links from the Git tree:

```bash
python scripts/check_publication.py
```

For fresh experiments, reuse the [first-use grader](../benchmarks/README.md#installed-skill-first-use-check).
It does not execute the target, authenticate the baseline, test external media/browser rendering,
verify scientific metrics or protect against coordinated evidence forgery.

Next-stage preparation is now in the [three-task paired pilot](PAIRED_PILOT.md):
frozen inputs and real grader calibration, with all six model slots still unrun.
Fresh-client loading, successful standalone model execution and model-quality comparisons still require separately confirmed budgets and acceptance.
