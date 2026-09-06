# Engineering roadmap and acceptance criteria

[简体中文](ENGINEERING_ROADMAP.zh-CN.md) · [README](../README.md) · [Implementation record](P0_P1_DELIVERY.md)

Updated 2026-09-06. Planned work is not an implemented capability.

## Product scope

RigorPilot turns research-repository README targets into bounded execution and
auditable evidence. It targets small inference/evaluation runs, reproduction
preflight, conservative training startup and diagnosis. Trusted execution is
the default; source exploration needs explicit authorization. It does not
replace researcher judgment or change algorithms/budgets to manufacture success.

## Current capabilities

| Area | Implementation | Boundary |
|---|---|---|
| Installation | Self-contained main skill; shared bundled runtime and guides for all-skills installs | Tests cover installed layouts, 20 public CLIs and actual short execution, not a live third-party installation service |
| Execution | Processes, timeout/cancel, events/logs and explicit executable identity | Local host, not an OS sandbox; sampling/admission is not a hard resource quota |
| Recovery | Checkpoints, completed-result reuse, uncertain-dispatch blocking | No blind request replay or training-checkpoint restoration |
| Verification | Independent commands/source checks; optional artifact size/hash and JSON-metric tolerances, rechecked at finish | Without configured structured checks, acceptance remains exit/stdout-only; no artifact-freshness or paper-reproduction claim |
| README | Byte-preserving inserts and optional source-adjacent copies in ordinary runs, preserving original media context | Conflicting files are retained; regenerate links after moving directories; external-media availability is not guaranteed |
| Models | Anthropic Messages tools, validated parameters and usage accounting | Three real attempts returned 502; no successful live acceptance. Other profile metadata does not imply transport support |
| External evidence | Four historical, commit-pinned protocols with retained source files/media | Includes selection-only and partial runs, not four paper reproductions or an unseen-task success rate |

## Acceptance layers

1. **Engineering regression:** `python scripts/run_all_tests.py` covers installed
   layouts, invalid model responses, recovery, source fidelity and a real target
   command asserting it executes inside the created virtualenv.
2. **Offline verification:** `python scripts/run_harness_lab.py` uses fixed
   simulated decisions with real failure, preparation, pause and process restart.
   No API/GPU/downloads; not model-quality evidence.
3. **Repository protocols:** [Pinned cases](../benchmarks/README.md) distinguish
   selection, execution, partial completion and metric matching.
4. **Optional standalone-runner acceptance:** one bounded
   [micrograd canary](../benchmarks/run_agent_canary.py), only with a working
   service and confirmed budget. Preserve actual model/tool traces, usage,
   independent verdict and source hash before expanding the matrix.

## Delivery priorities

| Priority | Deliverable | Acceptance gate |
|---|---|---|
| P0: ongoing | Installation, portability, publication, feedback and security documentation | Installed files work; three-platform CI passes; failures are not reported as success |
| P1: default skill | Fresh installed-skill use on one commit-pinned public repository | Actual logs, original-file/media integrity, browsable annotations and independent checks; distinguish installation, explicit invocation and client auto-loading |
| P1: optional standalone runner | One real-model run, with no manually substituted trajectory | Responses, tools, usage and verifier evidence; stop and retain service failures; not a prerequisite for the default skill route |
| P1: implemented, ongoing regression | Both main runners accept `--source-adjacent-readme` | Nested README/media/evidence links work; original bytes and unrelated files are retained; repeats check ownership |
| P2 | Frozen tasks, independent graders and same-condition baselines | Separate task completion, false success, incorrect blocking, cost, interventions and evidence integrity |
| P2 | Optional isolated executor, network/file boundaries and resource limits | Explicit threat model and boundary tests; no sandbox claim when unconfigured |
| P3 | Model regression, releases, compatibility notes and failure classification | Each version has regression evidence and change notes; historical evidence remains inspectable |

