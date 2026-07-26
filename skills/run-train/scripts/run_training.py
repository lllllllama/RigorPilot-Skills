#!/usr/bin/env python3
"""Execute a selected training command and normalize conservative training evidence."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


EPOCH_RE = re.compile(r"(?:epoch)\s*[:=\[/ ]+\s*(\d+)", flags=re.IGNORECASE)
STEP_RE = re.compile(r"(?:step|iter|iteration)\s*[:=\[/ ]+\s*(\d+)", flags=re.IGNORECASE)
CHECKPOINT_RE = re.compile(r"([\w./\\-]+\.(?:ckpt|pth|pt|bin|safetensors))", flags=re.IGNORECASE)
METRIC_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_.-]{1,31})\s*[:=]\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
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
        name = match.group(1)
        value = float(match.group(2))
        observed_metrics[name] = value

    priority_names = [
        name for name in observed_metrics
        if not any(token in name.lower() for token in {"loss", "lr", "time", "mem", "epoch", "step", "iter", "iteration"})
    ]
    if priority_names:
        chosen = priority_names[-1]
        best_metric = {"name": chosen, "value": observed_metrics[chosen]}
    elif observed_metrics:
        chosen = list(observed_metrics)[-1]
        best_metric = {"name": chosen, "value": observed_metrics[chosen]}

    return {
        "last_epoch": last_epoch,
        "last_step": last_step,
        "checkpoint_candidates": checkpoint_candidates,
        "observed_metrics": observed_metrics,
        "best_metric": best_metric,
    }


def split_command(command: str) -> List[str]:
    return shlex.split(command, posix=True)


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


def execute_command(repo: Path, command: str, timeout: int) -> Tuple[Dict[str, Any], str]:
    before_status, before_capture = git_status_snapshot(repo)
    try:
        result = subprocess.run(
            split_command(command),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        combined = combine_logs(
            [
                f"STDOUT:\n{result.stdout.strip()}" if result.stdout.strip() else "",
                f"STDERR:\n{result.stderr.strip()}" if result.stderr.strip() else "",
            ]
        )
        execution = {
            "returncode": result.returncode,
            "timed_out": False,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
        after_status, after_capture = git_status_snapshot(repo)
        execution.update(diff_status_snapshots(before_status, after_status))
        execution["evidence_capture"] = {
            **after_capture,
            "before_status_entries": before_capture.get("status_entries"),
        }
        return execution, combined
    except FileNotFoundError as exc:
        return {
            "returncode": None,
            "timed_out": False,
            "launch_error": str(exc),
            "stdout": "",
            "stderr": "",
            "changed_files": [],
            "new_files": [],
            "deleted_files": [],
            "touched_paths": [],
            "touched_symbols": [],
            "evidence_capture": before_capture,
        }, f"Command failed before launch: {exc}"
    except subprocess.TimeoutExpired as exc:
        stdout = decode_stream(exc.stdout)
        stderr = decode_stream(exc.stderr)
        combined = combine_logs(
            [
                f"STDOUT:\n{stdout.strip()}" if stdout.strip() else "",
                f"STDERR:\n{stderr.strip()}" if stderr.strip() else "",
                f"TIMEOUT: Command exceeded the {timeout}-second monitoring window.",
            ]
        )
        execution = {
            "returncode": None,
            "timed_out": True,
            "stdout": stdout,
            "stderr": stderr,
        }
        after_status, after_capture = git_status_snapshot(repo)
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
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    execution, combined = execute_command(repo, args.command, args.timeout)
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
