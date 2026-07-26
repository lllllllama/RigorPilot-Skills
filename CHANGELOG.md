# Changelog

## Unreleased

### Added

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

