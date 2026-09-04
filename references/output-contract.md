# Output Contract

This repository maintains two output styles.

## Trusted outputs

Trusted-lane outputs should be audit-heavy and durable.

Expected directories include:

- `repro_outputs/`
- `analysis_outputs/`
- `debug_outputs/`
- `train_outputs/`

Trusted output traits:

- stable machine-readable English keys
- concise human-readable summaries
- assumptions, deviations, and blockers recorded explicitly
- `SCIENTIFIC_CHANGELOG.md` and `COMPARABILITY_REPORT.md` emitted by the trusted run writers
- `repro_outputs/ANNOTATED_README.md` emitted by `ai-research-reproduction`: the target README preserved byte-for-byte inside mechanically strippable marker blocks, with exactly one color-coded status after every ATX heading block and SHA-256 round-trip proof in `status.json`
- next safe action recorded when work is partial or blocked
- executed commands persist immutable per-attempt runtime evidence under
  `<output-dir>/_runtime/<run-id>/`, including state, events, stdout/stderr,
  scoped resource samples, retry lineage, and a normalized model profile
- controller recovery must not auto-replay commands: dead runs become
  `interrupted`, while stale live processes become `orphaned`

## Explore outputs

Explore-lane outputs should be summary-heavy and disposable.

Expected directories include:

- `explore_outputs/`
- `sources/`

Explore output traits:

- `current_research` recorded as the exploratory anchor
- canonical `explore_context` recorded with `current_research`, `experiment_branch`, and explicit authorization
- campaign metadata recorded when `ai-research-explore` is used for a Rigor Explore campaign
- `eval_contract`, `baseline_gate`, `idea_gate`, `selected_idea`, `experiment_manifest`, and `experiment_ledger` recorded for campaign-style runs
- `SCIENTIFIC_CHANGELOG.md` and `COMPARABILITY_REPORT.md` recorded for candidate-only scientific meaning and comparability review
- `analysis_artifacts`, `lookup_records`, `idea_cards`, `improvement_bank`, `idea_seeds`, `target_location_map`, `minimal_patch_plan`, `resource_plan`, `atomic_idea_map`, `implementation_fidelity`, and `smoke_report` recorded when `ai-research-explore` runs the bounded campaign pipeline
- `source_inventory` and `source_support` recorded when `ai-research-explore` runs the free-first research lookup pass
- `static_smoke` and `runtime_smoke` recorded separately when the exploratory bundle includes transplant or execution checks
- helper stage trace recorded for the orchestration path that produced the bundle
- raw/pruned variant counts, budget caps, and best runs summarized
- pre-execution selection policy recorded when exploratory candidates are ranked before execution
- metric policy for candidate ranking recorded when explicit exploratory ranking is configured
- generated idea counts, selected-idea breakdown, atomic unit counts, and fidelity summaries recorded in `status.json`
- source references for transplanted or adapted modules recorded
- human-checkpoint state recorded when the flow should stop for researcher confirmation
- SOTA claim state recorded only against the user-provided frozen comparison table
- enough context for a human to decide whether to continue
- executed baseline and candidate runs retain runtime/resource/model evidence
  in `best_runs` or the baseline payload
- no implicit claim that exploratory gains are trusted baselines
- isolated branch or worktree context recorded

Expected `ai-research-explore` artifacts may now include:

- `explore_outputs/CHANGESET.md`
- `explore_outputs/IDEA_GATE.md`
- `explore_outputs/EXPERIMENT_PLAN.md`
- `explore_outputs/EXPERIMENT_MANIFEST.md`
- `explore_outputs/EXPERIMENT_LEDGER.md`
- `explore_outputs/TRANSPLANT_SMOKE_REPORT.md`
- `explore_outputs/SCIENTIFIC_CHANGELOG.md`
- `explore_outputs/COMPARABILITY_REPORT.md`
- `explore_outputs/TOP_RUNS.md`
- `explore_outputs/status.json`

Campaign-style analysis should also emit:

- `analysis_outputs/RESEARCH_MAP.md`
- `analysis_outputs/CHANGE_MAP.md`
- `analysis_outputs/EVAL_CONTRACT.md`
- `analysis_outputs/IMPROVEMENT_BANK.md`
- `analysis_outputs/IDEA_SEEDS.json`
- `analysis_outputs/IDEA_CARDS.json`
- `analysis_outputs/IDEA_EVALUATION.md`
- `analysis_outputs/IDEA_SCORES.json`
- `analysis_outputs/MODULE_CANDIDATES.md`
- `analysis_outputs/INTERFACE_DIFF.md`
- `analysis_outputs/RESOURCE_PLAN.md`
- `analysis_outputs/ATOMIC_IDEA_MAP.md`
- `analysis_outputs/ATOMIC_IDEA_MAP.json`
- `analysis_outputs/IMPLEMENTATION_FIDELITY.md`
- `analysis_outputs/IMPLEMENTATION_FIDELITY.json`
- `analysis_outputs/status.json`

`analysis_outputs/status.json` and `explore_outputs/status.json` remain on schema version `1.0` and additively extend the payload with:

- `idea_seeds`
- `atomic_idea_map`
- `implementation_fidelity`
- `generated_idea_count`
- `researcher_idea_count`
- `synthesized_idea_count`
- `selected_idea_breakdown`
- `atomic_unit_count`
- `fidelity_summary`

Research lookup should also emit cache-first, auditable records:

- `sources/records/`
- `sources/index.json`
- `sources/SUMMARY.md`
- `analysis_outputs/SOURCE_INVENTORY.md`
- `analysis_outputs/SOURCE_SUPPORT.json`

Current lookup is intentionally bounded and free-first: it resolves campaign seeds, repo-local extracted locators, and a small provider set such as GitHub repo URLs, arXiv IDs or URLs, DOI locators, and generic URL metadata. Optional external providers may enhance this path, but missing keys must not block `ai-research-explore`. It is not an open-ended literature search guarantee.

## Compatibility

- Existing trusted `repro_outputs/` remain stable.
- New lanes may add new output directories, but should not silently change established trusted schemas.

