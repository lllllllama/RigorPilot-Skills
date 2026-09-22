# Changelog

## Unreleased

### Short-call agent handoff

- Add an optional non-training `repro_job.py start/status/cancel` supervisor and
  exact handoff argv in the read-only plan. Freeze requests, reuse receipts on
  repeated submissions, reject conflicting outputs, and never replay lost jobs.
- Keep that handoff out of ordinary plan output unless the caller explicitly uses
  `--include-agent-handoff`; the retained micrograd plan shrinks from 4,324 to
  2,103 bytes while preserving the same target. Add a compact `--core` local
  regression mode, including the shared operating-principles contract, while
  retaining the full auto-discovered suite for commit/CI.
- Retry transient Windows sharing locks when reading job-control JSON so status
  polling does not turn an in-progress atomic replacement into a false job failure.
- Bind receipt polling/cancellation to job identity so a reused directory cannot
  silently substitute another job; path-only recovery queries expose unchecked identity.
- Keep target timeout separate from controller finalization; cooperative cancel
  uses the existing runtime. Distinguish controller completion, evidence validity
  and bounded task acceptance. Preserve the synchronous/training entrypoints.
- Harden verification against malformed JSON, missing or rebound required
  manifest records, and matching-but-nonterminal runtime states. Manifest `1.1`
  covers runtime specs and source-adjacent delivery; legacy coverage is explicit.
- Bound diagnostic log reads and retry transient atomic-replace sharing locks
  without exposing partial JSON. Exclusively claim short staging filenames and
  never unlink another writer's reused name after replacement. Add lifecycle, concurrency, negative-verifier
  and controlled fault-comparison regressions; no model-uplift claim is made.
- Retain the complete regression log and a machine-readable validation receipt
  with source/log hashes; publish only the reviewed validation log directory.

### Agent fast path

- Add a compact first-use path for the reproduction skill: `--plan-only` previews
  the selected README command and side-effect contract without target execution or
  evidence writes, `--agent-output` keeps control-plane stdout small, and
  `--verify-output` rechecks an existing bundle without replaying the target command.
- Persist `repro_outputs/invocation.json` and compare Git-tracked source snapshots
  before/after target execution. Tracked source mutations downgrade successful runs
  to `partial` and require review instead of being silently accepted.
- Move implementation reading off the routine happy path in `SKILL.md`; detailed
  internals remain available for concrete blockers, integrity failures and safety
  questions.
- Resolve the orchestrator's default evidence directory relative to the target
  repository (`<repo>/repro_outputs`) rather than the caller's working directory;
  explicit `--output-dir` values retain their existing behavior.
- Extend repository validation with Agent Skills name/description/compatibility
  bounds, `metadata`/`allowed-tools` type checks and the existing public-SKILL
  line limit, with focused negative tests.
- Add reviewable README-command selection: `--plan-only` returns `cmd-XX`
  candidates and a selection fingerprint; explicit execution can bind
  `--command-id` to that reviewed plan. Stale plans, unknown IDs, setup/download
  targets and direct-mode shell syntax fail before target execution.
- Add stable machine-readable reproduction error codes for common dependency,
  asset, timeout, command, metric, source-integrity and evidence-integrity failures.
- Add an API-free reviewed-selection suite over the four existing pinned real
  repositories (current result: 4/4 planning checks passed) and a repeatable
  1k/10k source-integrity performance baseline for future optimization decisions.
- Re-run pinned micrograd through a real Codex client. The explicit named-skill
  Fast Path now completes normally and passes task, source-integrity,
  independent-grader and evidence-verification gates. A separate natural-language
  fresh-client run proves project-skill auto-loading and normal client completion,
  but remains an end-to-end failure because the agent chose `--timeout 20` inside
  the user's 30-second command bound. Retain that failure, stop before A/B, and
  add timeout guidance that preserves explicit user bounds and the reviewed command.
- Run one additional natural-language AUTO canary with user-authorized quota-gate
  override. Auto-loading is again observed and the 30-second target timeout is
  preserved, but the agent wraps the whole orchestrator in an equal 30-second
  subprocess timeout. The wrapper interrupts cleanup/terminal evidence, leaves a
  runtime state at `running`, and the outer client later hits its 240-second
  watchdog. Add a structured plan contract forbidding equal/shorter outer timeout
  wrappers and teach `--verify-output` to report
  `runtime_incomplete_without_status` without replaying the command.
