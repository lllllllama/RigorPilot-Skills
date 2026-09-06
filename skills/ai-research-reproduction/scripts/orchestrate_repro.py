#!/usr/bin/env python3
"""Minimal orchestration for README-first reproduction scaffolding."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from annotate_readme import write_annotated_readme


SKILL_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHARED_SCRIPTS = Path(__file__).resolve().parents[3] / "shared" / "scripts"
BUNDLED_SHARED_SCRIPTS = SKILL_ROOT / "_bundled" / "shared" / "scripts"
SHARED_SCRIPTS = (
    SOURCE_SHARED_SCRIPTS
    if (SOURCE_SHARED_SCRIPTS / "command_utils.py").is_file()
    else BUNDLED_SHARED_SCRIPTS
)
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import run_persistent_command
from model_adapter import ModelAdapterError, load_model_profile, missing_capabilities


def load_lessons_store():
    """Load the shared lesson store; return None when unavailable (optional feature)."""
    import importlib.util

    module_path = SHARED_SCRIPTS / "lessons_store.py"
    if not module_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("lessons_store", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def maybe_record_lesson(repo_path: Path, context: Dict[str, Any]) -> Optional[str]:
    """Record failure blockers and later resolutions per the continuous-learning policy."""
    store = load_lessons_store()
    if store is None or not store.lessons_enabled():
        return None
    fingerprint = store.repo_fingerprint(repo_path)
    status = context.get("status")
    try:
        if status in {"partial", "blocked"}:
            path = store.record_lesson(
                kind="failure-fix",
                skill="ai-research-reproduction",
                summary=f"[{status}] {context.get('main_blocker', 'unrecorded blocker')}",
                detail=str(context.get("documented_command") or ""),
                fingerprint=fingerprint,
            )
            return str(path) if path else None
        if status == "success":
            prior_failures = [
                item
                for item in store.load_lessons()
                if item.get("fingerprint") == fingerprint and str(item.get("summary", "")).startswith("[")
            ]
            if prior_failures:
                path = store.record_lesson(
                    kind="failure-fix",
                    skill="ai-research-reproduction",
                    summary=f"[resolved] {context.get('documented_command')} now succeeds",
                    detail=f"previous blocker: {prior_failures[-1].get('summary', '')}",
                    fingerprint=fingerprint,
                )
                return str(path) if path else None
    except Exception:
        return None
    return None


def locale(user_language: str) -> str:
    return "zh" if user_language.lower().startswith("zh") else "en"


def text(user_language: str, en: str, zh: str) -> str:
    return zh if locale(user_language) == "zh" else en


def run_json(script: Path, args: List[str]) -> Dict[str, Any]:
    command = [sys.executable, str(script), *args]
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_env,
    )
    return json.loads(result.stdout)


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


def build_asset_commands(asset_data: Dict[str, Any]) -> List[Dict[str, str]]:
    commands: List[Dict[str, str]] = []
    for item in asset_data.get("manifest", []):
        group = item.get("asset_group", "asset")
        target = item.get("target_path", "")
        if item.get("status") == "present":
            commands.append({"label": "inferred", "command": f"# Found existing {group} asset path at {item.get('source_hint')}."})
        else:
            commands.append({"label": "inferred", "command": f"# Prepare {group} assets under {target} before the documented run."})

    for hint in asset_data.get("text_hints", [])[:3]:
        descriptor = hint.get("paths") or hint.get("urls") or hint.get("line", "")
        source = Path(hint.get("source", "README.md")).name
        commands.append({"label": "documented", "command": f"# Asset hint from {source}: {descriptor}"})
    return commands


def derive_dataset_hint(asset_data: Dict[str, Any]) -> str:
    for hint in asset_data.get("text_hints", []):
        if "dataset" in hint.get("line", "").lower():
            return hint.get("paths") or hint.get("urls") or "README-documented dataset"
    for item in asset_data.get("manifest", []):
        if item.get("asset_group") in {"datasets", "data"} and item.get("status") == "present":
            return item.get("source_hint", "repo-local dataset")
    return "unknown"


def derive_checkpoint_hint(asset_data: Dict[str, Any]) -> str:
    for hint in asset_data.get("text_hints", []):
        line = hint.get("line", "").lower()
        if "checkpoint" in line or "weight" in line or "model" in line:
            return hint.get("paths") or hint.get("urls") or "README-documented checkpoint"
    for item in asset_data.get("manifest", []):
        if item.get("asset_group") in {"checkpoints", "weights"} and item.get("status") == "present":
            return item.get("source_hint", "repo-local checkpoint")
    return "none"


def extract_config_path(command: str) -> str | None:
    tokens = shlex.split(command, posix=True)
    for index, token in enumerate(tokens):
        if token in {"--config", "--cfg"} and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--config="):
            return token.split("=", 1)[1]
        if token.startswith("--cfg="):
            return token.split("=", 1)[1]
    return None


def estimate_training_duration(repo_path: Path, command: str, max_train_steps: int) -> str:
    if max_train_steps > 0:
        if max_train_steps <= 200:
            return f"roughly minutes to under 1 hour for about {max_train_steps} steps, depending on dataset size and GPU throughput"
        if max_train_steps <= 5000:
            return f"roughly hours for about {max_train_steps} steps, depending on dataset size and GPU throughput"
        return f"likely many hours to multi-day for about {max_train_steps} steps, depending on dataset size and GPU throughput"

    config_rel = extract_config_path(command)
    if config_rel:
        config_path = (repo_path / config_rel).resolve()
        if config_path.exists() and config_path.suffix.lower() in {".yaml", ".yml", ".json", ".toml", ".py"}:
            text_content = config_path.read_text(encoding="utf-8", errors="replace")
            step_match = None
            for key in ["max_steps", "total_steps", "train_steps", "num_steps"]:
                step_match = re.search(rf"{key}\s*[:=]\s*(\d+)", text_content, flags=re.IGNORECASE)
                if step_match:
                    steps = int(step_match.group(1))
                    if steps <= 200:
                        return f"roughly minutes to under 1 hour from config-bound {steps} steps, depending on GPU throughput"
                    if steps <= 5000:
                        return f"roughly hours from config-bound {steps} steps, depending on GPU throughput"
                    return f"likely many hours to multi-day from config-bound {steps} steps, depending on dataset size and GPU throughput"

            epoch_match = None
            for key in ["epochs", "max_epochs", "num_epochs", "train_epochs"]:
                epoch_match = re.search(rf"{key}\s*[:=]\s*(\d+)", text_content, flags=re.IGNORECASE)
                if epoch_match:
                    epochs = int(epoch_match.group(1))
                    if epochs <= 3:
                        return f"roughly minutes to under 1 hour for about {epochs} epochs, depending on dataset size and GPU throughput"
                    if epochs <= 20:
                        return f"roughly hours for about {epochs} epochs, depending on dataset size and GPU throughput"
                    return f"likely many hours to multi-day for about {epochs} epochs, depending on dataset size and GPU throughput"

    return "unknown; likely hours to multi-day on the full dataset until a bounded schedule is confirmed"


OUT_DIR_RE = re.compile(r"--out[_-]?dir[= ]([\w./-]+)")


def command_score(command: Dict[str, Any], produced_out_dirs: frozenset = frozenset()) -> int:
    text_value = str(command.get("command", "")).lower()
    kind = command.get("kind", "run")
    score = {"run": 40, "smoke": 30, "asset": 10, "setup": 0}.get(kind, 0)

    if any(token in text_value for token in ["python ", "python3 ", "./", "whisper "]):
        score += 8
    if any(token in text_value for token in ["txt2img", "img2img", "amg.py", "transcribe", "infer", "eval"]):
        score += 8
    # Self-contained commands (pretrained init, downloadable weights) beat
    # commands that consume another documented command's training output.
    if re.search(r"--init_from=|--pretrained|https?://", text_value):
        score += 6
    out_match = OUT_DIR_RE.search(text_value)
    if out_match and out_match.group(1) in produced_out_dirs and command.get("category") != "training":
        score -= 8
    if "<" in text_value and ">" in text_value:
        score -= 10
    if text_value.startswith(("pip install", "conda install", "conda env create", "conda activate", "git clone", "cd ")):
        score -= 12
    if command.get("category") == "training":
        if "--device=cpu" in text_value:
            score += 6
        if re.search(r"--(?:max_iters|max-steps|max_steps|epochs?)[= ]\d+|--dry-run\b", text_value):
            score += 6
        if text_value.startswith(("torchrun ", "deepspeed ")) or "--nproc_per_node" in text_value:
            score -= 12
    return score


LARGE_REMOTE_MODEL_RE = re.compile(
    r"--init_from=(?:gpt2-(?:medium|large|xl)|[^\s]*(?:large|xl))\b",
    re.IGNORECASE,
)


def command_feasibility(command: Dict[str, Any], repo_path: Optional[Path]) -> tuple[bool, str]:
    text_value = str(command.get("command", ""))
    if command.get("category") != "inference":
        return True, "no static prerequisite blocker detected"
    out_match = OUT_DIR_RE.search(text_value)
    if out_match and repo_path is not None and not (repo_path / out_match.group(1)).exists():
        return False, f"required local output directory is absent: {out_match.group(1)}"
    if LARGE_REMOTE_MODEL_RE.search(text_value):
        return False, "command implies a large remote pretrained-model download"
    return True, "no static prerequisite blocker detected"


def choose_goal(commands: List[Dict[str, Any]], repo_path: Optional[Path] = None) -> Dict[str, Any]:
    produced_out_dirs = frozenset(
        match.group(1)
        for item in commands
        if item.get("category") == "training"
        for match in [OUT_DIR_RE.search(str(item.get("command", "")).lower())]
        if match
    )
    ranked = sorted(commands, key=lambda item: -command_score(item, produced_out_dirs))
    goal_candidates = [
        {
            "command": item.get("command", ""),
            "category": item.get("category"),
            "score": command_score(item, produced_out_dirs),
            "needs_substitution": bool(item.get("needs_substitution")),
            "feasible": command_feasibility(item, repo_path)[0],
            "feasibility_reason": command_feasibility(item, repo_path)[1],
        }
        for item in ranked[:3]
    ]

    for category in ["inference", "evaluation", "training", "other"]:
        candidates = [item for item in commands if item.get("category") == category]
        if not candidates:
            continue
        runnable = [
            item
            for item in candidates
            if not item.get("needs_substitution") and command_feasibility(item, repo_path)[0]
        ]
        if not runnable:
            continue
        best = max(runnable, key=lambda item: command_score(item, produced_out_dirs))
        return {
            "selected_goal": category,
            "goal_priority": category,
            "documented_command": best.get("command", ""),
            "command_source": best.get("source", "readme"),
            "documented_command_kind": best.get("kind", "run"),
            "documented_command_section": best.get("section"),
            "documented_command_source_file": best.get("source_file"),
            "requires_substitution": bool(best.get("needs_substitution")),
            "goal_candidates": goal_candidates,
        }

    return {
        "selected_goal": "repo-intake-only",
        "goal_priority": "other",
        "documented_command": "",
        "command_source": "none",
        "documented_command_kind": "none",
        "documented_command_section": None,
        "documented_command_source_file": None,
        "requires_substitution": False,
        "goal_candidates": goal_candidates,
    }


DOC_LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)\)")
DOC_PRIORITY_TOKENS = ("get_started", "getting_started", "install", "quick", "usage", "user_guide", "docs/")


def delegate_to_docs(readme_path: str, extract_script: Path, command_data: Dict[str, Any]) -> Dict[str, Any]:
    """When the README itself yields no runnable command, follow its local doc links.

    Real repos (e.g. mmsegmentation) keep all commands in docs/get_started
    files; without this the run degrades to repo-intake-only.
    """
    if any(item.get("kind") in {"run", "smoke"} for item in command_data.get("commands", [])):
        return command_data
    readme_file = Path(readme_path)
    readme_text = readme_file.read_text(encoding="utf-8-sig", errors="replace")
    links: List[tuple] = []
    for match in DOC_LINK_RE.finditer(readme_text):
        rel = match.group(1)
        if rel.startswith(("http://", "https://")):
            continue
        target = (readme_file.parent / rel).resolve()
        if target.exists() and target.suffix.lower() == ".md":
            links.append((rel, target))
    links.sort(key=lambda item: (0 if any(token in item[0].lower() for token in DOC_PRIORITY_TOKENS) else 1, len(item[0])))
    for rel, target in links[:3]:
        doc_data = run_json(extract_script, ["--readme", str(target), "--json"])
        doc_commands = doc_data.get("commands", [])
        for item in doc_commands:
            item["source_file"] = rel
        command_data["commands"].extend(doc_commands)
        if any(item.get("kind") in {"run", "smoke"} for item in doc_commands):
            command_data.setdefault("warnings", []).append(
                f"README had no runnable commands; delegated extraction to linked doc `{rel}`."
            )
            break
    return command_data


def plan_skill_chain(selected_goal: str, include_analysis_pass: bool, include_paper_gap: bool) -> List[str]:
    chain = [
        "repo-intake-and-plan",
        "env-and-assets-bootstrap",
    ]
    if include_analysis_pass:
        chain.append("analyze-project")
    chain.append("run-train" if selected_goal == "training" else "minimal-run-and-audit")
    if include_paper_gap:
        chain.append("paper-context-resolver")
    return chain


METRIC_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_.-]{1,31})\s*[:=]\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)
METRIC_NOISE_TOKENS = {"loss", "lr", "time", "mem", "epoch", "step", "iter", "iteration"}


def parse_observed_metrics(output_text: str) -> Dict[str, Any]:
    observed: Dict[str, float] = {}
    for match in METRIC_RE.finditer(output_text):
        observed[match.group(1)] = float(match.group(2))
    priority = [name for name in observed if not any(token in name.lower() for token in METRIC_NOISE_TOKENS)]
    chosen = priority[-1] if priority else (list(observed)[-1] if observed else None)
    return {
        "observed_metrics": observed,
        "best_metric": {"name": chosen, "value": observed[chosen]} if chosen else None,
    }


def parse_expected_metrics(values: List[str]) -> Dict[str, float]:
    expected: Dict[str, float] = {}
    for raw in values:
        name, separator, value_text = raw.partition("=")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"Expected metric must use NAME=VALUE syntax: {raw!r}")
        try:
            value = float(value_text.strip())
        except ValueError as exc:
            raise ValueError(f"Expected metric value is not numeric: {raw!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Expected metric value must be finite: {raw!r}")
        expected[name] = value
    return expected


def compare_expected_metrics(
    observed: Dict[str, Any],
    expected: Dict[str, float],
    absolute_tolerance: float,
) -> Dict[str, Any]:
    if not expected:
        return {
            "status": "not_evaluated",
            "reason": "No explicit expected metrics were supplied.",
            "absolute_tolerance": absolute_tolerance,
            "comparisons": [],
        }

    observed_by_key = {str(name).lower(): (str(name), value) for name, value in observed.items()}
    comparisons: List[Dict[str, Any]] = []
    for expected_name, expected_value in expected.items():
        matched_observed = observed_by_key.get(expected_name.lower())
        if matched_observed is None:
            comparisons.append(
                {
                    "metric": expected_name,
                    "expected": expected_value,
                    "observed": None,
                    "absolute_error": None,
                    "within_tolerance": False,
                    "reason": "metric_not_observed",
                }
            )
            continue
        observed_name, raw_observed_value = matched_observed
        try:
            observed_value = float(raw_observed_value)
        except (TypeError, ValueError):
            comparisons.append(
                {
                    "metric": expected_name,
                    "observed_name": observed_name,
                    "expected": expected_value,
                    "observed": raw_observed_value,
                    "absolute_error": None,
                    "within_tolerance": False,
                    "reason": "observed_value_not_numeric",
                }
            )
            continue
        absolute_error = abs(observed_value - expected_value)
        comparisons.append(
            {
                "metric": expected_name,
                "observed_name": observed_name,
                "expected": expected_value,
                "observed": observed_value,
                "absolute_error": absolute_error,
                "within_tolerance": absolute_error <= absolute_tolerance,
            }
        )

    matched = bool(comparisons) and all(item["within_tolerance"] for item in comparisons)
    return {
        "status": "matched" if matched else "mismatched",
        "reason": "All expected metrics are within tolerance." if matched else "At least one expected metric is missing or outside tolerance.",
        "absolute_tolerance": absolute_tolerance,
        "comparisons": comparisons,
    }


def maybe_run_command(
    repo_path: Path,
    command: str,
    timeout: int,
    user_language: str,
    shell_mode: str = "direct",
    runtime_root: Optional[Path] = None,
    model_adapter: Optional[Dict[str, Any]] = None,
    monitor_gpu: bool = False,
) -> Dict[str, Any]:
    if not command:
        return {
            "status": "not_run",
            "documented_command_status": "not_run",
            "execution_log": [],
            "main_blocker": text(
                user_language,
                "No documented command was extracted from README.",
                "README 中未提取到已文档化命令。",
            ),
        }

    selected_runtime_root = (runtime_root or (repo_path / "repro_outputs" / "_runtime")).resolve()
    result = run_persistent_command(
        repo=repo_path,
        command=command,
        timeout=timeout,
        runtime_root=selected_runtime_root,
        shell_mode=shell_mode,
        model_adapter=model_adapter,
        monitor_gpu=monitor_gpu,
    )
    if result.get("launch_error"):
        exc = result["launch_error"]
        return {
            "status": "blocked",
            "documented_command_status": "blocked",
            "execution_log": [f"Command failed before launch: {exc}"],
            "main_blocker": text(
                user_language,
                f"Executable not found for documented command: {exc}",
                f"文档命令缺少可执行程序：{exc}",
            ),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
        }
    if result.get("cancelled"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "execution_log": ["Command cancelled through the runtime control file."],
            "main_blocker": text(
                user_language,
                "The selected documented command was cancelled.",
                "选定的文档命令已取消。",
            ),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
        }
    if result.get("timed_out"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "execution_log": [
                item for item in [
                    f"STDOUT:\n{result.get('stdout', '').strip()}" if result.get("stdout", "").strip() else "",
                    f"STDERR:\n{result.get('stderr', '').strip()}" if result.get("stderr", "").strip() else "",
                    f"Command timed out after {timeout} seconds.",
                ] if item
            ],
            "main_blocker": text(
                user_language,
                f"Selected documented command did not finish within {timeout} seconds.",
                f"选定的文档命令未在 {timeout} 秒内完成。",
            ),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
        }

    combined: List[str] = []
    if result.get("stdout", "").strip():
        combined.append("STDOUT:\n" + result["stdout"].strip())
    if result.get("stderr", "").strip():
        combined.append("STDERR:\n" + result["stderr"].strip())

    metric_data = parse_observed_metrics("\n".join([result.get("stdout", ""), result.get("stderr", "")]))

    if result.get("returncode") == 0:
        return {
            "status": "success",
            "documented_command_status": "success",
            "execution_log": combined,
            "main_blocker": text(user_language, "None.", "无。"),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
            **metric_data,
        }

    return {
        "status": "partial",
        "documented_command_status": "partial",
        "execution_log": combined,
        **metric_data,
        "execution_mode": shell_mode,
        **runtime_metadata(result),
        "main_blocker": text(
            user_language,
            f"Selected documented command exited with code {result.get('returncode')}.",
            f"选定的文档命令以退出码 {result.get('returncode')} 结束。",
        ),
    }


def runtime_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "runtime_run_id",
        "runtime_dir",
        "runtime_status",
        "runtime_state_path",
        "runtime_events_path",
        "stdout_log_path",
        "stderr_log_path",
        "stdout_truncated",
        "stderr_truncated",
        "cancelled",
        "duration_seconds",
        "runtime_attempt",
        "runtime_retry_of",
        "resources_log_path",
        "resource_summary",
        "model_adapter",
    ]
    return {key: result.get(key) for key in keys}


def maybe_run_training(
    *,
    repo_path: Path,
    command: str,
    train_script: Path,
    lane: str,
    user_language: str,
    full_training_authorized: bool,
    train_timeout: int,
    dataset_hint: str,
    checkpoint_hint: str,
    resume_from: str,
    max_train_steps: int,
    shell_mode: str,
    runtime_root: Path,
    model_profile_json: str,
    required_model_capabilities: List[str],
    gpu_monitor_enabled: bool,
) -> Dict[str, Any]:
    if not command:
        return {
            "status": "not_run",
            "documented_command_status": "not_run",
            "execution_log": [],
            "main_blocker": text(
                user_language,
                "No documented training command was extracted from README.",
                "README 中未提取到已文档化训练命令。",
            ),
            "lane": lane,
            "run_mode": "startup_verification" if lane == "trusted" else "full_kickoff",
            "resume_from": resume_from or None,
            "dataset": dataset_hint,
            "checkpoint_source": checkpoint_hint,
            "max_steps": max_train_steps,
            "completed_steps": 0,
            "best_metric": None,
            "best_checkpoint": None,
            "stop_reason": "not_run",
            "last_epoch": None,
            "last_step": None,
            "observed_metrics": {},
            "checkpoint_candidates": [],
            "monitoring_scope": "not_run",
            "execution_mode": shell_mode,
        }

    if resume_from:
        run_mode = "resume"
    elif lane == "trusted" and not full_training_authorized:
        run_mode = "startup_verification"
    else:
        run_mode = "full_kickoff"

    training_args = [
            "--repo",
            str(repo_path),
            "--command",
            command,
            "--timeout",
            str(train_timeout),
            "--lane",
            lane,
            "--run-mode",
            run_mode,
            "--dataset",
            dataset_hint,
            "--checkpoint-source",
            checkpoint_hint,
            "--resume-from",
            resume_from,
            "--max-steps",
            str(max_train_steps),
            "--shell-mode",
            shell_mode,
            "--runtime-root",
            str(runtime_root),
        ]
    if model_profile_json:
        training_args.extend(["--model-profile-json", model_profile_json])
    for capability in required_model_capabilities:
        training_args.extend(["--require-model-capability", capability])
    if not gpu_monitor_enabled:
        training_args.append("--no-gpu-monitor")
    return run_json(train_script, training_args)


def build_context(
    *,
    chosen: Dict[str, Any],
    repo_path: Path,
    scan_data: Dict[str, Any],
    command_data: Dict[str, Any],
    setup_plan: Dict[str, Any],
    asset_data: Dict[str, Any],
    run_data: Dict[str, Any],
    user_language: str,
    run_selected: bool,
    include_analysis_pass: bool,
    include_paper_gap: bool,
    lane: str,
    full_training_authorized: bool,
    stage_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    skill_chain = plan_skill_chain(chosen["selected_goal"], include_analysis_pass, include_paper_gap)
    execution_skill = "run-train" if chosen["selected_goal"] == "training" else "minimal-run-and-audit"
    status = run_data["status"] if run_selected else "not_run"
    documented_status = (
        run_data["documented_command_status"]
        if run_selected
        else ("not_run" if not chosen["documented_command"] else "documented")
    )

    structure = scan_data.get("structure", {})
    setup_commands = setup_plan.get("setup_commands", [])
    asset_commands = build_asset_commands(asset_data)
    dataset_hint = run_data.get("dataset") or derive_dataset_hint(asset_data)
    checkpoint_hint = run_data.get("checkpoint_source") or derive_checkpoint_hint(asset_data)
    training_duration_hint = (
        estimate_training_duration(repo_path, chosen["documented_command"], int(run_data.get("max_steps") or 0))
        if chosen["selected_goal"] == "training" and chosen["documented_command"]
        else None
    )

    notes: List[str] = []
    notes.extend(scan_data.get("warnings", []))
    notes.extend(command_data.get("warnings", []))
    notes.extend(setup_plan.get("setup_notes", []))
    notes.extend(run_data.get("execution_log", []))

    assumptions = [
        "README remains the primary source of truth.",
        "Environment creation should prefer isolated setup before any semantic code changes.",
        "Model architecture should remain unchanged unless the researcher explicitly requests otherwise.",
    ]
    if chosen["selected_goal"] == "training" and lane == "trusted" and not full_training_authorized:
        assumptions.append("Only startup verification is allowed before the researcher explicitly authorizes a fuller training reproduction run.")

    unverified_inferences = [
        "Asset and dataset hints remain conservative until the repo or README confirms the exact path layout."
    ]
    protocol_deviations: List[str] = []
    human_decisions_required: List[str] = []

    if not chosen["documented_command"]:
        result_summary = text(
            user_language,
            "No documented runnable command was extracted. Repo intake was completed.",
            "未提取到可运行的文档命令，已完成仓库 intake。",
        )
    elif chosen["selected_goal"] != "training":
        result_summary = text(
            user_language,
            f"Selected goal `{chosen['selected_goal']}` from README evidence.",
            f"已根据 README 证据选择目标 `{chosen['selected_goal']}`。",
        )
    else:
        result_summary = text(
            user_language,
            "Selected the documented training command after no smaller inference or evaluation target was available.",
            "在没有更小的推理或评测目标时，已选择文档中的训练命令。",
        )

    if run_selected:
        if status == "success":
            result_summary = text(user_language, "Selected documented command finished successfully.", "选定的文档命令已成功完成。")
        elif status == "partial":
            result_summary = (
                text(
                    user_language,
                    "Selected training command produced early training evidence within the current monitoring window.",
                    "选定的训练命令已在当前监控窗口内产生早期训练证据。",
                )
                if chosen["selected_goal"] == "training"
                else text(
                    user_language,
                    "Selected documented command started but did not complete cleanly.",
                    "选定的文档命令已启动，但未完整成功结束。",
                )
            )
        elif status == "blocked":
            result_summary = (
                text(user_language, "Selected training command could not be launched.", "选定的训练命令无法启动。")
                if chosen["selected_goal"] == "training"
                else text(user_language, "Selected documented command could not be launched.", "选定的文档命令无法启动。")
            )

    section = chosen.get("documented_command_section")
    command_notes = [
        text(
            user_language,
            f"README path: {scan_data.get('readme_path') or 'not found'}",
            f"README 路径：{scan_data.get('readme_path') or 'not found'}",
        ),
        text(
            user_language,
            f"Detected top-level entries: {', '.join(structure.get('top_level', [])) or 'none'}",
            f"检测到的顶层条目：{', '.join(structure.get('top_level', [])) or 'none'}",
        ),
    ]
    if setup_plan.get("environment_file"):
        command_notes.append(f"Environment plan source: {setup_plan['environment_file']}")
    command_notes.extend(setup_plan.get("setup_notes", []))
    if chosen["documented_command"]:
        source_note = text(
            user_language,
            f"Main run label: documented from README ({chosen.get('command_source', 'readme')})",
            f"主运行标签：来自 README 的 documented（{chosen.get('command_source', 'readme')}）",
        )
        if section:
            source_note += text(user_language, f", section `{section}`", f"，章节 `{section}`")
        command_notes.append(source_note)
    command_notes.append(f"Planned skill chain: {', '.join(skill_chain)}")

    if setup_plan.get("unresolved_setup_risks"):
        human_decisions_required.extend(setup_plan["unresolved_setup_risks"])
    if chosen.get("requires_substitution"):
        human_decisions_required.append(
            "Substitute the placeholder values (<...>) in the selected documented command before execution."
        )
    if not chosen["documented_command"]:
        human_decisions_required.append("Select or confirm a documented runnable command before treating this as a reproduction run.")
    if chosen["selected_goal"] == "training" and lane == "trusted" and not full_training_authorized:
        human_decisions_required.append("Review the startup verification evidence and confirm whether to continue with a fuller training reproduction run.")
    if run_selected and status in {"partial", "blocked"}:
        human_decisions_required.append("Review the blocker before adapting commands, dependencies, or protocol-sensitive settings.")
    if include_paper_gap:
        human_decisions_required.append(
            "Provide a narrow paper question and an authoritative paper source before running paper-context-resolver."
        )

    if chosen["selected_goal"] == "training":
        if lane == "trusted" and not full_training_authorized:
            next_action = text(
                user_language,
                f"Review `train_outputs/status.json`, then decide whether to authorize a fuller training reproduction run. Planned command: `{chosen['documented_command']}`. Estimated duration: {training_duration_hint}.",
                f"先检查 `train_outputs/status.json`，再决定是否授权更完整的训练复现。计划继续执行的命令是：`{chosen['documented_command']}`。保守预估时长：{training_duration_hint}。",
            )
            next_safe_action = "Keep the repo unchanged, review startup evidence, and only continue with fuller training after explicit researcher approval."
        elif lane == "explore":
            next_action = text(
                user_language,
                "Review the recorded training evidence and continue isolated exploratory training if the variant still looks promising.",
                "先检查已记录的训练证据，如该变体仍有希望，再继续隔离的探索训练。",
            )
            next_safe_action = "Keep exploratory changes isolated and compare the recorded early metrics before widening the search."
        else:
            next_action = text(
                user_language,
                "Review the current training record and continue monitoring or resume from the latest checkpoint if needed.",
                "先检查当前训练记录，如有需要，再继续监控或从最新 checkpoint 恢复。",
            )
            next_safe_action = "Preserve the documented training semantics and continue from recorded checkpoints only if the current run remains faithful."
    else:
        next_action = (
            text(user_language, "Prepare environment and assets, then retry the documented command.", "先准备环境与资源，再重试该文档命令。")
            if status in {"partial", "blocked", "not_run"}
            else text(user_language, "Review outputs and continue with the next documented verification step.", "检查输出后继续下一步文档化验证。")
        )
        next_safe_action = (
            "Review setup assumptions and confirm the next documented command before making any semantic changes."
            if status in {"partial", "blocked", "not_run"}
            else "Review generated outputs and confirm that the next documented verification step preserves experiment meaning."
        )

    run_commands = ([{"label": "documented", "command": chosen["documented_command"]}] if chosen["documented_command"] else [])
    verification_commands = (
        [{"label": "inferred", "command": "python - <<'PY'\nimport pathlib\nprint(pathlib.Path('train_outputs/status.json').exists())\nPY"}]
        if chosen["selected_goal"] == "training"
        else []
    )
    if chosen["selected_goal"] != "training":
        comparison_status = run_data.get("result_match", {}).get("status", "not_evaluated")
        command_notes.append(text(
            user_language,
            f"No separate verification command was executed. Built-in metric comparison: `{comparison_status}`; inspect `status.json.result_match` for expected values and tolerance.",
            f"未执行单独的验证命令。内置指标比较状态为 `{comparison_status}`；期望值与容差见 `status.json.result_match`。",
        ))

    evidence = [
        text(
            user_language,
            f"Detected files: {', '.join(scan_data.get('detected_files', [])) or 'none'}",
            f"检测到的文件：{', '.join(scan_data.get('detected_files', [])) or 'none'}",
        ),
        text(
            user_language,
            f"Command categories: {json.dumps(command_data.get('counts', {}), ensure_ascii=False)}",
            f"命令分类：{json.dumps(command_data.get('counts', {}), ensure_ascii=False)}",
        ),
        text(
            user_language,
            f"Selected command kind: {chosen.get('documented_command_kind', 'none')}",
            f"已选命令类型：{chosen.get('documented_command_kind', 'none')}",
        ),
    ]
    if setup_plan.get("environment_file"):
        evidence.append(f"Environment file: {setup_plan['environment_file']}")
    if asset_data.get("text_hints"):
        evidence.append(f"Asset hints detected: {len(asset_data['text_hints'])}")

    timeline = [
        text(user_language, "Scanned repository structure and key metadata files.", "已扫描仓库结构和关键元数据文件。"),
        text(user_language, "Extracted README code blocks and shell-like commands.", "已提取 README 中的代码块和 shell 风格命令。"),
        text(user_language, f"Selected `{chosen['selected_goal']}` as the smallest trustworthy target.", f"已将 `{chosen['selected_goal']}` 选为最小可信目标。"),
        text(user_language, "Prepared conservative setup and asset assumptions.", "已准备保守的环境与资源假设。"),
        text(user_language, "Execution step was skipped." if not run_selected else "Attempted the selected documented command.", "执行步骤已跳过。" if not run_selected else "已尝试选定的文档命令。"),
    ]
    if chosen["selected_goal"] == "training":
        timeline.append(text(user_language, f"Training lane `{lane}` selected with run mode `{run_data.get('run_mode', 'startup_verification')}`.", f"已选择训练 lane `{lane}`，运行模式为 `{run_data.get('run_mode', 'startup_verification')}`。"))
        if training_duration_hint:
            timeline.append(text(user_language, f"Estimated fuller training duration: {training_duration_hint}.", f"保守估计完整训练时长：{training_duration_hint}。"))

    artifact_provenance = [
        {"artifact": "readme", "source": scan_data.get("readme_path") or "not found", "kind": "repo_file"},
        {"artifact": "documented_command", "source": chosen.get("command_source", "none"), "kind": "readme_extraction"},
        {"artifact": "environment_plan", "source": setup_plan.get("environment_file") or "inferred", "kind": "setup_plan"},
        {"artifact": "asset_manifest", "source": "artifacts/assets/asset_manifest.json", "kind": "generated"},
        {"artifact": "output_dir", "source": "repro_outputs/", "kind": "generated"},
    ]
    if chosen["selected_goal"] == "training":
        artifact_provenance.append({"artifact": "train_outputs", "source": "train_outputs/", "kind": "generated"})

    return {
        "schema_version": "1.0",
        "generated_at": scan_data.get("generated_at"),
        "user_language": user_language,
        "target_repo": str(repo_path.resolve()),
        "readme_first": True,
        "lane": lane,
        "selected_goal": chosen["selected_goal"],
        "goal_priority": chosen["goal_priority"],
        "execution_skill": execution_skill,
        "planned_skill_chain": skill_chain,
        "stage_results": stage_results,
        "status": status,
        "documented_command_status": documented_status,
        "documented_command": chosen["documented_command"] or "None extracted",
        "documented_command_kind": chosen.get("documented_command_kind", "none"),
        "documented_command_source": chosen.get("command_source", "none"),
        "documented_command_section": chosen.get("documented_command_section"),
        "documented_command_source_file": chosen.get("documented_command_source_file"),
        "requires_substitution": bool(chosen.get("requires_substitution")),
        "goal_candidates": chosen.get("goal_candidates", []),
        "evidence_level": "direct" if chosen["documented_command"] else "mixed",
        "result_summary": result_summary,
        "main_blocker": run_data.get("main_blocker", text(user_language, "No blocker recorded.", "未记录阻塞项。")),
        "next_action": next_action,
        "next_safe_action": next_safe_action,
        "setup_commands": setup_commands,
        "asset_commands": asset_commands,
        "run_commands": run_commands,
        "verification_commands": verification_commands,
        "command_notes": command_notes,
        "timeline": timeline,
        "assumptions": assumptions,
        "unverified_inferences": unverified_inferences,
        "evidence": evidence,
        "blockers": [run_data.get("main_blocker", text(user_language, "None.", "无。"))],
        "protocol_deviations": protocol_deviations,
        "human_decisions_required": human_decisions_required,
        "artifact_provenance": artifact_provenance,
        "notes": notes,
        "patches_applied": False,
        "patch_branch": "",
        "readme_fidelity": "preserved",
        "highest_patch_risk": "low",
        "verified_commits": [],
        "validation_summary": "",
        "patch_notes": [],
        "full_training_authorized": full_training_authorized,
        "requires_full_training_confirmation": chosen["selected_goal"] == "training" and lane == "trusted" and not full_training_authorized,
        "run_mode": run_data.get("run_mode", "startup_verification" if chosen["selected_goal"] == "training" else None),
        "resume_from": run_data.get("resume_from"),
        "dataset": dataset_hint,
        "checkpoint_source": checkpoint_hint,
        "full_training_command": chosen["documented_command"] if chosen["selected_goal"] == "training" else None,
        "training_duration_hint": training_duration_hint,
        "max_steps": run_data.get("max_steps"),
        "completed_steps": run_data.get("completed_steps"),
        "best_metric": run_data.get("best_metric"),
        "best_checkpoint": run_data.get("best_checkpoint"),
        "stop_reason": run_data.get("stop_reason"),
        "last_epoch": run_data.get("last_epoch"),
        "last_step": run_data.get("last_step"),
        "observed_metrics": run_data.get("observed_metrics", {}),
        "result_match": run_data.get("result_match", {"status": "not_evaluated"}),
        "checkpoint_candidates": run_data.get("checkpoint_candidates", []),
        "monitoring_scope": run_data.get("monitoring_scope"),
        "execution_mode": run_data.get("execution_mode", "direct"),
        "runtime_run_id": run_data.get("runtime_run_id"),
        "runtime_dir": run_data.get("runtime_dir"),
        "runtime_status": run_data.get("runtime_status"),
        "runtime_state_path": run_data.get("runtime_state_path"),
        "runtime_events_path": run_data.get("runtime_events_path"),
        "stdout_log_path": run_data.get("stdout_log_path"),
        "stderr_log_path": run_data.get("stderr_log_path"),
        "stdout_truncated": run_data.get("stdout_truncated", False),
        "stderr_truncated": run_data.get("stderr_truncated", False),
        "cancelled": run_data.get("cancelled", False),
        "duration_seconds": run_data.get("duration_seconds"),
        "runtime_attempt": run_data.get("runtime_attempt"),
        "runtime_retry_of": run_data.get("runtime_retry_of"),
        "resources_log_path": run_data.get("resources_log_path"),
        "resource_summary": run_data.get("resource_summary", {}),
        "model_adapter": run_data.get("model_adapter"),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run a minimal README-first reproduction orchestration.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--output-dir", default="repro_outputs", help="Directory to write standardized outputs into.")
    parser.add_argument("--source-adjacent-readme", action="store_true", help="Also write an owned RIGORPILOT_README.md beside the original README, preserving relative media paths.")
    parser.add_argument("--train-output-dir", default="", help="Optional override for the supplemental training output directory.")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Optional runtime state root (default: <output-dir>/_runtime).",
    )
    parser.add_argument("--model-profile-json", default="", help="Optional provider-neutral model identity/capability profile.")
    parser.add_argument(
        "--require-model-capability",
        action="append",
        default=[],
        help="Required model capability; repeat as needed.",
    )
    parser.add_argument("--monitor-gpu", action="store_true", help="Sample NVIDIA telemetry for non-training commands too.")
    parser.add_argument("--no-gpu-monitor", action="store_true", help="Disable NVIDIA telemetry for training commands.")
    parser.add_argument("--user-language", default="en", help="Language tag for human-readable reports.")
    parser.add_argument("--run-selected", action="store_true", help="Execute the selected documented command.")
    parser.add_argument("--include-analysis-pass", action="store_true", help="Run analyze-project and record its outputs in the stage ledger.")
    parser.add_argument(
        "--include-paper-gap",
        action="store_true",
        help="Request paper-context-resolver; records a blocked stage until a narrow question and source are supplied.",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Execution timeout in seconds for non-training documented commands.")
    parser.add_argument("--train-timeout", type=int, default=120, help="Monitoring timeout in seconds for training commands.")
    parser.add_argument("--lane", choices=["trusted", "explore"], default="trusted", help="Execution lane policy.")
    parser.add_argument("--full-training-authorized", action="store_true", help="Allow the orchestrator to proceed beyond startup verification for training.")
    parser.add_argument("--resume-from", default="", help="Optional checkpoint path to pass through to run-train.")
    parser.add_argument("--max-train-steps", type=int, default=0, help="Optional expected max train steps for reporting.")
    parser.add_argument(
        "--expected-metric",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Explicit expected metric for result matching. Repeat for multiple metrics.",
    )
    parser.add_argument(
        "--metric-absolute-tolerance",
        type=float,
        default=0.0,
        help="Maximum absolute error allowed for every --expected-metric value.",
    )
    parser.add_argument(
        "--shell-mode",
        choices=["direct", "native"],
        default="direct",
        help="Use direct argv execution by default; native shell execution requires explicit opt-in after review.",
    )
    args = parser.parse_args()

    if args.timeout <= 0 or args.train_timeout <= 0:
        parser.error("--timeout and --train-timeout must be greater than zero")
    if args.metric_absolute_tolerance < 0 or not math.isfinite(args.metric_absolute_tolerance):
        parser.error("--metric-absolute-tolerance must be a finite non-negative number")
    try:
        expected_metrics = parse_expected_metrics(args.expected_metric)
    except ValueError as exc:
        parser.error(str(exc))

    repo_path = Path(args.repo).resolve()
    source_skills_dir = Path(__file__).resolve().parents[2]
    bundled_skills_dir = SKILL_ROOT / "_bundled" / "skills"
    base_dir = (
        source_skills_dir
        if (source_skills_dir / "repo-intake-and-plan" / "scripts" / "scan_repo.py").is_file()
        else bundled_skills_dir
    )
    scan_script = base_dir / "repo-intake-and-plan" / "scripts" / "scan_repo.py"
    extract_script = base_dir / "repo-intake-and-plan" / "scripts" / "extract_commands.py"
    setup_script = base_dir / "env-and-assets-bootstrap" / "scripts" / "plan_setup.py"
    asset_script = base_dir / "env-and-assets-bootstrap" / "scripts" / "prepare_assets.py"
    repro_write_script = base_dir / "minimal-run-and-audit" / "scripts" / "write_outputs.py"
    train_write_script = base_dir / "run-train" / "scripts" / "write_outputs.py"
    train_execute_script = base_dir / "run-train" / "scripts" / "run_training.py"
    analyze_script = base_dir / "analyze-project" / "scripts" / "analyze_project.py"

    scan_data = run_json(scan_script, ["--repo", str(repo_path), "--json"])
    readme_path = scan_data.get("readme_path")
    command_data: Dict[str, Any] = {"commands": [], "counts": {}, "warnings": []}
    if readme_path:
        command_data = run_json(extract_script, ["--readme", readme_path, "--json"])
        command_data = delegate_to_docs(readme_path, extract_script, command_data)

    output_dir = Path(args.output_dir).resolve()
    train_output_dir = Path(args.train_output_dir).resolve() if args.train_output_dir else output_dir.parent / "train_outputs"
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else output_dir / "_runtime"
    try:
        model_adapter = load_model_profile(Path(args.model_profile_json) if args.model_profile_json else None)
        missing_model_capabilities = missing_capabilities(model_adapter, args.require_model_capability)
    except ModelAdapterError as exc:
        parser.error(str(exc))
    if missing_model_capabilities:
        parser.error(f"model profile is missing required capabilities: {', '.join(missing_model_capabilities)}")
    assets_root = output_dir.parent / "artifacts" / "assets"
    asset_manifest_path = assets_root / "asset_manifest.json"

    setup_plan = run_json(setup_script, ["--repo", str(repo_path), "--json"])
    asset_data = run_json(
        asset_script,
        [
            "--repo",
            str(repo_path),
            "--assets-root",
            str(assets_root),
            "--output-json",
            str(asset_manifest_path),
        ],
    )

    stage_results: List[Dict[str, Any]] = [
        {
            "stage": "repo-intake-and-plan",
            "status": "success",
            "detail": "Repository metadata and README commands were inspected.",
        },
        {
            "stage": "env-and-assets-bootstrap",
            "status": "success",
            "detail": "Setup plan and asset manifest were generated without installing dependencies.",
            "outputs": [str(asset_manifest_path)],
        },
    ]
    if args.include_analysis_pass:
        analysis_output_dir = output_dir.parent / "analysis_outputs"
        try:
            run_json(
                analyze_script,
                ["--repo", str(repo_path), "--output-dir", str(analysis_output_dir)],
            )
            stage_results.append(
                {
                    "stage": "analyze-project",
                    "status": "success",
                    "detail": "Read-only project analysis completed.",
                    "outputs": [str(analysis_output_dir / "status.json")],
                }
            )
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            stage_results.append(
                {
                    "stage": "analyze-project",
                    "status": "blocked",
                    "detail": f"Read-only project analysis failed: {type(exc).__name__}: {exc}",
                }
            )

    chosen = choose_goal(command_data.get("commands", []), repo_path)
    dataset_hint = derive_dataset_hint(asset_data)
    checkpoint_hint = derive_checkpoint_hint(asset_data)
    run_data: Dict[str, Any] = {
        "status": "not_run",
        "documented_command_status": "not_run",
        "execution_log": [],
        "main_blocker": text(args.user_language, "Execution was not requested.", "未请求执行。"),
        "lane": args.lane,
        "run_mode": "startup_verification" if chosen["selected_goal"] == "training" and args.lane == "trusted" and not args.full_training_authorized else ("full_kickoff" if chosen["selected_goal"] == "training" else None),
        "resume_from": args.resume_from or None,
        "dataset": dataset_hint,
        "checkpoint_source": checkpoint_hint,
        "max_steps": args.max_train_steps,
        "completed_steps": 0,
        "best_metric": None,
        "best_checkpoint": None,
        "stop_reason": "not_run" if chosen["selected_goal"] == "training" else None,
        "last_epoch": None,
        "last_step": None,
        "observed_metrics": {},
        "result_match": {"status": "not_evaluated", "reason": "Execution was not requested.", "comparisons": []},
        "checkpoint_candidates": [],
        "monitoring_scope": "not_run",
        "execution_mode": args.shell_mode,
        "model_adapter": model_adapter,
    }
    if args.run_selected and chosen.get("requires_substitution"):
        run_data["status"] = "not_run"
        run_data["documented_command_status"] = "not_run"
        run_data["main_blocker"] = text(
            args.user_language,
            "Documented command contains placeholder values (<...>); substitute them before execution.",
            "文档命令包含占位符（<...>），需要先替换为真实值再执行。",
        )
    elif args.run_selected:
        if chosen["selected_goal"] == "training":
            run_data = maybe_run_training(
                repo_path=repo_path,
                command=chosen["documented_command"],
                train_script=train_execute_script,
                lane=args.lane,
                user_language=args.user_language,
                full_training_authorized=args.full_training_authorized,
                train_timeout=args.train_timeout,
                dataset_hint=dataset_hint,
                checkpoint_hint=checkpoint_hint,
                resume_from=args.resume_from,
                max_train_steps=args.max_train_steps,
                shell_mode=args.shell_mode,
                runtime_root=runtime_root,
                model_profile_json=args.model_profile_json,
                required_model_capabilities=args.require_model_capability,
                gpu_monitor_enabled=not args.no_gpu_monitor,
            )
        else:
            run_data = maybe_run_command(
                repo_path,
                chosen["documented_command"],
                args.timeout,
                args.user_language,
                args.shell_mode,
                runtime_root,
                model_adapter,
                args.monitor_gpu,
            )

    run_data["result_match"] = compare_expected_metrics(
        run_data.get("observed_metrics", {}),
        expected_metrics,
        args.metric_absolute_tolerance,
    )

    execution_stage = "run-train" if chosen["selected_goal"] == "training" else "minimal-run-and-audit"
    stage_results.append(
        {
            "stage": execution_stage,
            "status": run_data["status"] if args.run_selected else "not_requested",
            "detail": (
                "Selected documented command was attempted."
                if args.run_selected
                else "Execution was not requested; no command was run."
            ),
        }
    )
    if args.include_paper_gap:
        stage_results.append(
            {
                "stage": "paper-context-resolver",
                "status": "blocked",
                "detail": "A narrow paper question and authoritative paper source were not supplied.",
            }
        )

    context = build_context(
        chosen=chosen,
        repo_path=repo_path,
        scan_data=scan_data,
        command_data=command_data,
        setup_plan=setup_plan,
        asset_data=asset_data,
        run_data=run_data,
        user_language=args.user_language,
        run_selected=args.run_selected,
        include_analysis_pass=args.include_analysis_pass,
        include_paper_gap=args.include_paper_gap,
        lane=args.lane,
        full_training_authorized=args.full_training_authorized,
        stage_results=stage_results,
    )

    context["annotated_readme"] = None
    context["readme_section_coverage"] = {}
    context["source_adjacent_readme"] = {"status": "not_requested", "path": None}
    if readme_path and Path(readme_path).exists():
        annotated_path, coverage = write_annotated_readme(
            readme_path=Path(readme_path),
            context={
                **context,
                "readme_commands": command_data.get("commands", []),
                "execution_log": run_data.get("execution_log", []),
                "local_dataset_present": any(
                    item.get("asset_group") in {"datasets", "data"} and item.get("status") == "present"
                    for item in asset_data.get("manifest", [])
                ),
            },
            output_path=output_dir / "ANNOTATED_README.md",
            source_adjacent=args.source_adjacent_readme,
            train_output_dir=train_output_dir,
        )
        context["annotated_readme"] = str(annotated_path)
        context["readme_section_coverage"] = coverage
        context["source_adjacent_readme"] = coverage["source_adjacent_readme"]
    elif args.source_adjacent_readme:
        context["source_adjacent_readme"] = {"status": "blocked", "path": None, "reason": "No source README was found; standard evidence retained."}

    write_bundle(repro_write_script, output_dir, context)
    if context["selected_goal"] == "training":
        write_bundle(train_write_script, train_output_dir, context)

    context["lesson_recorded"] = maybe_record_lesson(repo_path, context) if args.run_selected else None

    print(json.dumps(context, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