Defer large training runs, arbitrary source repair, multi-agent orchestration
and long-term memory infrastructure until demonstrated failures justify them.

## Current delivery plan

Installed explicit-skill use, reporting fixes and independent checks are now
recorded in the [micrograd acceptance report](FIRST_USE_ACCEPTANCE.md).
Fresh-client automatic loading and model comparisons remain unverified.

Apply these gates; generated files alone do not establish task completion:

| Order | Scope | Acceptance and stopping condition |
|---|---|---|
| 1 | One pinned micrograd checkout and independent installed-skill trial | Agent selects and executes from README without a supplied command; retain failures/interventions; reuse existing dependencies, no large downloads or training |
| 2 | Report issues observed during first use | Separate actual execution, unexecuted suggestions and observations; no automatic human decision merely for a missing environment file; real dependency/asset failures remain visible |
| 3 | Independent acceptance and publication | Check actual logs, original-file SHA-256, per-section restoration and local evidence links; full regression and Git publication checks before sync |
| 4 | Small paired evaluation (next) | Freeze three tasks and two conditions first; inspect graders and per-case differences before repeating or expanding |

Installation, execution with an explicitly named skill/path, and automatic skill
selection in a fresh client are separate gates. The first two do not establish
the third without session-loading evidence. Independent agents consume host
model resources; no separate API call does not mean zero tokens or zero cost.
Fresh client sessions and standalone calls require an explicit model and budget;
subscription balances are not available as a stopping signal.

## Reusable evaluation protocol (planned)

Begin with three tasks and two conditions (six attempts): normal execution,
missing required assets, and exit-zero/wrong-result. Missing-resource tasks
should identify the cause and take an authorized safe next step, not reward
blanket refusal. Label fault injection; single trials do not estimate unseen-task
success rates. Compare A/B for the default route first; add C after successful
standalone acceptance. Expand to six tasks and three conditions only when useful,
then to twelve frozen tasks across 4–6 repositories, with three repeats for key tasks.
Separate development from holdout data; existing public cases are regressions,
not unseen tasks.

A: same model with generic task instructions; B: A plus skill instructions;
C: B plus durable execution/recovery/evidence mechanics. Freeze model revision,
tool permissions, reviewed commands, budgets, source/environment and grader.
Retain raw traces for all arms. A baseline must not fail a business task merely
because it lacks a polished report. Different tools/permissions constitute an
end-to-end product comparison, not a single-factor ablation. Reviewed command
sets do not establish autonomous target discovery.

Cover normal execution, missing assets, exit-zero/wrong-result, interrupted
controller, premature completion and unauthorized large downloads. Label
injected faults separately. Protect external graders from agent modification;
check actual artifacts, metric tolerances and experimental conditions.

Record task/split/commit, harness/prompt/grader hashes, requested/returned model,
parameters, dependencies/cache, repeat, interventions, claimed/verified outcome,
trace, usage and latency. Mark unknown costs; include failed attempts in cost
per success. Report provider failures separately without removing them from
user-facing success denominators. Report both safe and incorrect blocking;
small samples warrant per-case evidence and uncertainty, not broad claims.
See [agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Upgrades and operation

Protocol/usage tests → one live canary → paired holdout comparison → release.
Change one factor at a time and preserve old results. Use ablations to remove
obsolete scaffolding as models improve. Borrow acceptance contracts and
independent checks from [long-running harness practice](https://www.anthropic.com/engineering/harness-design-long-running-apps),
and the checkpoint/memory distinction from [persistence design](https://docs.langchain.com/oss/python/langgraph/persistence),
without copying their architectural scale.

Prefer single-case, serial, budgeted validation. Token/time gates cannot read
subscription balances or replace provider-side spending caps. Do not download
large models implicitly or replay requests with unknown outcomes. Review traces
before publication; see [security](../SECURITY.md) and [contributing](../CONTRIBUTING.md).
Remote branch protection, private vulnerability reporting and account settings
require maintainer confirmation; repository templates do not enable them.
