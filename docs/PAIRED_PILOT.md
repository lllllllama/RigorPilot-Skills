# Small paired evaluation: prepare first, measure later

[简体中文](PAIRED_PILOT.zh-CN.md) · [Engineering roadmap](ENGINEERING_ROADMAP.md) · [Benchmarks](../benchmarks/README.md)

This kit freezes **three tasks × two conditions**, and runs real local commands
to check the independent graders. The six live model trials remain `not_run`.
Offline calibration is not an A/B result, an unseen-task success rate, or proof
that the skill improves model performance.

## Run locally

Run from the project root. Choose an **existing Python with both `torch` and
`pytest`** to calibrate all three tasks. No packages, models, data, or repositories
are downloaded or installed. The two injected tasks use only the standard library.

```bash
python benchmarks/paired_eval.py prepare --output repro_outputs/paired-pilot --python python
python benchmarks/paired_eval.py preflight --campaign repro_outputs/paired-pilot
python benchmarks/paired_eval.py calibrate --campaign repro_outputs/paired-pilot
python benchmarks/paired_eval.py summarize --campaign repro_outputs/paired-pilot
```

- `prepare` requires a new output directory and never replaces old evidence.
  `--python` selects the actual task interpreter, not just the CLI interpreter.
  For example, replace its value with `"D:/envs/research/Scripts/python.exe"`
  on Windows or `"/path/to/env/bin/python"` on Linux/macOS.
- `preflight` without model/budget configuration is expected to exit **1**.
  Inspect `input_ready` and `configuration_ready` separately. This does not prevent
  offline calibration. Missing `torch`/`pytest` is reported, not auto-repaired;
  package metadata alone does not establish import/runtime health.
- `calibrate` creates separate fresh repositories, executes the reviewed commands,
  and uses explicitly scripted claims to test the graders. Exit **0** means all
  requested calibrations passed; exit **1** means at least one did not. To run
  only standard-library tasks, add `--tasks missing_asset wrong_metric`.
- `summarize` prints JSON: live slots stay unrun, and live completion rate, paired
  effect, tokens, cost, and budget compliance remain unknown (`null`).

All commands above make **zero model API calls**. Developing or reviewing this
kit with a host agent can still consume tokens; its subscription usage is not
measured here. Storage checks use a 32 MiB campaign threshold and require 1 GiB
free space; these are checks, not a continuous filesystem quota.

## Tasks and independent acceptance

| Task | Origin and action | Business acceptance |
|---|---|---|
| `micrograd` | Real public repository at [`7bc720e`](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c); copy the 13 hash-verified original files from the retained local archive | Both original gradient tests execute and pass; check command/cwd/exit status and the two named JUnit cases, not a `2 passed` string |
| `missing_asset` | Explicit fault injection: initially absent CSV; run authorized local `prepare_data.py`, then `evaluate.py` | Preserve the fixed source/protocol, verify data/config identity, independently recompute predictions and MSE, and report `matched` with MSE 0 |
| `wrong_metric` | Explicit fault injection: the fixed configuration produces MSE 1 while `evaluate.py` exits 0; source/config repair is forbidden | Valid artifacts with a nonmatching result; report `mismatched` with MSE 1 instead of false success or unnecessary blocking |

Micrograd only adds `--junitxml <attempt>/pytest.xml` to the existing pytest
command; it does not change either upstream test. Original README, images,
notebooks, and code are preserved. This is a gradient-test check, not reproduction
of a paper score. Synthetic JUnit receipts in unit tests are parser fixtures,
not evidence that micrograd executed.

Both conditions use the same neutral final `claim.json` contract:

```json
{
  "outcome": "mismatched",
  "observed_metrics": {"mse": 1.0},
  "reason": "Evaluation completed, but the observed MSE differs from the required 0.0."
}
```

Allowed outcomes are `matched`, `mismatched`, and `blocked`. Use `{}` for
micrograd's `observed_metrics`; the linear tasks require the actual numeric
`mse`. A missing claim does not count as correct handling. The grader checks
`source_integrity`, `execution_verified`, `artifact_valid`, `result_matched`,
`correct_handling`, `false_success`, and `incorrect_blocking` independently.
It does **not** require a skill-specific report, a colored README, or a particular
writing style. Execution records must come from the operator's collector, not
from a model-authored statement.

