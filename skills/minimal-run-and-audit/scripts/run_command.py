#!/usr/bin/env python3
"""Execute a short non-training command and normalize the evidence."""

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


def parse_metrics(text: str) -> Dict[str, Any]:
    observed_metrics: Dict[str, float] = {}
    best_metric: Optional[Dict[str, Any]] = None

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
    monitor_gpu: bool = False,
) -> Dict[str, Any]:
    before_status, before_capture = git_status_snapshot(repo)
    selected_runtime_root = (runtime_root or (repo / "repro_outputs" / "_runtime")).resolve()
    execution = run_persistent_command(
        repo=repo,
        command=command,
        timeout=timeout,
        runtime_root=selected_runtime_root,
        shell_mode=shell_mode,
        model_adapter=model_adapter,
        monitor_gpu=monitor_gpu,
    )
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
    return execution


def decide_outcome(command: str, timeout: int, execution: Dict[str, Any], metric_data: Dict[str, Any]) -> Dict[str, Any]:
    combined_text = combine_logs(
        [
            f"STDOUT:\n{execution['stdout'].strip()}" if execution.get("stdout", "").strip() else "",
            f"STDERR:\n{execution['stderr'].strip()}" if execution.get("stderr", "").strip() else "",
        ]
    )

    if execution.get("launch_error"):
        return {
            "status": "blocked",
            "documented_command_status": "blocked",
            "main_blocker": f"Executable not found for command: {execution['launch_error']}",
            "execution_log": [f"Command failed before launch: {execution['launch_error']}"],
            "monitoring_scope": "no_run",
        }

    if execution.get("cancelled"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "main_blocker": "The selected command was cancelled through the runtime control file.",
            "execution_log": [combined_text] if combined_text else ["Command cancelled."],
            "monitoring_scope": "runtime_cancel",
        }

    if execution.get("timed_out"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "main_blocker": f"Selected command did not finish within {timeout} seconds.",
            "execution_log": [combined_text or f"Command timed out after {timeout} seconds."],
            "monitoring_scope": f"timeout:{timeout}s",
        }

    if execution.get("returncode") == 0:
        return {
            "status": "success",
            "documented_command_status": "success",
            "main_blocker": "None.",
            "execution_log": [combined_text] if combined_text else [],
            "monitoring_scope": "process_completion",
        }

    return {
        "status": "partial",
        "documented_command_status": "partial",
        "main_blocker": f"Selected command exited with code {execution.get('returncode')}.",
        "execution_log": [combined_text] if combined_text else [f"Command `{command}` exited non-zero."],
        "monitoring_scope": "process_completion",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a short non-training command and summarize the evidence.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--command", required=True, help="Command to execute.")
    parser.add_argument("--timeout", type=int, default=60, help="Execution timeout in seconds.")
    parser.add_argument(
        "--shell-mode",
        choices=["direct", "native"],
        default="direct",
        help="Use direct argv execution by default; native shell execution requires explicit opt-in.",
    )
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Directory for persistent runtime state and streamed logs (default: <repo>/repro_outputs/_runtime).",
    )
    parser.add_argument("--model-profile-json", default="", help="Optional provider-neutral model identity/capability profile.")
    parser.add_argument(
        "--require-model-capability",
        action="append",
        default=[],
        help="Required model capability; repeat as needed.",
    )
    parser.add_argument("--monitor-gpu", action="store_true", help="Sample NVIDIA device-level telemetry when available.")
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
    execution = execute_command(
        repo,
        args.command,
        args.timeout,
        args.shell_mode,
        runtime_root,
        model_adapter,
        args.monitor_gpu,
    )
    metric_data = parse_metrics(combine_logs([execution.get("stdout", ""), execution.get("stderr", "")]))
    outcome = decide_outcome(args.command, args.timeout, execution, metric_data)

    payload = {
        "status": outcome["status"],
        "documented_command_status": outcome["documented_command_status"],
        "main_blocker": outcome["main_blocker"],
        "execution_log": outcome["execution_log"],
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
        "best_metric": metric_data["best_metric"],
        "observed_metrics": metric_data["observed_metrics"],
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