- Run a fresh 2026-09-22 natural-language AUTO canary on the identity-bound job
  release. The client auto-loads the project skill and completes normally; the
  reviewed `python -m pytest` target, source integrity, independent grader and
  `--verify-output` all pass. The model chooses the synchronous orchestrator without
  an equal outer timeout rather than `repro_job.py`; retain separate bridge/fault
  evidence for the optional handoff. AUTO acceptance is closed; A/B remains unrun.

### Real-client first-use evidence and bounded handoff

- Publish a commit-pinned public installation and real Codex task trace: original
  micrograd tests and independent evidence checks pass, but the outer client times
  out at 240 seconds. Preserve both the obsolete-client rejection and insecure
  inherited-TLS installation attempt; do not claim end-to-end success or model uplift.
- Successful bounded non-training reports now hand the result back after evidence
  review instead of recommending unrequested follow-up execution. Clarify the skill's
  finish boundary and focused implementation reading; live timeout reduction is unverified.
- Record tested installer/Node versions and retain the original README command
  examples, color guide and supporting media. Publication checks include the new archive.

### Foundation and functional acceptance

- Canonicalize the A/B output parent before freezing and sealing. Reproduce the
  macOS path-alias failure with a symlink/junction regression without relaxing
  broker boundaries; retain full failing-test output in CI.
- Add a self-contained, read-only `doctor.py` for Python, Git, bundle integrity,
  target README and explicitly requested dependency discovery.
- Add repeatable installed-runtime acceptance for missing data, a matching
  metric, an exit-zero metric mismatch and optional pinned micrograd tests.
  Preserve raw logs and source/media bytes; independently recompute predictions
  and test tampered evidence. Keep the earlier success-only grader strict.
- Retain both acceptance attempts, including the first grader-integration failure.
  Four functional checks pass; no new model calls or measured model uplift.
- Add optional read-only Codex app-server quota-window lookup. It does not start
  model turns, reserve quota, read credential files or enforce a percentage floor.

### Neutral controlled-trial foundation

- Add a neutral injected-transport loop, reviewed-command broker and append-only
  per-trial budget ledger. Separate reservations from actual transport invocations;
  retain unknown usage and prevent automatic pending-request replay.
- Settle usage before tools, reject model identity/content/call-ID drift, and
  recheck elapsed time after journal writes before model and tool dispatch.
  Propagate remaining command timeouts without changing the 45-second default.
- Keep trace failures sticky: a missing tool-result or final record prevents
  acceptance, while retaining the independent grade and settled usage.
- Publish four real-process offline controller checks, including a retained
  missing-asset failure. Scripted responses are not live model evidence. The new
  core now has a bounded Messages CLI, but no campaign billing cap or OS sandbox; skill files
  are read-only, so it does not establish full bundled-skill execution capability.

### Paired evaluation foundation

- Freeze three development tasks and six A/B slots, including original source,
  prompts, environment, skill package and evaluator/executor hashes. Reject
  changed inputs, invalid model/budget declarations and overwritten evidence.
- Add independent task graders for real micrograd tests, local missing-asset
  preparation and an explicitly injected exit-zero/wrong-metric task. Reports
  distinguish process success, artifact validity, result match and correct handling.
- Publish actual offline calibration with unchanged upstream files/media and raw
  receipts; extend Git publication checks to this snapshot. Scripted claims only
  calibrate graders. All six live model slots remain unrun; unknown usage/cost
  stays null, and this kit has no generic live backend or enforced model budget.

### First-use output and acceptance

- Separate unexecuted setup suggestions, asset observations and actual command
  evidence; missing conventional directories no longer invent required setup.
  Preserve setup discovery gaps as advisories rather than automatic human decisions.
  Real dependency/asset failures remain visible with logs and review checkpoints.
- Correct overall acceptance for explicit missing/out-of-tolerance metrics:
  successful process execution remains recorded, but the reproduction outcome
  becomes `partial`, with a warning and a concrete review step. Unconfigured
  metric checks and the evidence-writing CLI exit-code contract are unchanged.
- Preserve normal controller pauses as incomplete/resumable work, not failures;
  separate controller status, task outcome and final acceptance in agent evidence.
