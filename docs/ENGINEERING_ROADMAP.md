# Engineering roadmap and acceptance criteria

[简体中文](ENGINEERING_ROADMAP.zh-CN.md) · [README](../README.md) · [Implementation record](P0_P1_DELIVERY.md)

Updated 2026-09-22. Planned work is not an implemented capability.

The [agent-runtime review](AGENT_RUNTIME_REVIEW.md) adds an optional short-call
supervisor with exact plan handoff argv, reusable job receipts and independent
completion-time acceptance. Real subprocess fault comparisons and separate
`ckrao` calls exercise the mechanism. Two installed micrograd attempts retain
valid timeout evidence and remain failures; the later review validation passes
the unchanged tests and independent grader at the same 30-second target limit.
This does not rewrite the historical AUTO failures or unlock a model A/B claim;
a fresh Codex-sandbox acceptance run is still a separate gate.

## Product scope

RigorPilot turns research-repository README targets into bounded execution and
auditable evidence. It targets small inference/evaluation runs, reproduction
preflight, conservative training startup and diagnosis. Trusted execution is
the default; source exploration needs explicit authorization. It does not
replace researcher judgment or change algorithms/budgets to manufacture success.

## Current capabilities

| Area | Implementation | Boundary |
|---|---|---|
| Installation | Self-contained main skill; shared bundled runtime and guides for all-skills installs | Tests cover installed layouts, public CLIs and actual short execution, not a live third-party installation service |
| Reviewed planning | `--plan-only` exposes README-backed `cmd-XX` candidates and a selection fingerprint; explicit execution binds command ID to the reviewed candidate set | Setup/download commands are excluded; a changed candidate set fails before target execution; this is not a sandbox or command-authenticity proof |
| Execution | Processes, timeout/cancel, events/logs and explicit executable identity | Local host, not an OS sandbox; sampling/admission is not a hard resource quota |
| Recovery | Checkpoints, completed-result reuse, uncertain-dispatch blocking | No blind request replay or training-checkpoint restoration |
| Verification | Independent commands/source checks; stable machine-readable error codes; optional artifact size/hash and JSON-metric tolerances, rechecked at finish | Without configured structured checks, acceptance remains exit/stdout-only; no artifact-freshness or paper-reproduction claim |
| README | Byte-preserving inserts and optional source-adjacent copies in ordinary runs, preserving original media context | Conflicting files are retained; regenerate links after moving directories; external-media availability is not guaranteed |
| Models / clients | Codex real-client acceptance has one successful explicit named-skill Fast Path; natural-language fresh-client runs repeatedly prove automatic project-skill loading | AUTO end-to-end acceptance is still failed: first on a self-tightened 20 s timeout, then after preserving 30 s but wrapping the whole orchestrator in an equal external timeout and interrupting terminal evidence. No A/B effect estimate; the optional standalone Anthropic transport remains separate |
| External evidence | Four historical commit-pinned protocols plus a fresh 4/4 plan-only reviewed-selection pass on the same pinned repositories | The new pass verifies target planning only; historical cases include selection-only and partial runs, not four paper reproductions or an unseen-task success rate |
| Integrity performance | Repeatable synthetic tracked-file benchmark; current Windows baseline records 1k and 10k file snapshot/verify costs | Small synthetic files, one host and Python-allocation measurements; not a latency SLA. Change the snapshot strategy only after a simpler replacement clearly wins on the same benchmark without weakening detection |
| Paired pilot preparation | Three frozen tasks, six A/B slots, independent graders and real local calibration | All six model slots remain unrun; no generic live executor or enforced model budget in this kit |
| Neutral trial core | Restricted tools, independent grading, durable reservations and a bounded Messages A/B CLI | Local HTTP integration tested; successful real-provider acceptance, campaign billing caps, bundled-helper execution and OS isolation remain absent |
| Functional acceptance | Installed-layout runtime, exact positive/negative outcomes, independent predictions/logs and README checks; optional pinned micrograd | [Four actual checks](SKILL_ACCEPTANCE.md); scripted preparation, existing dependencies, no model uplift or cold-install claim |

## Acceptance layers

1. **Engineering regression:** `python scripts/run_all_tests.py` covers installed
   layouts, invalid model responses, recovery, source fidelity and a real target
   command asserting it executes inside the created virtualenv.
2. **Offline verification:** `python scripts/run_harness_lab.py` uses fixed
   simulated decisions with real failure, preparation, pause and process restart.
   No API/GPU/downloads; not model-quality evidence.
3. **Repository protocols:** [Pinned cases](../benchmarks/README.md) distinguish
   selection, execution, partial completion and metric matching.
   The reviewed-selection suite independently checks `cmd-XX` identity,
   fingerprint binding and plan-only side effects on all four pinned repositories.
4. **Optional standalone-runner acceptance:** one bounded
   [micrograd canary](../benchmarks/run_agent_canary.py), only with a working
   service and confirmed budget. Preserve actual model/tool traces, usage,
   independent verdict and source hash before expanding the matrix.

## Delivery priorities

