# RigorPilot: learning and delivery roadmap

[简体中文：完整分析与学习路线](PROJECT_GUIDE.zh-CN.md) · [Engineering record](P0_P1_DELIVERY.md)

Assessment date: 2026-09-06. RigorPilot is best positioned as an **auditable
research-repository execution harness**, not an autonomous scientist. Its useful
differentiator is evidence placed alongside the original README. Its unproven
hypothesis is that this reduces false completion and researcher effort compared
with the same model without the harness.

## Evidence boundaries

Pinned repository snapshots, byte-preserving README annotation, bounded process
execution, recovery and publication checks exist. The four external protocols
include selection-only and partial-training cases; they are not four successful
paper reproductions. Three real provider attempts returned HTTP 502. There is
no successful live-model acceptance or held-out model-quality comparison yet.
The optional transport supports Anthropic Messages; other profile metadata does
not imply another working provider. Local execution is not an OS sandbox.
Ordinary `repro_outputs/ANNOTATED_README.md` output can change the resolution of
upstream relative media paths. The published showcases and lab retain a separate
source-adjacent `RIGORPILOT_README.md`; making that an optional ordinary-run
output, with nested-README/media tests, remains a usability improvement.

## Learn by running

From a clone, with Python 3.11+ and Git:

```bash
python scripts/run_harness_lab.py
```

The lab uses **scripted decisions and real subprocesses**, with no API, GPU or
model downloads. It demonstrates missing-asset failure, preparation, a durable
pause, controller restart and independent verification. Inspect the printed
output's `REPORT.json`, paused/final state, trajectory and source-adjacent
annotated README. Existing output is never overwritten; use
`--output tmp/my-lab-2` for another run. This is an engineering exercise, not
evidence of model intelligence.

Read in order: [skill contract](../skills/ai-research-reproduction/SKILL.md) →
[agent loop](../skills/ai-research-reproduction/scripts/run_agent.py) →
[runtime](../shared/scripts/runtime_runner.py) →
[verifier tests](../scripts/test_agent_runner.py) →
[publication checks](../scripts/check_publication.py).
Predict what happens with an incorrect acceptance condition, write a failing
recovery test yourself, then document a design decision and its trade-offs.

## Delivery gates

| Stage | Scope | Acceptance |
|---|---|---|
| Reliability | Installation, false-success and configuration regressions; lab | Full tests, installed entrypoints and failure cases pass |
| Live canary | One pinned micrograd run, roughly half to one engineering day | Actual model/tool trace, usage, verifier result and source identity |
| Pilot comparison | Six tasks × three conditions, roughly 2–4 days | All failures retained, reviewed graders, success/false-success/intervention/cost results |
| Reusable evaluation | Twelve frozen tasks over 4–6 repos, key cases repeated three times, roughly 3–5 days | Separate development and held-out tasks; paired model-upgrade checks |
| User validation | 5–10 target users, roughly 1–2 calendar weeks | Time to first success, unassisted completion, repeat usage and failure categories |

These are planning estimates, not promises. Advance from one canary to three
cases before a matrix. Stop on provider failure instead of cycling model names.
User-set provider billing caps remain necessary: token/time gates cannot monitor
subscription balance. Defer unrestricted edits, large GPU runs, multi-agent
debates and long-term memory until evidence justifies their cost and risk.

## Evaluation protocol to implement next

Compare A: same model with generic task instructions; B: A plus RigorPilot skill;
C: B plus durable execution/recovery/evidence mechanics. Freeze model revision,
tool permissions, approved commands, budgets, source/environment and grader.
Capture raw traces for all arms; lack of a polished report must not count as
business-task failure. Different tool permissions turn this into a product
comparison, not a single-factor harness ablation. Pre-reviewed commands do not
test autonomous target discovery.

Cover normal evaluation, missing assets, exit-zero/incorrect result, interrupted
controller, premature completion and an unauthorized large download. Label
injected faults separately. Existing public cases are development/regression
tasks, not unseen holdouts. Record task/split/commit, harness/prompt/grader hashes,
requested/returned model, parameters, cache/hardware, repeats, interventions,
claimed and verified outcomes, traces, tokens, known/unknown cost and latency.
The current model loop's exit/stdout checks are lightweight execution criteria;
P2 needs task-specific external graders for actual artifacts, metric tolerances
and evaluation conditions, protected from modification by the executing agent.

Report task success and false success with counts; safe and incorrect blocking;
cost per success including failed attempts; duplicate execution after recovery;
and evidence integrity separately. Include provider failures in user-facing
success denominators, with conditional availability metrics alongside them.
Small pilots warrant per-case evidence, not broad generalization percentages.
Freeze primary metrics and stop rules before testing the holdout.
See [Anthropic's evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Architecture and model iteration

Borrow testable acceptance contracts and independent evaluation from
[long-running harness practice](https://www.anthropic.com/engineering/harness-design-long-running-apps),
not its agent count. Distinguish per-task checkpoints from cross-task memory as
in [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
For a model upgrade: protocol/usage contract test → live canary → paired holdout
comparison. Change one factor at a time. Remove obsolete scaffolding only after
an ablation shows it no longer helps; preserve prior results.

## Career and community value

Tell three evidence-backed engineering stories: a verifier namespace collision
that falsely passed an unexecuted task; uncertain-dispatch recovery without
blind replay; and local-versus-installed/published artifact discrepancies.
These demonstrate agent application and evaluation engineering, not distributed
production scale or model-training research. The public
[Model Evaluations role](https://job-boards.greenhouse.io/anthropic/jobs/5198255008)
is one useful skills reference, not a hiring guarantee. Explain your own decisions,
tests and AI collaboration honestly; do not invent improvement or adoption metrics.

Keep the two installation commands and real evidence cards. Label the legacy
MiniSeg preview as an unverified historical interface illustration. Publish a
short genuine end-to-end demonstration only once it runs; invite users with
maintainer approval and collect [reproduction feedback](https://github.com/lllllllama/RigorPilot-Skills/issues/new?template=reproduction.yml).
Measure first success and repeat use before optimizing promotion. Stars are an
attention signal, not usage or a guaranteed outcome.