- Add optional reviewed artifact and JSON-metric checks to the model runner,
  including final rechecks; exit code zero alone cannot satisfy these checks.
  Existing exit/stdout-only tasks remain supported. File checks establish current
  contents, not that the current command created them or reproduced a paper.
- Add `--source-adjacent-readme` to both main runners while retaining the standard
  evidence bundle. Only inserted links are rebased; originals and media stay intact.
  An ownership receipt permits safe refresh and protects conflicting/edited files.
- Extend standalone-install validation through execution, source-adjacent output,
  original-byte restoration, media/evidence links and a reviewed repeat.
- Replace the non-training verification placeholder with the actual built-in
  metric-comparison status; do not invent a separately executed verifier command.

### September engineering hardening

#### Fixed

- Complete shared runtime and guidance in all-skills installations; preserve
  the self-contained main skill and reject stale shared-runtime shadowing.
- Prevent command IDs from overwriting independent verification checks.
- Reject malformed provider responses and unsupported model parameters;
  transmit supported parameters instead of silently ignoring them.
- Locate virtualenv interpreters across native Windows, MSYS2 and POSIX.
  Resolve direct executables against child PATH/PATHEXT and the declared cwd;
  record requested and actual argv while preserving virtualenv symlinks.
- Handle temporary-directory aliases in offline-example cleanup and installed
  reference checks; preserve unexpected Git pointers rather than deleting them.

#### Added

- A small offline verification example with simulated decisions and actual
  failure, preparation, process restart and independent acceptance checks.
- Installed-layout, provider, verifier, interpreter-isolation and cleanup
  regressions, plus engineering acceptance criteria and operational boundaries.
- Security guidance, reproduction feedback and pull-request templates, explicit
  read-only CI permissions, a job timeout and superseded-run cancellation.

#### Compatibility and evidence

- Agent state schema is `1.1`: command verdicts live under
  `verification.commands`, separate from `verification.source_unchanged`.
  Changed harness identity requires a fresh run; retain old checkpoints as
  evidence rather than manually rewriting them to resume.
- Direct mode no longer relies on implicit host interpreter/current-directory
  search. Use an explicit path or the intended child PATH. Native-shell mode
  is unchanged.
- Existing public repository snapshots remain historical evidence and are not
  regenerated by these changes. No successful live-model acceptance, sandbox
  guarantee or paper-reproduction improvement is claimed.

### P0 / P1 reliability and agent execution

- Fix Python 3.11 benchmark cleanup and Windows Unicode/process-tree test portability.
- Publish omitted showcase evidence and upstream files; retain exact checkout bytes
  and verify committed file hashes, README round trips and inserted evidence links in CI.
- Add an optional Anthropic Messages agent loop with reviewed tool commands,
  durable plans/messages, bounded usage, recovery and independent finish checks.
- Add offline transport and agent regressions plus an explicitly bounded live canary.
  Current live gateway trials returned HTTP 502; live P1 acceptance remains pending.

### Added (from studying real GitHub projects)

- Extractor robustness proven against real READMEs (dinov2, nanoGPT):
  backslash-continued commands are joined into single runnable commands, and
  classification is entrypoint-first with word-boundary keywords — a
  `train.py` command with `--eval_iters` no longer classifies as evaluation
  (which would have bypassed the training-authorization gate).
- Research thinking loop upgraded with AIDE / AI-Scientist-v2 mechanics:
  draft/debug/improve iteration types (debug capped at 3), a
  no-metric-means-buggy rule, replication-before-promotion (3 seeds), typed
  stop reasons, and a defaults table.
- Annotated README now grades evidence PaperBench-style: per-annotation
  evidence tiers (code-development / execution / result-match) and a
  weighted 0-1 reproduction score in the header and
  `readme_section_coverage`.
- Annotated README generation now reads the checked-out repository README as
  immutable bytes and inserts marker-delimited evidence at computed offsets.
  Built-in `strip` / `check` commands prove byte-for-byte round trips (including
  UTF-8 BOM, line endings, blank lines, and final-newline state), while the
  external benchmark independently verifies one annotation per ATX heading.
- Lessons store lifecycle: `touch` (usage tracking) and `prune`
  (kind-specific staleness windows, doubled for proven-useful lessons),
  broader credential-shape blocklist, and policy additions (what NOT to
  record; human-reviewed promotion flow).

