# Output Spec

All runs should target the same output directory:

```text
repro_outputs/
```

When the selected trustworthy target is documented training, the orchestrator may also emit a supplemental:

```text
train_outputs/
```

That training bundle should hold the training-specific checkpoint, metric, and monitoring state, while `repro_outputs/` remains the primary reproduction-facing summary.

## `SUMMARY.md`

Audience:

- first human reader
- another model that needs the high-level result fast

Requirements:

- keep it within one page when possible
- state target repo and selected reproduction goal
- state overall outcome clearly
- list the main documented command that was attempted or verified
- list the biggest blocker if not successful
- when patches were applied, surface patch state briefly:
  - `patches_applied`
  - patch branch
  - README fidelity impact
  - highest patch risk

## `COMMANDS.md`

Requirements:

- commands must be copyable
- separate setup, assets, run, and verification steps
- label each command as documented, adapted, or inferred
- avoid dumping noise from the shell history

## `LOG.md`

Requirements:

- concise chronological record
- include assumptions, evidence, failures, retries, and decisions
- distinguish between README-backed steps and inferred steps

## `status.json`

Requirements:

- keys remain in English
- enums remain stable
- values can summarize both success and partial verification
- preserve observability for assumptions, deviations, evidence level, and human review points

Suggested top-level keys:

- `schema_version`
- `generated_at`
- `user_language`
- `target_repo`
- `readme_first`
- `selected_goal`
- `goal_priority`
- `status`
- `documented_command_status`
- `documented_command`
- `documented_command_kind`
- `documented_command_source`
- `documented_command_section`
- `execution_mode`
- `runtime`
- `stage_results`
- `observed_metrics`
- `best_metric`
- `result_match`
- `patches_applied`
- `patch_branch`
- `readme_fidelity`
- `highest_patch_risk`
- `evidence_level`
- `assumptions`
- `unverified_inferences`
- `protocol_deviations`
- `human_decisions_required`
- `next_safe_action`
- `artifact_provenance`
- `verified_commit_count`
- `outputs`
- `notes`

Recommended status enums:

- `success`
- `partial`
- `blocked`
- `not_run`

Recommended evidence level enums:

- `direct`
- `mixed`
- `inferred`

Field intent:

- `assumptions`
  - important assumptions that still shape execution or interpretation
- `unverified_inferences`
  - bounded inferences that were useful but not directly verified
- `protocol_deviations`
  - meaningful differences from README, paper, or documented setup
- `human_decisions_required`
  - decisions that should not be taken implicitly by the agent
- `next_safe_action`
  - the lowest-risk next step a researcher can review or run
- `artifact_provenance`
  - where key inputs or outputs came from, such as README, repo path, paper, dataset root, checkpoint, or generated logs
- `stage_results`
  - a machine-readable ledger that separates `success`, `blocked`, and `not_requested` stages
  - planning a skill does not count as executing it; optional stages must record their actual outcome
- `result_match`
  - an independent comparison object with `status` set to `matched`, `mismatched`, or `not_evaluated`
  - `matched` requires explicit expected metrics and a recorded tolerance; observed metrics alone remain `not_evaluated`
- `runtime`
  - identifies the durable `_runtime/<run_id>/` directory, terminal state, event stream, full stdout/stderr logs, truncation flags, cancellation state, and duration
  - summary fields may contain only a bounded log tail; the referenced log files remain complete

## Runtime evidence

Every executed command should persist under the active evidence output directory:

```text
<output-dir>/_runtime/<run_id>/
├── spec.json
├── state.json
├── events.jsonl
├── resources.jsonl
├── stdout.log
└── stderr.log
```

The state lifecycle is `created -> running -> success|failed|timed_out|cancelled|blocked`.
Create an empty `CANCEL` file inside the active run directory to request cancellation.
Timeout and cancellation must terminate the child process tree before the terminal state is written.
Recovery may add `interrupted` or `orphaned`; retries create a new run with
`retry_of` and an incremented `attempt` rather than overwriting prior evidence.

The status bundle should also expose the normalized `model_adapter` snapshot
and its fingerprint. `resource_summary` must retain measurement scope so
device-global GPU data is not misrepresented as per-process attribution.

## Optional source-adjacent README

Add `--source-adjacent-readme` to `orchestrate_repro.py` or `run_agent.py` to
also create `RIGORPILOT_README.md` in the original README's directory. Keep
the standard `repro_outputs/ANNOTATED_README.md` and its evidence files.

The adjacent copy preserves all original bytes, including relative media and
file links. Only RigorPilot-inserted evidence links are rebased. Open the path
reported under `source_adjacent_readme`; `written` confirms delivery, while
`blocked` means the ordinary evidence remains available but the extra copy
could not safely be written. Cross-drive Windows evidence links use local
file URLs; browser policies may prevent opening them, so prefer the same drive.

The bundle retains `readme_delivery.json` to identify its generated copy.
Repeating with the same source and output may refresh an unchanged owned copy.
An unrelated or edited file, symlink, hard link, or conflicting receipt is not
overwritten. Keep the receipt with the evidence; do not use it to claim that
source code or external media were verified. The original README remains intact.

## `PATCHES.md`

Only create this file when repository files were modified.

Requirements:

- record patch branch name
- record highest patch risk
- record verified commits in order
- explain what changed and why for each verified commit
- explain how each change was verified
- state whether README fidelity was preserved, clarified, or diverged
- record changed files for each verified commit
- keep human-readable prose in the user's language when practical, but preserve commit hashes, branch names, and command strings verbatim
