#!/usr/bin/env python3
"""Build a conservative exploratory code-change plan."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


SKIP_PARTS = {
    "__pycache__",
    ".git",
    "repro_outputs",
    "train_outputs",
    "analysis_outputs",
    "debug_outputs",
    "explore_outputs",
    "tmp",
}

CODE_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml", ".ini"}
MODEL_PATTERN = re.compile(r"(model|network|backbone|encoder|decoder|adapter|lora|head|loss)", re.IGNORECASE)
TRAIN_PATTERN = re.compile(r"(train|trainer|optim|loss|config)", re.IGNORECASE)
TASK_KEYWORDS = {
    "classification": ("class", "imagenet", "knn", "linear", "log_regression"),
    "segmentation": ("seg", "segment", "mask", "ade20k", "m2f", "mask2former"),
    "detection": ("det", "detect", "detr", "coco", "box"),
    "depth": ("depth", "nyu", "dpt", "depther"),
    "text": ("text", "token", "clip", "dinotxt"),
    "pretrain": ("pretrain", "ssl", "teacher", "student", "gram", "distillation"),
}
COMMON_TOKENS = {"py", "yaml", "yml", "json", "toml", "ini", "run", "train", "eval", "config", "configs"}


def load_variant_spec(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).resolve().read_text(encoding="utf-8-sig"))


def load_structured_payload(path: str) -> Any:
    if not path:
        return {}
    return json.loads(Path(path).resolve().read_text(encoding="utf-8-sig"))


def normalize_task_family(value: Any) -> str:
    return str(value or "").strip().lower()


def focus_tokens(current_research: str, task_family: str) -> List[str]:
    tokens: List[str] = []
    for part in re.split(r"[^a-zA-Z0-9]+", current_research.lower()):
        if part and part not in COMMON_TOKENS and len(part) > 2:
            tokens.append(part)
    if task_family:
        tokens.append(task_family)
        tokens.extend(TASK_KEYWORDS.get(task_family, ()))
    ordered: List[str] = []
    for token in tokens:
        if token not in ordered:
            ordered.append(token)
    return ordered[:20]


def score_path(rel: str, task_family: str, tokens: List[str]) -> int:
    score = 0
    if MODEL_PATTERN.search(rel):
        score += 5
    if TRAIN_PATTERN.search(rel):
        score += 3
    if rel.endswith(".py"):
        score += 1
    lower = rel.lower()
    for token in TASK_KEYWORDS.get(task_family, ()):
        if token in lower:
            score += 4
    for token in tokens:
        if token in lower:
            score += 2
    if current_research_dir(rel, tokens):
        score += 3
    return score


def current_research_dir(rel: str, tokens: List[str]) -> bool:
    lower = rel.lower()
    slash_hits = [token for token in tokens if token in lower]
    return len(slash_hits) >= 2


def collect_candidate_edit_targets(repo: Path, current_research: str, task_family: str) -> List[str]:
    tokens = focus_tokens(current_research, task_family)
    scored: List[tuple[int, str]] = []
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(repo).parts):
            continue
        if path.suffix.lower() not in CODE_SUFFIXES:
            continue
        rel = path.relative_to(repo).as_posix()
        score = score_path(rel, task_family, tokens)
        if score:
            scored.append((score, rel))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [rel for _, rel in scored[:8]]


def select_idea_card(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            return first
    return {}


def derive_target_location_map(targets: List[str], idea_card: Dict[str, Any], analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    config_hints = analysis.get("config_binding_hints", [])
    constructor_candidates = analysis.get("constructor_candidates", [])
    target_symbol = constructor_candidates[0] if constructor_candidates else (analysis.get("forward_candidates", []) or ["unspecified-symbol"])[0]
    results: List[Dict[str, Any]] = []
    for path in targets[:4]:
        results.append(
            {
                "file": path,
                "role": "config" if path in config_hints else "code",
                "target_symbol": target_symbol,
                "reason": f"Maps `{idea_card.get('change_scope', 'candidate change')}` into `{idea_card.get('target_component', 'unspecified')}`.",
            }
        )
    return results


def derive_supporting_changes(spec: Dict[str, Any], idea_card: Dict[str, Any], analysis: Dict[str, Any]) -> List[str]:
    changes: List[str] = []
    for item in idea_card.get("supporting_changes", []) or []:
        if item not in changes:
            changes.append(str(item))
    for path in analysis.get("config_binding_hints", [])[:2]:
        changes.append(f"Review config binding in `{path}` for reversible wiring.")
    for axis in sorted((spec.get("variant_axes") or {}).keys())[:2]:
        changes.append(f"Keep `{axis}` plumbed through existing config or CLI surfaces.")
    unique: List[str] = []
    for item in changes:
        if item not in unique:
            unique.append(item)
    return unique[:6]


def derive_patch_surface_summary(target_location_map: List[Dict[str, Any]], supporting_changes: List[str]) -> Dict[str, Any]:
    code_targets = [item for item in target_location_map if item["role"] == "code"]
    config_targets = [item for item in target_location_map if item["role"] == "config"]
    surface_score = min(1.0, 0.15 + 0.10 * len(code_targets) + 0.05 * len(config_targets) + 0.04 * len(supporting_changes))
    return {
        "surface_score": round(surface_score, 4),
        "code_target_count": len(code_targets),
        "config_target_count": len(config_targets),
        "summary": f"{len(code_targets)} code target(s), {len(config_targets)} config target(s), {len(supporting_changes)} supporting change(s).",
    }


def derive_minimal_patch_plan(
    target_location_map: List[Dict[str, Any]],
    idea_card: Dict[str, Any],
    analysis: Dict[str, Any],
) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    config_targets = [item["file"] for item in target_location_map if item["role"] == "config"]
    code_targets = [item["file"] for item in target_location_map if item["role"] == "code"]
    if config_targets:
        plan.append(
            {
                "change_type": "config-only",
                "target_files": config_targets,
                "rollback": "Revert the config override or remove the added config key.",
                "rationale": f"Expose `{idea_card.get('change_scope', 'candidate change')}` through frozen config surfaces first.",
            }
        )
    if code_targets:
        plan.append(
            {
                "change_type": "import-glue",
                "target_files": [code_targets[0]],
                "rollback": "Remove the import/registry entry and restore the baseline route.",
                "rationale": "Keep wiring mechanical before any behavioral shim.",
            }
        )
        plan.append(
            {
                "change_type": "module-transplant-shim",
                "target_files": [code_targets[0]],
                "rollback": "Delete the shim and return the call-site to the baseline symbol.",
                "rationale": "Only add a thin shim if constructor or forward surfaces do not already match.",
            }
        )
    protected = analysis.get("metric_files", [])[:2]
    if protected:
        plan.append(
            {
                "change_type": "protected-zone-no-touch",
                "target_files": protected,
                "rollback": "No-op; evaluation and metric files should remain unchanged.",
                "rationale": "Preserve metric and leaderboard semantics unless the campaign explicitly allows mutation.",
            }
        )
    return plan


def derive_smoke_validation_plan(
    target_location_map: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    spec: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return [
        {
            "name": "syntax-parse",
            "scope": [item["file"] for item in target_location_map if item["file"].endswith(".py")],
            "status": "planned",
        },
        {
            "name": "import-resolution",
            "scope": [item["file"] for item in target_location_map if item["file"].endswith(".py")],
            "status": "planned",
        },
        {
            "name": "config-path",
            "scope": [item["file"] for item in target_location_map if item["role"] == "config"],
            "status": "planned",
        },
        {
            "name": "constructor-surface",
            "scope": analysis.get("constructor_candidates", [])[:4],
            "status": "planned",
        },
        {
            "name": "forward-surface",
            "scope": analysis.get("forward_candidates", [])[:4],
            "status": "planned",
        },
        {
            "name": "short-run-command",
            "scope": [str(spec.get("base_command") or "")],
            "status": "planned",
        },
    ]


def build_code_tracks(spec: Dict[str, Any], targets: List[str], task_family: str, current_research: str) -> List[str]:
    tracks: List[str] = []
    if task_family:
        tracks.append(f"Stay anchored to the `{task_family}` task family while planning exploratory edits.")
    tracks.append(f"Preserve `{current_research}` as the comparison anchor for all code changes.")

    for axis, values in sorted((spec.get("variant_axes") or {}).items()):
        if not isinstance(values, (list, tuple)):
            values = [values]
        shown_values = ", ".join(str(value) for value in values[:3])
        tracks.append(f"Review code touchpoints for `{axis}` variation across: {shown_values}.")

    if targets:
        tracks.append(f"Inspect candidate model files first: {', '.join(targets[:3])}.")

    if spec.get("base_command"):
        tracks.append(f"Keep `{spec['base_command']}` aligned with any exploratory code path changes.")

    tracks.extend(
        [
            "Prefer one reversible module-level adaptation before broader rewrites.",
            "Keep config and entrypoint changes coupled so candidate runs remain attributable.",
        ]
    )
    return tracks[:6]


def build_payload(
    repo: Path,
    current_research: str,
    experiment_branch: str,
    spec: Dict[str, Any],
    task_family: str,
    idea_card: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    candidate_targets = collect_candidate_edit_targets(repo, current_research, task_family)
    target_location_map = derive_target_location_map(candidate_targets, idea_card, analysis)
    supporting_changes = derive_supporting_changes(spec, idea_card, analysis)
    patch_surface_summary = derive_patch_surface_summary(target_location_map, supporting_changes)
    minimal_patch_plan = derive_minimal_patch_plan(target_location_map, idea_card, analysis)
    smoke_validation_plan = derive_smoke_validation_plan(target_location_map, analysis, spec)
    code_tracks = build_code_tracks(spec, candidate_targets, task_family, current_research)
    return {
        "schema_version": "1.0",
        "repo": str(repo.resolve()),
        "current_research": current_research,
        "task_family": task_family or None,
        "experiment_branch": experiment_branch,
        "candidate_edit_targets": candidate_targets,
        "target_location_map": target_location_map,
        "supporting_changes": supporting_changes,
        "patch_surface_summary": patch_surface_summary,
        "minimal_patch_plan": minimal_patch_plan,
        "smoke_validation_plan": smoke_validation_plan,
        "proposed_code_tracks": code_tracks,
        "source_repo_refs": [
            {
                "repo": repo.name,
                "ref": current_research,
                "note": "current_research anchor for exploratory code changes",
            }
        ],
        "notes": [
            "Exploratory code plan only; candidate-level changes should stay isolated from the trusted baseline.",
            "Inspect candidate model files before introducing adapter or head changes.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a conservative exploratory code-change plan.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--current-research", required=True, help="Durable identifier for the current research context.")
    parser.add_argument("--experiment-branch", required=True, help="Isolated experiment branch label.")
    parser.add_argument("--variant-spec-json", default="", help="Optional path to the variant-spec JSON file.")
    parser.add_argument("--task-family", default="", help="Optional task-family hint used to focus candidate edit targets.")
    parser.add_argument("--idea-card-json", default="", help="Optional path to a selected idea-card JSON object or list.")
    parser.add_argument("--analysis-json", default="", help="Optional path to an analysis JSON object for richer structural hints.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    idea_card = select_idea_card(load_structured_payload(args.idea_card_json))
    analysis = load_structured_payload(args.analysis_json)
    payload = build_payload(
        repo,
        args.current_research,
        args.experiment_branch,
        load_variant_spec(args.variant_spec_json),
        normalize_task_family(args.task_family),
        idea_card,
        analysis if isinstance(analysis, dict) else {},
    )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Current research: {payload['current_research']}")
        print(f"Task family: {payload.get('task_family') or 'unspecified'}")
        print(f"Experiment branch: {payload['experiment_branch']}")
        print("Candidate edit targets:", ", ".join(payload["candidate_edit_targets"]) or "none")
        print("Proposed code tracks:")
        for line in payload["proposed_code_tracks"]:
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
