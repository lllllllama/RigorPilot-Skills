#!/usr/bin/env python3
"""Plan or execute explicit exploratory research work on top of current_research."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from passes import (
    run_atomic_idea_decomposition_pass,
    run_candidate_idea_generation_pass,
    run_execution_feasibility_pass,
    run_idea_card_pass,
    run_idea_ranking_pass,
    run_implementation_fidelity_pass,
    run_improvement_bank_pass,
    run_lookup_pass,
    run_source_mapping_pass,
)


DURABLE_ANCHOR_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
EXTERNAL_REFERENCE_PREFIXES = ("run:", "checkpoint:", "branch:", "commit:", "model:", "state:")
DEFAULT_BASELINE_GATE = {
    "maximize": {"borderline_gap": 1.0, "abandon_gap": 2.0},
    "minimize": {"borderline_relative_gap": 0.02, "abandon_relative_gap": 0.05},
}
DEFAULT_EXECUTION_POLICY = {
    "run_selected_variants": False,
    "max_executed_variants": 1,
    "variant_timeout": 60,
    "run_full_after_short_run": False,
}
DEFAULT_IDEA_GENERATION_POLICY = {
    "allow_synthesized_seed_ideas": True,
    "max_generated_ideas": 3,
    "require_diverse_targets": True,
}


def run_json(script: Path, args: List[str]) -> Dict[str, Any]:
    result = subprocess.run([sys.executable, str(script), *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def run_text(command: List[str], cwd: Optional[Path] = None) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return result.stdout.strip()


def write_bundle(script: Path, output_dir: Path, context: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        context_path = Path(handle.name)
        handle.write(json.dumps(context, indent=2, ensure_ascii=False))

    try:
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--context-json",
                str(context_path),
                "--output-dir",
                str(output_dir),
            ],
            check=True,
        )
    finally:
        if context_path.exists():
            context_path.unlink()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "current-research"


def choose_experiment_branch(current_research: str, explicit_branch: str) -> str:
    if explicit_branch:
        return explicit_branch
    return f"exp/ai-research-explore-{slugify(current_research)}"


def maybe_git_root(repo_path: Path) -> Optional[Path]:
    try:
        return Path(run_text(["git", "rev-parse", "--show-toplevel"], cwd=repo_path)).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def build_context_id(current_research: str, experiment_branch: str) -> str:
    digest = hashlib.sha1(f"{current_research}::{experiment_branch}".encode("utf-8")).hexdigest()[:12]
    return f"ai-research-explore-{digest}"


def experiment_worktree_root(git_root: Path, experiment_branch: str) -> Path:
    base_dir = git_root.parent / f".{git_root.name}-explore-worktrees" / slugify(experiment_branch)
    return base_dir / git_root.name


def validate_current_research(repo_path: Path, current_research: str) -> Dict[str, Any]:
    value = current_research.strip()
    if not value:
        raise ValueError("`current_research` is required.")

    literal_path = Path(value)
    if literal_path.is_absolute() and literal_path.exists():
        return {"kind": "path", "value": value, "resolved_path": str(literal_path.resolve())}

    repo_relative = (repo_path / value).resolve()
    if repo_relative.exists():
        return {"kind": "repo-path", "value": value, "resolved_path": str(repo_relative)}

    git_root = maybe_git_root(repo_path)
    if git_root:
        try:
            resolved_ref = run_text(["git", "rev-parse", "--verify", f"{value}^{{commit}}"], cwd=git_root)
            return {
                "kind": "git-ref",
                "value": value,
                "resolved_ref": resolved_ref,
                "git_root": str(git_root),
            }
        except subprocess.CalledProcessError:
            pass

    if "@" in value:
        left, _, right = value.partition("@")
        if left and right and (
            DURABLE_ANCHOR_HASH_RE.fullmatch(right.strip())
            or any(right.strip().startswith(prefix) for prefix in EXTERNAL_REFERENCE_PREFIXES)
        ):
            return {"kind": "named-anchor", "value": value}

    raise ValueError(
        "`current_research` should map to a durable branch, commit, checkpoint, run record, or trained model state."
    )


def validate_existing_worktree(worktree_root: Path, expected_branch: str) -> Dict[str, Any]:
    actual_root = Path(run_text(["git", "rev-parse", "--show-toplevel"], cwd=worktree_root)).resolve()
    actual_branch = run_text(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=worktree_root)
    if actual_root != worktree_root.resolve():
        raise ValueError(f"Existing experiment workspace `{worktree_root}` is not a valid git worktree root.")
    if actual_branch != expected_branch:
        raise ValueError(
            f"Existing experiment workspace `{worktree_root}` is on branch `{actual_branch}`, expected `{expected_branch}`."
        )
    return {
        "workspace_root": str(actual_root),
        "worktree_root": str(actual_root),
        "mode": "worktree",
    }


def ensure_experiment_workspace(repo_path: Path, experiment_branch: str) -> Dict[str, Any]:
    git_root = maybe_git_root(repo_path)
    if git_root is None:
        raise ValueError("Explore orchestration requires a git repository so the isolated experiment branch can be created.")

    head_sha = run_text(["git", "rev-parse", "HEAD"], cwd=git_root)
    try:
        current_branch = run_text(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=git_root)
    except subprocess.CalledProcessError:
        current_branch = "DETACHED"

    branch_ref = f"refs/heads/{experiment_branch}"
    created_branch = False
    try:
        branch_sha = run_text(["git", "rev-parse", "--verify", branch_ref], cwd=git_root)
        branch_exists = True
    except subprocess.CalledProcessError:
        branch_sha = head_sha
        branch_exists = False

    if current_branch == experiment_branch:
        isolated_workspace = experiment_branch.startswith(("exp/", "explore/"))
        return {
            "mode": "branch",
            "workspace_root": str(git_root),
            "worktree_root": None,
            "branch": experiment_branch,
            "branch_ref": branch_ref,
            "branch_sha": branch_sha,
            "head_sha": head_sha,
            "current_branch": current_branch,
            "created_branch": created_branch,
            "isolated_workspace": isolated_workspace,
        }

    worktree_root = experiment_worktree_root(git_root, experiment_branch)
    if worktree_root.exists():
        worktree_info = validate_existing_worktree(worktree_root, experiment_branch)
    else:
        worktree_root.parent.mkdir(parents=True, exist_ok=True)
        if branch_exists:
            run_text(["git", "worktree", "add", str(worktree_root), experiment_branch], cwd=git_root)
        else:
            run_text(["git", "worktree", "add", "-b", experiment_branch, str(worktree_root), head_sha], cwd=git_root)
            created_branch = True
        branch_sha = run_text(["git", "rev-parse", "--verify", branch_ref], cwd=git_root)
        worktree_info = validate_existing_worktree(worktree_root, experiment_branch)

    return {
        "mode": worktree_info["mode"],
        "workspace_root": worktree_info["workspace_root"],
        "worktree_root": worktree_info["worktree_root"],
        "branch": experiment_branch,
        "branch_ref": branch_ref,
        "branch_sha": branch_sha,
        "head_sha": head_sha,
        "current_branch": current_branch,
        "created_branch": created_branch,
        "isolated_workspace": True,
    }


def normalize_task_family(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text or None


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def clamp_score(value: Optional[float], default: float = 0.5) -> float:
    if value is None:
        return default
    return max(0.0, min(1.0, float(value)))


def normalize_metric_goal(value: Any) -> str:
    text = str(value or "maximize").strip().lower()
    if text in {"min", "minimize", "lower", "lower_is_better"}:
        return "minimize"
    return "maximize"


def load_structured_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError("YAML input requires PyYAML to be installed.") from exc
        payload = yaml.safe_load(text) or {}
    else:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Structured input `{path}` must contain a top-level object.")
    return payload


def normalize_variant_spec(spec: Dict[str, Any], current_research: str) -> Dict[str, Any]:
    normalized = dict(spec)
    explicit_value = normalized.get("current_research") or normalized.get("baseline_ref")
    if explicit_value and explicit_value != current_research:
        raise ValueError(
            f"Variant spec current research `{explicit_value}` does not match current_research `{current_research}`."
        )
    normalized["current_research"] = current_research
    normalized.setdefault("baseline_ref", current_research)
    # Explicit nulls, empty lists, and scalar axis values are all valid-looking
    # campaign inputs; coerce them so downstream passes never see a non-list.
    raw_axes = normalized.get("variant_axes") or {}
    normalized["variant_axes"] = {
        key: list(value) if isinstance(value, (list, tuple)) else [value]
        for key, value in raw_axes.items()
    }
    normalized["subset_sizes"] = list(normalized.get("subset_sizes") or [None])
    normalized["short_run_steps"] = list(normalized.get("short_run_steps") or [None])
    return normalized


def load_variant_spec(path: Path, current_research: str) -> Dict[str, Any]:
    return normalize_variant_spec(load_structured_file(path), current_research)


def normalize_evaluation_source(raw: Any, variant_spec: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw, str):
        source = {"command": raw}
    elif isinstance(raw, dict):
        source = dict(raw)
    else:
        source = {}

    primary_metric = source.get("primary_metric") or variant_spec.get("primary_metric")
    metric_goal = normalize_metric_goal(source.get("metric_goal") or variant_spec.get("metric_goal"))
    execution_kind = str(source.get("execution_kind") or "").strip().lower()
    return {
        "command": str(source.get("command") or ""),
        "path": str(source.get("path") or ""),
        "primary_metric": primary_metric,
        "metric_goal": metric_goal,
        "execution_kind": execution_kind or None,
        "artifacts": list(source.get("artifacts", []) or []),
        "notes": list(source.get("notes", []) or []),
        "split": str(source.get("split") or ""),
    }


def bind_evaluation_command_to_variant_spec(
    variant_spec: Dict[str, Any],
    evaluation_source: Dict[str, Any],
) -> Dict[str, Any]:
    if variant_spec.get("base_command") or not evaluation_source.get("command"):
        return variant_spec

    normalized = dict(variant_spec)
    normalized["base_command"] = str(evaluation_source["command"]).strip()
    normalized["base_command_source"] = "evaluation_source"
    if evaluation_source.get("primary_metric") and not normalized.get("primary_metric"):
        normalized["primary_metric"] = evaluation_source["primary_metric"]
    if evaluation_source.get("metric_goal") and not normalized.get("metric_goal"):
        normalized["metric_goal"] = evaluation_source["metric_goal"]
    if evaluation_source.get("execution_kind") and not normalized.get("execution_kind"):
        normalized["execution_kind"] = evaluation_source["execution_kind"]
    return normalized


def normalize_sota_reference(items: Any, primary_metric: Optional[str], metric_goal: str) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, (int, float)):
            normalized.append(
                {
                    "id": f"sota-{index:03d}",
                    "name": f"SOTA reference {index}",
                    "metric": primary_metric,
                    "metric_goal": metric_goal,
                    "value": float(item),
                    "source": "",
                    "notes": "",
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        value = safe_float(item.get("value"))
        if value is None:
            continue
        normalized.append(
            {
                "id": str(item.get("id") or f"sota-{index:03d}"),
                "name": str(item.get("name") or item.get("paper") or f"SOTA reference {index}"),
                "metric": str(item.get("metric") or primary_metric or ""),
                "metric_goal": normalize_metric_goal(item.get("metric_goal") or metric_goal),
                "value": value,
                "source": str(item.get("source") or item.get("url") or ""),
                "notes": str(item.get("notes") or ""),
            }
        )
    return normalized


def normalize_compute_budget(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    budget = dict(raw)
    if "max_runtime_hours" in budget:
        runtime = safe_float(budget.get("max_runtime_hours"))
        if runtime is not None:
            budget["max_runtime_hours"] = runtime
    return budget


def normalize_baseline_gate(raw: Any, metric_goal: str) -> Dict[str, Any]:
    gate = dict(raw) if isinstance(raw, dict) else {}
    defaults = DEFAULT_BASELINE_GATE[metric_goal]
    normalized = {
        "metric_goal": metric_goal,
        "borderline_gap": safe_float(gate.get("borderline_gap")),
        "abandon_gap": safe_float(gate.get("abandon_gap")),
        "borderline_relative_gap": safe_float(gate.get("borderline_relative_gap")),
        "abandon_relative_gap": safe_float(gate.get("abandon_relative_gap")),
        "timeout": int(gate.get("timeout") or 60),
        "max_steps": int(gate.get("max_steps") or 0),
    }
    if metric_goal == "maximize":
        normalized["borderline_gap"] = normalized["borderline_gap"] if normalized["borderline_gap"] is not None else defaults["borderline_gap"]
        normalized["abandon_gap"] = normalized["abandon_gap"] if normalized["abandon_gap"] is not None else defaults["abandon_gap"]
    else:
        normalized["borderline_relative_gap"] = normalized["borderline_relative_gap"] if normalized["borderline_relative_gap"] is not None else defaults["borderline_relative_gap"]
        normalized["abandon_relative_gap"] = normalized["abandon_relative_gap"] if normalized["abandon_relative_gap"] is not None else defaults["abandon_relative_gap"]
    return normalized


def normalize_execution_policy(raw: Any, args: argparse.Namespace) -> Dict[str, Any]:
    policy = dict(DEFAULT_EXECUTION_POLICY)
    if isinstance(raw, dict):
        policy.update(raw)
    if args.run_selected_variants:
        policy["run_selected_variants"] = True
    if args.max_executed_variants is not None:
        policy["max_executed_variants"] = int(args.max_executed_variants)
    if args.variant_timeout is not None:
        policy["variant_timeout"] = int(args.variant_timeout)
    max_executed_variants = policy.get("max_executed_variants")
    variant_timeout = policy.get("variant_timeout")
    full_run_timeout = policy.get("full_run_timeout")
    return {
        "run_selected_variants": bool(policy.get("run_selected_variants", False)),
        "max_executed_variants": int(max_executed_variants) if max_executed_variants is not None else 1,
        "variant_timeout": int(variant_timeout) if variant_timeout is not None else 60,
        "run_full_after_short_run": bool(policy.get("run_full_after_short_run", False)),
        "full_run_timeout": (
            int(full_run_timeout)
            if full_run_timeout is not None
            else int(variant_timeout)
            if variant_timeout is not None
            else 60
        ),
    }


def stringify_campaign_binding(value: Any) -> str:
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


def normalize_candidate_ideas(
    raw: Any,
    variant_spec: Dict[str, Any],
    *,
    current_research: str,
    task_family: str,
    dataset: Any,
    evaluation_source: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        return []

    dataset_binding = stringify_campaign_binding(dataset)
    evaluation_binding = evaluation_binding_text(evaluation_source)
    task_binding = str(task_family or "").strip() or "unspecified"
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        change_scope = str(item.get("change_scope") or "unspecified")
        target_component = str(item.get("target_component") or "unspecified")
        normalized.append(
            {
                "id": str(item.get("id") or f"idea-{index:03d}"),
                "summary": str(item.get("summary") or item.get("description") or f"Candidate idea {index}"),
                "change_scope": change_scope,
                "target_component": target_component,
                "expected_upside": clamp_score(safe_float(item.get("expected_upside")), default=0.5),
                "implementation_risk": clamp_score(safe_float(item.get("implementation_risk")), default=0.5),
                "eval_risk": clamp_score(safe_float(item.get("eval_risk")), default=0.5),
                "rollback_ease": clamp_score(safe_float(item.get("rollback_ease")), default=0.5),
                "estimated_runtime_cost": clamp_score(safe_float(item.get("estimated_runtime_cost")), default=0.5),
                "single_variable_fit": clamp_score(safe_float(item.get("single_variable_fit")), default=0.8),
                "hypothesis": str(item.get("hypothesis") or item.get("summary") or ""),
                "supporting_changes": list(item.get("supporting_changes", []) or []),
                "seed_origin": "researcher",
                "campaign_idea_id": str(item.get("id") or f"idea-{index:03d}"),
                "source_support_hint": str(item.get("source_support_hint") or ""),
                "feasibility_hint": str(item.get("feasibility_hint") or ""),
                "source": str(item.get("source") or ""),
                "source_repo": str(item.get("source_repo") or ""),
                "source_file": str(item.get("source_file") or ""),
                "source_symbol": str(item.get("source_symbol") or ""),
                "selection_origin": "campaign",
                "context_anchor": str(item.get("context_anchor") or current_research),
                "task_family_binding": str(item.get("task_family_binding") or task_binding),
                "dataset_binding": str(item.get("dataset_binding") or dataset_binding),
                "evaluation_binding": str(item.get("evaluation_binding") or evaluation_binding),
                "constraint_notes": list(item.get("constraint_notes", []) or [
                    f"Anchor this candidate to current_research `{current_research}`.",
                    f"Keep the candidate inside task family `{task_binding}` and dataset `{dataset_binding}`.",
                    f"Preserve the frozen evaluation binding `{evaluation_binding}`.",
                    f"Keep `{change_scope}` around `{target_component}` single-variable and reversible.",
                ]),
            }
        )
    return normalized


def normalize_idea_generation(raw: Any) -> Dict[str, Any]:
    policy = dict(DEFAULT_IDEA_GENERATION_POLICY)
    if isinstance(raw, dict):
        policy.update(raw)
    try:
        policy["max_generated_ideas"] = max(0, int(policy.get("max_generated_ideas", 3)))
    except (TypeError, ValueError):
        policy["max_generated_ideas"] = 3
    policy["allow_synthesized_seed_ideas"] = bool(policy.get("allow_synthesized_seed_ideas", True))
    policy["require_diverse_targets"] = bool(policy.get("require_diverse_targets", True))
    return policy


def normalize_campaign(args: argparse.Namespace) -> Tuple[Dict[str, Any], bool]:
    if args.research_campaign_json:
        raw_campaign = load_structured_file(Path(args.research_campaign_json).resolve())
        compatibility_mode = False
    else:
        raw_campaign = {}
        compatibility_mode = True

    current_research = str(raw_campaign.get("current_research") or args.current_research or "").strip()
    if not current_research:
        raise ValueError("Either --current-research or --research-campaign-json with current_research is required.")

    if args.variant_spec_json:
        variant_spec = load_variant_spec(Path(args.variant_spec_json).resolve(), current_research)
    else:
        variant_spec = normalize_variant_spec(
            raw_campaign.get("variant_spec", {}) if isinstance(raw_campaign.get("variant_spec"), dict) else {},
            current_research,
        )

    evaluation_source = normalize_evaluation_source(raw_campaign.get("evaluation_source", {}), variant_spec)
    variant_spec = bind_evaluation_command_to_variant_spec(variant_spec, evaluation_source)
    metric_goal = normalize_metric_goal(evaluation_source.get("metric_goal") or variant_spec.get("metric_goal"))
    candidate_ideas = normalize_candidate_ideas(
        raw_campaign.get("candidate_ideas", []),
        variant_spec,
        current_research=current_research,
        task_family=str(raw_campaign.get("task_family") or ""),
        dataset=raw_campaign.get("dataset"),
        evaluation_source=evaluation_source,
    )
    execution_policy = normalize_execution_policy(raw_campaign.get("execution_policy", {}), args)
    sota_reference = normalize_sota_reference(raw_campaign.get("sota_reference", []), evaluation_source.get("primary_metric"), metric_goal)
    idea_generation = normalize_idea_generation(raw_campaign.get("idea_generation", {}))

    campaign = {
        "schema_version": "1.0",
        "mode": "legacy" if compatibility_mode else "campaign",
        "current_research": current_research,
        "task_family": normalize_task_family(raw_campaign.get("task_family")),
        "dataset": raw_campaign.get("dataset"),
        "benchmark": raw_campaign.get("benchmark"),
        "evaluation_source": evaluation_source,
        "sota_reference": sota_reference,
        "candidate_ideas": candidate_ideas,
        "researcher_candidate_ideas": candidate_ideas,
        "compute_budget": normalize_compute_budget(raw_campaign.get("compute_budget", {})),
        "variant_spec": variant_spec,
        "baseline_gate": normalize_baseline_gate(raw_campaign.get("baseline_gate", {}), metric_goal),
        "execution_policy": execution_policy,
        "research_lookup": dict(raw_campaign.get("research_lookup", {})) if isinstance(raw_campaign.get("research_lookup"), dict) else {},
        "idea_policy": dict(raw_campaign.get("idea_policy", {})) if isinstance(raw_campaign.get("idea_policy"), dict) else {},
        "idea_generation": idea_generation,
        "source_constraints": dict(raw_campaign.get("source_constraints", {})) if isinstance(raw_campaign.get("source_constraints"), dict) else {},
        "feasibility_policy": dict(raw_campaign.get("feasibility_policy", {})) if isinstance(raw_campaign.get("feasibility_policy"), dict) else {},
    }
    return campaign, compatibility_mode


def build_stage_trace_entry(stage: str, tool: str, summary: str, status: str = "completed") -> Dict[str, Any]:
    return {"stage": stage, "tool": tool, "status": status, "summary": summary}


def normalize_flag_name(key: str) -> str:
    return "--" + re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def quote_cli_value(value: Any) -> str:
    text = str(value)
    if any(char.isspace() for char in text):
        return f"\"{text}\""
    return text


def maybe_append_cli_arg(command: str, flag: Any, value: Any) -> str:
    if flag in {None, False, ""} or value is None:
        return command
    return f"{command} {flag} {quote_cli_value(value)}"


def compose_variant_command(base_command: str, variant: Dict[str, Any], spec: Dict[str, Any]) -> str:
    command = base_command.strip()
    axis_flag_map = spec.get("axis_flag_map") or {}
    for key, value in sorted(variant.get("axes", {}).items()):
        flag = axis_flag_map.get(key) or normalize_flag_name(key)
        command = maybe_append_cli_arg(command, flag, value)

    command = maybe_append_cli_arg(command, spec.get("subset_size_flag", "--subset-size"), variant.get("subset_size"))
    command = maybe_append_cli_arg(command, spec.get("short_run_steps_flag", "--max-steps"), variant.get("short_run_steps"))
    return command


def summarize_variant_result(result: Dict[str, Any]) -> str:
    metric = result.get("best_metric")
    if metric:
        return f"status={result.get('status', 'unknown')}, stop={result.get('stop_reason', 'unknown')}, metric={metric['name']}={metric['value']}"
    return f"status={result.get('status', 'unknown')}, stop={result.get('stop_reason', 'unknown')}"


def infer_execution_kind(base_command: Optional[str], spec_or_source: Dict[str, Any]) -> str:
    explicit = str(spec_or_source.get("execution_kind") or "").strip().lower()
    if explicit in {"train", "training"}:
        return "training"
    if explicit in {"run", "verify", "eval", "inference", "non_training", "non-training"}:
        return "non_training"

    lowered = str(base_command or "").lower()
    if any(token in lowered for token in [" train", "trainer", "fit", "fine-tune", "finetune"]):
        return "training"
    return "non_training"


def extract_metric_policy(variant_matrix: Dict[str, Any], variant_spec: Dict[str, Any], campaign: Dict[str, Any]) -> Dict[str, Any]:
    matrix_policy = dict(variant_matrix.get("metric_policy", {}))
    evaluation_source = campaign.get("evaluation_source", {})
    primary_metric = matrix_policy.get("primary_metric") or evaluation_source.get("primary_metric") or variant_spec.get("primary_metric")
    metric_goal = normalize_metric_goal(
        matrix_policy.get("metric_goal") or evaluation_source.get("metric_goal") or variant_spec.get("metric_goal")
    )
    return {"primary_metric": primary_metric, "metric_goal": metric_goal}


def extract_comparison_metric_policy(campaign: Dict[str, Any], metric_policy: Dict[str, Any]) -> Dict[str, Any]:
    evaluation_source = campaign.get("evaluation_source", {})
    return {
        "primary_metric": evaluation_source.get("primary_metric") or metric_policy.get("primary_metric"),
        "metric_goal": normalize_metric_goal(evaluation_source.get("metric_goal") or metric_policy.get("metric_goal")),
    }


def default_metric_payload(item: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    metric = item.get("best_metric")
    if isinstance(metric, dict):
        return safe_float(metric.get("value")), metric.get("name")
    return None, None


def metric_payload_for_policy(item: Dict[str, Any], primary_metric: Optional[str]) -> Tuple[Optional[float], Optional[str], bool]:
    observed_metrics = item.get("observed_metrics", {})
    if primary_metric and isinstance(observed_metrics, dict) and primary_metric in observed_metrics:
        return safe_float(observed_metrics[primary_metric]), primary_metric, True

    best_metric = item.get("best_metric")
    if primary_metric and isinstance(best_metric, dict) and best_metric.get("name") == primary_metric:
        return safe_float(best_metric.get("value")), primary_metric, True

    fallback_value, fallback_name = default_metric_payload(item)
    return fallback_value, fallback_name, False


def decorate_run_with_metric_policy(item: Dict[str, Any], metric_policy: Dict[str, Any]) -> Dict[str, Any]:
    primary_metric = metric_policy.get("primary_metric")
    metric_goal = normalize_metric_goal(metric_policy.get("metric_goal"))
    ranking_value, ranking_name, matched_primary_metric = metric_payload_for_policy(item, primary_metric)

    decorated = dict(item)
    decorated["ranking_metric"] = {
        "name": ranking_name,
        "value": ranking_value,
        "goal": metric_goal,
    } if ranking_name and ranking_value is not None else None
    decorated["ranking_metric_name"] = ranking_name
    decorated["ranking_metric_goal"] = metric_goal
    decorated["matched_primary_metric"] = matched_primary_metric if primary_metric else ranking_value is not None
    decorated["metric_policy_applied"] = bool(primary_metric)
    return decorated


def rank_executed_runs(executed_runs: List[Dict[str, Any]], metric_policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    status_rank = {"success": 3, "partial": 2, "blocked": 1, "not_run": 0}
    metric_goal = normalize_metric_goal(metric_policy.get("metric_goal"))

    def adjust_for_goal(value: Optional[float]) -> float:
        numeric_value = safe_float(value)
        if numeric_value is None:
            return float("-inf")
        return numeric_value if metric_goal == "maximize" else -numeric_value

    decorated = [decorate_run_with_metric_policy(item, metric_policy) for item in executed_runs]

    def sort_key(item: Dict[str, Any]) -> Tuple[int, int, float, float]:
        ranking_metric = item.get("ranking_metric")
        ranking_value = ranking_metric.get("value") if isinstance(ranking_metric, dict) else None
        fallback_value, _fallback_name = default_metric_payload(item)
        return (
            status_rank.get(item.get("status", "not_run"), 0),
            1 if item.get("matched_primary_metric") else 0,
            adjust_for_goal(ranking_value),
            adjust_for_goal(fallback_value),
        )

    return sorted(decorated, key=sort_key, reverse=True)


def build_variant_matrix(planner_script: Path, variant_spec: Dict[str, Any]) -> Dict[str, Any]:
    if not variant_spec.get("base_command"):
        current_research = variant_spec["current_research"]
        return {
            "schema_version": "1.0",
            "current_research": current_research,
            "baseline_ref": variant_spec.get("baseline_ref", current_research),
            "base_command": None,
            "raw_variant_count": 0,
            "variant_count": 0,
            "pruned_variant_count": 0,
            "variant_budget": {
                "max_variants": int(variant_spec.get("max_variants") or 0),
                "max_short_cycle_runs": int(variant_spec.get("max_short_cycle_runs") or 0),
            },
            "selection_policy": {
                "factors": ["cost", "success_rate", "expected_gain"],
                "weights": variant_spec.get("selection_weights", {}),
            },
            "metric_policy": {
                "primary_metric": variant_spec.get("primary_metric"),
                "metric_goal": normalize_metric_goal(variant_spec.get("metric_goal")),
            },
            "variants": [],
        }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        temp_spec_path = Path(handle.name)
        handle.write(json.dumps(variant_spec, indent=2, ensure_ascii=False))

    try:
        matrix = run_json(planner_script, ["--spec-json", str(temp_spec_path), "--json"])
    finally:
        if temp_spec_path.exists():
            temp_spec_path.unlink()
    return matrix


def execute_variant_candidates(
    *,
    train_execute_script: Path,
    run_execute_script: Path,
    repo_path: Path,
    variant_matrix: Dict[str, Any],
    variant_spec: Dict[str, Any],
    current_research: str,
    timeout: int,
    max_executed_variants: int,
    campaign: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    base_command = variant_matrix.get("base_command")
    variants = variant_matrix.get("variants", [])
    if not base_command or not variants or max_executed_variants <= 0:
        return [], []

    execution_kind = infer_execution_kind(base_command, variant_spec)
    metric_policy = extract_metric_policy(variant_matrix, variant_spec, campaign or {"evaluation_source": {}})
    executed_runs: List[Dict[str, Any]] = []
    stage_trace: List[Dict[str, Any]] = []
    for variant in variants[:max_executed_variants]:
        command = compose_variant_command(base_command, variant, variant_spec)
        if execution_kind == "training":
            run_mode = "short_run_verification" if variant.get("short_run_steps") is not None else "startup_verification"
            payload = run_json(
                train_execute_script,
                [
                    "--repo",
                    str(repo_path),
                    "--command",
                    command,
                    "--timeout",
                    str(timeout),
                    "--lane",
                    "explore",
                    "--run-mode",
                    run_mode,
                    "--dataset",
                    "current_research",
                    "--checkpoint-source",
                    current_research,
                    "--max-steps",
                    str(variant.get("short_run_steps") or 0),
                ],
            )
            tool_name = "run-train/scripts/run_training.py"
        else:
            run_mode = "candidate_verify"
            payload = run_json(
                run_execute_script,
                [
                    "--repo",
                    str(repo_path),
                    "--command",
                    command,
                    "--timeout",
                    str(timeout),
                ],
            )
            payload.setdefault("stop_reason", "command_completed" if payload.get("status") == "success" else "command_checked")
            tool_name = "minimal-run-and-audit/scripts/run_command.py"
        summary = summarize_variant_result(payload)
        executed_runs.append(
            {
                "id": variant.get("id", "unknown"),
                "metric": payload.get("best_metric", {}).get("value") if payload.get("best_metric") else payload.get("status", "unknown"),
                "metric_name": payload.get("best_metric", {}).get("name") if payload.get("best_metric") else None,
                "summary": summary,
                "status": payload.get("status", "unknown"),
                "stop_reason": payload.get("stop_reason", "unknown"),
                "command": command,
                "axes": variant.get("axes", {}),
                "subset_size": variant.get("subset_size"),
                "short_run_steps": variant.get("short_run_steps"),
                "best_metric": payload.get("best_metric"),
                "observed_metrics": payload.get("observed_metrics", {}),
                "best_checkpoint": payload.get("best_checkpoint"),
                "changed_files": payload.get("changed_files", []),
                "new_files": payload.get("new_files", []),
                "deleted_files": payload.get("deleted_files", []),
                "touched_paths": payload.get("touched_paths", []),
                "touched_symbols": payload.get("touched_symbols", []),
                "evidence_capture": payload.get("evidence_capture", {}),
            }
        )
        stage_trace.append(
            build_stage_trace_entry(
                "variant-execution",
                tool_name,
                f"Executed `{variant.get('id', 'unknown')}` with mode `{run_mode}` and observed {summary}.",
            )
        )

    return rank_executed_runs(executed_runs, metric_policy), stage_trace


def build_analysis_context(campaign: Dict[str, Any], metric_policy: Dict[str, Any], current_research: str) -> Dict[str, Any]:
    evaluation_source = dict(campaign.get("evaluation_source", {}))
    if metric_policy.get("primary_metric") and not evaluation_source.get("primary_metric"):
        evaluation_source["primary_metric"] = metric_policy["primary_metric"]
    if metric_policy.get("metric_goal") and not evaluation_source.get("metric_goal"):
        evaluation_source["metric_goal"] = metric_policy["metric_goal"]
    return {
        "current_research": current_research,
        "task_family": campaign.get("task_family"),
        "dataset": campaign.get("dataset"),
        "benchmark": campaign.get("benchmark"),
        "evaluation_source": evaluation_source,
    }


def run_analysis_pass(
    analysis_script: Path,
    workspace_repo_path: Path,
    analysis_output_dir: Path,
    analysis_context: Dict[str, Any],
) -> Dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        context_path = Path(handle.name)
        handle.write(json.dumps(analysis_context, indent=2, ensure_ascii=False))

    try:
        return run_json(
            analysis_script,
            [
                "--repo",
                str(workspace_repo_path),
                "--output-dir",
                str(analysis_output_dir),
                "--analysis-context-json",
                str(context_path),
            ],
        )
    finally:
        if context_path.exists():
            context_path.unlink()


def run_code_plan_pass(
    *,
    code_planner_script: Path,
    workspace_repo_path: Path,
    current_research: str,
    experiment_branch: str,
    task_family: str,
    variant_spec: Dict[str, Any],
    selected_idea: Optional[Dict[str, Any]] = None,
    analysis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    temp_paths: List[Path] = []
    args = [
        "--repo",
        str(workspace_repo_path),
        "--current-research",
        current_research,
        "--experiment-branch",
        experiment_branch,
        "--task-family",
        task_family,
        "--json",
    ]

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        variant_spec_path = Path(handle.name)
        handle.write(json.dumps(variant_spec, indent=2, ensure_ascii=False))
    temp_paths.append(variant_spec_path)
    args.extend(["--variant-spec-json", str(variant_spec_path)])

    if selected_idea:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            idea_card_path = Path(handle.name)
            handle.write(json.dumps(selected_idea, indent=2, ensure_ascii=False))
        temp_paths.append(idea_card_path)
        args.extend(["--idea-card-json", str(idea_card_path)])

    if analysis_data:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            analysis_path = Path(handle.name)
            handle.write(json.dumps(analysis_data, indent=2, ensure_ascii=False))
        temp_paths.append(analysis_path)
        args.extend(["--analysis-json", str(analysis_path)])

    try:
        return run_json(code_planner_script, args)
    finally:
        for path in temp_paths:
            if path.exists():
                path.unlink()


def best_sota_reference(sota_reference: Sequence[Dict[str, Any]], metric_policy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    primary_metric = metric_policy.get("primary_metric")
    metric_goal = normalize_metric_goal(metric_policy.get("metric_goal"))
    candidates = [
        item
        for item in sota_reference
        if safe_float(item.get("value")) is not None and (not primary_metric or item.get("metric") in {primary_metric, "", None})
    ]
    if not candidates:
        return None
    reverse = metric_goal == "maximize"
    return sorted(candidates, key=lambda item: safe_float(item.get("value")) or 0.0, reverse=reverse)[0]


def run_baseline_evaluation(
    *,
    train_execute_script: Path,
    run_execute_script: Path,
    repo_path: Path,
    current_research: str,
    evaluation_source: Dict[str, Any],
    baseline_gate_cfg: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], float]:
    command = str(evaluation_source.get("command") or "").strip()
    if not command:
        return (
            {
                "decision": "not-applicable",
                "reason": "No evaluation command was provided in evaluation_source.",
                "metric_name": evaluation_source.get("primary_metric"),
                "metric_value": None,
                "runtime_seconds": 0.0,
            },
            {},
            0.0,
        )

    execution_kind = infer_execution_kind(command, evaluation_source)
    start = time.perf_counter()
    if execution_kind == "training":
        max_steps = int(baseline_gate_cfg.get("max_steps") or 0)
        run_mode = "short_run_verification" if max_steps > 0 else "startup_verification"
        payload = run_json(
            train_execute_script,
            [
                "--repo",
                str(repo_path),
                "--command",
                command,
                "--timeout",
                str(int(baseline_gate_cfg.get("timeout") or 60)),
                "--lane",
                "explore",
                "--run-mode",
                run_mode,
                "--dataset",
                str(evaluation_source.get("split") or "baseline"),
                "--checkpoint-source",
                current_research,
                "--max-steps",
                str(max_steps),
            ],
        )
    else:
        payload = run_json(
            run_execute_script,
            [
                "--repo",
                str(repo_path),
                "--command",
                command,
                "--timeout",
                str(int(baseline_gate_cfg.get("timeout") or 60)),
            ],
        )
        payload.setdefault("stop_reason", "command_completed" if payload.get("status") == "success" else "command_checked")
    runtime_seconds = round(time.perf_counter() - start, 3)

    primary_metric = evaluation_source.get("primary_metric")
    metric_value, metric_name, matched_primary = metric_payload_for_policy(payload, primary_metric)
    baseline_metric_name = metric_name or primary_metric
    baseline_gate = {
        "decision": "not-applicable",
        "reason": "Evaluation ran, but no comparable SOTA reference was available.",
        "metric_name": baseline_metric_name,
        "metric_value": metric_value,
        "matched_primary_metric": matched_primary,
        "status": payload.get("status", "unknown"),
        "stop_reason": payload.get("stop_reason", "unknown"),
        "runtime_seconds": runtime_seconds,
        "execution_kind": execution_kind,
    }
    return baseline_gate, payload, runtime_seconds


def compare_baseline_to_sota(
    baseline_gate: Dict[str, Any],
    baseline_payload: Dict[str, Any],
    metric_policy: Dict[str, Any],
    sota_reference: Sequence[Dict[str, Any]],
    baseline_gate_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    baseline_value = safe_float(baseline_gate.get("metric_value"))
    metric_name = baseline_gate.get("metric_name") or metric_policy.get("primary_metric")
    if baseline_value is None or not metric_name:
        baseline_gate["decision"] = "not-applicable"
        baseline_gate["reason"] = "Baseline evaluation did not produce the primary metric."
        return baseline_gate

    reference = best_sota_reference(sota_reference, metric_policy)
    if not reference:
        baseline_gate["decision"] = "not-applicable"
        baseline_gate["reason"] = "No comparable SOTA reference was provided."
        return baseline_gate

    metric_goal = normalize_metric_goal(metric_policy.get("metric_goal"))
    sota_value = float(reference["value"])
    baseline_gate["reference"] = reference
    if metric_goal == "maximize":
        gap = round(sota_value - baseline_value, 4)
        baseline_gate["gap_to_sota"] = gap
        if gap > float(baseline_gate_cfg["abandon_gap"]):
            baseline_gate["decision"] = "abandon"
            baseline_gate["reason"] = f"Baseline `{metric_name}={baseline_value}` trails provided SOTA `{sota_value}` by `{gap}` absolute points."
        elif gap > float(baseline_gate_cfg["borderline_gap"]):
            baseline_gate["decision"] = "borderline"
            baseline_gate["reason"] = f"Baseline `{metric_name}={baseline_value}` is within a plausible improvement range but still `{gap}` points off the provided SOTA."
        else:
            baseline_gate["decision"] = "proceed"
            baseline_gate["reason"] = f"Baseline `{metric_name}={baseline_value}` is close enough to the provided SOTA `{sota_value}` to justify follow-up work."
    else:
        relative_gap = 0.0 if sota_value == 0 else round(max(0.0, (baseline_value - sota_value) / abs(sota_value)), 4)
        baseline_gate["relative_gap_to_sota"] = relative_gap
        if relative_gap > float(baseline_gate_cfg["abandon_relative_gap"]):
            baseline_gate["decision"] = "abandon"
            baseline_gate["reason"] = f"Baseline `{metric_name}={baseline_value}` is worse than the provided SOTA `{sota_value}` by `{relative_gap:.2%}`."
        elif relative_gap > float(baseline_gate_cfg["borderline_relative_gap"]):
            baseline_gate["decision"] = "borderline"
            baseline_gate["reason"] = f"Baseline `{metric_name}={baseline_value}` is close enough to the provided SOTA `{sota_value}` to review manually before scaling."
        else:
            baseline_gate["decision"] = "proceed"
            baseline_gate["reason"] = f"Baseline `{metric_name}={baseline_value}` is close enough to the provided SOTA `{sota_value}` to justify follow-up work."
    baseline_gate["observed_metrics"] = baseline_payload.get("observed_metrics", {})
    baseline_gate["best_metric"] = baseline_payload.get("best_metric")
    baseline_gate["best_checkpoint"] = baseline_payload.get("best_checkpoint")
    return baseline_gate


def score_candidate_idea(idea: Dict[str, Any]) -> float:
    score = (
        0.40 * clamp_score(safe_float(idea.get("expected_upside")), default=0.5)
        + 0.20 * clamp_score(safe_float(idea.get("single_variable_fit")), default=0.8)
        + 0.15 * clamp_score(safe_float(idea.get("rollback_ease")), default=0.5)
        - 0.10 * clamp_score(safe_float(idea.get("implementation_risk")), default=0.5)
        - 0.10 * clamp_score(safe_float(idea.get("eval_risk")), default=0.5)
        - 0.05 * clamp_score(safe_float(idea.get("estimated_runtime_cost")), default=0.5)
    )
    return round(score, 4)


def build_idea_gate(candidate_ideas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ranked = [dict(item, idea_score=score_candidate_idea(item)) for item in candidate_ideas]
    ranked.sort(
        key=lambda item: (
            -item["idea_score"],
            -item.get("expected_upside", 0.0),
            item.get("implementation_risk", 1.0),
            item.get("estimated_runtime_cost", 1.0),
            item.get("id", ""),
        )
    )
    top_diff = None
    if len(ranked) >= 2:
        top_diff = round(ranked[0]["idea_score"] - ranked[1]["idea_score"], 4)
    return {
        "decision": "selected" if ranked else "not-configured",
        "ranked_ideas": ranked,
        "selected_idea": ranked[0] if ranked else None,
        "top_idea_score_diff": top_diff,
    }


def human_checkpoint_state(
    *,
    compatibility_mode: bool,
    eval_contract_complete: bool,
    baseline_gate: Dict[str, Any],
    idea_gate: Dict[str, Any],
) -> Tuple[str, List[str]]:
    if compatibility_mode:
        return "not-required", []

    reasons: List[str] = []
    if not eval_contract_complete:
        reasons.append("eval-contract-incomplete")
    if baseline_gate.get("decision") == "borderline":
        reasons.append("baseline-borderline")
    top_diff = safe_float(idea_gate.get("top_idea_score_diff"))
    if top_diff is not None and top_diff < 0.05:
        reasons.append("idea-selection-confirmation-required")
    if not reasons:
        return "not-required", []
    if len(reasons) == 1:
        return reasons[0], reasons
    return "multiple-reasons", reasons


def build_config_diff_summary(selected_idea: Optional[Dict[str, Any]], variant_matrix: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if selected_idea:
        lines.append(f"Primary change scope: `{selected_idea.get('change_scope', 'unspecified')}`.")
    if variant_matrix.get("variants"):
        variant = variant_matrix["variants"][0]
        for key, value in sorted(variant.get("axes", {}).items()):
            lines.append(f"Set `{key}` to `{value}` for the leading short-run candidate.")
        if variant.get("subset_size") is not None:
            lines.append(f"Use subset size `{variant['subset_size']}` during the short-run gate.")
        if variant.get("short_run_steps") is not None:
            lines.append(f"Cap short-run execution at `{variant['short_run_steps']}` steps.")
    if not lines:
        lines.append("No config overrides were derived from the current campaign.")
    return lines


def feasibility_score(short_run_feasibility: str) -> float:
    if short_run_feasibility == "proceed":
        return 1.0
    if short_run_feasibility == "borderline":
        return 0.5
    return 0.0


def enrich_cards_with_feasibility(
    cards: Sequence[Dict[str, Any]],
    feasibility_bundle: Dict[str, Any],
) -> List[Dict[str, Any]]:
    short_run_feasibility = str(feasibility_bundle.get("feasibility", {}).get("short_run_feasibility") or "plausible")
    score = feasibility_score(short_run_feasibility)
    enriched: List[Dict[str, Any]] = []
    for item in cards:
        card = dict(item)
        card["short_run_feasibility"] = short_run_feasibility
        card["execution_feasibility_score"] = score
        enriched.append(card)
    return enriched


def merge_selected_idea_with_source_mapping(
    selected_idea: Optional[Dict[str, Any]],
    source_mapping: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if selected_idea is None:
        return None
    merged = dict(selected_idea)
    merged["requested_patch_class"] = source_mapping.get("requested_patch_class") or str(merged.get("patch_class") or "")
    merged["patch_class"] = source_mapping.get("resolved_patch_class") or str(merged.get("patch_class") or "config-only")
    merged["patch_class_source"] = source_mapping.get("patch_class_source") or ("campaign" if merged.get("patch_class") else "default")
    merged["requires_source_triple"] = bool(source_mapping.get("requires_source_triple"))
    return merged


def observed_changed_files_from_fidelity(implementation_fidelity: Dict[str, Any]) -> List[str]:
    observed: List[str] = []
    for unit in implementation_fidelity.get("fidelity_units", []) or []:
        for site in unit.get("observed_implementation_sites", []) or unit.get("actual_observed_implementation_site", []):
            text = str(site or "").strip()
            if not text:
                continue
            _label, _sep, path = text.partition(":")
            candidate = path or text
            candidate = candidate.strip()
            if candidate and candidate not in observed:
                observed.append(candidate)
    return observed


def build_experiment_manifest(
    *,
    current_research: str,
    selected_idea: Optional[Dict[str, Any]],
    code_plan: Dict[str, Any],
    campaign: Dict[str, Any],
    metric_policy: Dict[str, Any],
    analysis_output_dir: Path,
    variant_matrix: Dict[str, Any],
    source_mapping: Optional[Dict[str, Any]] = None,
    feasibility_bundle: Optional[Dict[str, Any]] = None,
    atomic_bundle: Optional[Dict[str, Any]] = None,
    implementation_fidelity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    mapping = source_mapping or {}
    atomic = atomic_bundle or {}
    fidelity = implementation_fidelity or {}
    planned_changed_files = [item.get("file") for item in mapping.get("target_location_map", [])[:3] if item.get("file")]
    observed_changed_files = observed_changed_files_from_fidelity(fidelity)
    if selected_idea is None:
        return {
            "status": "blocked",
            "parent_baseline": current_research,
            "idea_id": None,
            "hypothesis": "",
            "changed_files": [],
            "planned_changed_files": [],
            "observed_changed_files": [],
            "config_overrides": {},
            "dataset": campaign.get("dataset"),
            "eval_contract_ref": str((analysis_output_dir / "EVAL_CONTRACT.md").as_posix()),
            "improvement_bank_ref": str((analysis_output_dir / "IMPROVEMENT_BANK.md").as_posix()),
            "idea_cards_ref": str((analysis_output_dir / "IDEA_CARDS.json").as_posix()),
            "idea_scores_ref": str((analysis_output_dir / "IDEA_SCORES.json").as_posix()),
            "idea_seeds_ref": str((analysis_output_dir / "IDEA_SEEDS.json").as_posix()),
            "module_candidates_ref": str((analysis_output_dir / "MODULE_CANDIDATES.md").as_posix()),
            "interface_diff_ref": str((analysis_output_dir / "INTERFACE_DIFF.md").as_posix()),
            "resource_plan_ref": str((analysis_output_dir / "RESOURCE_PLAN.md").as_posix()),
            "atomic_idea_map_ref": str((analysis_output_dir / "ATOMIC_IDEA_MAP.json").as_posix()),
            "implementation_fidelity_ref": str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.json").as_posix()),
            "primary_metric": metric_policy.get("primary_metric"),
            "seed_policy": "inherit-baseline-seeds",
            "budget": campaign.get("compute_budget", {}),
            "promotion_rule": "No promotion; experiment manifest is blocked until one idea passes the idea gate.",
            "supporting_changes": mapping.get("supporting_changes", []),
            "selected_source_reference": [],
            "selected_source_record": mapping.get("selected_source_record", {}),
            "target_location_map": mapping.get("target_location_map", []),
            "minimal_patch_plan": mapping.get("minimal_patch_plan", []),
            "smoke_validation_plan": mapping.get("smoke_plan", []),
            "feasibility_summary": (feasibility_bundle or {}).get("feasibility", {}),
            "atomic_idea_summary": {
                "status": atomic.get("status", "blocked"),
                "atomic_unit_count": atomic.get("atomic_unit_count", 0),
            },
            "implementation_fidelity_summary": fidelity.get("fidelity_summary", {}),
            "blockers": ["no-selected-idea"],
        }
    idea = selected_idea
    manifest_blockers = list(mapping.get("source_blockers", [])) if mapping.get("requires_source_triple") else []
    manifest_blockers.extend(list(atomic.get("blockers", [])))
    manifest_blockers = [item for item in manifest_blockers if item]
    return {
        "status": "blocked" if manifest_blockers else "ready",
        "parent_baseline": current_research,
        "idea_id": idea.get("id"),
        "hypothesis": idea.get("hypothesis") or idea.get("summary"),
        "changed_files": observed_changed_files,
        "planned_changed_files": planned_changed_files,
        "observed_changed_files": observed_changed_files,
        "config_overrides": variant_matrix.get("variants", [{}])[0].get("axes", {}) if variant_matrix.get("variants") else {},
        "dataset": campaign.get("dataset"),
        "eval_contract_ref": str((analysis_output_dir / "EVAL_CONTRACT.md").as_posix()),
        "improvement_bank_ref": str((analysis_output_dir / "IMPROVEMENT_BANK.md").as_posix()),
        "idea_cards_ref": str((analysis_output_dir / "IDEA_CARDS.json").as_posix()),
        "idea_scores_ref": str((analysis_output_dir / "IDEA_SCORES.json").as_posix()),
        "idea_seeds_ref": str((analysis_output_dir / "IDEA_SEEDS.json").as_posix()),
        "module_candidates_ref": str((analysis_output_dir / "MODULE_CANDIDATES.md").as_posix()),
        "interface_diff_ref": str((analysis_output_dir / "INTERFACE_DIFF.md").as_posix()),
        "resource_plan_ref": str((analysis_output_dir / "RESOURCE_PLAN.md").as_posix()),
        "atomic_idea_map_ref": str((analysis_output_dir / "ATOMIC_IDEA_MAP.json").as_posix()),
        "implementation_fidelity_ref": str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.json").as_posix()),
        "primary_metric": metric_policy.get("primary_metric"),
        "seed_policy": "inherit-baseline-seeds",
        "budget": campaign.get("compute_budget", {}),
        "promotion_rule": "Promote only if the candidate improves the primary metric and exceeds the provided SOTA reference under the frozen evaluation contract.",
        "supporting_changes": mapping.get("supporting_changes", []) or idea.get("supporting_changes", []),
        "selected_source_reference": idea.get("source_reference", []),
        "selected_source_record": mapping.get("selected_source_record", {}),
        "target_location_map": mapping.get("target_location_map", []),
        "minimal_patch_plan": mapping.get("minimal_patch_plan", []),
        "smoke_validation_plan": mapping.get("smoke_plan", []),
        "feasibility_summary": (feasibility_bundle or {}).get("feasibility", {}),
        "atomic_idea_summary": {
            "status": atomic.get("status", "blocked"),
            "atomic_unit_count": atomic.get("atomic_unit_count", 0),
        },
        "implementation_fidelity_summary": fidelity.get("fidelity_summary", {}),
        "blockers": manifest_blockers,
    }


def metric_delta_text(candidate_value: Optional[float], baseline_value: Optional[float], metric_goal: str) -> Optional[float]:
    if candidate_value is None or baseline_value is None:
        return None
    return round(candidate_value - baseline_value, 4) if metric_goal == "maximize" else round(baseline_value - candidate_value, 4)


def build_experiment_ledger(
    *,
    baseline_gate: Dict[str, Any],
    executed_runs: List[Dict[str, Any]],
    metric_policy: Dict[str, Any],
    experiment_branch: str,
    short_run_runtime_seconds: float,
) -> Dict[str, Any]:
    baseline_value = safe_float(baseline_gate.get("metric_value"))
    ledger = {
        "baseline": {
            "metric_name": baseline_gate.get("metric_name"),
            "metric_value": baseline_value,
            "runtime_seconds": baseline_gate.get("runtime_seconds", 0.0),
        },
        "candidate_runs": [],
    }
    metric_goal = normalize_metric_goal(metric_policy.get("metric_goal"))
    per_run_runtime = round(short_run_runtime_seconds / len(executed_runs), 3) if executed_runs else 0.0
    best_run_id = None
    for item in executed_runs:
        ranking_metric = item.get("ranking_metric") if isinstance(item.get("ranking_metric"), dict) else {}
        ranking_value = safe_float(ranking_metric.get("value"))
        # AIDE journal semantics: a run with no parsed ranking metric is buggy
        # and can never be best — only debugged or abandoned.
        is_buggy = ranking_metric.get("value") is None or item.get("status") not in {"success", "partial"}
        if best_run_id is None and not is_buggy:
            best_run_id = item.get("id")
        ledger["candidate_runs"].append(
            {
                "id": item.get("id"),
                "parent_run_id": "baseline",
                "node_state": "debug-needed" if is_buggy else "improve",
                "is_buggy": is_buggy,
                "phase": "short-run",
                "baseline_metric_diff": metric_delta_text(ranking_value, baseline_value, metric_goal),
                "runtime_seconds": per_run_runtime,
                "stop_reason": item.get("stop_reason", "unknown"),
                "rollback_target": experiment_branch,
                "code_diff_summary": "Isolated candidate branch/worktree changes only.",
                "config_diff_summary": item.get("axes", {}),
            }
        )
    ledger["best_run_id"] = best_run_id
    return ledger


def short_run_gate(executed_runs: List[Dict[str, Any]], eval_contract_complete: bool, selected_idea: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not eval_contract_complete:
        return {"status": "failed", "reason": "Evaluation contract is incomplete; stop before candidate training."}
    if selected_idea and clamp_score(safe_float(selected_idea.get("single_variable_fit")), default=0.8) < 0.5:
        return {"status": "failed", "reason": "Selected idea does not satisfy the single-variable requirement."}
    if not executed_runs:
        return {"status": "not-run", "reason": "No short-run candidates were executed."}
    # A run without a parsed ranking metric is buggy and can never pass the
    # gate as "best" — comparability requires an observed number.
    metric_backed = [
        item
        for item in executed_runs
        if item.get("status") in {"success", "partial"}
        and isinstance(item.get("ranking_metric"), dict)
        and item["ranking_metric"].get("value") is not None
    ]
    if not metric_backed:
        best = executed_runs[0]
        return {
            "status": "failed",
            "reason": (
                f"No executed run produced a parsed primary metric "
                f"(best candidate `{best.get('id', 'unknown')}` ended in `{best.get('status', 'unknown')}`)."
            ),
        }
    return {"status": "passed", "reason": f"Short-run gate passed with `{metric_backed[0].get('id', 'unknown')}`."}


def eval_contract_complete(eval_contract: Dict[str, Any]) -> bool:
    return bool(eval_contract.get("primary_metric")) and bool(eval_contract.get("evaluation_command") or eval_contract.get("evaluation_path"))


def build_candidate_hypotheses(
    campaign: Dict[str, Any],
    analysis_data: Dict[str, Any],
    code_plan: Dict[str, Any],
    idea_gate: Dict[str, Any],
) -> List[str]:
    hypotheses: List[str] = []
    for idea in idea_gate.get("ranked_ideas", [])[:2]:
        hypotheses.append(f"{idea['id']}: {idea['summary']}")
    for axis, values in sorted((campaign["variant_spec"].get("variant_axes") or {}).items()):
        shown_values = ", ".join(str(value) for value in values[:3])
        hypotheses.append(f"Probe `{axis}` variation across: {shown_values}.")
    if campaign["variant_spec"].get("base_command"):
        hypotheses.append(f"Keep `{campaign['variant_spec']['base_command']}` as the execution anchor for candidate trials.")
    for track in code_plan.get("proposed_code_tracks", [])[:2]:
        hypotheses.append(track)
    for suggestion in analysis_data.get("conservative_suggestions", [])[:2]:
        hypotheses.append(suggestion)
    if not hypotheses:
        hypotheses.append("Start with one low-risk exploratory code change plus one short-cycle candidate run.")
    return hypotheses[:6]


def build_recommended_next_trials(
    *,
    variant_matrix: Dict[str, Any],
    metric_policy: Dict[str, Any],
    setup_plan: Dict[str, Any],
    analysis_data: Dict[str, Any],
    code_plan: Dict[str, Any],
    executed_runs: List[Dict[str, Any]],
    baseline_gate: Dict[str, Any],
    selected_idea: Optional[Dict[str, Any]],
    human_checkpoint: str,
) -> List[str]:
    trials: List[str] = []
    if baseline_gate.get("decision"):
        trials.append(f"Baseline gate decision: `{baseline_gate['decision']}`.")
    if selected_idea:
        trials.append(f"Implement `{selected_idea['id']}` first: {selected_idea['summary']}")
    for item in executed_runs[:1]:
        metric = item.get("ranking_metric") if isinstance(item.get("ranking_metric"), dict) else item.get("best_metric")
        if metric:
            trials.append(f"Inspect `{item['id']}` further because `{metric['name']}={metric['value']}` under exploratory execution.")
        else:
            trials.append(f"Review `{item['id']}` logs before launching broader candidate runs.")
    if metric_policy.get("primary_metric"):
        trials.append(f"Rank follow-up work by `{metric_policy['primary_metric']}` ({metric_policy['metric_goal']}) before widening the search.")
    for target in code_plan.get("candidate_edit_targets", [])[:1]:
        trials.append(f"Review `{target}` before widening exploratory code changes.")
    for item in variant_matrix.get("variants", [])[:2]:
        axes = ", ".join(f"{key}={value}" for key, value in sorted(item.get("axes", {}).items())) or "no axis overrides"
        subset = item.get("subset_size") if item.get("subset_size") is not None else "full-data"
        steps = item.get("short_run_steps") if item.get("short_run_steps") is not None else "documented schedule"
        trials.append(f"Run `{item['id']}` with {axes}, subset={subset}, steps={steps}.")
    for item in setup_plan.get("unresolved_setup_risks", [])[:1]:
        trials.append(f"Resolve setup risk before scaling out: {item}")
    if human_checkpoint != "not-required":
        trials.append(f"Pause for user confirmation before broader training: `{human_checkpoint}`.")
    if not trials:
        trials.append("Confirm one isolated candidate branch and run one short-cycle check before broader exploration.")
    return trials[:6]


def build_changes_summary(
    *,
    context_id: str,
    current_research: str,
    experiment_branch: str,
    workspace_info: Dict[str, Any],
    code_plan: Dict[str, Any],
    executed_runs: List[Dict[str, Any]],
    planned_skill_chain: List[str],
    variant_matrix: Dict[str, Any],
    metric_policy: Dict[str, Any],
    include_analysis_pass: bool,
    include_setup_pass: bool,
    baseline_gate: Dict[str, Any],
    selected_idea: Optional[Dict[str, Any]],
) -> List[str]:
    summary = [
        f"Context id: `{context_id}`.",
        f"Anchored exploratory work to `current_research={current_research}`.",
        f"Validated isolated experiment branch `{experiment_branch}` in `{workspace_info['workspace_root']}`.",
        f"Planned orchestrator chain: {', '.join(planned_skill_chain)}.",
    ]
    if workspace_info.get("created_branch"):
        summary.append(f"Created experiment branch `{experiment_branch}` from `{workspace_info['head_sha']}`.")
    if include_analysis_pass:
        summary.append("Included a read-only analysis pass before wider exploratory edits.")
    if include_setup_pass:
        summary.append("Included a setup planning pass to preserve environment and asset assumptions.")
    if baseline_gate.get("decision"):
        summary.append(f"Baseline gate result: `{baseline_gate['decision']}`.")
    if selected_idea:
        summary.append(f"Selected `{selected_idea['id']}` as the current single-variable idea.")
    for track in code_plan.get("proposed_code_tracks", [])[:2]:
        summary.append(track)
    if variant_matrix.get("variant_count"):
        summary.append(f"Prepared `{variant_matrix['variant_count']}` exploratory run candidates from the variant matrix.")
    if variant_matrix.get("pruned_variant_count"):
        summary.append(f"Pruned `{variant_matrix['pruned_variant_count']}` higher-cost candidates under the explore-run budget policy.")
    if variant_matrix.get("selection_policy", {}).get("factors"):
        summary.append("Pre-execution candidate selection used `cost`, `success_rate`, and `expected_gain` as the primary factors.")
    if metric_policy.get("primary_metric"):
        summary.append(f"Configured candidate ranking around `{metric_policy['primary_metric']}` with goal `{metric_policy['metric_goal']}`.")
    if executed_runs:
        summary.append(f"Executed `{len(executed_runs)}` exploratory candidate runs through controlled helper handoff.")
    return summary


def build_execution_notes(
    *,
    workspace_info: Dict[str, Any],
    scan_data: Dict[str, Any],
    setup_plan: Dict[str, Any],
    analysis_data: Dict[str, Any],
    code_plan: Dict[str, Any],
    variant_matrix: Dict[str, Any],
    metric_policy: Dict[str, Any],
    executed_runs: List[Dict[str, Any]],
    baseline_gate: Dict[str, Any],
    human_checkpoint: str,
) -> List[str]:
    notes: List[str] = []
    notes.append(f"Workspace mode: `{workspace_info['mode']}` on branch `{workspace_info['branch']}` (current branch before orchestration: `{workspace_info['current_branch']}`).")
    if scan_data.get("readme_path"):
        notes.append(f"Repository README: `{scan_data['readme_path']}`.")
    if setup_plan.get("environment_file"):
        notes.append(f"Environment plan source: `{setup_plan['environment_file']}`.")
    targets = code_plan.get("candidate_edit_targets", [])
    if targets:
        notes.append(f"Primary code targets: {', '.join(targets[:3])}.")
    if variant_matrix.get("base_command"):
        notes.append(f"Base command: `{variant_matrix['base_command']}`.")
    suspicious = analysis_data.get("suspicious_patterns", [])
    if suspicious:
        notes.append(f"Analysis surfaced `{len(suspicious)}` suspicious pattern hints for review before heavier exploration.")
    if baseline_gate.get("decision"):
        notes.append(f"Baseline gate decision: `{baseline_gate['decision']}`.")
    if variant_matrix.get("variant_count"):
        notes.append("Prefer short-cycle candidate ranking before widening exploratory runs.")
    if variant_matrix.get("variant_budget", {}).get("max_variants"):
        notes.append(f"Variant budget capped selection at `{variant_matrix['variant_budget']['max_variants']}` candidates.")
    if variant_matrix.get("variant_budget", {}).get("max_short_cycle_runs"):
        notes.append(f"Short-cycle runs were capped at `{variant_matrix['variant_budget']['max_short_cycle_runs']}` candidates.")
    if metric_policy.get("primary_metric"):
        notes.append(f"Executed runs are ranked by `{metric_policy['primary_metric']}` with goal `{metric_policy['metric_goal']}`.")
    if executed_runs:
        notes.append(f"Executed `{len(executed_runs)}` candidate variants and fed their results back into `best_runs`.")
    if human_checkpoint != "not-required":
        notes.append(f"Human checkpoint required before broader training: `{human_checkpoint}`.")
    return notes


def eval_contract_payload(analysis_data: Dict[str, Any], campaign: Dict[str, Any], metric_policy: Dict[str, Any]) -> Dict[str, Any]:
    contract = dict(analysis_data.get("eval_contract", {}))
    if not contract:
        evaluation_source = campaign.get("evaluation_source", {})
        contract = {
            "task_family": campaign.get("task_family"),
            "dataset": campaign.get("dataset"),
            "benchmark": campaign.get("benchmark"),
            "evaluation_command": evaluation_source.get("command"),
            "evaluation_path": evaluation_source.get("path"),
            "primary_metric": evaluation_source.get("primary_metric") or metric_policy.get("primary_metric"),
            "metric_goal": evaluation_source.get("metric_goal") or metric_policy.get("metric_goal"),
            "expected_artifacts": evaluation_source.get("artifacts", []),
            "notes": evaluation_source.get("notes", []),
        }
    if not contract.get("primary_metric") and metric_policy.get("primary_metric"):
        contract["primary_metric"] = metric_policy["primary_metric"]
    if not contract.get("metric_goal") and metric_policy.get("metric_goal"):
        contract["metric_goal"] = metric_policy["metric_goal"]
    return contract


def compute_sota_claim_state(
    *,
    executed_runs: List[Dict[str, Any]],
    metric_policy: Dict[str, Any],
    sota_reference: Sequence[Dict[str, Any]],
) -> str:
    reference = best_sota_reference(sota_reference, metric_policy)
    if not executed_runs or not reference:
        return "not-applicable"
    ranked_runs = rank_executed_runs(executed_runs, metric_policy)
    ranking_metric = ranked_runs[0].get("ranking_metric") if isinstance(ranked_runs[0].get("ranking_metric"), dict) else None
    if not ranking_metric:
        return "not-applicable"
    candidate_value = safe_float(ranking_metric.get("value"))
    reference_value = safe_float(reference.get("value"))
    if candidate_value is None or reference_value is None:
        return "not-applicable"
    metric_goal = normalize_metric_goal(metric_policy.get("metric_goal"))
    if metric_goal == "maximize" and candidate_value > reference_value:
        return "candidate-exceeds-provided-sota"
    if metric_goal == "minimize" and candidate_value < reference_value:
        return "candidate-exceeds-provided-sota"
    return "not-applicable"


def write_analysis_status(
    *,
    analysis_output_dir: Path,
    analysis_data: Dict[str, Any],
    lookup_bundle: Dict[str, Any],
    idea_seed_bundle: Dict[str, Any],
    improvement_bank: Dict[str, Any],
    idea_cards: Dict[str, Any],
    idea_gate: Dict[str, Any],
    selected_idea: Optional[Dict[str, Any]],
    source_mapping: Dict[str, Any],
    atomic_bundle: Dict[str, Any],
    implementation_fidelity: Dict[str, Any],
    feasibility_bundle: Dict[str, Any],
) -> Path:
    outputs = {
        "summary": "analysis_outputs/SUMMARY.md",
        "risks": "analysis_outputs/RISKS.md",
        "research_map": "analysis_outputs/RESEARCH_MAP.md",
        "change_map": "analysis_outputs/CHANGE_MAP.md",
        "eval_contract": "analysis_outputs/EVAL_CONTRACT.md",
        "source_inventory": "analysis_outputs/SOURCE_INVENTORY.md",
        "source_support": "analysis_outputs/SOURCE_SUPPORT.json",
        "improvement_bank": "analysis_outputs/IMPROVEMENT_BANK.md",
        "idea_cards": "analysis_outputs/IDEA_CARDS.json",
        "idea_seeds": "analysis_outputs/IDEA_SEEDS.json",
        "idea_evaluation": "analysis_outputs/IDEA_EVALUATION.md",
        "idea_scores": "analysis_outputs/IDEA_SCORES.json",
        "module_candidates": "analysis_outputs/MODULE_CANDIDATES.md",
        "interface_diff": "analysis_outputs/INTERFACE_DIFF.md",
        "atomic_idea_map": "analysis_outputs/ATOMIC_IDEA_MAP.json",
        "implementation_fidelity": "analysis_outputs/IMPLEMENTATION_FIDELITY.json",
        "resource_plan": "analysis_outputs/RESOURCE_PLAN.md",
    }
    existing_outputs = {
        key: rel
        for key, rel in outputs.items()
        if (analysis_output_dir / Path(rel).name).exists()
    }
    payload = {
        "schema_version": "1.0",
        "status": "analyzed",
        "repo": analysis_data.get("repo"),
        "task_family": analysis_data.get("task_family"),
        "entrypoints": analysis_data.get("entrypoints", {}),
        "task_relevant_files": analysis_data.get("task_relevant_files", []),
        "research_map": analysis_data.get("research_map", {}),
        "change_map": analysis_data.get("change_map", {}),
        "eval_contract": analysis_data.get("eval_contract", {}),
        "symbol_hints": analysis_data.get("symbol_hints", []),
        "constructor_candidates": analysis_data.get("constructor_candidates", []),
        "forward_candidates": analysis_data.get("forward_candidates", []),
        "config_binding_hints": analysis_data.get("config_binding_hints", []),
        "module_files": analysis_data.get("module_files", []),
        "metric_files": analysis_data.get("metric_files", []),
        "lookup_records": [
            {
                "source_id": item.get("source_id"),
                "source_type": item.get("source_type") or item.get("kind"),
                "title": item.get("title"),
                "artifact_path": item.get("artifact_path"),
                "provider_type": item.get("provider_type"),
                "locator_type": item.get("locator_type"),
                "normalized_id": item.get("normalized_id"),
                "url": item.get("url") or item.get("source_url"),
                "evidence_class": item.get("evidence_class"),
                "evidence_weight": item.get("evidence_weight"),
                "parse_status": item.get("parse_status"),
                "source_repo": item.get("source_repo"),
                "source_file": item.get("source_file"),
                "source_symbol": item.get("source_symbol"),
            }
            for item in lookup_bundle.get("records", [])
        ],
        "source_inventory": {
            "artifact_path": lookup_bundle.get("inventory_path"),
            "support_path": lookup_bundle.get("support_path"),
            "records_by_evidence_class": lookup_bundle.get("records_by_evidence_class", []),
            "repo_extracted_locators": lookup_bundle.get("repo_extracted_locators", []),
        },
        "idea_seeds": {
            "artifact_path": idea_seed_bundle.get("artifact_path"),
            "generation_policy": idea_seed_bundle.get("generation_policy", {}),
            "researcher_idea_count": len(idea_seed_bundle.get("researcher_ideas", [])),
            "generated_idea_count": len(idea_seed_bundle.get("generated_ideas", [])),
            "synthesized_idea_count": sum(1 for item in idea_seed_bundle.get("generated_ideas", []) if item.get("seed_origin") == "synthesized"),
        },
        "idea_cards": idea_cards.get("cards", []),
        "idea_gate": idea_gate,
        "selected_idea": selected_idea,
        "selected_idea_breakdown": idea_gate.get("selected_idea_breakdown", {}),
        "module_candidates": source_mapping.get("module_candidates", []),
        "selected_source_record": source_mapping.get("selected_source_record", {}),
        "interface_diff": source_mapping.get("interface_diff", {}),
        "minimal_patch_plan": source_mapping.get("minimal_patch_plan", []),
        "atomic_idea_map": atomic_bundle,
        "implementation_fidelity": implementation_fidelity,
        "generated_idea_count": len(idea_seed_bundle.get("generated_ideas", [])),
        "researcher_idea_count": len(idea_seed_bundle.get("researcher_ideas", [])),
        "synthesized_idea_count": sum(1 for item in idea_seed_bundle.get("generated_ideas", []) if item.get("seed_origin") == "synthesized"),
        "atomic_unit_count": atomic_bundle.get("atomic_unit_count", 0),
        "fidelity_summary": implementation_fidelity.get("fidelity_summary", {}),
        "resource_plan": feasibility_bundle.get("feasibility", {}),
        "outputs": {
            **existing_outputs,
            "status": "analysis_outputs/status.json",
        },
    }
    path = analysis_output_dir / "status.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_context(
    *,
    repo_path: Path,
    analysis_output_dir: Path,
    context_id: str,
    campaign: Dict[str, Any],
    current_research: str,
    experiment_branch: str,
    durable_current_research: Dict[str, Any],
    workspace_info: Dict[str, Any],
    scan_data: Dict[str, Any],
    setup_plan: Dict[str, Any],
    analysis_data: Dict[str, Any],
    analysis_status_path: Optional[Path],
    lookup_bundle: Dict[str, Any],
    idea_seed_bundle: Dict[str, Any],
    improvement_bank: Dict[str, Any],
    idea_cards: Dict[str, Any],
    code_plan: Dict[str, Any],
    source_mapping: Dict[str, Any],
    atomic_bundle: Dict[str, Any],
    implementation_fidelity: Dict[str, Any],
    feasibility_bundle: Dict[str, Any],
    variant_matrix: Dict[str, Any],
    metric_policy: Dict[str, Any],
    executed_runs: List[Dict[str, Any]],
    planned_skill_chain: List[str],
    helper_stage_trace: List[Dict[str, Any]],
    include_analysis_pass: bool,
    include_setup_pass: bool,
    baseline_gate: Dict[str, Any],
    idea_gate: Dict[str, Any],
    selected_idea: Optional[Dict[str, Any]],
    experiment_manifest: Dict[str, Any],
    experiment_ledger: Dict[str, Any],
    short_run_gate_payload: Dict[str, Any],
    config_diff_summary: List[str],
    human_checkpoint: str,
    human_checkpoint_reasons: List[str],
) -> Dict[str, Any]:
    explore_context = {
        "context_id": context_id,
        "current_research": current_research,
        "experiment_branch": experiment_branch,
        "explicit_explore_authorization": True,
        "isolated_workspace": workspace_info.get("isolated_workspace", True),
        "workspace_mode": workspace_info.get("mode", "branch"),
        "workspace_root": workspace_info.get("workspace_root"),
    }
    eval_contract = eval_contract_payload(analysis_data, campaign, metric_policy)
    comparison_metric_policy = extract_comparison_metric_policy(campaign, metric_policy)
    return {
        "schema_version": "1.0",
        "context_id": context_id,
        "status": "completed" if executed_runs else "planned",
        "explore_context": explore_context,
        "current_research": current_research,
        "baseline_ref": current_research,
        "experiment_branch": experiment_branch,
        "isolated_workspace": explore_context["isolated_workspace"],
        "workspace_mode": explore_context["workspace_mode"],
        "workspace_root": explore_context["workspace_root"],
        "durable_current_research": durable_current_research,
        "campaign": campaign,
        "eval_contract": eval_contract,
        "analysis_output_dir": str(analysis_output_dir),
        "analysis_artifacts": {
            "analysis_status": str(analysis_status_path) if analysis_status_path else str((analysis_output_dir / "status.json")),
            "source_inventory": str((analysis_output_dir / "SOURCE_INVENTORY.md")),
            "source_support": str((analysis_output_dir / "SOURCE_SUPPORT.json")),
            "improvement_bank": str((analysis_output_dir / "IMPROVEMENT_BANK.md")),
            "idea_cards": str((analysis_output_dir / "IDEA_CARDS.json")),
            "idea_seeds": str((analysis_output_dir / "IDEA_SEEDS.json")),
            "idea_evaluation": str((analysis_output_dir / "IDEA_EVALUATION.md")),
            "idea_scores": str((analysis_output_dir / "IDEA_SCORES.json")),
            "module_candidates": str((analysis_output_dir / "MODULE_CANDIDATES.md")),
            "interface_diff": str((analysis_output_dir / "INTERFACE_DIFF.md")),
            "atomic_idea_map": str((analysis_output_dir / "ATOMIC_IDEA_MAP.json")),
            "atomic_idea_map_markdown": str((analysis_output_dir / "ATOMIC_IDEA_MAP.md")),
            "implementation_fidelity": str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.json")),
            "implementation_fidelity_markdown": str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.md")),
            "resource_plan": str((analysis_output_dir / "RESOURCE_PLAN.md")),
        },
        "sources_dir": lookup_bundle.get("sources_dir"),
        "sources_records_dir": lookup_bundle.get("records_dir"),
        "sources_index_path": lookup_bundle.get("index_path"),
        "source_inventory_path": lookup_bundle.get("inventory_path"),
        "source_support_path": lookup_bundle.get("support_path"),
        "source_record_count": len(lookup_bundle.get("records", [])),
        "source_records_by_evidence_class": lookup_bundle.get("records_by_evidence_class", []),
        "lookup_records": lookup_bundle.get("records", []),
        "source_repo_refs": code_plan.get("source_repo_refs") or [{"repo": repo_path.name, "ref": current_research, "note": "current_research anchor"}],
        "raw_variant_count": variant_matrix.get("raw_variant_count", variant_matrix.get("variant_count", 0)),
        "variant_count": variant_matrix.get("variant_count", 0),
        "pruned_variant_count": variant_matrix.get("pruned_variant_count", 0),
        "variant_budget": variant_matrix.get("variant_budget", {"max_variants": 0, "max_short_cycle_runs": 0}),
        "selection_policy": variant_matrix.get("selection_policy", {}),
        "metric_policy": metric_policy,
        "baseline_gate": baseline_gate,
        "idea_gate": idea_gate,
        "selected_idea": selected_idea,
        "selected_idea_breakdown": idea_gate.get("selected_idea_breakdown", {}),
        "idea_seeds": idea_seed_bundle,
        "generated_idea_count": len(idea_seed_bundle.get("generated_ideas", [])),
        "researcher_idea_count": len(idea_seed_bundle.get("researcher_ideas", [])),
        "synthesized_idea_count": sum(1 for item in idea_seed_bundle.get("generated_ideas", []) if item.get("seed_origin") == "synthesized"),
        "idea_cards": idea_cards.get("cards", []),
        "improvement_bank": improvement_bank.get("items", []),
        "atomic_idea_map": atomic_bundle,
        "atomic_unit_count": atomic_bundle.get("atomic_unit_count", 0),
        "implementation_fidelity": implementation_fidelity,
        "fidelity_summary": implementation_fidelity.get("fidelity_summary", {}),
        "experiment_manifest": experiment_manifest,
        "experiment_ledger": experiment_ledger,
        "short_run_gate": short_run_gate_payload,
        "best_runs": executed_runs,
        "candidate_edit_targets": code_plan.get("candidate_edit_targets", []),
        "selected_source_record": source_mapping.get("selected_source_record", {}),
        "target_location_map": source_mapping.get("target_location_map", []),
        "supporting_changes": source_mapping.get("supporting_changes", []),
        "patch_surface_summary": source_mapping.get("patch_surface_summary", {}),
        "minimal_patch_plan": source_mapping.get("minimal_patch_plan", []),
        "smoke_validation_plan": source_mapping.get("smoke_plan", []),
        "module_candidates": source_mapping.get("module_candidates", []),
        "interface_diff": source_mapping.get("interface_diff", {}),
        "code_tracks": code_plan.get("proposed_code_tracks", []),
        "config_diff_summary": config_diff_summary,
        "candidate_hypotheses": build_candidate_hypotheses(campaign, analysis_data, code_plan, idea_gate),
        "resource_plan": feasibility_bundle.get("feasibility", {}),
        "resource_detection": feasibility_bundle.get("resources", {}),
        "resource_recommendations": feasibility_bundle.get("recommendations", {}),
        "static_smoke": feasibility_bundle.get("static_smoke", {}),
        "runtime_smoke": feasibility_bundle.get("runtime_smoke", {}),
        "smoke_report": feasibility_bundle.get("smoke_report", {}),
        "planned_skill_chain": planned_skill_chain,
        "helper_stage_trace": helper_stage_trace,
        "recommended_next_trials": build_recommended_next_trials(
            variant_matrix=variant_matrix,
            metric_policy=metric_policy,
            setup_plan=setup_plan,
            analysis_data=analysis_data,
            code_plan=code_plan,
            executed_runs=executed_runs,
            baseline_gate=baseline_gate,
            selected_idea=selected_idea,
            human_checkpoint=human_checkpoint,
        ),
        "trusted_promote_candidate": False,
        "explicit_explore_authorization": True,
        "human_checkpoint_state": human_checkpoint,
        "human_checkpoint_reasons": human_checkpoint_reasons,
        "sota_claim_state": compute_sota_claim_state(
            executed_runs=executed_runs,
            metric_policy=comparison_metric_policy,
            sota_reference=campaign.get("sota_reference", []),
        ),
        "changes_summary": build_changes_summary(
            context_id=context_id,
            current_research=current_research,
            experiment_branch=experiment_branch,
            workspace_info=workspace_info,
            code_plan=code_plan,
            executed_runs=executed_runs,
            planned_skill_chain=planned_skill_chain,
            variant_matrix=variant_matrix,
            metric_policy=metric_policy,
            include_analysis_pass=include_analysis_pass,
            include_setup_pass=include_setup_pass,
            baseline_gate=baseline_gate,
            selected_idea=selected_idea,
        ),
        "execution_notes": build_execution_notes(
            workspace_info=workspace_info,
            scan_data=scan_data,
            setup_plan=setup_plan,
            analysis_data=analysis_data,
            code_plan=code_plan,
            variant_matrix=variant_matrix,
            metric_policy=metric_policy,
            executed_runs=executed_runs,
            baseline_gate=baseline_gate,
            human_checkpoint=human_checkpoint,
        ),
        "notes": [
            "Exploratory result only; do not present this as trusted reproduction success.",
            "`current_research` should map to a durable branch, commit, checkpoint, run record, or trained model state.",
            "Provided SOTA references are treated as the frozen comparison set for this campaign; the orchestrator does not prove completeness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan explicit exploratory research work on top of current_research.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--current-research", default="", help="Durable identifier for the current research context.")
    parser.add_argument("--research-campaign-json", default="", help="Optional path to a high-level research_campaign JSON or YAML file.")
    parser.add_argument("--output-dir", default="explore_outputs", help="Directory to write exploratory outputs into.")
    parser.add_argument("--experiment-branch", default="", help="Optional experiment branch or worktree label.")
    parser.add_argument("--variant-spec-json", default="", help="Optional path to a variant-spec JSON file.")
    parser.add_argument("--include-analysis-pass", action="store_true", help="Include analyze-project in the planned chain.")
    parser.add_argument("--include-setup-pass", action="store_true", help="Include env-and-assets-bootstrap in the planned chain.")
    parser.add_argument("--run-selected-variants", action="store_true", help="Execute a small number of exploratory variants through the trusted execution helpers.")
    parser.add_argument("--max-executed-variants", type=int, default=None, help="Maximum number of exploratory variants to execute when execution is enabled.")
    parser.add_argument("--variant-timeout", type=int, default=None, help="Timeout in seconds for each executed exploratory variant.")
    args = parser.parse_args()

    repo_path = Path(args.repo).resolve()
    output_dir = Path(args.output_dir).resolve()
    analysis_output_dir = output_dir.parent / "analysis_outputs"
    analysis_output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = output_dir.parent / "sources"

    campaign, compatibility_mode = normalize_campaign(args)
    current_research = campaign["current_research"]
    base_dir = Path(__file__).resolve().parents[2]
    scan_script = base_dir / "repo-intake-and-plan" / "scripts" / "scan_repo.py"
    setup_script = base_dir / "env-and-assets-bootstrap" / "scripts" / "plan_setup.py"
    analysis_script = base_dir / "analyze-project" / "scripts" / "analyze_project.py"
    code_planner_script = base_dir / "explore-code" / "scripts" / "plan_code_changes.py"
    planner_script = base_dir / "explore-run" / "scripts" / "plan_variants.py"
    run_execute_script = base_dir / "minimal-run-and-audit" / "scripts" / "run_command.py"
    train_execute_script = base_dir / "run-train" / "scripts" / "run_training.py"
    writer_script = Path(__file__).resolve().parent / "write_outputs.py"

    durable_current_research = validate_current_research(repo_path, current_research)
    experiment_branch = choose_experiment_branch(current_research, args.experiment_branch)
    workspace_info = ensure_experiment_workspace(repo_path, experiment_branch)
    context_id = build_context_id(current_research, experiment_branch)
    workspace_repo_path = Path(workspace_info["workspace_root"]).resolve()

    helper_stage_trace = [
        build_stage_trace_entry("validate-current-research", "ai-research-explore/validate_current_research", f"Validated durable current research `{current_research}` as `{durable_current_research['kind']}`."),
        build_stage_trace_entry("workspace", "ai-research-explore/ensure_experiment_workspace", f"{'Created' if workspace_info['created_branch'] else 'Validated'} isolated {workspace_info['mode']} for branch `{experiment_branch}` at `{workspace_info['workspace_root']}`."),
    ]

    scan_data = run_json(scan_script, ["--repo", str(workspace_repo_path), "--json"])
    helper_stage_trace.append(build_stage_trace_entry("repo-scan", "repo-intake-and-plan/scripts/scan_repo.py", f"Scanned repository structure and README signals for `{repo_path.name}`."))

    include_analysis_pass = args.include_analysis_pass or not compatibility_mode
    include_setup_pass = args.include_setup_pass or not compatibility_mode
    setup_plan = run_json(setup_script, ["--repo", str(workspace_repo_path), "--json"]) if include_setup_pass else {}
    if include_setup_pass:
        helper_stage_trace.append(build_stage_trace_entry("setup-plan", "env-and-assets-bootstrap/scripts/plan_setup.py", "Planned environment and asset setup for exploratory execution."))

    variant_spec = campaign["variant_spec"]
    variant_matrix = build_variant_matrix(planner_script, variant_spec)
    metric_policy = extract_metric_policy(variant_matrix, variant_spec, campaign)
    comparison_metric_policy = extract_comparison_metric_policy(campaign, metric_policy)

    analysis_data: Dict[str, Any] = {}
    if include_analysis_pass:
        analysis_context = build_analysis_context(campaign, metric_policy, current_research)
        analysis_data = run_analysis_pass(analysis_script, workspace_repo_path, analysis_output_dir, analysis_context)
        helper_stage_trace.append(build_stage_trace_entry("analysis-pass", "analyze-project/scripts/analyze_project.py", "Ran a task-aware read-only analysis pass and wrote analysis_outputs artifacts."))

    initial_code_plan = run_code_plan_pass(
        code_planner_script=code_planner_script,
        workspace_repo_path=workspace_repo_path,
        current_research=current_research,
        experiment_branch=experiment_branch,
        task_family=campaign.get("task_family") or "",
        variant_spec=variant_spec,
        analysis_data=analysis_data or None,
    )
    helper_stage_trace.append(build_stage_trace_entry("code-plan-seed", "explore-code/scripts/plan_code_changes.py", f"Prepared {len(initial_code_plan.get('candidate_edit_targets', []))} seed edit targets."))
    helper_stage_trace.append(build_stage_trace_entry("run-plan", "explore-run/scripts/plan_variants.py", f"Prepared {variant_matrix.get('variant_count', 0)} exploratory run variants after pruning {variant_matrix.get('pruned_variant_count', 0)} by budget."))

    eval_contract = eval_contract_payload(analysis_data, campaign, metric_policy)
    baseline_gate: Dict[str, Any] = {"decision": "not-applicable", "reason": "Baseline gate was not evaluated."}
    baseline_payload: Dict[str, Any] = {}
    if not compatibility_mode:
        baseline_gate, baseline_payload, _baseline_runtime = run_baseline_evaluation(
            train_execute_script=train_execute_script,
            run_execute_script=run_execute_script,
            repo_path=workspace_repo_path,
            current_research=current_research,
            evaluation_source=campaign["evaluation_source"],
            baseline_gate_cfg=campaign["baseline_gate"],
        )
        baseline_gate = compare_baseline_to_sota(
            baseline_gate,
            baseline_payload,
            comparison_metric_policy,
            campaign.get("sota_reference", []),
            campaign["baseline_gate"],
        )
        helper_stage_trace.append(build_stage_trace_entry("baseline-gate", "ai-research-explore/run_baseline_gate", f"Baseline gate decision: `{baseline_gate.get('decision', 'not-applicable')}`."))

    lookup_bundle = run_lookup_pass(
        sources_dir=sources_dir,
        repo_path=workspace_repo_path,
        analysis_output_dir=analysis_output_dir,
        campaign=campaign,
        analysis_data=analysis_data,
        code_plan=initial_code_plan,
    )
    helper_stage_trace.append(build_stage_trace_entry("research-lookup", "ai-research-explore/passes/lookup_sources.py", f"Cached {len(lookup_bundle.get('records', []))} source lookup records into `{lookup_bundle.get('sources_dir', sources_dir)}`."))

    researcher_candidate_ideas = list(campaign.get("researcher_candidate_ideas", []))
    improvement_bank = run_improvement_bank_pass(
        analysis_output_dir=analysis_output_dir,
        campaign=campaign,
        analysis_data=analysis_data,
        code_plan=initial_code_plan,
        lookup_bundle=lookup_bundle,
        baseline_gate=baseline_gate,
        candidate_ideas=researcher_candidate_ideas,
    )
    helper_stage_trace.append(build_stage_trace_entry("improvement-bank-researcher", "ai-research-explore/passes/improvement_bank.py", f"Built {len(improvement_bank.get('items', []))} researcher-anchored improvements."))

    idea_seed_bundle = run_candidate_idea_generation_pass(
        analysis_output_dir=analysis_output_dir,
        current_research=current_research,
        task_family=campaign.get("task_family") or "",
        dataset=campaign.get("dataset"),
        evaluation_source=campaign.get("evaluation_source", {}),
        variant_spec=variant_spec,
        analysis_data=analysis_data,
        improvement_bank=improvement_bank,
        researcher_candidate_ideas=researcher_candidate_ideas,
        idea_generation=campaign.get("idea_generation", {}),
    )
    helper_stage_trace.append(build_stage_trace_entry("idea-generation", "ai-research-explore/passes/candidate_idea_generation.py", f"Preserved {len(idea_seed_bundle.get('researcher_ideas', []))} researcher ideas and generated {len(idea_seed_bundle.get('generated_ideas', []))} bounded seed ideas."))

    merged_candidate_ideas = list(idea_seed_bundle.get("all_seed_ideas", []))
    campaign["all_candidate_ideas"] = merged_candidate_ideas
    improvement_bank = run_improvement_bank_pass(
        analysis_output_dir=analysis_output_dir,
        campaign=campaign,
        analysis_data=analysis_data,
        code_plan=initial_code_plan,
        lookup_bundle=lookup_bundle,
        baseline_gate=baseline_gate,
        candidate_ideas=merged_candidate_ideas,
    )
    helper_stage_trace.append(build_stage_trace_entry("improvement-bank", "ai-research-explore/passes/improvement_bank.py", f"Rebuilt {len(improvement_bank.get('items', []))} bounded improvements across the merged idea pool."))

    idea_cards = run_idea_card_pass(
        analysis_output_dir=analysis_output_dir,
        improvement_items=improvement_bank.get("items", []),
    )
    helper_stage_trace.append(build_stage_trace_entry("hypothesis-cards", "ai-research-explore/passes/idea_cards.py", f"Materialized {len(idea_cards.get('cards', []))} hypothesis cards."))

    source_mapping = {
        "schema_version": "1.0",
        "artifact_paths": [],
        "selected_source_record": {},
        "transplant_ready": False,
        "source_blockers": [],
        "target_location_map": [],
        "supporting_changes": initial_code_plan.get("supporting_changes", []),
        "patch_surface_summary": initial_code_plan.get("patch_surface_summary", {}),
        "module_candidates": [],
        "interface_diff": {},
        "minimal_patch_plan": [],
        "smoke_plan": [],
        "requested_patch_class": "",
        "resolved_patch_class": "config-only",
        "patch_class_source": "source-mapping",
        "requires_source_triple": False,
    }
    code_plan = initial_code_plan
    feasibility_bundle = run_execution_feasibility_pass(
        analysis_output_dir=analysis_output_dir,
        repo_path=workspace_repo_path,
        campaign=campaign,
        analysis_data=analysis_data,
        variant_matrix=variant_matrix,
        source_mapping=source_mapping,
        executed_runs=[],
    )
    helper_stage_trace.append(build_stage_trace_entry("execution-feasibility", "ai-research-explore/passes/execution_feasibility.py", f"Short-run feasibility: `{feasibility_bundle.get('feasibility', {}).get('short_run_feasibility', 'unknown')}`."))

    idea_cards["cards"] = enrich_cards_with_feasibility(idea_cards.get("cards", []), feasibility_bundle)
    idea_gate = run_idea_ranking_pass(
        analysis_output_dir=analysis_output_dir,
        cards=idea_cards.get("cards", []),
        baseline_gate=baseline_gate,
    )
    selected_idea = idea_gate.get("selected_idea")
    helper_stage_trace.append(build_stage_trace_entry("idea-gate", "ai-research-explore/passes/idea_ranking.py", f"Ranked {len(idea_gate.get('ranked_ideas', []))} idea cards with active selection pool `{idea_gate.get('active_selection_pool', 'all-eligible')}` and selected `{(selected_idea or {}).get('id', 'none')}`."))

    if selected_idea is not None:
        code_plan = run_code_plan_pass(
            code_planner_script=code_planner_script,
            workspace_repo_path=workspace_repo_path,
            current_research=current_research,
            experiment_branch=experiment_branch,
            task_family=campaign.get("task_family") or "",
            variant_spec=variant_spec,
            selected_idea=selected_idea,
            analysis_data=analysis_data or None,
        )
        helper_stage_trace.append(build_stage_trace_entry("code-plan-final", "explore-code/scripts/plan_code_changes.py", f"Prepared {len(code_plan.get('candidate_edit_targets', []))} candidate edit targets for the final selected idea."))

        source_mapping = run_source_mapping_pass(
            analysis_output_dir=analysis_output_dir,
            selected_idea=selected_idea,
            analysis_data=analysis_data,
            code_plan=code_plan,
            lookup_bundle=lookup_bundle,
            variant_matrix=variant_matrix,
        )
        selected_idea = merge_selected_idea_with_source_mapping(selected_idea, source_mapping)
        idea_gate["selected_idea"] = selected_idea
        helper_stage_trace.append(build_stage_trace_entry("source-mapping-final", "ai-research-explore/passes/source_mapping.py", f"Canonical source mapping uses {len(source_mapping.get('target_location_map', []))} target locations and transplant_ready=`{source_mapping.get('transplant_ready', False)}`."))
        atomic_bundle = run_atomic_idea_decomposition_pass(
            analysis_output_dir=analysis_output_dir,
            selected_idea=selected_idea,
            analysis_data=analysis_data,
            source_mapping=source_mapping,
            lookup_bundle=lookup_bundle,
            current_research=current_research,
            variant_spec=variant_spec,
        )
        helper_stage_trace.append(build_stage_trace_entry("atomic-decomposition", "ai-research-explore/passes/atomic_idea_decomposition.py", f"Atomic idea map status: `{atomic_bundle.get('status', 'blocked')}` with `{atomic_bundle.get('atomic_unit_count', 0)}` units."))
    else:
        helper_stage_trace.append(build_stage_trace_entry("source-mapping-final", "ai-research-explore/passes/source_mapping.py", "Skipped source mapping because no idea passed the idea gate.", status="blocked"))
        atomic_bundle = {
            "schema_version": "1.0",
            "status": "blocked",
            "selected_idea_id": None,
            "atomic_units": [],
            "atomic_unit_count": 0,
            "blockers": ["no-selected-idea"],
            "artifact_paths": [],
            "artifact_path": str((analysis_output_dir / "ATOMIC_IDEA_MAP.json")),
        }
        (analysis_output_dir / "ATOMIC_IDEA_MAP.json").write_text(json.dumps({k: v for k, v in atomic_bundle.items() if k not in {"artifact_paths", "artifact_path"}}, indent=2, ensure_ascii=False), encoding="utf-8")
        (analysis_output_dir / "ATOMIC_IDEA_MAP.md").write_text("# Atomic Idea Map\n\n- Status: `blocked`\n- Selected idea: `none`\n\n## Blockers\n\n- no-selected-idea\n", encoding="utf-8")
        helper_stage_trace.append(build_stage_trace_entry("atomic-decomposition", "ai-research-explore/passes/atomic_idea_decomposition.py", "Atomic decomposition was blocked because no idea passed the gate.", status="blocked"))

    if selected_idea is not None:
        pre_execution_fidelity = run_implementation_fidelity_pass(
            analysis_output_dir=analysis_output_dir,
            selected_idea=selected_idea,
            atomic_bundle=atomic_bundle,
            source_mapping=source_mapping,
            code_plan=code_plan,
            experiment_manifest={},
            executed_runs=[],
            phase="pre-execution",
        )
        helper_stage_trace.append(build_stage_trace_entry("implementation-fidelity-pre", "ai-research-explore/passes/implementation_fidelity.py", f"Pre-execution fidelity summary: `{pre_execution_fidelity.get('fidelity_summary', {}).get('states', {})}`."))
    else:
        pre_execution_fidelity = {
            "schema_version": "1.0",
            "status": "blocked",
            "phase": "pre-execution",
            "selected_idea_id": None,
            "fidelity_units": [],
            "fidelity_summary": {
                "unit_count": 0,
                "states": {"not-started": 0},
                "verification_levels": {"not_checked": 0},
                "verification_modes": {"not_checked": 0},
            },
            "blockers": ["no-selected-idea"],
            "artifact_paths": [str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.md")), str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.json"))],
            "artifact_path": str((analysis_output_dir / "IMPLEMENTATION_FIDELITY.json")),
        }
        (analysis_output_dir / "IMPLEMENTATION_FIDELITY.json").write_text(json.dumps({k: v for k, v in pre_execution_fidelity.items() if k not in {"artifact_paths", "artifact_path"}}, indent=2, ensure_ascii=False), encoding="utf-8")
        (analysis_output_dir / "IMPLEMENTATION_FIDELITY.md").write_text("# Implementation Fidelity\n\n- Status: `blocked`\n- Phase: `pre-execution`\n- Selected idea: `none`\n\n## Summary\n\n- Atomic unit count: `0`\n- States: `{'not-started': 0}`\n- Verification levels: `{'not_checked': 0}`\n", encoding="utf-8")

    checkpoint_state, checkpoint_reasons = human_checkpoint_state(
        compatibility_mode=compatibility_mode,
        eval_contract_complete=eval_contract_complete(eval_contract),
        baseline_gate=baseline_gate,
        idea_gate=idea_gate,
    )
    if not compatibility_mode and selected_idea is None:
        checkpoint_reasons = [*checkpoint_reasons, "no-selected-idea"]
        checkpoint_state = "no-selected-idea" if len(checkpoint_reasons) == 1 else "multiple-reasons"
    if not compatibility_mode and feasibility_bundle.get("feasibility", {}).get("short_run_feasibility") == "blocked":
        checkpoint_reasons = [*checkpoint_reasons, "short-run-feasibility-blocked"]
        checkpoint_state = "short-run-feasibility-blocked" if len(checkpoint_reasons) == 1 else "multiple-reasons"
    if not compatibility_mode and selected_idea is not None and source_mapping.get("requires_source_triple") and source_mapping.get("source_blockers"):
        checkpoint_reasons = [*checkpoint_reasons, *source_mapping.get("source_blockers", [])]
        checkpoint_state = source_mapping["source_blockers"][0] if len(checkpoint_reasons) == 1 else "multiple-reasons"
    if not compatibility_mode and atomic_bundle.get("status") == "blocked" and atomic_bundle.get("blockers"):
        checkpoint_reasons = [*checkpoint_reasons, *atomic_bundle.get("blockers", [])]
        checkpoint_state = "atomic-decomposition-blocked" if len(checkpoint_reasons) == 1 else "multiple-reasons"

    experiment_manifest = build_experiment_manifest(
        current_research=current_research,
        selected_idea=selected_idea,
        code_plan=code_plan,
        campaign=campaign,
        metric_policy=metric_policy,
        analysis_output_dir=analysis_output_dir,
        variant_matrix=variant_matrix,
        source_mapping=source_mapping,
        feasibility_bundle=feasibility_bundle,
        atomic_bundle=atomic_bundle,
        implementation_fidelity=pre_execution_fidelity,
    )
    config_diff_summary = build_config_diff_summary(selected_idea, variant_matrix)

    planned_skill_chain: List[str] = []
    if include_analysis_pass:
        planned_skill_chain.append("analyze-project")
    if include_setup_pass:
        planned_skill_chain.append("env-and-assets-bootstrap")
    planned_skill_chain.extend(["explore-code", "explore-run"])

    execution_kind = infer_execution_kind(variant_matrix.get("base_command"), variant_spec) if variant_matrix.get("base_command") else None
    executed_runs: List[Dict[str, Any]] = []
    short_run_runtime_seconds = 0.0
    should_run_variants = bool(campaign["execution_policy"]["run_selected_variants"])
    if not compatibility_mode and baseline_gate.get("decision") == "abandon":
        should_run_variants = False
    if not compatibility_mode and checkpoint_state != "not-required":
        should_run_variants = False
    if experiment_manifest.get("status") == "blocked":
        should_run_variants = False

    if should_run_variants:
        if variant_matrix.get("base_command") and variant_matrix.get("variants"):
            planned_skill_chain.append("run-train" if execution_kind == "training" else "minimal-run-and-audit")
        started = time.perf_counter()
        executed_runs, execution_trace = execute_variant_candidates(
            train_execute_script=train_execute_script,
            run_execute_script=run_execute_script,
            repo_path=workspace_repo_path,
            variant_matrix=variant_matrix,
            variant_spec=variant_spec,
            current_research=current_research,
            timeout=campaign["execution_policy"]["variant_timeout"],
            max_executed_variants=campaign["execution_policy"]["max_executed_variants"],
            campaign=campaign,
        )
        short_run_runtime_seconds = round(time.perf_counter() - started, 3)
        helper_stage_trace.extend(execution_trace)

    feasibility_bundle = run_execution_feasibility_pass(
        analysis_output_dir=analysis_output_dir,
        repo_path=workspace_repo_path,
        campaign=campaign,
        analysis_data=analysis_data,
        variant_matrix=variant_matrix,
        source_mapping=source_mapping,
        executed_runs=executed_runs,
    )
    helper_stage_trace.append(build_stage_trace_entry("smoke-validation", "ai-research-explore/passes/execution_feasibility.py", f"Smoke report status: `{feasibility_bundle.get('smoke_report', {}).get('status', 'unknown')}`."))

    short_run_gate_payload = short_run_gate(executed_runs, eval_contract_complete(eval_contract), selected_idea)
    if short_run_gate_payload["status"] != "failed" and feasibility_bundle.get("feasibility", {}).get("short_run_feasibility") == "blocked":
        short_run_gate_payload = {
            "status": "failed",
            "reason": "Execution feasibility blocked the short-run path before broader candidate execution.",
        }
    helper_stage_trace.append(build_stage_trace_entry("short-run-gate", "ai-research-explore/short_run_gate", f"Short-run gate status: `{short_run_gate_payload['status']}`."))
    if campaign["execution_policy"].get("run_full_after_short_run"):
        helper_stage_trace.append(build_stage_trace_entry("full-run", "ai-research-explore/full_run_governor", "Full-run execution is configured but remains conservative; this implementation records the intent and stops after the short-run gate.", status="planned"))

    if selected_idea is not None:
        implementation_fidelity = run_implementation_fidelity_pass(
            analysis_output_dir=analysis_output_dir,
            selected_idea=selected_idea,
            atomic_bundle=atomic_bundle,
            source_mapping=source_mapping,
            code_plan=code_plan,
            experiment_manifest=experiment_manifest,
            executed_runs=executed_runs,
            phase="post-execution" if executed_runs else "pre-execution",
        )
        helper_stage_trace.append(build_stage_trace_entry("implementation-fidelity-post", "ai-research-explore/passes/implementation_fidelity.py", f"Final fidelity summary: `{implementation_fidelity.get('fidelity_summary', {}).get('states', {})}`."))
    else:
        implementation_fidelity = pre_execution_fidelity

    experiment_manifest = build_experiment_manifest(
        current_research=current_research,
        selected_idea=selected_idea,
        code_plan=code_plan,
        campaign=campaign,
        metric_policy=metric_policy,
        analysis_output_dir=analysis_output_dir,
        variant_matrix=variant_matrix,
        source_mapping=source_mapping,
        feasibility_bundle=feasibility_bundle,
        atomic_bundle=atomic_bundle,
        implementation_fidelity=implementation_fidelity,
    )

    experiment_ledger = build_experiment_ledger(
        baseline_gate=baseline_gate,
        executed_runs=executed_runs,
        metric_policy=metric_policy,
        experiment_branch=experiment_branch,
        short_run_runtime_seconds=short_run_runtime_seconds,
    )
    analysis_status_path = write_analysis_status(
        analysis_output_dir=analysis_output_dir,
        analysis_data=analysis_data,
        lookup_bundle=lookup_bundle,
        idea_seed_bundle=idea_seed_bundle,
        improvement_bank=improvement_bank,
        idea_cards=idea_cards,
        idea_gate=idea_gate,
        selected_idea=selected_idea,
        source_mapping=source_mapping,
        atomic_bundle=atomic_bundle,
        implementation_fidelity=implementation_fidelity,
        feasibility_bundle=feasibility_bundle,
    )

    helper_stage_trace.append(build_stage_trace_entry("bundle-write", "ai-research-explore/scripts/write_outputs.py", f"Writing the exploratory output bundle into `{output_dir}`."))
    context = build_context(
        repo_path=repo_path,
        analysis_output_dir=analysis_output_dir,
        context_id=context_id,
        campaign=campaign,
        current_research=current_research,
        experiment_branch=experiment_branch,
        durable_current_research=durable_current_research,
        workspace_info=workspace_info,
        scan_data=scan_data,
        setup_plan=setup_plan,
        analysis_data=analysis_data,
        analysis_status_path=analysis_status_path,
        lookup_bundle=lookup_bundle,
        idea_seed_bundle=idea_seed_bundle,
        improvement_bank=improvement_bank,
        idea_cards=idea_cards,
        code_plan=code_plan,
        source_mapping=source_mapping,
        atomic_bundle=atomic_bundle,
        implementation_fidelity=implementation_fidelity,
        feasibility_bundle=feasibility_bundle,
        variant_matrix=variant_matrix,
        metric_policy=metric_policy,
        executed_runs=executed_runs,
        planned_skill_chain=planned_skill_chain,
        helper_stage_trace=helper_stage_trace,
        include_analysis_pass=include_analysis_pass,
        include_setup_pass=include_setup_pass,
        baseline_gate=baseline_gate,
        idea_gate=idea_gate,
        selected_idea=selected_idea,
        experiment_manifest=experiment_manifest,
        experiment_ledger=experiment_ledger,
        short_run_gate_payload=short_run_gate_payload,
        config_diff_summary=config_diff_summary,
        human_checkpoint=checkpoint_state,
        human_checkpoint_reasons=checkpoint_reasons,
    )
    write_bundle(writer_script, output_dir, context)

    payload = {
        "schema_version": "1.0",
        "context_id": context_id,
        "repo": str(repo_path),
        "current_research": current_research,
        "experiment_branch": experiment_branch,
        "workspace": workspace_info,
        "durable_current_research": durable_current_research,
        "campaign": campaign,
        "eval_contract": context["eval_contract"],
        "baseline_gate": baseline_gate,
        "idea_gate": idea_gate,
        "selected_idea": selected_idea,
        "selected_idea_breakdown": context.get("selected_idea_breakdown", {}),
        "idea_seeds": context.get("idea_seeds", {}),
        "generated_idea_count": context.get("generated_idea_count", 0),
        "researcher_idea_count": context.get("researcher_idea_count", 0),
        "synthesized_idea_count": context.get("synthesized_idea_count", 0),
        "atomic_idea_map": context.get("atomic_idea_map", {}),
        "atomic_unit_count": context.get("atomic_unit_count", 0),
        "implementation_fidelity": context.get("implementation_fidelity", {}),
        "fidelity_summary": context.get("fidelity_summary", {}),
        "experiment_manifest": experiment_manifest,
        "experiment_ledger": experiment_ledger,
        "short_run_gate": short_run_gate_payload,
        "planned_skill_chain": planned_skill_chain,
        "candidate_edit_targets": code_plan.get("candidate_edit_targets", []),
        "code_tracks": code_plan.get("proposed_code_tracks", []),
        "raw_variant_count": context["raw_variant_count"],
        "variant_count": context["variant_count"],
        "pruned_variant_count": context["pruned_variant_count"],
        "variant_budget": context["variant_budget"],
        "selection_policy": context["selection_policy"],
        "metric_policy": context["metric_policy"],
        "execution_kind": execution_kind,
        "candidate_hypotheses": context["candidate_hypotheses"],
        "recommended_next_trials": context["recommended_next_trials"],
        "executed_variant_count": len(executed_runs),
        "best_runs": executed_runs,
        "setup_commands": setup_plan.get("setup_commands", []),
        "setup_notes": setup_plan.get("setup_notes", []),
        "analysis_summary": analysis_data.get("summary_lines", []),
        "analysis_suspicious_patterns": analysis_data.get("suspicious_patterns", []),
        "analysis_output_dir": str(analysis_output_dir),
        "analysis_artifacts": context["analysis_artifacts"],
        "sources_dir": context.get("sources_dir"),
        "sources_index_path": context.get("sources_index_path"),
        "lookup_record_count": len(context.get("lookup_records", [])),
        "selected_source_record": context.get("selected_source_record", {}),
        "target_location_map": context.get("target_location_map", []),
        "minimal_patch_plan": context.get("minimal_patch_plan", []),
        "static_smoke": context.get("static_smoke", {}),
        "runtime_smoke": context.get("runtime_smoke", {}),
        "smoke_report": context.get("smoke_report", {}),
        "resource_plan": context.get("resource_plan", {}),
        "invoked_stage_trace": helper_stage_trace,
        "base_command": variant_matrix.get("base_command"),
        "human_checkpoint_state": checkpoint_state,
        "human_checkpoint_reasons": checkpoint_reasons,
        "sota_claim_state": context["sota_claim_state"],
        "output_dir": str(output_dir),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

