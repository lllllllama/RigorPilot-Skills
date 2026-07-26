"""Source module lookup and interface diff pass for ai-research-explore."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

from lookup.record_schema import normalize_evidence_class

ALLOWED_PATCH_CLASSES = {
    "config-only",
    "import-glue",
    "module-transplant-shim",
}


def first_items(values: Sequence[Any], limit: int) -> List[Any]:
    ordered: List[Any] = []
    for item in values:
        if item not in ordered:
            ordered.append(item)
        if len(ordered) >= limit:
            break
    return ordered


def select_source_record(selected_idea: Dict[str, Any], lookup_bundle: Dict[str, Any]) -> Dict[str, Any]:
    source_lookup = {item["source_id"]: item for item in lookup_bundle.get("records", [])}
    references = list(selected_idea.get("source_reference", []) or [])
    matched = [source_lookup[source_id] for source_id in references if source_id in source_lookup]
    for item in matched:
        if item.get("source_repo") and item.get("source_file") and item.get("source_symbol"):
            return item
    tokens: List[str] = []
    for raw in [
        str(selected_idea.get("summary") or ""),
        str(selected_idea.get("target_component") or ""),
        str(selected_idea.get("change_scope") or ""),
    ]:
        for token in re.split(r"[^a-z0-9]+", raw.lower()):
            if len(token) > 2 and token not in tokens:
                tokens.append(token)
    scored_candidates: List[tuple[int, int, float, Dict[str, Any]]] = []
    for item in lookup_bundle.get("records", []):
        if not (item.get("source_repo") and item.get("source_file") and item.get("source_symbol")):
            continue
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("query") or ""),
                str(item.get("source_repo") or ""),
                str(item.get("source_file") or ""),
                str(item.get("source_symbol") or ""),
            ]
        ).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            evidence = normalize_evidence_class(item.get("evidence_class"))
            evidence_priority = {
                "external_provider": 3,
                "parsed_locator": 2,
                "repo_local_extracted": 1,
                "seed_only": 0,
            }.get(evidence, 0)
            scored_candidates.append((score, evidence_priority, float(item.get("evidence_weight") or 0.0), item))
    scored_candidates.sort(key=lambda pair: (-pair[0], -pair[1], -pair[2], pair[3].get("source_id", "")))
    if scored_candidates:
        return scored_candidates[0][3]
    return matched[0] if matched else {}


def source_blockers(source_record: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if not source_record.get("source_repo"):
        blockers.append("missing-source-repo")
    if not source_record.get("source_file"):
        blockers.append("missing-source-file")
    if not source_record.get("source_symbol"):
        blockers.append("missing-source-symbol")
    return blockers


def normalize_patch_class(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in ALLOWED_PATCH_CLASSES else ""


def best_target_symbol(selected_idea: Dict[str, Any], analysis_data: Dict[str, Any]) -> str:
    component = str(selected_idea.get("target_component") or "").lower()
    for item in analysis_data.get("constructor_candidates", []):
        if component and component in str(item).lower():
            return str(item)
    for item in analysis_data.get("forward_candidates", []):
        if component and component in str(item).lower():
            return str(item)
    for item in first_items(analysis_data.get("constructor_candidates", []), 1):
        return str(item)
    for item in first_items(analysis_data.get("forward_candidates", []), 1):
        return str(item)
    return "unspecified-symbol"


def build_target_location_map(
    selected_idea: Dict[str, Any],
    analysis_data: Dict[str, Any],
    code_plan: Dict[str, Any],
) -> List[Dict[str, Any]]:
    target_symbol = best_target_symbol(selected_idea, analysis_data)
    config_hints = list(analysis_data.get("config_binding_hints", []))
    target_component = str(selected_idea.get("target_component") or "").lower()
    prefer_config_only = "config" in target_component
    results: List[Dict[str, Any]] = []
    candidate_paths = first_items(code_plan.get("candidate_edit_targets", []), 4)
    if not config_hints:
        config_hints = [
            path
            for path in candidate_paths
            if any(token in str(path).lower() for token in ("config", ".yaml", ".yml", ".json", ".toml", ".ini"))
        ]
    if prefer_config_only and config_hints:
        candidate_paths = first_items(
            [path for path in candidate_paths if path in config_hints] or list(config_hints),
            4,
        )
    for path in candidate_paths:
        results.append(
            {
                "file": path,
                "target_symbol": target_symbol,
                "role": "config" if path in config_hints else "code",
                "reason": f"Selected for `{selected_idea.get('change_scope', 'candidate change')}` with target component `{selected_idea.get('target_component', 'unspecified')}`.",
            }
        )
    return results


def build_module_candidates(
    selected_idea: Dict[str, Any],
    lookup_bundle: Dict[str, Any],
    analysis_data: Dict[str, Any],
    code_plan: Dict[str, Any],
) -> List[Dict[str, Any]]:
    target_location_map = build_target_location_map(selected_idea, analysis_data, code_plan)
    target_symbol = target_location_map[0]["target_symbol"] if target_location_map else "unspecified-symbol"
    module_files = analysis_data.get("module_files", []) or code_plan.get("candidate_edit_targets", [])
    source_record = select_source_record(selected_idea, lookup_bundle)
    source_reference = [source_record.get("source_id")] if source_record.get("source_id") else []
    transplant_ready = not source_blockers(source_record)
    candidates: List[Dict[str, Any]] = []
    for path in first_items(module_files, 3):
        candidates.append(
            {
                "idea_id": selected_idea.get("id"),
                "source_repo": (source_record or {}).get("source_repo") or code_plan.get("source_repo_refs", [{}])[0].get("repo", "current-research"),
                "source_reference": source_reference,
                "source_file": (source_record or {}).get("source_file") or "",
                "source_symbol": (source_record or {}).get("source_symbol") or "",
                "target_file": path,
                "target_symbol": target_symbol,
                "supporting_files": first_items(analysis_data.get("config_binding_hints", []), 3),
                "source_triple_ready": transplant_ready,
                "why_fit": (
                    f"`{path}` is in the allowed change zone and matches `{selected_idea.get('target_component', 'component')}`."
                    if transplant_ready
                    else "The target location is plausible, but the source transplant triple is incomplete."
                ),
                "why_not_fit": (
                    "Keep the patch reversible and avoid changing evaluation or leaderboard parsing files."
                    if transplant_ready
                    else f"Transplant path blocked: {', '.join(source_blockers(source_record))}."
                ),
            }
        )
    return candidates


def build_interface_diff(
    selected_idea: Dict[str, Any],
    analysis_data: Dict[str, Any],
    module_candidates: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    transplant_ready = bool(module_candidates[0].get("source_triple_ready")) if module_candidates else False
    return {
        "selected_idea": selected_idea.get("id"),
        "transplant_ready": transplant_ready,
        "constructor_surface": first_items(analysis_data.get("constructor_candidates", []), 6),
        "forward_surface": first_items(analysis_data.get("forward_candidates", []), 6),
        "config_surface": first_items(analysis_data.get("config_binding_hints", []), 6),
        "metric_surface": first_items(analysis_data.get("metric_files", []), 4),
        "required_shims": [
            "Keep constructor wiring mechanical and reversible.",
            "Prefer import/registry glue over behavioral rewrites.",
            "Preserve frozen evaluation and metric parsing surfaces.",
            *(
                []
                if transplant_ready
                else ["Do not enter the transplant path until source_repo + source_file + source_symbol are all present."]
            ),
        ],
        "candidate_targets": [item["target_file"] for item in module_candidates],
    }


def build_minimal_patch_plan(
    selected_idea: Dict[str, Any],
    target_location_map: Sequence[Dict[str, Any]],
    interface_diff: Dict[str, Any],
    selected_source_record: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not target_location_map:
        return []
    plan: List[Dict[str, Any]] = []
    config_targets = [item for item in target_location_map if item["role"] == "config"]
    code_targets = [item for item in target_location_map if item["role"] == "code"]
    triple_blockers = source_blockers(selected_source_record)
    if config_targets:
        plan.append(
            {
                "change_type": "config-only",
                "target_files": [item["file"] for item in config_targets],
                "rationale": f"Expose `{selected_idea.get('change_scope', 'candidate change')}` through existing config bindings.",
                "rollback": "Revert config keys to the baseline values.",
                "smoke_checks": ["config-path", "short-run-command"],
            }
        )
    if code_targets and not triple_blockers:
        plan.append(
            {
                "change_type": "import-glue",
                "target_files": [code_targets[0]["file"]],
                "rationale": "Wire the candidate module through the smallest registry or import boundary.",
                "rollback": "Remove the candidate import and restore the baseline registry entry.",
                "smoke_checks": ["syntax-parse", "import-resolution", "constructor-surface"],
            }
        )
        plan.append(
            {
                "change_type": "module-transplant-shim",
                "target_files": [code_targets[0]["file"]],
                "rationale": "Add a thin compatibility shim only if constructor/forward surfaces do not match.",
                "rollback": "Delete the shim and point the call-site back to the baseline module.",
                "smoke_checks": ["forward-surface", "short-run-command"],
            }
        )
    elif code_targets and triple_blockers:
        plan.append(
            {
                "change_type": "transplant-blocked",
                "target_files": [code_targets[0]["file"]],
                "rationale": "Do not enter the transplant path until source_repo + source_file + source_symbol are all available.",
                "rollback": "No-op; keep the baseline module path unchanged.",
                "smoke_checks": ["static-smoke-only"],
                "blockers": triple_blockers,
            }
        )
    if interface_diff.get("metric_surface"):
        plan.append(
            {
                "change_type": "protected-zone-no-touch",
                "target_files": interface_diff["metric_surface"],
                "rationale": "Metric and leaderboard surfaces are protected unless the campaign explicitly allows them.",
                "rollback": "No-op; these files should remain unchanged.",
                "smoke_checks": ["metric-surface-protected"],
            }
        )
    return plan


def build_smoke_plan(
    selected_idea: Dict[str, Any],
    target_location_map: Sequence[Dict[str, Any]],
    variant_matrix: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return [
        {
            "name": "syntax-parse",
            "scope": [item["file"] for item in target_location_map if item["file"].endswith(".py")],
            "reason": "Candidate patch must keep Python files parseable.",
        },
        {
            "name": "import-resolution",
            "scope": [item["file"] for item in target_location_map if item["file"].endswith(".py")],
            "reason": "Candidate patch must not break module loading paths.",
        },
        {
            "name": "config-path",
            "scope": [item["file"] for item in target_location_map if item["role"] == "config"],
            "reason": "Frozen command/config references must still resolve.",
        },
        {
            "name": "constructor-surface",
            "scope": [str(selected_idea.get("target_component") or "candidate-component")],
            "reason": "Constructor wiring should remain mechanical and reversible.",
        },
        {
            "name": "forward-surface",
            "scope": [str(selected_idea.get("target_component") or "candidate-component")],
            "reason": "Forward path should stay single-variable and attribution-friendly.",
        },
        {
            "name": "short-run-command",
            "scope": [str(variant_matrix.get("base_command") or "no-base-command")],
            "reason": "Use short-run smoke before any broader candidate run.",
        },
    ]


def resolve_patch_class(
    selected_idea: Dict[str, Any],
    minimal_patch_plan: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    change_types = {str(item.get("change_type") or "") for item in minimal_patch_plan}
    requested_patch_class = normalize_patch_class(selected_idea.get("patch_class"))
    # A researcher-requested class the plan can satisfy must not be escalated
    # to the transplant path (which demands a full source triple); per
    # source-mapping-policy, config-only stays the least invasive choice.
    if requested_patch_class and requested_patch_class in change_types:
        return {
            "requested_patch_class": requested_patch_class,
            "resolved_patch_class": requested_patch_class,
            "patch_class_source": "campaign",
            "requires_source_triple": requested_patch_class == "module-transplant-shim",
        }
    if "module-transplant-shim" in change_types or "transplant-blocked" in change_types:
        return {
            "requested_patch_class": requested_patch_class,
            "resolved_patch_class": "module-transplant-shim",
            "patch_class_source": "source-mapping",
            "requires_source_triple": True,
        }
    if "import-glue" in change_types:
        return {
            "requested_patch_class": requested_patch_class,
            "resolved_patch_class": "import-glue",
            "patch_class_source": "source-mapping",
            "requires_source_triple": False,
        }
    return {
        "requested_patch_class": requested_patch_class,
        "resolved_patch_class": requested_patch_class or "config-only",
        "patch_class_source": "campaign" if requested_patch_class else "source-mapping",
        "requires_source_triple": False,
    }


def write_module_candidates(output_dir: Path, module_candidates: Sequence[Dict[str, Any]]) -> Path:
    lines = [
        "# Module Candidates",
        "",
    ]
    if not module_candidates:
        lines.append("- None.")
    else:
        for item in module_candidates:
            lines.extend(
                [
                    f"## {item['idea_id']} -> {item['target_file']}",
                    "",
                    f"- Source repo: `{item['source_repo']}`",
                    f"- Source file: `{item['source_file']}`",
                    f"- Source symbol: `{item['source_symbol']}`",
                    f"- Target symbol: `{item['target_symbol']}`",
                    f"- Supporting files: {', '.join(item['supporting_files']) or 'none'}",
                    f"- Why fit: {item['why_fit']}",
                    f"- Why not fit: {item['why_not_fit']}",
                    "",
                ]
            )
    path = output_dir / "MODULE_CANDIDATES.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_interface_diff(output_dir: Path, interface_diff: Dict[str, Any]) -> Path:
    constructor_surface = [f"- {item}" for item in interface_diff.get("constructor_surface", [])] or ["- none"]
    forward_surface = [f"- {item}" for item in interface_diff.get("forward_surface", [])] or ["- none"]
    config_surface = [f"- {item}" for item in interface_diff.get("config_surface", [])] or ["- none"]
    required_shims = [f"- {item}" for item in interface_diff.get("required_shims", [])] or ["- none"]
    lines = [
        "# Interface Diff",
        "",
        f"- Selected idea: `{interface_diff.get('selected_idea', 'none')}`",
        "",
        "## Constructor Surface",
        "",
        *constructor_surface,
        "",
        "## Forward Surface",
        "",
        *forward_surface,
        "",
        "## Config Surface",
        "",
        *config_surface,
        "",
        "## Required Shims",
        "",
        *required_shims,
        "",
    ]
    path = output_dir / "INTERFACE_DIFF.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_source_mapping_pass(
    *,
    analysis_output_dir: Path,
    selected_idea: Dict[str, Any],
    analysis_data: Dict[str, Any],
    code_plan: Dict[str, Any],
    lookup_bundle: Dict[str, Any],
    variant_matrix: Dict[str, Any],
) -> Dict[str, Any]:
    target_location_map = build_target_location_map(selected_idea, analysis_data, code_plan)
    selected_source_record = select_source_record(selected_idea, lookup_bundle)
    module_candidates = build_module_candidates(selected_idea, lookup_bundle, analysis_data, code_plan)
    interface_diff = build_interface_diff(selected_idea, analysis_data, module_candidates)
    minimal_patch_plan = build_minimal_patch_plan(selected_idea, target_location_map, interface_diff, selected_source_record)
    smoke_plan = build_smoke_plan(selected_idea, target_location_map, variant_matrix)
    patch_class = resolve_patch_class(selected_idea, minimal_patch_plan)
    module_candidates_path = write_module_candidates(analysis_output_dir, module_candidates)
    interface_diff_path = write_interface_diff(analysis_output_dir, interface_diff)
    return {
        "schema_version": "1.0",
        "artifact_paths": [str(module_candidates_path), str(interface_diff_path)],
        "selected_source_record": selected_source_record or {},
        "transplant_ready": not source_blockers(selected_source_record),
        "source_blockers": source_blockers(selected_source_record),
        "target_location_map": target_location_map,
        "supporting_changes": code_plan.get("supporting_changes", []),
        "patch_surface_summary": code_plan.get("patch_surface_summary", {}),
        "module_candidates": module_candidates,
        "interface_diff": interface_diff,
        "minimal_patch_plan": minimal_patch_plan,
        "smoke_plan": smoke_plan,
        "requested_patch_class": patch_class["requested_patch_class"],
        "resolved_patch_class": patch_class["resolved_patch_class"],
        "patch_class_source": patch_class["patch_class_source"],
        "requires_source_triple": patch_class["requires_source_triple"],
    }

