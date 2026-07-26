#!/usr/bin/env python3
"""Read-only analysis for deep learning research repositories."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ENTRYPOINT_PATTERNS = {
    "train": re.compile(r"(train|trainer|fit|pretrain)", re.IGNORECASE),
    "infer": re.compile(r"(infer|inference|demo|predict|serve)", re.IGNORECASE),
    "eval": re.compile(r"(eval|evaluate|validation|test|benchmark|metric)", re.IGNORECASE),
    "model": re.compile(r"(model|network|backbone|encoder|decoder|head|adapter|lora|loss)", re.IGNORECASE),
    "config": re.compile(r"(config|configs)", re.IGNORECASE),
}
TASK_KEYWORDS = {
    "classification": ("class", "imagenet", "log_regression", "linear", "knn"),
    "segmentation": ("seg", "segment", "mask", "ade20k", "m2f", "mask2former"),
    "detection": ("det", "detect", "coco", "detr", "box"),
    "depth": ("depth", "nyu", "dpt", "depther"),
    "text": ("text", "clip", "token", "dinotxt"),
    "pretrain": ("ssl", "pretrain", "teacher", "student", "distillation", "gram"),
}
OUTPUT_HINTS = ("checkpoint", "results", "metrics", "tensorboard", "events", "log", "output")
SKIP_PARTS = {
    "tmp",
    "artifacts",
    "repro_outputs",
    "train_outputs",
    "analysis_outputs",
    "debug_outputs",
    "explore_outputs",
    "__pycache__",
    ".git",
    ".claude",
    ".codex",
}
COMMON_FOCUS_TOKENS = {"py", "yaml", "yml", "json", "toml", "ini", "md", "run", "train", "eval", "config", "configs"}


def load_context(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    context_path = Path(path).resolve()
    text = context_path.read_text(encoding="utf-8-sig")
    if context_path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ValueError(f"YAML analysis context requires PyYAML: {context_path}") from exc
    payload = yaml.safe_load(text)
    return payload if isinstance(payload, dict) else {}


def normalize_task_family(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text or None


def normalize_scalar_string(value: Any) -> str:
    if isinstance(value, dict):
        name = value.get("name")
        if name:
            return str(name)
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def metric_goal(value: Any) -> str:
    text = str(value or "maximize").strip().lower()
    if text in {"min", "minimize", "lower", "lower_is_better"}:
        return "minimize"
    return "maximize"


def first_existing(root: Path, names: Iterable[str]) -> Optional[Path]:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def command_paths(command: str) -> List[str]:
    paths: List[str] = []
    for token in re.findall(r"[\w./\\-]+\.(?:py|ya?ml|json|toml|ini|csv|pth|pt)", command):
        token = token.strip().strip("\"'")
        if token and token not in paths:
            paths.append(token.replace("\\", "/"))
    return paths


def focus_tokens(current_research: str, evaluation_source: Dict[str, Any], task_family: Optional[str]) -> List[str]:
    tokens: List[str] = []
    for raw in [current_research, evaluation_source.get("path"), evaluation_source.get("command")]:
        for part in re.split(r"[^a-zA-Z0-9]+", str(raw or "").lower()):
            if part and part not in COMMON_FOCUS_TOKENS and len(part) > 2:
                tokens.append(part)
    if task_family:
        tokens.append(task_family)
        tokens.extend(TASK_KEYWORDS.get(task_family, ()))
    ordered: List[str] = []
    for token in tokens:
        if token not in ordered:
            ordered.append(token)
    return ordered[:20]


def task_score(rel: str, task_family: Optional[str], tokens: List[str]) -> int:
    lower = rel.lower()
    score = 0
    if task_family:
        for token in TASK_KEYWORDS.get(task_family, ()):
            if token in lower:
                score += 4
    for token in tokens:
        if token in lower:
            score += 2
    return score


def collect_candidates(repo: Path, task_family: Optional[str], tokens: List[str]) -> Dict[str, List[str]]:
    scored = {key: [] for key in ENTRYPOINT_PATTERNS}
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(repo).as_posix()
        if any(part in SKIP_PARTS for part in path.relative_to(repo).parts):
            continue
        for key, pattern in ENTRYPOINT_PATTERNS.items():
            if pattern.search(rel):
                score = 1 + task_score(rel, task_family, tokens)
                scored[key].append((score, rel))
    candidates = {}
    for key, values in scored.items():
        values.sort(key=lambda item: (-item[0], item[1]))
        candidates[key] = [rel for _score, rel in values[:20]]
    return candidates


def collect_task_focus_files(repo: Path, task_family: Optional[str], tokens: List[str]) -> List[str]:
    scored: List[tuple[int, str]] = []
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(repo).parts):
            continue
        rel = path.relative_to(repo).as_posix()
        score = task_score(rel, task_family, tokens)
        if any(part in rel.lower() for part in OUTPUT_HINTS):
            score += 1
        if path.suffix.lower() in {".py", ".yaml", ".yml", ".json", ".toml", ".ini"}:
            score += 1
        if score > 0:
            scored.append((score, rel))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [rel for _score, rel in scored[:20]]


def collect_data_interface_files(repo: Path, task_family: Optional[str]) -> List[str]:
    hits: List[str] = []
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(repo).parts):
            continue
        rel = path.relative_to(repo).as_posix()
        lower = rel.lower()
        if any(token in lower for token in ("data", "dataset", "loader", "transform", "sampler")):
            hits.append(rel)
        elif task_family and any(token in lower for token in TASK_KEYWORDS.get(task_family, ())):
            if "data" in lower or "dataset" in lower:
                hits.append(rel)
    unique: List[str] = []
    for item in sorted(hits):
        if item not in unique:
            unique.append(item)
    return unique[:20]


def collect_output_hints(repo: Path, evaluation_source: Dict[str, Any]) -> List[str]:
    hints = command_paths(str(evaluation_source.get("command") or ""))
    for rel in [
        "results.csv",
        "metrics.json",
        "config.yaml",
        "checkpoint.pth",
    ]:
        candidate = repo / rel
        if candidate.exists():
            hints.append(rel)
    unique: List[str] = []
    for item in hints:
        if item not in unique:
            unique.append(item)
    return unique[:12]


def unique_limit(values: Iterable[str], limit: int) -> List[str]:
    ordered: List[str] = []
    for item in values:
        if item and item not in ordered:
            ordered.append(item)
        if len(ordered) >= limit:
            break
    return ordered


def collect_module_files(
    candidates: Dict[str, List[str]],
    focus_files: List[str],
) -> List[str]:
    module_candidates = candidates.get("model", []) + candidates.get("train", []) + focus_files
    return unique_limit(
        [
            path
            for path in module_candidates
            if path.endswith(".py") or any(token in path.lower() for token in ("model", "backbone", "encoder", "decoder", "head"))
        ],
        20,
    )


def collect_metric_files(candidates: Dict[str, List[str]], focus_files: List[str]) -> List[str]:
    metric_candidates = candidates.get("eval", []) + focus_files
    return unique_limit(
        [
            path
            for path in metric_candidates
            if any(token in path.lower() for token in ("eval", "metric", "benchmark", "test", "validation"))
        ],
        20,
    )


def collect_symbol_hints(repo: Path, candidate_paths: List[str]) -> Dict[str, List[str]]:
    symbol_hints: List[str] = []
    constructor_candidates: List[str] = []
    forward_candidates: List[str] = []

    for rel in candidate_paths[:24]:
        path = repo / rel
        if not path.exists() or path.suffix.lower() != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbol_hints.append(f"{rel}:{node.name}")
                has_init = any(isinstance(item, ast.FunctionDef) and item.name == "__init__" for item in node.body)
                has_forward = any(isinstance(item, ast.FunctionDef) and item.name == "forward" for item in node.body)
                if has_init:
                    constructor_candidates.append(f"{rel}:{node.name}")
                if has_forward:
                    forward_candidates.append(f"{rel}:{node.name}.forward")
            elif isinstance(node, ast.FunctionDef):
                symbol_hints.append(f"{rel}:{node.name}")
                if node.name in {"forward", "__call__", "predict"}:
                    forward_candidates.append(f"{rel}:{node.name}")

    return {
        "symbol_hints": unique_limit(symbol_hints, 50),
        "constructor_candidates": unique_limit(constructor_candidates, 20),
        "forward_candidates": unique_limit(forward_candidates, 20),
    }


def collect_config_binding_hints(repo: Path, candidate_paths: List[str]) -> List[str]:
    hints: List[str] = []
    patterns = ("yaml.safe_load", "omegaconf", "argparse", "json.load", "fromfile", "config")
    for rel in candidate_paths[:24]:
        path = repo / rel
        if not path.exists():
            continue
        if path.suffix.lower() not in {".py", ".yaml", ".yml", ".json", ".toml", ".ini"}:
            continue
        if path.suffix.lower() != ".py":
            hints.append(rel)
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if any(pattern in text for pattern in patterns):
            hints.append(rel)
    return unique_limit(hints, 20)


def collect_suspicious_patterns(repo: Path) -> List[str]:
    findings: List[str] = []
    python_files = [path for path in repo.rglob("*.py") if "__pycache__" not in path.parts]
    saw_attention = False
    saw_position = False

    for path in python_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(repo).as_posix()
        lower = text.lower()

        if "attention" in lower or "transformer" in lower:
            saw_attention = True
        if any(token in lower for token in ["positional", "position_embedding", "position encoding", "pos_embed"]):
            saw_position = True
        if "sigmoid" in lower and lower.count("sigmoid") >= 2:
            findings.append(f"{rel}: repeated `sigmoid` usage detected; review for duplicated post-processing.")
        if "relu" in lower and "sigmoid" in lower:
            findings.append(f"{rel}: both `relu` and `sigmoid` appear in the same file; check activation order and intent.")
        if ".eval()" in lower and "dropout" in lower:
            findings.append(f"{rel}: review whether dropout-sensitive evaluation behavior is intentional.")
        if "optimizer" in lower and "requires_grad" not in lower and "param_groups" not in lower:
            findings.append(f"{rel}: verify optimizer parameter coverage if custom freezing is expected.")

    if saw_attention and not saw_position:
        findings.append(
            "Repository contains attention-like code but no obvious positional encoding signal was detected; review sequence-order handling."
        )

    unique: List[str] = []
    for item in findings:
        if item not in unique:
            unique.append(item)
    return unique[:20]


def build_research_map(
    repo: Path,
    readme: Path,
    task_family: Optional[str],
    candidates: Dict[str, List[str]],
    focus_files: List[str],
    output_hints: List[str],
) -> Dict[str, Any]:
    return {
        "task_family": task_family,
        "readme_present": readme.exists(),
        "train_entrypoints": candidates["train"][:8],
        "inference_entrypoints": candidates["infer"][:8],
        "evaluation_entrypoints": candidates["eval"][:8],
        "model_entrypoints": candidates["model"][:8],
        "config_entrypoints": candidates["config"][:8],
        "task_relevant_files": focus_files[:10],
        "output_hints": output_hints,
        "checkpoint_chain_hints": [item for item in output_hints if any(token in item.lower() for token in ("checkpoint", "pth", "pt", "config"))][:8],
        "repo_root": str(repo.resolve()),
    }


def build_change_map(
    research_map: Dict[str, Any],
    data_interface_files: List[str],
    evaluation_source: Dict[str, Any],
) -> Dict[str, Any]:
    eval_path = str(evaluation_source.get("path") or "")
    protected_eval = [eval_path] if eval_path else []
    protected_eval.extend(research_map["evaluation_entrypoints"][:5])
    protected_eval.extend([path for path in research_map["task_relevant_files"] if "metric" in path.lower()][:3])
    unique_protected: List[str] = []
    for item in protected_eval:
        if item and item not in unique_protected:
            unique_protected.append(item)

    allowed = []
    for section in ("model_entrypoints", "config_entrypoints", "train_entrypoints", "task_relevant_files"):
        for item in research_map[section]:
            if item not in allowed:
                allowed.append(item)
    high_risk = unique_protected[:]
    for item in research_map["config_entrypoints"][:3]:
        if item not in high_risk:
            high_risk.append(item)

    return {
        "allowed_change_zones": allowed[:12],
        "protected_eval_zones": unique_protected[:8],
        "data_interface_zones": data_interface_files[:8],
        "single_variable_high_risk_zones": high_risk[:10],
    }


def build_eval_contract(
    dataset: Any,
    benchmark: Any,
    evaluation_source: Dict[str, Any],
    task_family: Optional[str],
    output_hints: List[str],
) -> Dict[str, Any]:
    benchmark_name = normalize_scalar_string(benchmark)
    dataset_name = normalize_scalar_string(dataset)
    primary_metric = str(
        evaluation_source.get("primary_metric")
        or (benchmark.get("primary_metric") if isinstance(benchmark, dict) else "")
        or ""
    )
    return {
        "task_family": task_family,
        "dataset": dataset_name,
        "benchmark": benchmark_name,
        "evaluation_command": str(evaluation_source.get("command") or ""),
        "evaluation_path": str(evaluation_source.get("path") or ""),
        "primary_metric": primary_metric,
        "metric_goal": metric_goal(
            evaluation_source.get("metric_goal")
            or (benchmark.get("metric_goal") if isinstance(benchmark, dict) else "maximize")
        ),
        "expected_artifacts": evaluation_source.get("artifacts", []) or output_hints[:4],
        "notes": evaluation_source.get("notes", []),
    }


def analyze_repo(repo: Path, context: Optional[Dict[str, Any]] = None) -> Dict[str, object]:
    context = context or {}
    readme = first_existing(repo, ["README.md", "README"])
    task_family = normalize_task_family(context.get("task_family"))
    evaluation_source = context.get("evaluation_source", {}) if isinstance(context.get("evaluation_source"), dict) else {}
    dataset = context.get("dataset")
    benchmark = context.get("benchmark")
    current_research = str(context.get("current_research") or "")
    tokens = focus_tokens(current_research, evaluation_source, task_family)

    candidates = collect_candidates(repo, task_family, tokens)
    focus_files = collect_task_focus_files(repo, task_family, tokens)
    data_interface_files = collect_data_interface_files(repo, task_family)
    suspicious = collect_suspicious_patterns(repo)
    output_hints = collect_output_hints(repo, evaluation_source)
    module_files = collect_module_files(candidates, focus_files)
    metric_files = collect_metric_files(candidates, focus_files)
    symbol_info = collect_symbol_hints(repo, unique_limit(module_files + metric_files + candidates["train"] + candidates["eval"], 30))
    config_binding_hints = collect_config_binding_hints(repo, unique_limit(candidates["config"] + focus_files + output_hints, 30))
    research_map = build_research_map(repo, readme or repo / "README.md", task_family, candidates, focus_files, output_hints)
    change_map = build_change_map(research_map, data_interface_files, evaluation_source)
    eval_contract = build_eval_contract(dataset, benchmark, evaluation_source, task_family, output_hints)

    summary_lines = [
        f"Target repo: `{repo.resolve()}`",
        f"README present: `{bool(readme and readme.exists())}`",
        f"Task family: `{task_family or 'unspecified'}`",
        f"Top-level items: {', '.join(sorted(item.name for item in repo.iterdir())[:20]) or 'none'}",
        f"Train entry candidates: {', '.join(candidates['train'][:5]) or 'none'}",
        f"Inference entry candidates: {', '.join(candidates['infer'][:5]) or 'none'}",
        f"Evaluation entry candidates: {', '.join(candidates['eval'][:5]) or 'none'}",
        f"Task-relevant files: {', '.join(focus_files[:5]) or 'none'}",
    ]

    conservative_suggestions = [
        "Read the main model or backbone file before changing configs.",
        "Verify the train entrypoint and config loading path before inserting new modules.",
        "Treat suspicious patterns as heuristics until confirmed by command-level evidence.",
    ]
    if eval_contract["evaluation_command"]:
        conservative_suggestions.append("Freeze one evaluation contract before comparing any candidate result against SOTA.")

    return {
        "repo": str(repo.resolve()),
        "task_family": task_family,
        "entrypoints": candidates,
        "task_relevant_files": focus_files,
        "data_interface_files": data_interface_files,
        "research_map": research_map,
        "change_map": change_map,
        "eval_contract": eval_contract,
        "symbol_hints": symbol_info["symbol_hints"],
        "constructor_candidates": symbol_info["constructor_candidates"],
        "forward_candidates": symbol_info["forward_candidates"],
        "config_binding_hints": config_binding_hints,
        "module_files": module_files,
        "metric_files": metric_files,
        "suspicious_patterns": suspicious,
        "conservative_suggestions": conservative_suggestions[:5],
        "summary_lines": summary_lines,
    }


def write_research_map(output_dir: Path, data: Dict[str, object]) -> None:
    research_map = data["research_map"]
    task_files = [f"- {line}" for line in research_map.get("task_relevant_files", [])] or ["- none"]
    output_lines = [f"- {line}" for line in research_map.get("output_hints", [])] or ["- none"]
    lines = [
        "# Research Map",
        "",
        f"- Task family: `{research_map.get('task_family') or 'unspecified'}`",
        f"- Repository root: `{research_map.get('repo_root')}`",
        "",
        "## Entrypoints",
        "",
        f"- Train: {', '.join(research_map.get('train_entrypoints', [])) or 'none'}",
        f"- Inference: {', '.join(research_map.get('inference_entrypoints', [])) or 'none'}",
        f"- Evaluation: {', '.join(research_map.get('evaluation_entrypoints', [])) or 'none'}",
        f"- Model: {', '.join(research_map.get('model_entrypoints', [])) or 'none'}",
        f"- Config: {', '.join(research_map.get('config_entrypoints', [])) or 'none'}",
        "",
        "## Task-Relevant Files",
        "",
        *task_files,
        "",
        "## Output Hints",
        "",
        *output_lines,
        "",
    ]
    (output_dir / "RESEARCH_MAP.md").write_text("\n".join(lines), encoding="utf-8")


def write_change_map(output_dir: Path, data: Dict[str, object]) -> None:
    change_map = data["change_map"]
    allowed = [f"- {line}" for line in change_map.get("allowed_change_zones", [])] or ["- none"]
    protected = [f"- {line}" for line in change_map.get("protected_eval_zones", [])] or ["- none"]
    data_zones = [f"- {line}" for line in change_map.get("data_interface_zones", [])] or ["- none"]
    high_risk = [f"- {line}" for line in change_map.get("single_variable_high_risk_zones", [])] or ["- none"]
    lines = [
        "# Change Map",
        "",
        "## Allowed Change Zones",
        "",
        *allowed,
        "",
        "## Protected Eval Zones",
        "",
        *protected,
        "",
        "## Data Interface Zones",
        "",
        *data_zones,
        "",
        "## Single-Variable High-Risk Zones",
        "",
        *high_risk,
        "",
    ]
    (output_dir / "CHANGE_MAP.md").write_text("\n".join(lines), encoding="utf-8")


def write_eval_contract(output_dir: Path, data: Dict[str, object]) -> None:
    eval_contract = data["eval_contract"]
    artifacts = [f"- {line}" for line in eval_contract.get("expected_artifacts", [])] or ["- none"]
    notes = [f"- {line}" for line in eval_contract.get("notes", [])] or ["- none"]
    lines = [
        "# Eval Contract",
        "",
        f"- Task family: `{eval_contract.get('task_family') or 'unspecified'}`",
        f"- Dataset: `{eval_contract.get('dataset') or 'unspecified'}`",
        f"- Benchmark: `{eval_contract.get('benchmark') or 'unspecified'}`",
        f"- Primary metric: `{eval_contract.get('primary_metric') or 'unspecified'}`",
        f"- Metric goal: `{eval_contract.get('metric_goal') or 'maximize'}`",
        "",
        "## Evaluation Source",
        "",
        f"- Command: `{eval_contract.get('evaluation_command') or 'not provided'}`",
        f"- Path: `{eval_contract.get('evaluation_path') or 'not provided'}`",
        "",
        "## Expected Artifacts",
        "",
        *artifacts,
        "",
        "## Notes",
        "",
        *notes,
        "",
    ]
    (output_dir / "EVAL_CONTRACT.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(output_dir: Path, data: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = [
        "# Project Analysis Summary",
        "",
        *[f"- {line}" for line in data["summary_lines"]],
        "",
        "## Conservative Suggestions",
        "",
        *[f"- {line}" for line in data["conservative_suggestions"]],
        "",
        "## Additional Documents",
        "",
        "- `RESEARCH_MAP.md`",
        "- `CHANGE_MAP.md`",
        "- `EVAL_CONTRACT.md`",
        "",
    ]
    (output_dir / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")

    risks = [
        "# Suspicious Patterns",
        "",
    ]
    patterns = data["suspicious_patterns"]
    if patterns:
        risks.extend(f"- {item}" for item in patterns)
    else:
        risks.append("- No high-signal suspicious patterns were detected by the lightweight heuristic pass.")
    risks.append("")
    (output_dir / "RISKS.md").write_text("\n".join(risks), encoding="utf-8")

    write_research_map(output_dir, data)
    write_change_map(output_dir, data)
    write_eval_contract(output_dir, data)

    status = {
        "schema_version": "1.0",
        "repo": data["repo"],
        "status": "analyzed",
        "task_family": data.get("task_family"),
        "entrypoints": data["entrypoints"],
        "task_relevant_files": data["task_relevant_files"],
        "research_map": data["research_map"],
        "change_map": data["change_map"],
        "eval_contract": data["eval_contract"],
        "symbol_hints": data["symbol_hints"],
        "constructor_candidates": data["constructor_candidates"],
        "forward_candidates": data["forward_candidates"],
        "config_binding_hints": data["config_binding_hints"],
        "module_files": data["module_files"],
        "metric_files": data["metric_files"],
        "suspicious_patterns": data["suspicious_patterns"],
        "conservative_suggestions": data["conservative_suggestions"],
        "outputs": {
            "summary": "analysis_outputs/SUMMARY.md",
            "risks": "analysis_outputs/RISKS.md",
            "research_map": "analysis_outputs/RESEARCH_MAP.md",
            "change_map": "analysis_outputs/CHANGE_MAP.md",
            "eval_contract": "analysis_outputs/EVAL_CONTRACT.md",
            "status": "analysis_outputs/status.json",
        },
    }
    (output_dir / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a deep learning research repository conservatively.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--output-dir", default="analysis_outputs", help="Directory for analysis outputs.")
    parser.add_argument("--analysis-context-json", default="", help="Optional analysis context JSON or YAML path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout instead of writing files.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    context = load_context(args.analysis_context_json)
    data = analyze_repo(repo, context)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    write_outputs(Path(args.output_dir).resolve(), data)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
