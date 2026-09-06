# Harness Smoke Benchmarks

## Small paired-evaluation kit

Prepare three frozen tasks and six unrun A/B slots, then calibrate the independent
graders with real local commands. This kit does **not** execute live models:

```bash
python benchmarks/paired_eval.py prepare --output repro_outputs/paired-pilot --python python
python benchmarks/paired_eval.py calibrate --campaign repro_outputs/paired-pilot
python benchmarks/paired_eval.py summarize --campaign repro_outputs/paired-pilot
```

Use an existing Python with torch/pytest for micrograd; the other two tasks need
only the standard library. No dependency installation, network fetch or model
call. Read the [protocol, preflight and actual calibration evidence](../docs/PAIRED_PILOT.md)
([简体中文](../docs/PAIRED_PILOT.zh-CN.md)) before using the results. All six model
slots remain `not_run`; a valid budget configuration is not an enforced budget.

## Golden reproduction smoke

Run the deterministic, API-free harness check:

```bash
python benchmarks/run_golden_smoke.py
```

The benchmark creates isolated temporary repositories and verifies high-value
reproduction outcomes:

- an explicitly expected metric matches within tolerance;
- an out-of-tolerance metric is not mislabeled as a result match;
- a missing executable is recorded as blocked with a complete evidence bundle;
- shell syntax is refused in direct mode until native shell execution is
  explicitly authorized.

The machine-readable report is written to
`benchmark_outputs/golden_smoke.json`. It makes no API calls and requires no
GPU. This is a harness regression smoke test, not evidence of broad paper
reproduction capability.

## Installed-skill first-use check

Inspect the [recorded micrograd trial](../docs/FIRST_USE_ACCEPTANCE.md): one
independent explicit-skill use, a retained failed parent replay, and a corrected
replay. This is not a model A/B benchmark or fresh-client auto-loading test.

For a new local experiment with a pre-run baseline and source-adjacent output:

```bash
python benchmarks/check_first_use.py --baseline trial/BASELINE.json --repo trial/repo --output-dir trial/repro_outputs --expected-stdout "2 passed" --report trial/CHECK.json
```

Capture the baseline **before** execution: its non-empty `originals` object maps
every original repo-relative file path (including media) to its SHA-256. An
example is the recorded trial's [baseline](../benchmark_outputs/showcases/micrograd-first-use-before/BASELINE.json).
The baseline is trusted input, not an agent-produced success claim. The grader
does not prove that the baseline is complete or authentic.

The checker reads raw runtime state/events/logs, independently scans annotation
bytes and insertion offsets, and checks local evidence links. `--report` must
be a new file outside both the target and evidence directories. Exit 0 means
these checks passed; exit 1 means a failed check. Omitting `--expected-stdout`
makes no task-completion claim. Use a task-specific condition; `2 passed` is
for this micrograd case, not a universal grader. README quality is scored
separately from the task log condition.

It does not run the target, verify scientific metrics or implement an OS
security boundary. Recorded paths must refer to the active local experiment;
for relocated public snapshots use `python scripts/check_publication.py`
instead. Calibration tests: `python scripts/test_first_use_verifier.py`.

## Persistent queue smoke

Run the deterministic local scheduler check:

```bash
python benchmarks/run_queue_smoke.py
```

It verifies two-job concurrency admission, dependency gating, failure
isolation, over-budget blocking, and complete per-job Runtime evidence. Its
machine-readable report is written to `benchmark_outputs/queue_smoke.json`.
The benchmark makes no API calls and requires no GPU. Resource requests are
admission values, not proof of OS-level resource enforcement.

## Pinned external reproduction

Run one explicitly selected real-repository case:

```bash
python benchmarks/run_external_reproduction.py --case micrograd
```

The ready `micrograd` correctness canary performs a fresh commit-pinned fetch,
creates a new virtual environment, follows the README installation, asks the
real reproduction orchestrator to select and execute the documented test, and
checks the evidence bundle plus tracked-source integrity. Secret-named host
environment variables are removed before any external command runs. By default
the checkout, venv, data, and raw runtime logs are deleted after compact
evidence files are copied to `benchmark_outputs/evidence/` with SHA-256 hashes.
Use `--keep-workspace` only for active debugging.

For a durable, directly browsable example, retain only the pinned repository's
tracked files plus its reproduction evidence (no `.git`, venv, cache, or
untracked runtime residue):

```bash
python benchmarks/run_external_reproduction.py --case micrograd --showcase-root benchmark_outputs/showcases
```

The result is `benchmark_outputs/showcases/micrograd/repo/`: the untouched
upstream `README.md`, all tracked files it references, `repro_outputs/`, and a
source-adjacent `RIGORPILOT_README.md`. Relative images and repository links
therefore resolve in the same repository context. `SHOWCASE.json` records the
source URL, exact commit, file count, size, and README round-trip hashes.

Run an explicit ordered matrix sequentially:

```bash
python benchmarks/run_external_suite.py --cases micrograd mingpt pytorch-mnist nanogpt-shakespeare --max-total-minutes 8 --showcase-root benchmark_outputs/showcases
```

There is no implicit run-all mode. The suite enforces time and free-disk gates,
isolates failures, writes `external_suite_latest.json`, and appends compact
identity-keyed rows to `external_suite_history.jsonl`. Each case also enforces
a 128-256 MiB workspace ceiling. The harness content, case configuration, and
target commit are independently fingerprinted.

Cases and exact commits live in `external_cases.json`:

| Case | State | Purpose |
|---|---|---|
| `micrograd` | execution | README selection and gradient correctness tests |
| `mingpt` | selection-only | Select the unit test but avoid its unbounded GPT-2 download |
| `pytorch-mnist` | bounded execution | Data download, training startup, metric parsing, process-tree stop |
| `nanogpt-shakespeare` | bounded execution | Prerequisite-aware CPU selection, data preparation, progress capture |

The training cases intentionally expect `partial`: the trusted runtime stops
their process trees at 60 and 45 seconds respectively. That proves bounded
startup and evidence capture, not convergence or paper-result reproduction.
minGPT is explicitly selection-only because its README unit test downloads
GPT-2 weights; a selection-only pass must never be reported as execution.

The micrograd lane reuses host PyTorch and pytest inside a fresh venv and keeps
package/network caches. The matrix is therefore a low-cost fresh-workspace
benchmark, not a fully cache-purged dependency cold start. Retry only failed
cases during diagnosis, then rerun the explicit matrix for a common harness
fingerprint.

The runner locates the created virtualenv's actual `Scripts`/`bin` entrypoint
and records it. Direct commands resolve executables against child PATH/PATHEXT,
with relative paths anchored to the target cwd; the local pinned fixture asserts
that the target command really runs inside that venv. Existing public snapshots
predate this assertion and have not been rerun as part of the installation audit.
They remain historical execution evidence, not proof of strict interpreter isolation.