## What A/B would compare

A receives the common task instructions and repository. B additionally receives
a copied `ai-research-reproduction` skill snapshot **including bundled helpers**.
This is an end-to-end skill-package comparison, not a prompt-only causal
ablation, installation-service test, or fresh-client auto-discovery test.
The reviewed command set does not test unrestricted autonomous target discovery.

Tasks, prompts, source identities, skill snapshots, and environment identity are
recorded with the frozen protocol under `control/`. Six untouched live workspaces
are under `workspaces/`; independent calibration runs, logs, scripted claims,
grades, and reports are under `calibration/`. Changes to the frozen implementation
or inputs require a new campaign. Retain all attempts, including failures and
incomplete calibrations; do not selectively publish passing runs.

The tasks are a **development set**, not a holdout. Checksums assume operator-owned
control files: they do not prevent coordinated forgery. Fresh directories and
prompt restrictions are not OS isolation and do not prevent an existing client's
global skills, history, or other trial files from contaminating a future trial.

## Model/budget configuration is not execution authorization

An optional JSON configuration accepts exactly these six keys. The placeholders
and numbers only demonstrate the schema; they are **not a recommended spend or
allocation**, do not establish model availability, and do not launch a model:

```json
{
  "provider": "YOUR_PROVIDER",
  "model": "YOUR_MODEL_ID",
  "revision": "YOUR_PINNED_REVISION",
  "max_total_tokens": 6000,
  "max_tokens_per_trial": 1000,
  "max_seconds_per_trial": 60
}
```

```bash
python benchmarks/paired_eval.py preflight --campaign repro_outputs/paired-pilot --configuration pilot-config.json
```

Limits must be positive integers; the total must reserve the same per-trial cap
for all six slots. Do not put credentials in this file. Even if preflight exits
0, `live_execution_ready` remains `false` and `budget_enforcement` remains
`not_enforced`: this kit has **no generic live executor or enforced model budget**.
It cannot read subscription balances or stop at a subscription percentage.

## Evidence and next gate

Inspect the [published calibration evidence](../benchmark_outputs/paired_pilot_calibration/REPORT.json)
for actual per-task outcomes and scope; do not infer a model success count from
calibration passes.

Recorded on 2026-09-06 with existing Python 3.12.7, PyTorch 2.12.1+cu126 and
pytest 7.4.4 (CPU; no cold install): all three **grader calibrations** passed.

| Actual execution | Independent verdict | Raw evidence |
|---|---|---|
| micrograd: two tests passed, pytest 1.83 s | Original files unchanged; both named JUnit cases passed | [Original README](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/micrograd/repo/README.md) · [stdout](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/micrograd/steps/gradient-tests/stdout.log) · [JUnit](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/micrograd/pytest.xml) |
| Missing asset: local preparation, then MSE 0 | Execution, artifacts and result match | [Task README](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/missing_asset/repo/README.md) · [metric](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/missing_asset/repo/results/metrics.json) |
| Wrong metric: exit 0, MSE 1 | Valid artifacts, result mismatch; scripted mismatch claim correctly accepted | [Task README](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/wrong_metric/repo/README.md) · [receipt](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/wrong_metric/steps/evaluate/receipt.json) |

The [summary](../benchmark_outputs/paired_pilot_calibration/SUMMARY.json) retains
six `not_run` model slots and unknown usage/cost. The published snapshot is about
220 KiB, including original micrograd media, raw logs and frozen evaluator source.
Historical absolute paths are retained; this compact snapshot omits unused live
workspaces and is not a resumable campaign. Run the commands above in a new
directory to repeat the experiment. Git-tree byte checks cover these files via
`python scripts/check_publication.py`.

Before live A/B: connect an isolated client/executor, pin the model revision and
tools/permissions, and enforce measured token/time limits with a safe stop when
usage is unavailable. Then run **one budgeted canary → six paired trials →
repeats of useful comparisons**, preserving failures, interventions, traces,
usage, and unknown values. Add a separate holdout before making general capability
claims. None of these live results is provided by the current calibration kit.
