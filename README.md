# RigorPilot Skills

Run research repositories from their README, with bounded execution and auditable evidence.
RigorPilot adds section-level results without rewriting the original README.
Trusted reproduction is the default; candidate exploration requires explicit authorization.

[English](README.md) · [简体中文](README.zh-CN.md)

[![Skillselion Top 100](https://skillselion.com/badge/skills/lllllllama/rigorpilot-skills/paper-context-resolver.svg?award=1)](https://skillselion.com/skills/lllllllama/rigorpilot-skills/paper-context-resolver)

<p>
  <a href="https://github.com/lllllllama/RigorPilot-Skills/actions/workflows/validate.yml"><img alt="CI" src="https://github.com/lllllllama/RigorPilot-Skills/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://skillselion.com/skills/lllllllama/rigorpilot-skills/ai-research-reproduction"><img alt="Listed on Skillselion" src="https://skillselion.com/badge/skills/lllllllama/rigorpilot-skills/ai-research-reproduction.svg"></a>
  <a href="https://skills.sh/lllllllama/rigorpilot-skills"><img alt="skills.sh installs" src="https://skills.sh/b/lllllllama/rigorpilot-skills"></a>
  <a href="https://github.com/lllllllama/RigorPilot-Skills/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/lllllllama/RigorPilot-Skills?style=flat-square"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square"></a>
  <a href="https://agentskills.io"><img alt="Agent Skills standard" src="https://img.shields.io/badge/Agent%20Skills-open%20standard-1f6feb?style=flat-square"></a>
  <img alt="platforms" src="https://img.shields.io/badge/Windows%20%7C%20Linux-supported-6f42c1?style=flat-square">
  <img alt="local regression" src="https://img.shields.io/badge/local%20regression-76%2F76%20passed-8250df?style=flat-square">
  <a href="benchmark_outputs/external_suite_latest.json"><img alt="historical external protocols" src="https://img.shields.io/badge/historical%20protocols-4%2F4%20passed-238636?style=flat-square"></a>
</p>

<p align="center">
  <a href="#examples"><strong>Real examples</strong></a> ·
  <a href="#quick-start"><strong>Install & use</strong></a> ·
  <a href="#skills"><strong>Skill index</strong></a> ·
  <a href="#validation"><strong>Validation</strong></a> ·
  <a href="docs/ENGINEERING_ROADMAP.md"><strong>Engineering roadmap</strong></a>
</p>

<a id="examples"></a>
<a id="evidence"></a>

## 📄 Real repositories, inspectable results

Original commands, prose, badges, images, videos and HTML stay in the source file.
RigorPilot splits that file into sections and inserts one evidence-linked card per section.
Removing its insertion blocks restores the retained original README byte for byte.

Each card below opens a full annotated README **beside the original README in a
retained repository checkout**. Supporting repository files are kept so relative
links and media retain their original context.

🟢 selected checks passed · 🔵 not executed · ⚪ read only · 🟡 partial · 🔴 blocked · 🟣 decision needed.
Green does not automatically mean paper-result reproduction; blue is not an execution failure.

<table>
  <tr>
    <td align="center" width="50%">
      <a href="benchmark_outputs/showcases/micrograd/repo/RIGORPILOT_README.md"><img src="assets/showcase/external-micrograd.png" width="100%" alt="micrograd: recorded pytest execution and section-level evidence"/></a><br/>
      <b>micrograd · correctness checks</b><br/>
      <sub>🟢 2 tests passed in 7.62 s<br/>8 headings = 8 annotations · original bytes preserved</sub><br/>
      <a href="benchmark_outputs/showcases/micrograd/repo/RIGORPILOT_README.md">Open full RigorPilot README →</a>
    </td>
    <td align="center" width="50%">
      <a href="benchmark_outputs/showcases/mingpt/repo/RIGORPILOT_README.md"><img src="assets/showcase/external-mingpt.png" width="100%" alt="minGPT: target selection only, with no model download or execution"/></a><br/>
      <b>minGPT · selection boundary</b><br/>
      <sub>🔵 Test selected, not executed · no model download<br/>11 headings = 11 annotations · original bytes preserved</sub><br/>
      <a href="benchmark_outputs/showcases/mingpt/repo/RIGORPILOT_README.md">Open full RigorPilot README →</a>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <a href="benchmark_outputs/showcases/pytorch-mnist/repo/mnist/RIGORPILOT_README.md"><img src="assets/showcase/external-pytorch-mnist.png" width="100%" alt="PyTorch MNIST: partial bounded training and captured loss"/></a><br/>
      <b>PyTorch MNIST · bounded startup</b><br/>
      <sub>🟡 Partial training · observed loss 0.038893<br/>1 heading = 1 annotation · original bytes preserved</sub><br/>
      <a href="benchmark_outputs/showcases/pytorch-mnist/repo/mnist/RIGORPILOT_README.md">Open full RigorPilot README →</a>
    </td>
    <td align="center" width="50%">
      <a href="benchmark_outputs/showcases/nanogpt-shakespeare/repo/RIGORPILOT_README.md"><img src="assets/showcase/external-nanogpt.png" width="100%" alt="nanoGPT Shakespeare: partial CPU training and captured train and validation losses"/></a><br/>
      <b>nanoGPT Shakespeare · bounded training</b><br/>
      <sub>🟡 Partial · train loss 4.1676 · validation loss 4.1649<br/>11 headings = 11 annotations · original bytes preserved</sub><br/>
      <a href="benchmark_outputs/showcases/nanogpt-shakespeare/repo/RIGORPILOT_README.md">Open full RigorPilot README →</a>
    </td>
  </tr>
</table>

[All four cases and upstream links](benchmark_outputs/EXTERNAL_REPRODUCTIONS.md) ·
[Recorded suite](benchmark_outputs/external_suite_latest.json) ·
[Case definitions](benchmarks/external_cases.json) · [Methodology](benchmarks/README.md)

These are historical, commit-pinned deterministic runs: **4/4 case protocols**
passed in `251.0 s`, with a peak workspace of `98.67 MiB` and `0` model API calls.
The zero-API count applies only to that suite. Selection-only and partial cases
are not completed evaluations, converged training or reproduced paper scores.

New: [installed-skill micrograd trial](docs/FIRST_USE_ACCEPTANCE.md), with before/after command reports, a retained failed attempt and independent checks—not a model-quality comparison.

Real model trial: [public install → 2 tests passed → evidence verified → client timed out](docs/REAL_CLIENT_ACCEPTANCE.md). Full outputs and failed attempts are retained; end-to-end acceptance and model uplift are not claimed.

<a id="quick-start"></a>

## 🚀 Install and use

The installer needs Node.js/npm. Tested with `skills@1.5.26` and Node 22.20.0;
that installer requires Node ≥22.20.0. If you see `EBADENGINE`, check the requested version.

Install all skills:

```bash
npx skills add lllllllama/rigorpilot-skills --all
```

Or install only the self-contained reproduction skill:

```bash
npx skills add lllllllama/rigorpilot-skills --skill ai-research-reproduction
```

Open the target repository in a Skills-capable agent, then ask:

> Use ai-research-reproduction: run the smallest README-documented evaluation, preserve the source and write evidence to repro_outputs/, plus an annotated copy beside the original README. Ask before large downloads or long training.

The main skill works alone; choose **all skills** for companion and leaf entrypoints.
Your existing agent loads the skill. The standalone model runner is optional.
[Client compatibility](references/client-compatibility-policy.md)

Recommended first run:

| Step | What it does | What it does not do |
|---|---|---|
| Plan | Lists README-backed `cmd-XX` candidates, selects the smallest trusted target, and returns a selection fingerprint | No target execution, installs, downloads, source edits or evidence writes |
| Run | Executes a reviewed `command-id` bound to that plan fingerprint and writes evidence under the target repo by default | Setup/download commands cannot be selected; a changed plan fails before target execution |
| Verify | Rechecks the retained evidence, README round trip, runtime state and current source snapshot | Does not rerun the target command |

Start with the `RIGORPILOT_README.md` reported in `source_adjacent_readme.path`,
then follow its command and log links. If a conflicting file blocks the extra
copy, that file stays intact; inspect `repro_outputs/SUMMARY.md` for the outcome
and next action.

## What it does—and does not do

README → documented target → reviewed setup → bounded execution → verification → evidence.

- Preserves source meaning; records assumptions, deviations, failures and blockers.
- Records process state, logs and attempt lineage; supports explicit cancellation,
  recovery and retry through the persistent runtime.
- Separates trusted reproduction from explicitly authorized, candidate-only exploration.
- Checks execution criteria independently of the model's completion claim.

This is **local execution, not an OS sandbox**. Approved commands can access the
host and network; use trusted repositories. Resource admission and between-action
budget checks are not hard OS quotas or subscription-balance monitoring.

The optional model loop currently supports Anthropic Messages and reviewed command
IDs, not unrestricted source repair. **This standalone runner has no successful
live-model acceptance recorded yet**: three provider attempts returned HTTP 502. Other model profiles
are metadata, not proof of working transports or equivalent model performance.
[Runner and recovery contract](skills/ai-research-reproduction/references/agent-runner.md) ·
[Implementation evidence and limits](docs/P0_P1_DELIVERY.md)

<a id="skills"></a>

## 🎯 Skill index

| Task | Skill |
|---|---|
| Reproduce from README commands | [`ai-research-reproduction`](skills/ai-research-reproduction/SKILL.md) |
| Read-only repository analysis | [`analyze-project`](skills/analyze-project/SKILL.md) |
| Prepare environment, data and weights | [`env-and-assets-bootstrap`](skills/env-and-assets-bootstrap/SKILL.md) |
| Run documented inference or evaluation | [`minimal-run-and-audit`](skills/minimal-run-and-audit/SKILL.md) |
| Start or verify training conservatively | [`run-train`](skills/run-train/SKILL.md) |
| Diagnose before proposing a patch | [`safe-debug`](skills/safe-debug/SKILL.md) |
| Coordinate authorized candidate exploration | [`ai-research-explore`](skills/ai-research-explore/SKILL.md) |
| Implement a candidate change on an isolated branch | [`explore-code`](skills/explore-code/SKILL.md) |
| Execute a bounded candidate experiment | [`explore-run`](skills/explore-run/SKILL.md) |

Two helpers support orchestration: `repo-intake-and-plan` and `paper-context-resolver`.
Exploration requires a durable `current_research` anchor and a frozen comparison
contract. Candidate results never become trusted baseline results by declaration.
[Routing](references/routing-policy.md) · [Research loop](references/research-thinking-loop.md) ·
[Campaign inputs](skills/ai-research-explore/references/research-campaign-spec.md)

## 📦 Evidence bundle

| Artifact | What to inspect |
|---|---|
| `repro_outputs/ANNOTATED_README.md` | Original README with inserted section verdicts |
| `SUMMARY.md`, `COMMANDS.md`, `LOG.md`, `status.json` | Outcome, exact commands, reviewed selection provenance, stable `error.code`, observations and machine-readable status |
| `invocation.json`, `evidence_manifest.json` | Invocation/source-integrity summary plus retained file sizes and SHA-256 hashes for local consistency checks |
| `PATCHES.md`, `SCIENTIFIC_CHANGELOG.md`, `COMPARABILITY_REPORT.md` | Changes, scientific meaning and comparison boundaries |
| `_runtime/<run_id>/` | Process state, events, resource samples and stdout/stderr |
| `agent_state.json`, `trajectory.jsonl` | Optional model runner's checkpoints, tool calls and reported usage |

🟢 success · 🔵 not executed · ⚪ read only · 🟡 partial · 🔴 blocked · 🟣 decision required

Standard evidence stays under `repro_outputs/`. Both main runners accept
`--source-adjacent-readme` to also write `RIGORPILOT_README.md` beside the original,
preserving the context of its relative media/file links. Only inserted evidence
links are rebased. The same output directory may refresh its unchanged owned
copy, never an unrelated or manually edited file. Retain supporting repository
files and the evidence directory's `readme_delivery.json`.
[Output contract](references/output-contract.md) · [Rigor principles](references/research-rigor-principles.md)

For agent clients, the shortest normal path is `--plan-only --agent-output`, then
run a returned `cmd-XX` with its `--plan-fingerprint`, then `--verify-output --agent-output`.
The fingerprint binds execution to the reviewed README command set; setup/download
commands are excluded from reproduction candidates. Routine success should not
require reading orchestrator, bundle, writer, or runtime source.
When `--output-dir` is omitted, the orchestrator writes to the target repository's
`repro_outputs/` directory, not the caller's current working directory.
The evidence manifest detects later changes against the retained manifest; it is
not a digital signature, external attestation or substitute for an OS sandbox.

<a id="validation"></a>

## ✅ Offline validation

From a clone of this project, with Python 3.11+ and Git:

```bash
python benchmarks/run_skill_acceptance.py --output tmp/skill-check
```

Runs the installed-layout skill runtime on three small cases: missing data,
matching metrics, and exit-zero/wrong metrics. Independently checks raw logs,
predictions, original files and README insertions. With existing PyTorch/pytest,
add `--include-micrograd` to run the two unchanged upstream tests too.
No model calls, downloads or package installs; use a fresh output directory each time.
[Recorded outcomes and full evidence](docs/SKILL_ACCEPTANCE.md) — **4/4 functional
checks**, not four successful reproductions or measured model uplift.

For installation/environment problems (replace the skill path after installation):

```bash
python skills/ai-research-reproduction/scripts/doctor.py --repo /path/to/target
```

This read-only check reports the actual Python, Git, bundled-file integrity and
README availability. Add `--require-module torch --require-module pytest` for
dependency discovery; it does not install anything or execute target code.

For the failure-and-recovery walkthrough:

```bash
python scripts/run_harness_lab.py
```

This offline example uses **scripted decisions and actual processes**. It exercises
failure → preparation → pause → controller restart → independent verification,
without API calls, GPU use or model downloads. Inspect the printed `REPORT.json`
path and its linked artifacts. Existing output is never overwritten; use
`--output tmp/check-2` to repeat. It is not evidence of live-model capability.
[Example source and checks](examples/harness-lab/README.md)

Run the repository regression suite:

```bash
python scripts/run_all_tests.py
```

The validator also checks the repository's Agent Skills metadata constraints,
including skill-name syntax/length, description length, optional compatibility
length, `metadata`/`allowed-tools` types, and the repository's public `SKILL.md`
line limit.

Two additional API-free checks cover the new control path:

```bash
python benchmarks/run_reviewed_selection_suite.py --cases micrograd mingpt pytorch-mnist nanogpt-shakespeare --output tmp/reviewed-selection.json
python benchmarks/run_source_integrity_benchmark.py --counts 1000 10000 --output tmp/source-integrity.json
```

The pinned reviewed-selection suite currently passes **4/4** without executing
target commands. The local source-integrity baseline records about **0.705 s / 0.670 s**
for snapshot/verify at 1k tracked files and **6.054 s / 5.897 s** at 10k small
tracked files. These are Windows synthetic-file measurements, not general latency guarantees.
[Reviewed-selection result](benchmark_outputs/reviewed_selection_latest.json) ·
[Integrity baseline](benchmark_outputs/source_integrity_latest.json)

Latest local Windows record (2026-09-20): **76/76 scripts passed in 245.9 s**.
The CI badge links to the current Windows, Linux and macOS results.
Local tests do not substitute for live-model or held-out evaluation.

For model comparisons, the [small paired-evaluation kit](docs/PAIRED_PILOT.md)
provides frozen tasks and actual grader-calibration logs. The six planned model
trials remain unrun; calibration is not evidence of skill uplift.

[Controlled-trial checks](docs/CONTROLLED_TRIALS.md) add real failure/recovery
logs, restricted tools and unknown-usage stops, with scripted model responses.
The guide also provides a [bounded A/B command-line entrypoint](docs/CONTROLLED_TRIALS.md#one-bounded-ab-pair)
for model transport → reviewed commands → independent grading → sealed summary.
Local HTTP integration is tested; real-provider effectiveness is not yet measured.

## Engineering and contributions

[Engineering roadmap](docs/ENGINEERING_ROADMAP.md) · [Contributing](CONTRIBUTING.md) ·
[Security and reporting](SECURITY.md) · [CI workflow](.github/workflows/validate.yml) ·
[Reproduction feedback](https://github.com/lllllllama/RigorPilot-Skills/issues/new?template=reproduction.yml) ·
[MIT license](LICENSE)

Keep acceptance checks independent, retain failed evidence and review traces
before publication. Do not publish credentials or unreviewed private repository data.
[Agent guidance](AGENTS.md) · [Operating principles](references/agent-operating-principles.md) ·
[Personalization policy](references/continuous-learning-policy.md)

<details>
<summary>Historical interface illustration—not execution evidence</summary>

<img src="assets/annotated-readme-preview.png" width="840" alt="Historical MiniSeg interface illustration, not independently verified execution evidence"/>

[First attempt](examples/annotated-readme-demo/first-run/ANNOTATED_README.md) ·
[After setup](examples/annotated-readme-demo/after-setup/ANNOTATED_README.md).
This older MiniSeg preview illustrates error, metric and authorization displays.
Its execution provenance is not independently verified; it is excluded from benchmarks.

</details>