### Added

- README credibility showcase in both English and Chinese: a full annotated
  README preview, a two-by-two gallery of four fixed-commit public-repository
  reproductions, per-case deep links into a shared evidence index, direct links
  to each complete RigorPilot README, Skillselion and skills.sh discovery
  badges, and two minimal install commands.
- A sequential, explicit external benchmark suite with per-case workspace
  ceilings, free-disk and total-time gates, default cleanup, compact SHA-256
  evidence archives, append-only history, and harness/case/commit identities.
- Optional durable showcase snapshots retain every tracked file from the pinned
  upstream checkout plus reproduction evidence, while excluding `.git`, venvs,
  caches, and untracked runtime residue. A source-adjacent
  `RIGORPILOT_README.md` keeps original relative images and repository links
  functional without changing the upstream `README.md`.
- Fixed-commit micrograd, minGPT, PyTorch MNIST, and nanoGPT Shakespeare lanes;
  execution, selection-only, and bounded-startup evidence remain distinct.
- Prerequisite-aware selection rejects missing local checkpoint outputs and
  obvious large-model downloads, then prefers explicitly bounded CPU training
  commands when no cheaper runnable target exists.
- Training metrics are allowlisted and normalized case-insensitively; fraction
  accuracy is converted to a ratio, while configuration values are excluded.

- A shared persistent command Runtime with per-run IDs, atomic lifecycle state,
  append-only events, streamed full logs, bounded in-memory log tails,
  heartbeats, timeouts, cancellation files, and process-tree termination.
  Trusted reproduction, training, and exploratory execution now use the same
  runtime contract.
- Restart reconciliation marks dead runs `interrupted` and stale live runs
  `orphaned`; explicit retries preserve immutable attempt lineage instead of
  silently replaying commands.
- Dependency-free root-process CPU/RSS sampling, optional device-global NVIDIA
  telemetry, and a provider-neutral model identity/capability profile with
  stable fingerprints and inline-secret rejection.
- A durable single-host task queue with dependency gates, deterministic
  priority/FIFO selection, bounded concurrency, request-based CPU/GPU/RAM
  admission, failure isolation, cancellation markers, restart reconciliation,
  and explicit job retry lineage.
- Deterministic `benchmarks/run_queue_smoke.py` proof for concurrent admission,
  dependency ordering, failure isolation, over-budget blocking, and complete
  per-job runtime evidence without API or GPU use.
- A commit-pinned external reproduction runner and low-cost micrograd case. It
  records fresh-workspace scope, exact dependency versions, every setup/runtime
  phase, README command and goal selection, tracked-source integrity, evidence
  completeness, intervention accounting, and secret-environment stripping
  before external code executes.
- README test sections and `pytest` commands now classify as evaluation after
  the micrograd canary exposed the previous generic `other` classification.
- Setup and asset command syntax now outranks generic README headings, and a
  referenced local Python entrypoint with strong training-loop evidence is
  promoted to `training`. A pinned PyTorch MNIST preflight therefore keeps
  `pip install` as setup while routing `python main.py` through the training
  authorization gate.

- Deterministic `benchmarks/run_golden_smoke.py` coverage for explicit metric
  matching, mismatch detection, blocked commands, complete evidence bundles,
  and shell-authorization boundaries without API or GPU usage.
- CI regression coverage for the golden smoke benchmark through the existing
  auto-discovered test entrypoint.
- Explicit `--expected-metric NAME=VALUE` and
  `--metric-absolute-tolerance` controls for trustworthy result comparison.
- A persisted stage ledger; `--include-analysis-pass` now performs the
  read-only analysis, while unresolved paper-context requests are reported as
  blocked instead of implied to have run.
- Cross-platform shared command construction with Windows-native quoting and
  an explicit `--shell-mode native` opt-in for shell syntax.

- `references/research-thinking-loop.md`: the greedy, evidence-anchored
  research cycle (observe → ground → hypothesize → design → run → fair
  compare → keep/rollback → record) required in the explore lane; adapted
  from AIDE's greedy search and AI-Scientist-v2's managed tree search under
  RigorPilot's comparability-first gates.
