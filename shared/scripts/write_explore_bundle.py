#!/usr/bin/env python3
"""Shared writer for exploratory code and exploratory run bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def load_context(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bullets(items: Iterable[str]) -> str:
    values = [item for item in items if item]
    if not values:
        return "- None."
    return "\n".join(f"- {item}" for item in values)


def format_source_refs(source_repo_refs: Iterable[Dict[str, Any]]) -> List[str]:
    refs = []
    for item in source_repo_refs:
        repo = item.get("repo", "unknown")
        ref = item.get("ref", "unknown")
        note = item.get("note")
        line = f"- `{repo}` @ `{ref}`"
        if note:
            line += f": {note}"
        refs.append(line)
    return refs or ["- None."]


def current_research_value(context: Dict[str, Any]) -> str:
    return str(context.get("current_research") or context.get("baseline_ref") or "unknown")


def require_field(value: Any, field_name: str) -> Any:
    if value is None or value == "":
        raise ValueError(f"Missing required explore field: {field_name}")
    return value


def explore_context_payload(context: Dict[str, Any]) -> Dict[str, Any]:
    explicit_auth = context.get("explicit_explore_authorization")
    raw = dict(context.get("explore_context", {}))
    current_research = str(raw.get("current_research") or current_research_value(context))
    experiment_branch = str(raw.get("experiment_branch") or context.get("experiment_branch") or "")
    return {
        "context_id": raw.get("context_id") or context.get("context_id"),
        "current_research": require_field(current_research, "current_research"),
        "experiment_branch": require_field(experiment_branch, "experiment_branch"),
        "explicit_explore_authorization": require_field(
            raw.get("explicit_explore_authorization", explicit_auth),
            "explicit_explore_authorization",
        ),
        "isolated_workspace": raw.get("isolated_workspace", context.get("isolated_workspace", True)),
        "workspace_mode": raw.get("workspace_mode", context.get("workspace_mode")),
        "workspace_root": raw.get("workspace_root", context.get("workspace_root")),
    }


def format_stage_trace(stage_trace: Iterable[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for item in stage_trace:
        stage = item.get("stage", "unknown")
        status = item.get("status", "unknown")
        tool = item.get("tool")
        summary = item.get("summary")
        line = f"- `{stage}` [{status}]"
        if tool:
            line += f" via `{tool}`"
        if summary:
            line += f": {summary}"
        lines.append(line)
    return lines or ["- None."]


def write_changeset(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    explore_context = explore_context_payload(context)
    title = "# Explore Changeset"
    if mode == "code":
        intent_title = "## Exploratory code focus"
    elif mode == "run":
        intent_title = "## Experiment focus"
    else:
        intent_title = "## Research exploration focus"
    lines = [
        title,
        "",
        f"- Mode: `{mode}`",
        f"- Current research: `{explore_context['current_research']}`",
        f"- Experiment branch: `{explore_context['experiment_branch']}`",
        f"- Isolated workspace: `{explore_context['isolated_workspace']}`",
        f"- Workspace mode: `{explore_context.get('workspace_mode') or 'unknown'}`",
        f"- Human checkpoint state: `{context.get('human_checkpoint_state', 'not-applicable')}`",
        f"- SOTA claim state: `{context.get('sota_claim_state', 'not-applicable')}`",
        f"- Trusted promotion candidate: `{context.get('trusted_promote_candidate', False)}`",
        "",
        "## Source references",
        "",
        *format_source_refs(context.get("source_repo_refs", [])),
        "",
        "## Helper stage trace",
        "",
        *format_stage_trace(context.get("helper_stage_trace", [])),
        "",
        intent_title,
        "",
        bullets(context.get("changes_summary", [])),
        "",
        "## Notes",
        "",
        bullets(context.get("notes", [])),
        "",
    ]
    (output_dir / "CHANGESET.md").write_text("\n".join(lines), encoding="utf-8")


def write_top_runs(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    explore_context = explore_context_payload(context)
    metric_policy = context.get("metric_policy", {})
    variant_budget = context.get("variant_budget", {})
    selection_policy = context.get("selection_policy", {})
    lines = [
        "# Top Runs",
        "",
        f"- Raw variant count: `{context.get('raw_variant_count', context.get('variant_count', 0))}`",
        f"- Variant count: `{context.get('variant_count', 0)}`",
        f"- Pruned variant count: `{context.get('pruned_variant_count', 0)}`",
        f"- Current research: `{explore_context['current_research']}`",
        f"- Human checkpoint state: `{context.get('human_checkpoint_state', 'not-applicable')}`",
        "",
    ]
    if selection_policy.get("factors"):
        factor_list = ", ".join(selection_policy.get("factors", []))
        lines.extend(
            [
                f"- Pre-execution selection factors: `{factor_list}`",
                "",
            ]
        )
    if metric_policy.get("primary_metric"):
        lines.extend(
            [
                f"- Ranking metric: `{metric_policy['primary_metric']}` ({metric_policy.get('metric_goal', 'maximize')})",
                "",
            ]
        )
    if variant_budget.get("max_variants") or variant_budget.get("max_short_cycle_runs"):
        lines.extend(
            [
                f"- Budget: max_variants=`{variant_budget.get('max_variants', 0)}`, max_short_cycle_runs=`{variant_budget.get('max_short_cycle_runs', 0)}`",
                "",
            ]
        )
    if context.get("baseline_gate", {}).get("decision"):
        lines.extend(
            [
                f"- Baseline gate: `{context['baseline_gate']['decision']}`",
                "",
            ]
        )
    if context.get("sota_claim_state"):
        lines.extend(
            [
                f"- SOTA claim state: `{context['sota_claim_state']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Candidate hypotheses",
            "",
            bullets(context.get("candidate_hypotheses", [])),
            "",
            "## Best runs",
            "",
        ]
    )
    best_runs = context.get("best_runs", [])
    if not best_runs:
        lines.append("- None.")
    else:
        for item in best_runs:
            best_metric = item.get("best_metric")
            ranking_metric = item.get("ranking_metric")
            parts = [f"- `{item.get('id', 'unknown')}`"]
            if isinstance(best_metric, dict) and best_metric.get("name") and best_metric.get("value") is not None:
                parts.append(f"best_metric=`{best_metric['name']}={best_metric['value']}`")
            elif item.get("metric") is not None:
                parts.append(f"metric=`{item.get('metric', 'unknown')}`")
            if isinstance(ranking_metric, dict) and ranking_metric.get("name") and ranking_metric.get("value") is not None:
                parts.append(
                    f"ranking_metric=`{ranking_metric['name']}={ranking_metric['value']}` ({ranking_metric.get('goal', 'maximize')})"
                )
            parts.append(f"summary={item.get('summary', 'none')}")
            lines.append(" ".join(parts))
    lines.extend(
        [
            "",
            "## Recommended next trials",
            "",
            bullets(context.get("recommended_next_trials", [])),
            "",
        ]
    )
    if mode in {"run", "research"}:
        lines.extend(
            [
                "## Execution notes",
                "",
                bullets(context.get("execution_notes", [])),
                "",
            ]
        )
    (output_dir / "TOP_RUNS.md").write_text("\n".join(lines), encoding="utf-8")


def write_idea_gate(output_dir: Path, context: Dict[str, Any]) -> None:
    idea_gate = context.get("idea_gate", {})
    ranked = idea_gate.get("ranked_ideas", [])
    selected = context.get("selected_idea") or idea_gate.get("selected_idea")
    lines = [
        "# Idea Gate",
        "",
        f"- Decision: `{idea_gate.get('decision', 'not-configured')}`",
        f"- Active selection pool: `{idea_gate.get('active_selection_pool', 'all-eligible')}`",
        f"- Selection reason: {idea_gate.get('selection_reason', 'none')}",
        f"- Human checkpoint state: `{context.get('human_checkpoint_state', 'not-applicable')}`",
        "",
        "## Ranked Ideas",
        "",
    ]
    if not ranked:
        lines.append("- None.")
    else:
        for item in ranked:
            lines.append(
                f"- `{item.get('id', 'unknown')}` origin=`{item.get('seed_origin', 'researcher')}` score=`{item.get('idea_score', 'n/a')}` summary={item.get('summary', 'none')}"
            )
    lines.extend(
        [
            "",
            "## Selected Idea",
            "",
        ]
    )
    if not selected:
        lines.append("- None.")
    else:
        lines.extend(
            [
                f"- id: `{selected.get('id', 'unknown')}`",
                f"- summary: {selected.get('summary', 'none')}",
                f"- seed_origin: `{selected.get('seed_origin', 'researcher')}`",
                f"- selection_pool: `{selected.get('selection_pool', idea_gate.get('active_selection_pool', 'all-eligible'))}`",
                f"- target_component: `{selected.get('target_component', 'unspecified')}`",
                f"- change_scope: `{selected.get('change_scope', 'unspecified')}`",
            ]
        )
    (output_dir / "IDEA_GATE.md").write_text("\n".join(lines), encoding="utf-8")


def write_experiment_plan(output_dir: Path, context: Dict[str, Any]) -> None:
    manifest = context.get("experiment_manifest", {})
    short_run_gate = context.get("short_run_gate", {})
    atomic = context.get("atomic_idea_map", {})
    fidelity = context.get("implementation_fidelity", {})
    lines = [
        "# Experiment Plan",
        "",
        f"- Manifest status: `{manifest.get('status', 'ready')}`",
        f"- Current research: `{current_research_value(context)}`",
        f"- Parent baseline: `{manifest.get('parent_baseline', current_research_value(context))}`",
        f"- Idea id: `{manifest.get('idea_id', 'none')}`",
        f"- Primary metric: `{manifest.get('primary_metric', context.get('metric_policy', {}).get('primary_metric') or 'unspecified')}`",
        f"- Eval contract ref: `{manifest.get('eval_contract_ref', 'analysis_outputs/EVAL_CONTRACT.md')}`",
        f"- Promotion rule: `{manifest.get('promotion_rule', 'manual-review')}`",
        "",
        "## Hypothesis",
        "",
        bullets([manifest.get("hypothesis", "")]),
        "",
        "## Planned Changed Files",
        "",
        bullets(manifest.get("planned_changed_files", manifest.get("changed_files", []))),
        "",
        "## Observed Changed Files",
        "",
        bullets(manifest.get("observed_changed_files", manifest.get("changed_files", []))),
        "",
        "## Config Overrides",
        "",
        bullets(context.get("config_diff_summary", [])),
        "",
        "## Supporting Changes",
        "",
        bullets(manifest.get("supporting_changes", [])),
        "",
        "## Atomic Decomposition",
        "",
        bullets(
            [
                f"status={atomic.get('status', 'blocked')}",
                f"atomic_unit_count={atomic.get('atomic_unit_count', 0)}",
            ]
        ),
        "",
        "## Implementation Fidelity",
        "",
        bullets(
            [
                f"states={fidelity.get('fidelity_summary', {}).get('states', {})}",
                f"verification_levels={fidelity.get('fidelity_summary', {}).get('verification_levels', {})}",
            ]
        ),
        "",
        "## Blockers",
        "",
        bullets(manifest.get("blockers", [])),
        "",
        "## Short-Run Gate",
        "",
        f"- Status: `{short_run_gate.get('status', 'not-run')}`",
        f"- Reason: {short_run_gate.get('reason', 'none')}",
        "",
    ]
    (output_dir / "EXPERIMENT_PLAN.md").write_text("\n".join(lines), encoding="utf-8")


def write_experiment_manifest(output_dir: Path, context: Dict[str, Any]) -> None:
    manifest = context.get("experiment_manifest", {})
    atomic = context.get("atomic_idea_map", {})
    fidelity = context.get("implementation_fidelity", {})
    lines = [
        "# Experiment Manifest",
        "",
        f"- Status: `{manifest.get('status', 'ready')}`",
        f"- Current research: `{current_research_value(context)}`",
        f"- Idea id: `{manifest.get('idea_id', 'none')}`",
        f"- Parent baseline: `{manifest.get('parent_baseline', current_research_value(context))}`",
        f"- Primary metric: `{manifest.get('primary_metric', 'unspecified')}`",
        f"- Promotion rule: `{manifest.get('promotion_rule', 'manual-review')}`",
        "",
        "## Hypothesis",
        "",
        bullets([manifest.get("hypothesis", "")]),
        "",
        "## Source References",
        "",
        bullets([str(item) for item in manifest.get("selected_source_reference", [])]),
        "",
        "## Source Record",
        "",
        bullets(
            [
                f"source_repo={manifest.get('selected_source_record', {}).get('source_repo', '') or 'none'}",
                f"source_file={manifest.get('selected_source_record', {}).get('source_file', '') or 'none'}",
                f"source_symbol={manifest.get('selected_source_record', {}).get('source_symbol', '') or 'none'}",
            ]
        ),
        "",
        "## Target Location Map",
        "",
        bullets(
            [
                f"{item.get('file', 'unknown')} -> {item.get('target_symbol', 'unknown')} ({item.get('role', 'unknown')})"
                for item in manifest.get("target_location_map", [])
            ]
        ),
        "",
        "## Minimal Patch Plan",
        "",
        bullets(
            [
                f"{item.get('change_type', 'unknown')}: {', '.join(item.get('target_files', [])) or 'none'}"
                for item in manifest.get("minimal_patch_plan", [])
            ]
        ),
        "",
        "## Smoke Validation Plan",
        "",
        bullets(
            [
                f"{item.get('name', 'unknown')}: {item.get('reason', 'no-reason')}"
                for item in manifest.get("smoke_validation_plan", [])
            ]
        ),
        "",
        "## Feasibility Summary",
        "",
        bullets(
            [
                f"short_run_feasibility={manifest.get('feasibility_summary', {}).get('short_run_feasibility', 'unknown')}",
                f"full_run_feasibility={manifest.get('feasibility_summary', {}).get('full_run_feasibility', 'unknown')}",
            ]
        ),
        "",
        "## Atomic Idea Map",
        "",
        bullets(
            [
                f"ref={manifest.get('atomic_idea_map_ref', 'analysis_outputs/ATOMIC_IDEA_MAP.json')}",
                f"status={atomic.get('status', 'blocked')}",
                f"atomic_unit_count={atomic.get('atomic_unit_count', 0)}",
            ]
        ),
        "",
        "## Implementation Fidelity",
        "",
        bullets(
            [
                f"ref={manifest.get('implementation_fidelity_ref', 'analysis_outputs/IMPLEMENTATION_FIDELITY.json')}",
                f"states={fidelity.get('fidelity_summary', {}).get('states', {})}",
                f"verification_levels={fidelity.get('fidelity_summary', {}).get('verification_levels', {})}",
            ]
        ),
        "",
        "## Blockers",
        "",
        bullets(manifest.get("blockers", [])),
        "",
    ]
    (output_dir / "EXPERIMENT_MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")


def write_experiment_ledger(output_dir: Path, context: Dict[str, Any]) -> None:
    ledger = context.get("experiment_ledger", {})
    baseline = ledger.get("baseline", {})
    candidate_runs = ledger.get("candidate_runs", [])
    lines = [
        "# Experiment Ledger",
        "",
        "## Baseline",
        "",
        f"- Decision: `{context.get('baseline_gate', {}).get('decision', 'not-configured')}`",
        f"- Metric: `{baseline.get('metric_name', 'unknown')}={baseline.get('metric_value', 'unknown')}`",
        f"- Runtime seconds: `{baseline.get('runtime_seconds', 0)}`",
        "",
        "## Candidate Runs",
        "",
    ]
    if not candidate_runs:
        lines.append("- None.")
    else:
        for item in candidate_runs:
            lines.append(
                f"- `{item.get('id', 'unknown')}` phase=`{item.get('phase', 'unknown')}` "
                f"metric_diff=`{item.get('baseline_metric_diff', 'n/a')}` runtime_seconds=`{item.get('runtime_seconds', 0)}` "
                f"stop_reason=`{item.get('stop_reason', 'unknown')}` rollback=`{item.get('rollback_target', 'unknown')}`"
            )
    (output_dir / "EXPERIMENT_LEDGER.md").write_text("\n".join(lines), encoding="utf-8")


def write_transplant_smoke_report(output_dir: Path, context: Dict[str, Any]) -> None:
    smoke_report = context.get("smoke_report", {})
    static_smoke = context.get("static_smoke", smoke_report.get("static_smoke", {}))
    runtime_smoke = context.get("runtime_smoke", smoke_report.get("runtime_smoke", {}))
    resource_plan = context.get("resource_plan", {})
    lines = [
        "# Transplant Smoke Report",
        "",
        f"- Overall status: `{smoke_report.get('status', 'not-run')}`",
        f"- Candidate-only semantics: `true`",
        f"- Short-run feasibility: `{resource_plan.get('short_run_feasibility', 'unknown')}`",
        f"- Full-run feasibility: `{resource_plan.get('full_run_feasibility', 'unknown')}`",
        "",
        "## Static Smoke",
        "",
    ]
    static_checks = static_smoke.get("checks", [])
    if not static_checks:
        lines.append("- None.")
    else:
        for item in static_checks:
            passed = ", ".join(item.get("passed", [])) or "none"
            blockers = ", ".join(item.get("blockers", [])) or "none"
            lines.append(
                f"- `{item.get('name', 'unknown')}` status=`{item.get('status', 'unknown')}` passed={passed} blockers={blockers}"
            )
    lines.extend(["", "## Runtime Smoke", ""])
    runtime_checks = runtime_smoke.get("checks", [])
    if not runtime_checks:
        lines.append("- None.")
    else:
        for item in runtime_checks:
            passed = ", ".join(item.get("passed", [])) or "none"
            blockers = ", ".join(item.get("blockers", [])) or "none"
            lines.append(
                f"- `{item.get('name', 'unknown')}` status=`{item.get('status', 'unknown')}` passed={passed} blockers={blockers}"
            )
    lines.extend(
        [
            "",
            "## Combined Blockers",
            "",
        ]
    )
    blockers = smoke_report.get("blockers", [])
    if not blockers:
        lines.append("- None.")
    else:
        lines.extend([f"- {item}" for item in blockers])
    (output_dir / "TRANSPLANT_SMOKE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def explore_comparability_status(context: Dict[str, Any], mode: str) -> str:
    explicit = context.get("comparability_status")
    if explicit:
        return str(explicit)
    if context.get("sota_claim_state") not in {None, "", "not-applicable", "candidate-only"}:
        return "candidate-only"
    if mode == "research" and context.get("eval_contract"):
        return "anchored-to-frozen-eval"
    return "candidate-only"


def write_scientific_changelog(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    manifest = context.get("experiment_manifest", {})
    selected = context.get("selected_idea") or context.get("idea_gate", {}).get("selected_idea") or {}
    lines = [
        "# Scientific Changelog",
        "",
        f"- Mode: `{mode}`",
        f"- Current research: `{current_research_value(context)}`",
        f"- Experiment branch: `{context.get('experiment_branch', context.get('explore_context', {}).get('experiment_branch', 'unknown'))}`",
        f"- Status: `{context.get('status', 'planned')}`",
        f"- Comparability status: `{explore_comparability_status(context, mode)}`",
        f"- Candidate-only: `true`",
        "",
        "## Candidate Change",
        "",
        bullets(
            context.get("changes_summary", [])
            or [
                f"Selected idea: {selected.get('summary', 'none')}",
                f"Target component: {selected.get('target_component', 'unspecified')}",
                f"Change scope: {selected.get('change_scope', 'unspecified')}",
            ]
        ),
        "",
        "## Changed Files",
        "",
        bullets(
            manifest.get("observed_changed_files")
            or manifest.get("planned_changed_files")
            or context.get("candidate_edit_targets", [])
        ),
        "",
        "## Why It May Matter",
        "",
        bullets(
            context.get("candidate_hypotheses", [])
            or [manifest.get("hypothesis", "Novelty and significance remain hypotheses until supported.")]
        ),
        "",
        "## Scientific Meaning",
        "",
        bullets(
            context.get("scientific_meaning_notes", [])
            or [
                "This is exploratory evidence, not trusted reproduction success.",
                "Engineering fixes and candidate changes are not method contributions until supported by fair comparison and ablation evidence.",
            ]
        ),
        "",
        "## Evidence Status",
        "",
        bullets(
            [
                f"baseline_gate={context.get('baseline_gate', {}).get('decision', 'not-configured')}",
                f"short_run_gate={context.get('short_run_gate', {}).get('status', 'not-run')}",
                f"static_smoke={context.get('static_smoke', {}).get('status', 'not-run')}",
                f"runtime_smoke={context.get('runtime_smoke', {}).get('status', 'not-run')}",
                f"human_checkpoint_state={context.get('human_checkpoint_state', 'not-applicable')}",
            ]
        ),
        "",
    ]
    (output_dir / "SCIENTIFIC_CHANGELOG.md").write_text("\n".join(lines), encoding="utf-8")


def write_comparability_report(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    eval_contract = context.get("eval_contract", {})
    metric_policy = context.get("metric_policy", {})
    lines = [
        "# Comparability Report",
        "",
        f"- Mode: `{mode}`",
        f"- Current research: `{current_research_value(context)}`",
        f"- Experiment branch: `{context.get('experiment_branch', context.get('explore_context', {}).get('experiment_branch', 'unknown'))}`",
        f"- Comparability status: `{explore_comparability_status(context, mode)}`",
        f"- SOTA claim state: `{context.get('sota_claim_state', 'not-applicable')}`",
        f"- Trusted promotion candidate: `{context.get('trusted_promote_candidate', False)}`",
        "",
        "## Comparison Anchors",
        "",
        bullets(
            [
                f"current_research={current_research_value(context)}",
                f"task_family={eval_contract.get('task_family', context.get('campaign', {}).get('task_family', 'not-recorded'))}",
                f"dataset={eval_contract.get('dataset', 'not-recorded')}",
                f"benchmark={eval_contract.get('benchmark', 'not-recorded')}",
                f"evaluation_command={eval_contract.get('evaluation_command', 'not-recorded')}",
                f"primary_metric={metric_policy.get('primary_metric', eval_contract.get('primary_metric', 'not-recorded'))}",
                f"metric_goal={metric_policy.get('metric_goal', eval_contract.get('metric_goal', 'not-recorded'))}",
            ]
        ),
        "",
        "## Candidate Boundary",
        "",
        bullets(
            [
                "Exploratory results are candidate-only.",
                "Provided SOTA references are treated as frozen comparison inputs, not proof of global completeness.",
                "Direct comparability depends on unchanged dataset, preprocessing, metric, checkpoint, and evaluation conditions.",
            ]
        ),
        "",
        "## Known Risks",
        "",
        bullets(
            context.get("comparability_risks", [])
            or [
                f"eval_risk={(context.get('selected_idea') or {}).get('eval_risk', 'not-recorded')}",
                f"patch_surface={(context.get('patch_surface_summary') or {}).get('estimated_patch_surface', 'not-recorded')}",
                f"dependency_drag={(context.get('selected_idea') or {}).get('dependency_drag', 'not-recorded')}",
            ]
        ),
        "",
        "## Interpretation",
        "",
        context.get(
            "comparability_interpretation",
            "Do not promote exploratory gains to trusted baseline or SOTA claims without reproduction, ablation, and fair-comparison evidence.",
        ),
        "",
    ]
    (output_dir / "COMPARABILITY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_status(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    explore_context = explore_context_payload(context)
    current_research = explore_context["current_research"]
    outputs = {
        "changeset": "explore_outputs/CHANGESET.md",
        "top_runs": "explore_outputs/TOP_RUNS.md",
        "scientific_changelog": "explore_outputs/SCIENTIFIC_CHANGELOG.md",
        "comparability_report": "explore_outputs/COMPARABILITY_REPORT.md",
        "status": "explore_outputs/status.json",
    }
    if mode == "research":
        outputs.update(
            {
                "idea_gate": "explore_outputs/IDEA_GATE.md",
                "experiment_plan": "explore_outputs/EXPERIMENT_PLAN.md",
                "experiment_manifest": "explore_outputs/EXPERIMENT_MANIFEST.md",
                "experiment_ledger": "explore_outputs/EXPERIMENT_LEDGER.md",
                "transplant_smoke_report": "explore_outputs/TRANSPLANT_SMOKE_REPORT.md",
                "analysis_status": "analysis_outputs/status.json",
                "idea_seeds": "analysis_outputs/IDEA_SEEDS.json",
                "atomic_idea_map": "analysis_outputs/ATOMIC_IDEA_MAP.json",
                "implementation_fidelity": "analysis_outputs/IMPLEMENTATION_FIDELITY.json",
            }
        )
    payload = {
        "schema_version": context.get("schema_version", "1.0"),
        "context_id": context.get("context_id") or explore_context.get("context_id"),
        "mode": mode,
        "status": context.get("status", "planned"),
        "current_research": current_research,
        "baseline_ref": context.get("baseline_ref", current_research),
        "experiment_branch": explore_context["experiment_branch"],
        "isolated_workspace": explore_context["isolated_workspace"],
        "explore_context": explore_context,
        "campaign": context.get("campaign", {}),
        "source_repo_refs": context.get("source_repo_refs", []),
        "raw_variant_count": context.get("raw_variant_count", context.get("variant_count", 0)),
        "variant_count": context.get("variant_count", 0),
        "pruned_variant_count": context.get("pruned_variant_count", 0),
        "variant_budget": context.get("variant_budget", {"max_variants": 0, "max_short_cycle_runs": 0}),
        "selection_policy": context.get("selection_policy", {}),
        "metric_policy": context.get("metric_policy", {"primary_metric": None, "metric_goal": "maximize"}),
        "eval_contract": context.get("eval_contract", {}),
        "baseline_gate": context.get("baseline_gate", {}),
        "idea_gate": context.get("idea_gate", {}),
        "selected_idea": context.get("selected_idea"),
        "selected_idea_breakdown": context.get("selected_idea_breakdown", {}),
        "idea_seeds": context.get("idea_seeds", {}),
        "generated_idea_count": context.get("generated_idea_count", 0),
        "researcher_idea_count": context.get("researcher_idea_count", 0),
        "synthesized_idea_count": context.get("synthesized_idea_count", 0),
        "atomic_idea_map": context.get("atomic_idea_map", {}),
        "atomic_unit_count": context.get("atomic_unit_count", 0),
        "implementation_fidelity": context.get("implementation_fidelity", {}),
        "fidelity_summary": context.get("fidelity_summary", {}),
        "experiment_manifest": context.get("experiment_manifest", {}),
        "experiment_ledger": context.get("experiment_ledger", {}),
        "short_run_gate": context.get("short_run_gate", {}),
        "best_runs": context.get("best_runs", []),
        "candidate_edit_targets": context.get("candidate_edit_targets", []),
        "target_location_map": context.get("target_location_map", []),
        "supporting_changes": context.get("supporting_changes", []),
        "patch_surface_summary": context.get("patch_surface_summary", {}),
        "minimal_patch_plan": context.get("minimal_patch_plan", []),
        "smoke_validation_plan": context.get("smoke_validation_plan", []),
        "module_candidates": context.get("module_candidates", []),
        "selected_source_record": context.get("selected_source_record", {}),
        "interface_diff": context.get("interface_diff", {}),
        "code_tracks": context.get("code_tracks", []),
        "candidate_hypotheses": context.get("candidate_hypotheses", []),
        "analysis_artifacts": context.get("analysis_artifacts", {}),
        "sources_dir": context.get("sources_dir"),
        "sources_records_dir": context.get("sources_records_dir"),
        "sources_index_path": context.get("sources_index_path"),
        "source_inventory_path": context.get("source_inventory_path"),
        "source_support_path": context.get("source_support_path"),
        "source_record_count": context.get("source_record_count", 0),
        "source_records_by_evidence_class": context.get("source_records_by_evidence_class", []),
        "lookup_records": context.get("lookup_records", []),
        "idea_cards": context.get("idea_cards", []),
        "improvement_bank": context.get("improvement_bank", []),
        "resource_plan": context.get("resource_plan", {}),
        "resource_detection": context.get("resource_detection", {}),
        "resource_recommendations": context.get("resource_recommendations", {}),
        "static_smoke": context.get("static_smoke", {}),
        "runtime_smoke": context.get("runtime_smoke", {}),
        "smoke_report": context.get("smoke_report", {}),
        "planned_skill_chain": context.get("planned_skill_chain", []),
        "helper_stage_trace": context.get("helper_stage_trace", []),
        "recommended_next_trials": context.get("recommended_next_trials", []),
        "execution_notes": context.get("execution_notes", []),
        "trusted_promote_candidate": context.get("trusted_promote_candidate", False),
        "explicit_explore_authorization": explore_context["explicit_explore_authorization"],
        "human_checkpoint_state": context.get("human_checkpoint_state", "not-applicable"),
        "sota_claim_state": context.get("sota_claim_state", "not-applicable"),
        "outputs": outputs,
        "notes": context.get("notes", []),
    }
    (output_dir / "status.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_bundle(mode: str, output_dir: Path, context: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_changeset(output_dir, context, mode)
    write_top_runs(output_dir, context, mode)
    write_scientific_changelog(output_dir, context, mode)
    write_comparability_report(output_dir, context, mode)
    if mode == "research":
        write_idea_gate(output_dir, context)
        write_experiment_plan(output_dir, context)
        write_experiment_manifest(output_dir, context)
        write_experiment_ledger(output_dir, context)
        write_transplant_smoke_report(output_dir, context)
    write_status(output_dir, context, mode)


def main(default_mode: str = "code", default_output_dir: Optional[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Write exploratory output bundles.")
    parser.add_argument("--context-json", required=True, help="Path to a context JSON file.")
    parser.add_argument("--mode", choices=["code", "run", "research"], default=default_mode)
    parser.add_argument(
        "--output-dir",
        default=default_output_dir or "explore_outputs",
        help="Directory where output files will be written.",
    )
    args = parser.parse_args()

    context = load_context(Path(args.context_json).resolve())
    write_bundle(args.mode, Path(args.output_dir).resolve(), context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
