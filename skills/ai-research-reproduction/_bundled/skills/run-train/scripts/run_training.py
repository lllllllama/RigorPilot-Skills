#!/usr/bin/env python3
"""Execute a selected training command and normalize conservative training evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SHARED_SCRIPTS = Path(__file__).resolve().parents[3] / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import run_persistent_command
from model_adapter import ModelAdapterError, load_model_profile, missing_capabilities


EPOCH_RE = re.compile(r"(?:epoch)\s*[:=\[/ ]+\s*(\d+)", flags=re.IGNORECASE)
STEP_RE = re.compile(r"(?:step|iter|iteration)\s*[:=\[/ ]+\s*(\d+)", flags=re.IGNORECASE)
CHECKPOINT_RE = re.compile(r"([\w./\\-]+\.(?:ckpt|pth|pt|bin|safetensors))", flags=re.IGNORECASE)
METRIC_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_.-]{1,31})\s*[:=]\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\d./])"
)
FRACTION_METRIC_RE = re.compile(
    r"\b(acc(?:uracy)?|precision|recall)\s*:\s*(\d+)\s*/\s*(\d+)(?:\s*\([^)]*%\))?",
    flags=re.IGNORECASE,
)
CONTEXT_METRIC_RE = re.compile(
    r"\b(train|val|valid|validation|test)\s+"
    r"(loss|acc(?:uracy)?|precision|recall|f1|auc|iou|miou|dice|bleu|rouge|ppl|perplexity|rmse|mae|reward|score)"
    r"\s*[:=]?\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
    flags=re.IGNORECASE,
)
METRIC_NAME_RE = re.compile(
    r"^(?:(?:train|val|valid|validation|test)[_.-]?)?"
    r"(?:loss|acc(?:uracy)?|precision|recall|f1(?:_score)?|auc|ap|map|iou|miou|dice|"
    r"bleu|rouge\w*|ppl|perplexity|rmse|mae|wer|cer|reward|score|psnr|ssim)$",
    flags=re.IGNORECASE,
)


def combine_logs(parts: Iterable[str]) -> str:
    return "\n".join(part for part in parts if part).strip()


def decode_stream(value: Any) -> str:
    # On POSIX, subprocess.TimeoutExpired carries captured output as bytes
    # even when the run was started with text=True.
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def parse_progress(text: str) -> Dict[str, Any]:
    last_epoch: Optional[int] = None
    last_step: Optional[int] = None
    checkpoint_candidates: List[str] = []
    observed_metrics: Dict[str, float] = {}
    best_metric: Optional[Dict[str, Any]] = None

    for match in EPOCH_RE.finditer(text):
        last_epoch = int(match.group(1))
    for match in STEP_RE.finditer(text):
        last_step = int(match.group(1))
    for match in CHECKPOINT_RE.finditer(text):
        candidate = match.group(1).replace("\\", "/")
        if candidate not in checkpoint_candidates:
            checkpoint_candidates.append(candidate)
    for match in METRIC_RE.finditer(text):
        name = match.group(1).lower()
        if not METRIC_NAME_RE.fullmatch(name):
            continue
        value = float(match.group(2))
        observed_metrics[name] = value
    for match in FRACTION_METRIC_RE.finditer(text):
        denominator = int(match.group(3))
        if denominator:
            name = "accuracy" if match.group(1).lower() in {"acc", "accuracy"} else match.group(1).lower()
            observed_metrics[name] = int(match.group(2)) / denominator
    for match in CONTEXT_METRIC_RE.finditer(text):
        prefix = "val" if match.group(1).lower() in {"valid", "validation"} else match.group(1).lower()
        metric = "acc" if match.group(2).lower() == "accuracy" else match.group(2).lower()
        observed_metrics[f"{prefix}_{metric}"] = float(match.group(3))

    priority_names = [
        name for name in observed_metrics
        if not any(token in name.lower() for token in {"loss", "error", "rmse", "mae", "wer", "cer"})
    ]
    if priority_names:
        chosen = priority_names[-1]
        best_metric = {"name": chosen, "value": observed_metrics[chosen]}
    elif observed_metrics:
        validation_losses = [name for name in observed_metrics if name.lower() in {"val_loss", "validation_loss", "valid_loss"}]
        chosen = validation_losses[-1] if validation_losses else list(observed_metrics)[-1]
        best_metric = {"name": chosen, "value": observed_metrics[chosen]}

    return {
        "last_epoch": last_epoch,
        "last_step": last_step,
        "checkpoint_candidates": checkpoint_candidates,
        "observed_metrics": observed_metrics,
        "best_metric": best_metric,
    }


def run_git(repo: Path, args: List[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        # A missing or hanging git binary must degrade to the documented
        # "git-unavailable" evidence path, not crash the runner.
        return subprocess.CompletedProcess(["git", *args], returncode=127, stdout="", stderr=str(exc))


def git_status_snapshot(repo: Path) -> Tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    probe = run_git(repo, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None, {
            "collection_method": "git-status-diff",
            "available": False,
            "reason": "git-unavailable-or-not-a-worktree",
        }

    result = run_git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    if result.returncode != 0:
        return None, {
            "collection_method": "git-status-diff",
            "available": False,
            "reason": "git-status-failed",
            "stderr": result.stderr.strip(),
        }

    snapshot: Dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            _old, _arrow, path = path.partition(" -> ")
        normalized = path.replace("\\", "/").strip()
        if normalized:
            snapshot[normalized] = status
    return snapshot, {
        "collection_method": "git-status-diff",
        "available": True,
        "status_entries": len(snapshot),
    }


def diff_status_snapshots(
    before: Optional[Dict[str, str]],
    after: Optional[Dict[str, str]],
) -> Dict[str, List[str]]:
    if before is None or after is None:
        return {
            "changed_files": [],
            "new_files": [],
            "deleted_files": [],
            "touched_paths": [],
            "touched_symbols": [],
        }

    changed_files: List[str] = []
    new_files: List[str] = []
    deleted_files: List[str] = []
    for path, status in after.items():
        previous_status = before.get(path)
        if previous_status == status:
            continue
        normalized_status = status.replace(" ", "")
        if "D" in normalized_status:
            deleted_files.append(path)
            continue
        if "?" in normalized_status or "A" in normalized_status:
            new_files.append(path)
            continue
        changed_files.append(path)

    touched_paths = []
    for path in [*changed_files, *new_files, *deleted_files]:
        if path not in touched_paths:
            touched_paths.append(path)
    return {
        "changed_files": changed_files,
        "new_files": new_files,
        "deleted_files": deleted_files,
        "touched_paths": touched_paths,
        "touched_symbols": [],
    }


def exclude_runtime_snapshot(
    repo: Path,
    runtime_dir: Path,
    snapshot: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    if snapshot is None:
        return None
    try:
        prefix = runtime_dir.resolve().relative_to(repo.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        return snapshot
    return {path: status for path, status in snapshot.items() if not path.startswith(prefix)}


def execute_command(
    repo: Path,
    command: str,
    timeout: int,
    shell_mode: str = "direct",
    runtime_root: Optional[Path] = None,
    model_adapter: Optional[Dict[str, Any]] = None,
    monitor_gpu: bool = True,
) -> Tuple[Dict[str, Any], str]:
    before_status, before_capture = git_status_snapshot(repo)
    selected_runtime_root = (runtime_root or (repo / "train_outputs" / "_runtime")).resolve()
    execution = run_persistent_command(
        repo=repo,
        command=command,
        timeout=timeout,
        runtime_root=selected_runtime_root,
        shell_mode=shell_mode,
        model_adapter=model_adapter,
        monitor_gpu=monitor_gpu,
    )
    combined_parts = [
        f"STDOUT:\n{execution['stdout'].strip()}" if execution.get("stdout", "").strip() else "",
        f"STDERR:\n{execution['stderr'].strip()}" if execution.get("stderr", "").strip() else "",
    ]
    if execution.get("timed_out"):
        combined_parts.append(f"TIMEOUT: Command exceeded the {timeout}-second monitoring window.")
    combined = combine_logs(combined_parts)
    after_status, after_capture = git_status_snapshot(repo)
    after_status = exclude_runtime_snapshot(repo, Path(execution["runtime_dir"]), after_status)
    if after_status is not None:
        after_capture["status_entries"] = len(after_status)
        after_capture["runtime_artifacts_excluded"] = True
    execution.update(diff_status_snapshots(before_status, after_status))
    execution["evidence_capture"] = {
        **after_capture,
        "before_status_entries": before_capture.get("status_entries"),
    }
    return execution, combined


def decide_outcome(
    *,
    command: str,
    run_mode: str,
    lane: str,
    timeout: int,
    execution: Dict[str, Any],
    progress: Dict[str, Any],
) -> Dict[str, Any]:
    combined_text = combine_logs([execution.get("stdout", ""), execution.get("stderr", "")])
    last_step = progress.get("last_step")
    completed_steps = last_step if last_step is not None else 0
    checkpoint_candidates = progress.get("checkpoint_candidates", [])
    best_checkpoint = checkpoint_candidates[-1] if checkpoint_candidates else None

    if execution.get("launch_error"):
        return {
            "status": "blocked",
            "documented_command_status": "blocked",
            "main_blocker": f"Executable not found for training command: {execution['launch_error']}",
            "stop_reason": "launch_failed",
            "completed_steps": completed_steps,
            "best_checkpoint": best_checkpoint,
            "best_metric": progress.get("best_metric"),
            "execution_log": [f"Command failed before launch: {execution['launch_error']}"],
            "monitoring_scope": "no_run",
        }

    if execution.get("cancelled"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "main_blocker": "The training run was cancelled through the runtime control file.",
            "stop_reason": "cancelled",
            "completed_steps": completed_steps,
            "best_checkpoint": best_checkpoint,
            "best_metric": progress.get("best_metric"),
            "execution_log": [combined_text] if combined_text else ["Training run cancelled."],
            "monitoring_scope": "runtime_cancel",
        }

    if execution.get("timed_out"):
        if run_mode == "startup_verification" and completed_steps > 0:
            return {
                "status": "partial",
                "documented_command_status": "partial",
                "main_blocker": "The run stopped after the planned startup verification window.",
                "stop_reason": "startup_verification_window_elapsed",
                "completed_steps": completed_steps,
                "best_checkpoint": best_checkpoint,
                "best_metric": progress.get("best_metric"),
                "execution_log": [combined_text],
                "monitoring_scope": f"timeout:{timeout}s",
            }
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "main_blocker": f"The run exceeded the {timeout}-second monitoring window.",
            "stop_reason": "monitoring_window_elapsed",
            "completed_steps": completed_steps,
            "best_checkpoint": best_checkpoint,
            "best_metric": progress.get("best_metric"),
            "execution_log": [combined_text],
            "monitoring_scope": f"timeout:{timeout}s",
        }

    if execution.get("returncode") == 0:
        stop_reason = "completed"
        if run_mode == "startup_verification":
            stop_reason = "startup_verified"
        elif run_mode == "short_run_verification":
            stop_reason = "short_run_verified"
        elif run_mode == "resume":
            stop_reason = "resume_checkpoint_verified"
        elif run_mode == "full_kickoff":
            stop_reason = "full_training_command_completed"

        return {
            "status": "success",
            "documented_command_status": "success",
            "main_blocker": "None.",
            "stop_reason": stop_reason,
            "completed_steps": completed_steps,
            "best_checkpoint": best_checkpoint,
            "best_metric": progress.get("best_metric"),
            "execution_log": [combined_text] if combined_text else [],
            "monitoring_scope": "process_completion",
        }

    main_blocker = f"Training command exited with code {execution.get('returncode')}."
    if not combined_text:
        combined_text = main_blocker
    return {
        "status": "partial",
        "documented_command_status": "partial",
        "main_blocker": main_blocker,
        "stop_reason": "nonzero_exit",
        "completed_steps": completed_steps,
        "best_checkpoint": best_checkpoint,
        "best_metric": progress.get("best_metric"),
        "execution_log": [combined_text],
        "monitoring_scope": "process_completion",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a conservative training command and summarize evidence.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--command", required=True, help="Selected training command.")
    parser.add_argument("--timeout", type=int, default=120, help="Monitoring timeout in seconds.")
    parser.add_argument("--lane", choices=["trusted", "explore"], default="trusted")
    parser.add_argument(
        "--run-mode",
        choices=["startup_verification", "short_run_verification", "full_kickoff", "resume"],
        default="startup_verification",
    )
    parser.add_argument("--dataset", default="unknown")
    parser.add_argument("--checkpoint-source", default="none")
    parser.add_argument("--resume-from", default="")
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument(
        "--shell-mode",
        choices=["direct", "native"],
        default="direct",
        help="Use direct argv execution by default; native shell execution requires explicit opt-in.",
    )
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Directory for persistent runtime state and streamed logs (default: <repo>/train_outputs/_runtime).",
    )
    parser.add_argument("--model-profile-json", default="", help="Optional provider-neutral model identity/capability profile.")
    parser.add_argument(
        "--require-model-capability",
        action="append",
        default=[],
        help="Required model capability; repeat as needed.",
    )
    parser.add_argument("--no-gpu-monitor", action="store_true", help="Disable NVIDIA device-level telemetry sampling.")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    repo = Path(args.repo).resolve()
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else None
    try:
        model_adapter = load_model_profile(Path(args.model_profile_json) if args.model_profile_json else None)
        missing = missing_capabilities(model_adapter, args.require_model_capability)
    except ModelAdapterError as exc:
        parser.error(str(exc))
    if missing:
        parser.error(f"model profile is missing required capabilities: {', '.join(missing)}")
    execution, combined = execute_command(
        repo,
        args.command,
        args.timeout,
        args.shell_mode,
        runtime_root,
        model_adapter,
        not args.no_gpu_monitor,
    )
    progress = parse_progress(combine_logs([execution.get("stdout", ""), execution.get("stderr", "")]))
    outcome = decide_outcome(
        command=args.command,
        run_mode=args.run_mode,
        lane=args.lane,
        timeout=args.timeout,
        execution=execution,
        progress=progress,
    )

    payload = {
        "lane": args.lane,
        "run_mode": args.run_mode,
        "resume_from": args.resume_from or None,
        "dataset": args.dataset,
        "checkpoint_source": args.checkpoint_source,
        "max_steps": args.max_steps,
        "completed_steps": outcome["completed_steps"],
        "best_metric": outcome["best_metric"],
        "best_checkpoint": outcome["best_checkpoint"],
        "stop_reason": outcome["stop_reason"],
        "status": outcome["status"],
        "documented_command_status": outcome["documented_command_status"],
        "main_blocker": outcome["main_blocker"],
        "execution_log": outcome["execution_log"],
        "last_epoch": progress.get("last_epoch"),
        "last_step": progress.get("last_step"),
        "observed_metrics": progress.get("observed_metrics", {}),
        "checkpoint_candidates": progress.get("checkpoint_candidates", []),
        "monitoring_scope": outcome["monitoring_scope"],
        "execution_mode": execution.get("execution_mode", args.shell_mode),
        "runtime_run_id": execution.get("runtime_run_id"),
        "runtime_dir": execution.get("runtime_dir"),
        "runtime_status": execution.get("runtime_status"),
        "runtime_state_path": execution.get("runtime_state_path"),
        "runtime_events_path": execution.get("runtime_events_path"),
        "stdout_log_path": execution.get("stdout_log_path"),
        "stderr_log_path": execution.get("stderr_log_path"),
        "stdout_truncated": execution.get("stdout_truncated", False),
        "stderr_truncated": execution.get("stderr_truncated", False),
        "cancelled": execution.get("cancelled", False),
        "duration_seconds": execution.get("duration_seconds"),
        "runtime_attempt": execution.get("runtime_attempt", 1),
        "runtime_retry_of": execution.get("runtime_retry_of"),
        "resources_log_path": execution.get("resources_log_path"),
        "resource_summary": execution.get("resource_summary", {}),
        "model_adapter": execution.get("model_adapter"),
        "changed_files": execution.get("changed_files", []),
        "new_files": execution.get("new_files", []),
        "deleted_files": execution.get("deleted_files", []),
        "touched_paths": execution.get("touched_paths", []),
        "touched_symbols": execution.get("touched_symbols", []),
        "evidence_capture": execution.get("evidence_capture", {}),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