- Continuous learning: `references/continuous-learning-policy.md` plus
  `shared/scripts/lessons_store.py` — an immutable rigor core with a
  user-owned lessons overlay (`~/.rigorpilot/lessons.jsonl`, distilled to
  `PERSONAL_RIGOR.md`). Failed and later-resolved reproduction runs are
  auto-recorded; secrets are refused; lessons are advisory and never edit
  skill files. `RIGORPILOT_LESSONS=0` opts out.
- READMEs: Research Thinking Loop and Continuous Learning sections; both
  shipped as installed shared references.

### Fixed

- Single-skill installations of `ai-research-reproduction` now include a
  synchronized runtime bundle and local policy references, so the documented
  `npx skills add ... --skill ai-research-reproduction` path works outside the
  source checkout.
- Non-training reproduction status now preserves `observed_metrics`,
  `best_metric`, and the independent `result_match` decision.
- Observed metrics alone no longer earn the `result-match` evidence tier.
- Windows symlink installs fall back to portable copies when the OS denies
  symlink creation with error 1314.

## v1.1.0 (2026-07-26)

### Added

- `scripts/run_all_tests.py`: single cross-platform entrypoint that runs
  `validate_repo.py` plus every `scripts/test_*.py`; CI now uses it on the
  ubuntu/macos/windows matrix, so all 44 test scripts run on every push
  (previously only 9 were hand-listed) and new tests are picked up
  automatically. CI status badge added to both READMEs.

- Root `AGENTS.md` for AGENTS.md-aware agents (Codex, Cursor, Copilot,
  Gemini CLI, …): lane model, entrypoint table, and hard rules at the
  project level, aligned with the Agent Skills open standard.
- Rubric-style section-coverage scoreboard in `ANNOTATED_README.md` and a
  machine-readable `readme_section_coverage` field in
  `repro_outputs/status.json` (PaperBench-inspired).
- Multi-agent / multi-model section in both READMEs; client-compatibility
  policy now covers the Agent Skills standard and `AGENTS.md`.

- `ai-research-reproduction` now writes `repro_outputs/ANNOTATED_README.md`: the
  target README replayed verbatim, split into heading blocks, each followed by a
  color-coded annotation (GitHub admonitions) of what the agent did in that
  section, linked to the evidence bundle.
- `scripts/test_readme_annotation.py` regression coverage for the renderer.

### Fixed

- Comprehensive-review fixes across the explore and trusted lanes, the
  installer, and docs (see commit history for the full list).

## v1.0.0

Initial public release lineage for what is now `RigorPilot Skills`.

### Scope

- README-first reproduction of deep learning research repositories
- one main orchestration skill plus four narrow sub-skills
- inference and evaluation first
- training only as startup or partial verification unless explicitly needed
- conservative patching with standardized outputs

### Rename compatibility

- repository brand migrated from `ai-research-workflow-skills` to `RigorPilot Skills`
- recommended repository slug migrated from `ai-paper-reproduction-skills` to `rigorpilot-skills`
- `ai-paper-reproduction` remains a compatibility alias for `ai-research-reproduction`
- `research-explore` remains a compatibility alias for `ai-research-explore`

### Included skills

- `ai-research-reproduction`
  - main orchestration for README-first target selection, policy control, and output normalization
- `repo-intake-and-plan`
  - scans the repository and extracts documented commands
- `env-and-assets-bootstrap`
  - prepares conservative environment and asset assumptions
- `minimal-run-and-audit`
  - normalizes execution evidence and writes `repro_outputs/`
- `paper-context-resolver`
  - optional paper-assisted gap resolution for reproduction-critical details only

### Output contract

The standardized output directory is:

```text
repro_outputs/
  SUMMARY.md
  COMMANDS.md
  LOG.md
  status.json
  PATCHES.md   # only when repository files changed
```

### Validation

Release validation currently includes:

- repository structure validation
- trigger boundary regression checks
- README command selection regression checks
- rendered output regression checks

### Real-repo trials

The main flow has been trialed against a small set of public deep learning research repositories. See [examples/real_repo_trials.md](examples/real_repo_trials.md).

### Known limits

- environment and asset preparation stays conservative and lightweight
- multilingual human-readable output currently focuses on English and Chinese
- the repository is intentionally not a general paper summary, benchmark design, or open-ended experiment orchestration system
