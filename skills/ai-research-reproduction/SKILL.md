---
name: ai-research-reproduction
description: Rigor Reproduce compatible skill slug for README-first deep learning repository reproduction. Use when the user wants an end-to-end, minimal-trustworthy flow that reads the repository first, selects the smallest documented inference or evaluation target, coordinates intake, setup, trusted execution, optional trusted training, optional repository analysis, and optional paper-gap resolution, enforces conservative patch rules, records evidence assumptions deviations and human decision points, and writes the standardized `repro_outputs/` bundle. Do not use for paper summary, generic environment setup, isolated repo scanning, standalone command execution, silent protocol changes, score chasing, or broad research assistance outside repository-grounded reproduction.
compatibility: Requires Python 3.11+ and Git for bundled orchestration; target repositories may require additional reviewed dependencies, network access, or accelerators.
---

# ai-research-reproduction

## Purpose

Guide README-first deep learning reproduction toward a minimal trustworthy run
with auditable evidence. Reproduction is not "make it run by changing
anything"; faithfully read the README, environment, weights, datasets, and
documented commands, then record results and deviations. Start with
`references/agent-operating-principles.md`; load
`references/research-rigor-principles.md` and
`references/deep-learning-experiment-principles.md` when scientific meaning or
experiment details are at stake.

## Fast Path

For a routine bounded run, keep the control path short:

1. Read the target README and only the target test/config/source needed to understand the documented command.
2. Run `scripts/orchestrate_repro.py --repo <repo> --plan-only --agent-output`; review `command_candidates`, the selected `cmd-XX`, side-effect contract, and selection fingerprint. With no `--output-dir`, later evidence goes to `<repo>/repro_outputs` regardless of caller cwd.
3. Run the selected candidate, or another reviewed candidate, with `--run-selected --command-id <cmd-XX> --plan-fingerprint <fingerprint> --agent-output` plus requested timeout/metric/source-adjacent options. A changed command set fails closed; setup/download commands are never target candidates.
4. Run `--verify-output --agent-output`; inspect detailed evidence files only when verification fails or the result is partial/blocked.
5. Deliver the bounded result and stop.

Do **not** inspect `orchestrate_repro.py`, `annotate_readme.py`, `_bundled/`, writers, or runtime internals on a normal success path. Inspect implementation only for a concrete blocker, unexpected side effect, bundle-integrity failure, or unresolved safety question. Use `scripts/doctor.py` for first-use environment/install diagnostics. Executed commands keep full lifecycle/log evidence under `repro_outputs/_runtime/<run_id>/`.

## Fit

Use this skill when all are true:

- The target is an AI code repository with a README, scripts, configs, or
  documented commands.
- The request spans multiple trusted phases such as intake, setup, execution,
  training verification, analysis, paper-gap resolution, and reporting.
- The desired result is a small reproducible target, not broad experimentation.

Do not use this skill for paper summaries, generic environment setup, isolated
repo scanning, standalone command execution, open-ended research design, or
explicit candidate-only exploration.

## Trusted Target Selection

Choose the smallest target that can honestly demonstrate repository-grounded
reproduction:

1. documented inference
2. documented evaluation
3. documented training startup or partial verification
4. full training only after explicit user confirmation

Treat README guidance as the primary reproduction intent. Use repository files
to clarify the README, not to silently replace it. When the README and paper
conflict, record the conflict and use `paper-context-resolver` only for the
narrow reproduction-critical gap.

## Workflow

1. Treat README guidance as primary; extract and select the minimum trustworthy target.
2. Use setup/assets only for target-specific prerequisites and `analyze-project` only when structural clarification is needed.
3. Use `minimal-run-and-audit` for inference/evaluation/smoke and `run-train` for training startup, kickoff, or resume; direct execution is the default.
4. Pause before fuller training or changes to dataset, split, checkpoint, preprocessing, metric, loss, model semantics, or interpretation.
5. Award `result-match` only against explicit expected metrics and tolerance; process success alone is not reproduction success.
6. Write the evidence bundle, return the requested bounded result, and stop; optional stages are not automatic follow-up work.

## Patch Boundary

Prefer no repository edits. If edits are needed, keep them conservative and
auditable:

- Try command-line arguments, environment variables, path fixes, dependency
  version fixes, or dependency-file fixes before code changes.
- Reproduction fixes are allowed when needed, but they must not be hidden. State
  what changed, why it was necessary, whether it changes scientific meaning,
  and whether it affects comparability with the paper, README, or baseline.
- Avoid changing model architecture, core inference semantics, training logic,
  loss functions, or experiment meaning.
- If repository files must change, create a branch named
  `repro/YYYY-MM-DD-short-task`, keep verified patch commits sparse, and record
  README-fidelity impact in `PATCHES.md`.

See `references/patch-policy.md`.

## Outputs

Always target `repro_outputs/`:
```text
SUMMARY.md
COMMANDS.md
LOG.md
SCIENTIFIC_CHANGELOG.md
COMPARABILITY_REPORT.md
status.json
ANNOTATED_README.md   # original README + colored per-section agent-action annotations
PATCHES.md   # only if patches were applied
```

Use the templates under `assets/` and the field rules in `references/output-spec.md`.

- Put the shortest high-value summary in `SUMMARY.md`.
- Put copyable commands in `COMMANDS.md`.
- Put process evidence, assumptions, failures, and decisions in `LOG.md`.
- Put scientific meaning and change effects in `SCIENTIFIC_CHANGELOG.md`.
- Put comparison anchors and protocol deviations in `COMPARABILITY_REPORT.md`.
- Put durable machine-readable state in `status.json`.
- Put branch, commit, validation, and README-fidelity impact in `PATCHES.md` when needed.
- Put the researcher's at-a-glance view in `ANNOTATED_README.md`: the README replayed byte-for-byte—including its image, GIF, video, and HTML markup—with exactly one marked color annotation after every heading block. Never extract a text-only surrogate. Generation must pass the built-in strip/check round trip before the file is kept.
- For original relative media/file context, use `--source-adjacent-readme` to also write `RIGORPILOT_README.md` beside the source README; inspect the reported path/status and never replace an unrelated existing file. See `references/output-spec.md`.
- Distinguish verified facts from inferred guesses.

## Reference Loading

- Load `references/language-policy.md` when writing human-readable outputs.
- Load `references/research-rigor-principles.md` before making comparability, contribution, or research-result claims.
- Load `references/deep-learning-experiment-principles.md` when dataset, split, metric, checkpoint, training, or evaluation details matter.
- Consult `~/.rigorpilot/PERSONAL_RIGOR.md` if present, under `references/continuous-learning-policy.md` (advisory only; core wins).
- Failed and later-resolved runs are auto-recorded as lessons via `shared/scripts/lessons_store.py` (`RIGORPILOT_LESSONS=0` disables).
- Load `references/research-safety-principles.md` before protocol-sensitive
  decisions.
- Load `references/patch-policy.md` before modifying repository files.
- Keep specialized logic in sub-skills, scripts, templates, or references rather than expanding this entrypoint.

