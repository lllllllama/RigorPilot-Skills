"""Candidate idea generation pass for ai-research-explore."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


DEFAULT_POLICY = {
    "allow_synthesized_seed_ideas": True,
    "max_generated_ideas": 3,
    "require_diverse_targets": True,
}
REWRITE_RISK_TOKENS = {"rewrite", "architecture", "backbone", "full-model", "all-modules", "trainer-core"}
SKIP_COMPONENT_TOKENS = {"eval", "metric", "benchmark", "leaderboard"}


def clamp(value: Any, default: float = 0.5) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(0.0, min(1.0, numeric))


def tokenize(value: Any) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", str(value or "").lower()) if len(token) > 2]


def unique_preserving(values: Sequence[str], *, limit: int | None = None) -> List[str]:
    ordered: List[str] = []
    for value in values:
        if not value or value in ordered:
            continue
        ordered.append(value)
        if limit is not None and len(ordered) >= limit:
            break
    return ordered


def normalize_policy(raw: Any) -> Dict[str, Any]:
    policy = dict(DEFAULT_POLICY)
    if isinstance(raw, dict):
        policy.update(raw)
    policy["allow_synthesized_seed_ideas"] = bool(policy.get("allow_synthesized_seed_ideas", True))
    try:
        policy["max_generated_ideas"] = max(0, int(policy.get("max_generated_ideas", 3)))
    except (TypeError, ValueError):
        policy["max_generated_ideas"] = 3
    policy["require_diverse_targets"] = bool(policy.get("require_diverse_targets", True))
    return policy


def stringify_binding(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "id", "path", "label"):
            if value.get(key):
                return str(value[key])
        items = [f"{key}={value[key]}" for key in sorted(value) if value.get(key) not in {None, ""}]
        return ", ".join(items) or "unspecified"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip()) or "unspecified"
    text = str(value or "").strip()
    return text or "unspecified"


def evaluation_binding_text(evaluation_source: Dict[str, Any]) -> str:
    command = str(evaluation_source.get("command") or "").strip()
    path = str(evaluation_source.get("path") or "").strip()
    metric = str(evaluation_source.get("primary_metric") or "").strip()
    parts = []
    if path:
        parts.append(f"path={path}")
    if command:
        parts.append(f"command={command}")
    if metric:
        parts.append(f"metric={metric}")
    return " | ".join(parts) or "unspecified"


def normalize_context_bindings(
    *,
    current_research: str,
    task_family: str,
    dataset: Any,
    evaluation_source: Dict[str, Any],
) -> Dict[str, Any]:
    dataset_binding = stringify_binding(dataset)
    evaluation_binding = evaluation_binding_text(evaluation_source)
    task_binding = str(task_family or "").strip() or "unspecified"
    evaluation_tokens = unique_preserving(
        tokenize(evaluation_source.get("command"))
        + tokenize(evaluation_source.get("path"))
        + tokenize(evaluation_source.get("primary_metric"))
        + tokenize(evaluation_source.get("split")),
        limit=10,
    )
    task_tokens = unique_preserving(tokenize(task_binding) + tokenize(dataset_binding), limit=10)
    return {
        "context_anchor": str(current_research or "").strip() or "unspecified",
        "task_family_binding": task_binding,
        "dataset_binding": dataset_binding,
        "evaluation_binding": evaluation_binding,
        "evaluation_tokens": evaluation_tokens,
        "task_tokens": task_tokens,
    }


def context_constraint_notes(context: Dict[str, Any], *, axis: str, target_component: str) -> List[str]:
    notes = [
        f"Anchor all generated work to current_research `{context['context_anchor']}`.",
        f"Keep the candidate inside task family `{context['task_family_binding']}` and dataset `{context['dataset_binding']}`.",
        f"Preserve the frozen evaluation binding `{context['evaluation_binding']}`.",
        f"Prefer the single-variable axis `{axis}` around `{target_component}` and keep rollback easy.",
    ]
    return unique_preserving(notes, limit=4)


def module_component_candidates(analysis_data: Dict[str, Any]) -> List[str]:
    all_candidates: List[str] = []
    preferred_candidates: List[str] = []
    for path in analysis_data.get("module_files", []):
        stem = Path(str(path)).stem.replace("_", "-")
        if not stem:
            continue
        all_candidates.append(stem)
        if stem not in {"model", "train", "eval"}:
            preferred_candidates.append(stem)
    for item in analysis_data.get("constructor_candidates", []):
        token = str(item).split(":", 1)[-1].split(".", 1)[0].replace("_", "-")
        if token:
            preferred_candidates.append(token)
            all_candidates.append(token)
    for item in analysis_data.get("forward_candidates", []):
        token = str(item).split(":", 1)[-1].split(".", 1)[0].replace("_", "-")
        if token:
            preferred_candidates.append(token)
            all_candidates.append(token)
    candidates = preferred_candidates or all_candidates
    return unique_preserving(candidates, limit=6)


def component_pool(
    researcher_candidate_ideas: Sequence[Dict[str, Any]],
    analysis_data: Dict[str, Any],
    improvement_bank: Sequence[Dict[str, Any]],
) -> List[str]:
    candidates: List[str] = []
    for idea in researcher_candidate_ideas:
        candidates.append(str(idea.get("target_component") or ""))
    for item in improvement_bank:
        candidates.append(str(item.get("target_component") or ""))
    candidates.extend(module_component_candidates(analysis_data))
    return unique_preserving([item for item in candidates if item and item != "unspecified"], limit=10)


def contextual_component_pool(components: Sequence[str], context: Dict[str, Any]) -> List[str]:
    task_tokens = set(context.get("task_tokens", []))
    evaluation_tokens = set(context.get("evaluation_tokens", []))

    def score(component: str) -> Tuple[int, int, str]:
        tokens = set(tokenize(component))
        task_overlap = len(tokens & task_tokens)
        evaluation_overlap = len(tokens & evaluation_tokens)
        return (task_overlap, -evaluation_overlap, component)

    ordered = sorted(unique_preserving(components), key=score, reverse=True)
    if ordered:
        return ordered
    fallback = str(context.get("task_family_binding") or "training-config").replace(" ", "-").lower()
    if not fallback or fallback == "unspecified":
        fallback = "training-config"
    return [fallback]


def source_hint_for_component(component: str, improvement_bank: Sequence[Dict[str, Any]], analysis_data: Dict[str, Any]) -> str:
    lowered = component.lower()
    for item in improvement_bank:
        if lowered and lowered in str(item.get("target_component") or "").lower():
            refs = item.get("external_source_reference") or item.get("source_reference") or []
            if refs:
                return f"Bound to source support from {', '.join(refs[:2])}."
    for path in analysis_data.get("module_files", []):
        if lowered and lowered in str(path).lower():
            return f"Anchored to repo-local component `{path}`."
    return "Anchored to repo-local structure and frozen evaluation constraints."


def feasibility_hint_for_scope(change_scope: str, variant_spec: Dict[str, Any], analysis_data: Dict[str, Any]) -> str:
    if change_scope in (variant_spec.get("variant_axes") or {}):
        return f"Variant axis `{change_scope}` already exists in variant_spec, so short-run feasibility can stay command-level."
    if analysis_data.get("config_binding_hints"):
        return f"Likely feasible through existing config bindings such as `{analysis_data['config_binding_hints'][0]}`."
    return "Feasibility remains heuristic; keep the patch single-variable and reversible."


def make_seed_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}"


def broad_rewrite_risk(change_scope: str, target_component: str) -> bool:
    tokens = set(tokenize(change_scope) + tokenize(target_component))
    return bool(tokens & REWRITE_RISK_TOKENS)


def eval_contract_risk(target_component: str, evaluation_tokens: Sequence[str]) -> bool:
    tokens = set(tokenize(target_component))
    return bool(tokens & (SKIP_COMPONENT_TOKENS | set(evaluation_tokens)))


def axis_seed(
    *,
    axis: str,
    axis_values: Sequence[Any],
    target_component: str,
    source_support_hint: str,
    feasibility_hint: str,
    index: int,
    seed_origin: str,
    context: Dict[str, Any],
    campaign_idea_id: str = "",
) -> Dict[str, Any]:
    value_summary = ", ".join(str(value) for value in list(axis_values)[:3]) or "bounded values"
    return {
        "id": make_seed_id("idea-seed", index),
        "summary": (
            f"Probe `{axis}` as a single-variable change around `{target_component}` while keeping "
            f"`{context['evaluation_binding']}` unchanged."
        ),
        "change_scope": axis,
        "target_component": target_component,
        "expected_upside": clamp(0.55 if seed_origin == "synthesized" else 0.60, default=0.55),
        "implementation_risk": clamp(0.28 if seed_origin == "hybrid" else 0.22, default=0.25),
        "eval_risk": clamp(0.18, default=0.18),
        "rollback_ease": clamp(0.88, default=0.88),
        "estimated_runtime_cost": clamp(0.30 if len(list(axis_values)) <= 2 else 0.38, default=0.35),
        "single_variable_fit": clamp(0.94, default=0.94),
        "seed_origin": seed_origin,
        "campaign_idea_id": campaign_idea_id or None,
        "source_support_hint": source_support_hint,
        "feasibility_hint": f"{feasibility_hint} Candidate values: {value_summary}.",
        "context_anchor": context["context_anchor"],
        "task_family_binding": context["task_family_binding"],
        "dataset_binding": context["dataset_binding"],
        "evaluation_binding": context["evaluation_binding"],
        "constraint_notes": context_constraint_notes(context, axis=axis, target_component=target_component),
    }


def fallback_seed(
    *,
    target_component: str,
    source_support_hint: str,
    feasibility_hint: str,
    index: int,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    axis = f"single-variable-{target_component.replace(' ', '-').lower()}"
    return {
        "id": make_seed_id("idea-seed", index),
        "summary": (
            f"Introduce one bounded follow-up around `{target_component}` while preserving "
            f"`{context['evaluation_binding']}` and avoiding architecture rewrites."
        ),
        "change_scope": axis,
        "target_component": target_component,
        "expected_upside": 0.50,
        "implementation_risk": 0.24,
        "eval_risk": 0.18,
        "rollback_ease": 0.90,
        "estimated_runtime_cost": 0.32,
        "single_variable_fit": 0.90,
        "seed_origin": "synthesized",
        "campaign_idea_id": None,
        "source_support_hint": source_support_hint,
        "feasibility_hint": feasibility_hint,
        "context_anchor": context["context_anchor"],
        "task_family_binding": context["task_family_binding"],
        "dataset_binding": context["dataset_binding"],
        "evaluation_binding": context["evaluation_binding"],
        "constraint_notes": context_constraint_notes(context, axis=axis, target_component=target_component),
    }


def reject_seed(seed: Dict[str, Any], reason: str) -> Dict[str, Any]:
    rejected = dict(seed)
    rejected["rejection_reason"] = reason
    return rejected


def existing_signatures(researcher_candidate_ideas: Sequence[Dict[str, Any]]) -> set[Tuple[str, str]]:
    return {
        (
            str(item.get("change_scope") or "").lower(),
            str(item.get("target_component") or "").lower(),
        )
        for item in researcher_candidate_ideas
    }


def build_generated_ideas(
    *,
    current_research: str,
    task_family: str,
    dataset: Any,
    evaluation_source: Dict[str, Any],
    variant_spec: Dict[str, Any],
    researcher_candidate_ideas: Sequence[Dict[str, Any]],
    improvement_bank: Sequence[Dict[str, Any]],
    analysis_data: Dict[str, Any],
    policy: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    context = normalize_context_bindings(
        current_research=current_research,
        task_family=task_family,
        dataset=dataset,
        evaluation_source=evaluation_source,
    )
    if not policy["allow_synthesized_seed_ideas"] or policy["max_generated_ideas"] <= 0:
        return [], [], context

    generated: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    existing = existing_signatures(researcher_candidate_ideas)
    used_targets: set[str] = set()
    axis_map = {
        key: list(value) if isinstance(value, (list, tuple)) else [value]
        for key, value in (variant_spec.get("variant_axes") or {}).items()
    }
    components = contextual_component_pool(
        component_pool(researcher_candidate_ideas, analysis_data, improvement_bank),
        context,
    )
    if context.get("task_family_binding") == "unspecified" and analysis_data.get("config_binding_hints"):
        components = unique_preserving(["training-config", *components], limit=10)
    researcher_ideas = list(researcher_candidate_ideas)
    evaluation_tokens = context.get("evaluation_tokens", [])

    if researcher_ideas:
        for idea in researcher_ideas:
            for axis, axis_values in sorted(axis_map.items()):
                if len(generated) >= policy["max_generated_ideas"]:
                    break
                target_component = str(idea.get("target_component") or components[0] or "training-config")
                signature = (str(axis).lower(), str(target_component).lower())
                if signature in existing:
                    continue
                seed = axis_seed(
                    axis=axis,
                    axis_values=list(axis_values),
                    target_component=target_component,
                    source_support_hint=source_hint_for_component(target_component, improvement_bank, analysis_data),
                    feasibility_hint=feasibility_hint_for_scope(axis, variant_spec, analysis_data),
                    index=len(generated) + 1,
                    seed_origin="hybrid",
                    context=context,
                    campaign_idea_id=str(idea.get("id") or ""),
                )
                if broad_rewrite_risk(seed["change_scope"], seed["target_component"]):
                    rejected.append(reject_seed(seed, "broad-architecture-rewrite-risk"))
                    continue
                if eval_contract_risk(seed["target_component"], evaluation_tokens):
                    rejected.append(reject_seed(seed, "frozen-eval-contract-risk"))
                    continue
                if policy["require_diverse_targets"] and seed["target_component"] in used_targets:
                    rejected.append(reject_seed(seed, "diverse-targets-required"))
                    continue
                generated.append(seed)
                used_targets.add(seed["target_component"])
            if len(generated) >= policy["max_generated_ideas"]:
                break

    if len(generated) < policy["max_generated_ideas"]:
        for axis, axis_values in sorted(axis_map.items()):
            if len(generated) >= policy["max_generated_ideas"]:
                break
            target_component = next(
                (
                    component
                    for component in components
                    if not (policy["require_diverse_targets"] and component in used_targets)
                    and not eval_contract_risk(component, evaluation_tokens)
                ),
                components[0],
            )
            signature = (str(axis).lower(), str(target_component).lower())
            if signature in existing:
                continue
            seed = axis_seed(
                axis=axis,
                axis_values=list(axis_values),
                target_component=target_component,
                source_support_hint=source_hint_for_component(target_component, improvement_bank, analysis_data),
                feasibility_hint=feasibility_hint_for_scope(axis, variant_spec, analysis_data),
                index=len(generated) + 1,
                seed_origin="synthesized",
                context=context,
            )
            if broad_rewrite_risk(seed["change_scope"], seed["target_component"]):
                rejected.append(reject_seed(seed, "broad-architecture-rewrite-risk"))
                continue
            if eval_contract_risk(seed["target_component"], evaluation_tokens):
                rejected.append(reject_seed(seed, "frozen-eval-contract-risk"))
                continue
            if policy["require_diverse_targets"] and seed["target_component"] in used_targets:
                rejected.append(reject_seed(seed, "diverse-targets-required"))
                continue
            generated.append(seed)
            used_targets.add(seed["target_component"])

    if len(generated) < policy["max_generated_ideas"] and not axis_map:
        for component in components:
            if len(generated) >= policy["max_generated_ideas"]:
                break
            if eval_contract_risk(component, evaluation_tokens):
                continue
            seed = fallback_seed(
                target_component=component,
                source_support_hint=source_hint_for_component(component, improvement_bank, analysis_data),
                feasibility_hint="No explicit variant axis was provided, so this stays a repo-local bounded follow-up.",
                index=len(generated) + 1,
                context=context,
            )
            if policy["require_diverse_targets"] and seed["target_component"] in used_targets:
                rejected.append(reject_seed(seed, "diverse-targets-required"))
                continue
            generated.append(seed)
            used_targets.add(seed["target_component"])

    return generated, rejected, context


def diversity_summary(researcher_ideas: Sequence[Dict[str, Any]], generated: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    all_ideas = list(researcher_ideas) + list(generated)
    targets = unique_preserving([str(item.get("target_component") or "") for item in all_ideas if item.get("target_component")])
    scopes = unique_preserving([str(item.get("change_scope") or "") for item in all_ideas if item.get("change_scope")])
    by_origin: Dict[str, int] = {}
    for item in all_ideas:
        origin = str(item.get("seed_origin") or "researcher")
        by_origin[origin] = by_origin.get(origin, 0) + 1
    return {
        "unique_target_components": targets,
        "unique_change_scopes": scopes,
        "by_seed_origin": by_origin,
        "researcher_idea_count": len(researcher_ideas),
        "generated_idea_count": len(generated),
        "synthesized_idea_count": sum(1 for item in generated if item.get("seed_origin") == "synthesized"),
        "hybrid_idea_count": sum(1 for item in generated if item.get("seed_origin") == "hybrid"),
    }


def write_seed_artifact(
    output_dir: Path,
    *,
    policy: Dict[str, Any],
    researcher_ideas: Sequence[Dict[str, Any]],
    generated: Sequence[Dict[str, Any]],
    rejected: Sequence[Dict[str, Any]],
    diversity: Dict[str, Any],
) -> Path:
    payload = {
        "schema_version": "1.0",
        "generation_policy": policy,
        "researcher_ideas": list(researcher_ideas),
        "generated_ideas": list(generated),
        "all_seed_ideas": [*researcher_ideas, *generated],
        "diversity_summary": diversity,
        "rejected_seed_ideas": list(rejected),
    }
    path = output_dir / "IDEA_SEEDS.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_candidate_idea_generation_pass(
    *,
    analysis_output_dir: Path,
    current_research: str,
    task_family: str,
    dataset: Any,
    evaluation_source: Dict[str, Any],
    variant_spec: Dict[str, Any],
    analysis_data: Dict[str, Any],
    improvement_bank: Dict[str, Any],
    researcher_candidate_ideas: Sequence[Dict[str, Any]],
    idea_generation: Any,
) -> Dict[str, Any]:
    policy = normalize_policy(idea_generation)
    generated, rejected, context = build_generated_ideas(
        current_research=current_research,
        task_family=task_family,
        dataset=dataset,
        evaluation_source=evaluation_source,
        variant_spec=variant_spec,
        researcher_candidate_ideas=researcher_candidate_ideas,
        improvement_bank=improvement_bank.get("items", []),
        analysis_data=analysis_data,
        policy=policy,
    )
    diversity = diversity_summary(researcher_candidate_ideas, generated)
    path = write_seed_artifact(
        analysis_output_dir,
        policy=policy,
        researcher_ideas=researcher_candidate_ideas,
        generated=generated,
        rejected=rejected,
        diversity=diversity,
    )
    return {
        "schema_version": "1.0",
        "artifact_path": str(path),
        "generation_policy": policy,
        "researcher_ideas": list(researcher_candidate_ideas),
        "generated_ideas": generated,
        "all_seed_ideas": [*researcher_candidate_ideas, *generated],
        "diversity_summary": diversity,
        "rejected_seed_ideas": rejected,
        "context_bindings": {
            "context_anchor": context["context_anchor"],
            "task_family_binding": context["task_family_binding"],
            "dataset_binding": context["dataset_binding"],
            "evaluation_binding": context["evaluation_binding"],
        },
    }