| Priority | Deliverable | Acceptance gate |
|---|---|---|
| P0: ongoing | Installation, portability, publication, feedback and security documentation | Installed files work; three-platform CI passes; failures are not reported as success |
| P1: implemented, ongoing regression | Reviewable README command selection | Candidate IDs and fingerprint are exposed before execution; stale plans, unknown IDs, setup/download targets and unreviewed shell syntax fail closed |
| P1: default skill | Fresh installed-skill use on one commit-pinned public repository | Actual logs, original-file/media integrity, browsable annotations and independent checks; distinguish installation, explicit invocation and client auto-loading |
| P1: optional standalone runner | One real-model run, with no manually substituted trajectory | Responses, tools, usage and verifier evidence; stop and retain service failures; not a prerequisite for the default skill route |
| P1: implemented, ongoing regression | Both main runners accept `--source-adjacent-readme` | Nested README/media/evidence links work; original bytes and unrelated files are retained; repeats check ownership |
| P2 | Frozen tasks, independent graders and same-condition baselines | Separate task completion, false success, incorrect blocking, cost, interventions and evidence integrity |
| P2 | Optional isolated executor, network/file boundaries and resource limits | Explicit threat model and boundary tests; no sandbox claim when unconfigured |
| P3 | Model regression, releases, compatibility notes and failure classification | Each version has regression evidence and change notes; historical evidence remains inspectable |

Defer large training runs, arbitrary source repair, multi-agent orchestration
and long-term memory infrastructure until demonstrated failures justify them.

## Current delivery plan

Installed explicit-skill use, reporting fixes and independent checks are recorded
in the [micrograd acceptance report](FIRST_USE_ACCEPTANCE.md). The default
orchestrator now has a reviewable `plan -> command-id/fingerprint -> run -> verify`
path, stable error codes, and a fresh 4/4 pinned-repository planning check.
The [real-client follow-up](REAL_CLIENT_ACCEPTANCE.md) passed explicit named-skill
Fast Path acceptance and repeatedly observed fresh-client automatic skill loading.
The 2026-09-20 AUTO failed after tightening the allowed 30 s command bound to 20 s.
The 2026-09-21 AUTO preserved 30 s but wrapped the whole orchestrator in an equal
30 s external timeout, leaving the runtime nonterminal and no `status.json` before
the outer client hit 240 s. A/B comparisons remain unrun.

The source-integrity benchmark currently records roughly `0.705 s / 0.670 s`
snapshot/verify at 1k tracked 128-byte files and `6.054 s / 5.897 s` at 10k on
the local Windows host. Keep the direct full-content hash implementation for now;
revisit it only when a lower-complexity Git-tree/index design shows a clear win
on the same benchmark without weakening dirty-source detection.

The [neutral controller core](CONTROLLED_TRIALS.md) now exercises tool and budget
boundaries without new model calls. Its skill namespace is read-only, so future
trials using it require a new constrained-tool protocol, not silently relabeling
the earlier full skill-package schedule. The next live gate still requires an
explicit model/budget, audited transport, campaign accounting and execution isolation.

Apply these gates; generated files alone do not establish task completion:

| Order | Scope | Acceptance and stopping condition |
|---|---|---|
| 1 | Reviewed planning across pinned repositories | `--plan-only` selects the expected README target, exposes a review token and writes no evidence; current four-case result is 4/4 |
| 2 | Explicit named-skill real-client canary | **Passed 2026-09-20**: task/runtime success, independent grader, source integrity, evidence verification and `turn.completed` |
| 3 | Fresh-client natural-language auto-loading canary | Skill loading is repeatedly observed. End-to-end acceptance still fails: the latest run preserves the 30 s target timeout but kills the orchestrator with an equal external wrapper timeout. Keep failures; require direct orchestrator execution and terminal evidence before A/B |
| 4 | Independent acceptance and publication | Check actual logs, original-file SHA-256, per-section restoration and local evidence links; full regression and Git publication checks before sync |
| 5 | Small paired evaluation (preparation/calibration delivered; live pending) | Start only after the corrected AUTO gate passes; then use [frozen tasks and actual grader calibration](PAIRED_PILOT.md) for one canary and six paired trials |

Installation, execution with an explicitly named skill/path, and automatic skill
selection in a fresh client are separate gates. The first two do not establish
the third without session-loading evidence. Independent agents consume host
model resources; no separate API call does not mean zero tokens or zero cost.
Fresh client sessions and standalone calls require an explicit model and budget.
An optional read-only [Codex quota helper](SKILL_ACCEPTANCE.md#optional-codex-quota-snapshot)
can retrieve reported windows; it is not integrated budget enforcement and cannot
guarantee a minimum subscription percentage after a running request.

## Reusable evaluation protocol (offline foundation delivered; live planned)

The [paired pilot kit](PAIRED_PILOT.md) implements task/input/implementation
freezing, fresh directories, independent graders and append-only local calibration.
Its three real-command calibrations are separate from the six still-unrun live
slots. Model configuration is preflight validation only, not execution or spending
enforcement. Next acceptance: isolated client, measured usage/time stops, one live
canary, then paired trials with all attempts retained.

Begin with three tasks and two conditions (six attempts): normal execution,
missing required assets, and exit-zero/wrong-result. Missing-resource tasks
should identify the cause and take an authorized safe next step, not reward
blanket refusal. Label fault injection; single trials do not estimate unseen-task
success rates. Compare A/B for the default route first; add C after successful
standalone acceptance. Expand to six tasks and three conditions only when useful,
then to twelve frozen tasks across 4–6 repositories, with three repeats for key tasks.
Separate development from holdout data; existing public cases are regressions,
not unseen tasks.

A: same model with generic task instructions; B: A plus the skill package,
including bundled helpers (an end-to-end package comparison, not prompt-only);
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
