#!/usr/bin/env python3
"""Generate a budget-aware exploratory variant matrix for isolated runs."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

DEFAULT_SELECTION_WEIGHTS = {
    "cost": 0.25,
    "success_rate": 0.35,
    "expected_gain": 0.40,
}


def load_spec(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def current_research_value(spec: Dict[str, Any]) -> str:
    return str(spec.get("current_research") or spec.get("baseline_ref") or "unknown")


def normalize_metric_goal(value: Any) -> str:
    text = str(value or "maximize").strip().lower()
    if text in {"min", "minimize", "lower", "lower_is_better"}:
        return "minimize"
    return "maximize"


def safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def can_float(value: Any) -> bool:
    try:
        float(str(value))
        return True
    except (TypeError, ValueError):
        return False


def unique_preserving_order(values: Sequence[Any]) -> List[Any]:
    ordered: List[Any] = []
    for item in values:
        if item not in ordered:
            ordered.append(item)
    return ordered


def rank_lookup(values: Sequence[Any]) -> Dict[Any, int]:
    ordered_values = unique_preserving_order(values)
    if not ordered_values:
        return {}

    has_none = any(item is None for item in ordered_values)
    non_none = [item for item in ordered_values if item is not None]
    if non_none and all(can_float(item) for item in non_none):
        ordered_non_none = sorted(non_none, key=lambda item: (safe_float(item), str(item)))
    else:
        ordered_non_none = non_none

    ordered = ([None] if has_none else []) + ordered_non_none
    return {item: index for index, item in enumerate(ordered)}


def normalized_lookup_score(value: Any, lookup: Dict[Any, int]) -> float:
    if not lookup:
        return 0.0
    index = lookup.get(value, 0)
    max_index = max(lookup.values(), default=0)
    if max_index <= 0:
        return 0.0
    return index / max_index


def normalize_weights(spec: Dict[str, Any]) -> Dict[str, float]:
    raw = dict(DEFAULT_SELECTION_WEIGHTS)
    raw.update(spec.get("selection_weights", {}))
    total = sum(max(0.0, safe_float(value)) for value in raw.values())
    if total <= 0:
        return dict(DEFAULT_SELECTION_WEIGHTS)
    return {
        "cost": max(0.0, safe_float(raw.get("cost"))) / total,
        "success_rate": max(0.0, safe_float(raw.get("success_rate"))) / total,
        "expected_gain": max(0.0, safe_float(raw.get("expected_gain"))) / total,
    }


def axis_aggressiveness_score(axis_values: Dict[str, Any], axes: Dict[str, Sequence[Any]]) -> float:
    if not axis_values:
        return 0.0
    scores: List[float] = []
    for key, value in axis_values.items():
        options = list(axes.get(key, []))
        if not options:
            scores.append(0.0)
            continue
        lookup = {option: index for index, option in enumerate(options)}
        max_index = max(len(options) - 1, 1)
        scores.append(lookup.get(value, 0) / max_index)
    return sum(scores) / len(scores)


def annotate_variant_scores(
    raw_variants: List[Dict[str, Any]],
    spec: Dict[str, Any],
    subset_lookup: Dict[Any, int],
    step_lookup: Dict[Any, int],
) -> List[Dict[str, Any]]:
    axes = spec.get("variant_axes", {})
    weights = normalize_weights(spec)
    annotated: List[Dict[str, Any]] = []

    for item in raw_variants:
        subset_scale = normalized_lookup_score(item.get("subset_size"), subset_lookup)
        step_scale = normalized_lookup_score(item.get("short_run_steps"), step_lookup)
        axis_scale = axis_aggressiveness_score(item.get("axes", {}), axes)

        raw_cost = 0.50 * step_scale + 0.35 * subset_scale + 0.15 * axis_scale
        cost_efficiency_score = clamp_score(1.0 - raw_cost)
        predicted_success_score = clamp_score(1.0 - (0.45 * axis_scale + 0.35 * step_scale + 0.20 * subset_scale))
        predicted_gain_score = clamp_score(0.50 * axis_scale + 0.30 * step_scale + 0.20 * subset_scale)
        total_score = (
            weights["cost"] * cost_efficiency_score
            + weights["success_rate"] * predicted_success_score
            + weights["expected_gain"] * predicted_gain_score
        )

        annotated_item = dict(item)
        annotated_item.update(
            {
                "cost_score": round(raw_cost, 4),
                "cost_efficiency_score": round(cost_efficiency_score, 4),
                "predicted_success_score": round(predicted_success_score, 4),
                "predicted_gain_score": round(predicted_gain_score, 4),
                "total_score": round(total_score, 4),
                "estimated_runtime_units": round(1.0 + 3.0 * step_scale + 2.0 * subset_scale + axis_scale, 4),
                "feasibility_annotations": [],
            }
        )
        annotated.append(annotated_item)
    return annotated


def build_raw_variants(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    axes = {
        key: list(value) if isinstance(value, (list, tuple)) else [value]
        for key, value in (spec.get("variant_axes") or {}).items()
    }
    keys = sorted(axes)
    values = [axes[key] for key in keys]
    subset_sizes = spec.get("subset_sizes") or [None]
    short_run_steps = spec.get("short_run_steps") or [None]
    current_research = current_research_value(spec)

    subset_rank = rank_lookup(subset_sizes)
    step_rank = rank_lookup(short_run_steps)

    variants: List[Dict[str, Any]] = []
    index = 1
    for combo in itertools.product(*values):
        axis_values = dict(zip(keys, combo))
        axis_position_penalty = sum(axes[key].index(axis_values[key]) for key in keys)
        for subset_size in subset_sizes:
            for step_limit in short_run_steps:
                subset_position = subset_rank.get(subset_size, 0)
                step_position = step_rank.get(step_limit, 0)
                variants.append(
                    {
                        "id": f"variant-{index:03d}",
                        "axes": axis_values,
                        "subset_size": subset_size,
                        "short_run_steps": step_limit,
                        "current_research": current_research,
                        "baseline_ref": spec.get("baseline_ref", current_research),
                        "base_command": spec.get("base_command"),
                        "axis_position_penalty": axis_position_penalty,
                        "subset_rank": subset_position,
                        "step_rank": step_position,
                    }
                )
                index += 1

    return annotate_variant_scores(variants, spec, subset_rank, step_rank)


def prune_variants(raw_variants: List[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    max_variants = int(spec.get("max_variants") or 0)
    max_short_cycle_runs = int(spec.get("max_short_cycle_runs") or 0)

    ordered = sorted(
        raw_variants,
        key=lambda item: (
            -item.get("total_score", 0.0),
            -item.get("predicted_gain_score", 0.0),
            -item.get("predicted_success_score", 0.0),
            -item.get("cost_efficiency_score", 0.0),
            item.get("cost_score", 0.0),
            item.get("id", ""),
        ),
    )

    selected: List[Dict[str, Any]] = []
    short_cycle_count = 0
    for item in ordered:
        is_short_cycle = item.get("short_run_steps") is not None
        if max_short_cycle_runs > 0 and is_short_cycle and short_cycle_count >= max_short_cycle_runs:
            continue
        selected.append(item)
        if is_short_cycle:
            short_cycle_count += 1
        if max_variants > 0 and len(selected) >= max_variants:
            break
    return selected


def build_variants(spec: Dict[str, Any]) -> Dict[str, Any]:
    current_research = current_research_value(spec)
    raw_variants = build_raw_variants(spec)
    variants = prune_variants(raw_variants, spec)
    raw_variant_count = len(raw_variants)
    variant_count = len(variants)

    return {
        "schema_version": "1.0",
        "current_research": current_research,
        "baseline_ref": spec.get("baseline_ref", current_research),
        "base_command": spec.get("base_command"),
        "raw_variant_count": raw_variant_count,
        "variant_count": variant_count,
        "pruned_variant_count": raw_variant_count - variant_count,
        "variant_budget": {
            "max_variants": int(spec.get("max_variants") or 0),
            "max_short_cycle_runs": int(spec.get("max_short_cycle_runs") or 0),
        },
        "selection_policy": {
            "factors": ["cost", "success_rate", "expected_gain"],
            "weights": normalize_weights(spec),
            "scores": {
                "cost_score": "Lower is cheaper; derived from steps, subset size, and axis aggressiveness.",
                "cost_efficiency_score": "Higher is cheaper after inverting cost_score.",
                "predicted_success_score": "Higher means the candidate is more likely to run cleanly.",
                "predicted_gain_score": "Higher means the candidate is more likely to produce a measurable improvement.",
                "total_score": "Weighted composite used for pre-execution candidate ranking.",
            },
        },
        "metric_policy": {
            "primary_metric": spec.get("primary_metric"),
            "metric_goal": normalize_metric_goal(spec.get("metric_goal")),
        },
        "variants": variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a budget-aware exploratory variant matrix.")
    parser.add_argument("--spec-json", required=True, help="Path to the exploration spec JSON file.")
    parser.add_argument("--output-json", help="Optional output path for the generated matrix.")
    parser.add_argument("--json", action="store_true", help="Emit the matrix to stdout.")
    args = parser.parse_args()

    payload = build_variants(load_spec(Path(args.spec_json).resolve()))
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json or not args.output_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
