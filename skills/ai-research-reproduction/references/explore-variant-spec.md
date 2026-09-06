# Explore Variant Spec

## Purpose

Use this reference when preparing a `variant_spec.json` for `explore-run` or `ai-research-explore`.

In Rigor Explore campaigns, `variant_spec` is the run-level section inside a larger `research_campaign.json` / `research_campaign.yaml`. Load `references/research-campaign-spec.md` from the installed `ai-research-explore` skill (or `skills/ai-research-explore/` in a source checkout). Sharing this reference does not authorize exploration.

The spec describes:

- which `current_research` context the exploration is anchored to
- which command should be varied
- which exploratory axes should be combined
- how large the exploratory budget should be
- how candidates should be ranked before and after execution

## Minimal Shape

```json
{
  "current_research": "improved-model@branch",
  "base_command": "python train.py --config configs/demo.yaml",
  "variant_axes": {
    "adapter": ["none", "lora"],
    "lr": ["1e-4", "5e-5"]
  }
}
```

## Core Fields

### Required in most real runs

- `current_research`
  A durable branch, commit, checkpoint, run record, or already-trained local model state.
- `base_command`
  The command template used as the exploratory execution anchor.
- `variant_axes`
  A dictionary of candidate dimensions. Each key is a knob to vary; each value is the ordered list of candidate settings.

### Optional scale controls

- `subset_sizes`
  Candidate subset sizes for exploratory runs.
- `short_run_steps`
  Candidate short-run step counts.
- `execution_kind`
  Use `training` or `verify` / `eval` / `non_training` when auto-inference would be ambiguous.

### Optional command-shaping controls

- `axis_flag_map`
  Maps a variant axis name to a command-line flag.
- `subset_size_flag`
  Overrides the default `--subset-size` flag.
- `short_run_steps_flag`
  Overrides the default `--max-steps` flag.

## Budget Controls

- `max_variants`
  Maximum number of candidates kept after pre-execution ranking.
- `max_short_cycle_runs`
  Maximum number of short-cycle candidates kept when `short_run_steps` is used.

These are hard budget controls. Candidate scoring happens first, then these limits prune the matrix.

## Ranking Controls

### Pre-execution candidate ranking

Before any command is executed, candidates are ranked with three factors:

- `cost`
- `success_rate`
- `expected_gain`

Use `selection_weights` to rebalance them:

```json
{
  "selection_weights": {
    "cost": 0.25,
    "success_rate": 0.35,
    "expected_gain": 0.40
  }
}
```

Interpretation:

- `cost`
  Lower runtime and smaller subsets are cheaper.
- `success_rate`
  Lighter, less aggressive candidates are more likely to run cleanly.
- `expected_gain`
  Candidates that move farther from the current setting are treated as having higher upside.

The weights are normalized before scoring. This stage is heuristic and should be treated as exploratory prioritization, not scientific proof.

### Post-execution result ranking

After candidates actually run, downstream ranking should use real execution evidence:

- `status` first
- then `primary_metric`
- then `metric_goal`

Example:

```json
{
  "primary_metric": "val_acc",
  "metric_goal": "maximize"
}
```

Accepted `metric_goal` values include:

- `maximize`
- `minimize`
- `max`
- `min`
- `lower_is_better`

## Recommended Starting Template

```json
{
  "current_research": "improved-model@branch",
  "base_command": "python train.py --config configs/demo.yaml",
  "variant_axes": {
    "adapter": ["none", "lora"],
    "lr": ["1e-4", "5e-5"]
  },
  "subset_sizes": [128, 512],
  "short_run_steps": [100, 300],
  "max_variants": 4,
  "max_short_cycle_runs": 2,
  "selection_weights": {
    "cost": 0.25,
    "success_rate": 0.35,
    "expected_gain": 0.40
  },
  "primary_metric": "val_acc",
  "metric_goal": "maximize"
}
```

## Notes

- Keep `current_research` durable and auditable.
- In campaign mode, pair `variant_spec` with a frozen task family, dataset, evaluation source, and provided SOTA table.
- Keep exploratory output candidate-only.
- Do not treat pre-execution ranking scores as trusted scientific conclusions.
- If `primary_metric` is omitted, downstream ranking falls back to parsed `best_metric`.
