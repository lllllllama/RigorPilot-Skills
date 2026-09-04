#!/usr/bin/env python3
"""Persistent, streaming subprocess runtime for reproducible agent runs."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from command_utils import ShellSyntaxRequired, build_command
from resource_monitor import append_resource_sample, sample_resources


SCHEMA_VERSION = "1.0"
TERMINAL_STATES = {"success", "failed", "timed_out", "cancelled", "blocked", "interrupted"}
ACTIVE_STATES = {"created", "running", "orphaned"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the sibling name short: exploratory Git worktrees can already sit
    # close to the legacy Windows MAX_PATH boundary.
    temporary = path.with_name(f".{uuid.uuid4().hex[:4]}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class TailBuffer:
    """Retain the newest text up to a fixed character budget."""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, limit)
        self.value = ""
        self.truncated = False
        self.lock = threading.Lock()

    def append(self, chunk: str) -> None:
        with self.lock:
            combined = self.value + chunk
            if len(combined) > self.limit:
                self.truncated = True
                combined = combined[-self.limit :] if self.limit else ""
            self.value = combined

    def get(self) -> str:
        with self.lock:
            return self.value


class RuntimeJournal:
    def __init__(self, run_dir: Path, state: Dict[str, Any]) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "state.json"
        self.events_path = run_dir / "events.jsonl"
        self.state = state
        self.sequence = 0
        self.lock = threading.Lock()
        atomic_write_json(self.state_path, self.state)

    def event(self, event_type: str, **data: Any) -> None:
        with self.lock:
            self.sequence += 1
            payload = {
                "schema_version": SCHEMA_VERSION,
                "sequence": self.sequence,
                "timestamp": utc_now(),
                "type": event_type,
                "data": data,
            }
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def update(self, **changes: Any) -> None:
        with self.lock:
            self.state.update(changes)
            atomic_write_json(self.state_path, self.state)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def append_existing_event(run_dir: Path, event_type: str, **data: Any) -> None:
    events_path = run_dir / "events.jsonl"
    sequence = 0
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                sequence = max(sequence, int(json.loads(line).get("sequence") or 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence + 1,
        "timestamp": utc_now(),
        "type": event_type,
        "data": data,
    }
    with events_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def pid_is_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x00100000, 0, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def timestamp_age_seconds(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def reconcile_run(run_dir: Path, stale_after_seconds: float = 30.0) -> Dict[str, Any]:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        return {"run_id": run_dir.name, "status": "invalid", "reason": "missing-state"}
    try:
        state = read_json(state_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"run_id": run_dir.name, "status": "invalid", "reason": f"unreadable-state:{type(exc).__name__}"}
    status = str(state.get("status") or "invalid")
    if status not in ACTIVE_STATES:
        return {"run_id": state.get("run_id", run_dir.name), "status": status, "action": "unchanged"}

    pid = state.get("pid")
    alive = pid_is_alive(pid if isinstance(pid, int) else None)
    heartbeat_age = timestamp_age_seconds(state.get("last_heartbeat"))
    if alive and heartbeat_age is not None and heartbeat_age <= stale_after_seconds and status != "orphaned":
        return {"run_id": state.get("run_id", run_dir.name), "status": status, "action": "active"}
    if alive:
        if status == "orphaned":
            return {"run_id": state.get("run_id", run_dir.name), "status": "orphaned", "action": "unchanged-orphaned"}
        state.update(status="orphaned", recovery_checked_at=utc_now(), recovery_reason="stale-heartbeat-process-alive")
        atomic_write_json(state_path, state)
        append_existing_event(run_dir, "recovered_orphaned", pid=pid, heartbeat_age_seconds=heartbeat_age)
        return {"run_id": state.get("run_id", run_dir.name), "status": "orphaned", "action": "marked-orphaned"}

    finished_at = utc_now()
    state.update(
        status="interrupted",
        finished_at=finished_at,
        last_heartbeat=finished_at,
        recovery_checked_at=finished_at,
        recovery_reason="process-not-running",
    )
    atomic_write_json(state_path, state)
    append_existing_event(run_dir, "recovered_interrupted", prior_status=status, pid=pid)
    return {"run_id": state.get("run_id", run_dir.name), "status": "interrupted", "action": "marked-interrupted"}


def recover_runtime_root(runtime_root: Path, stale_after_seconds: float = 30.0) -> list[Dict[str, Any]]:
    root = Path(runtime_root).resolve()
    if not root.is_dir():
        return []
    return [reconcile_run(path, stale_after_seconds) for path in sorted(root.iterdir()) if path.is_dir()]


def request_cancel(runtime_root: Path, run_id: str) -> Dict[str, Any]:
    run_dir = Path(runtime_root).resolve() / run_id
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"Unknown runtime run: {run_id}")
    state = read_json(state_path)
    if state.get("status") in TERMINAL_STATES:
        return {"run_id": run_id, "status": state.get("status"), "cancel_requested": False}
    if state.get("status") == "orphaned":
        return {
            "run_id": run_id,
            "status": "orphaned",
            "cancel_requested": False,
            "reason": "orphaned-run-requires-explicit-process-inspection",
        }
    (run_dir / "CANCEL").touch()
    return {"run_id": run_id, "status": state.get("status"), "cancel_requested": True}


def list_runs(runtime_root: Path) -> list[Dict[str, Any]]:
    root = Path(runtime_root).resolve()
    if not root.is_dir():
        return []
    rows = []
    for run_dir in sorted(root.iterdir()):
        state_path = run_dir / "state.json"
        if not run_dir.is_dir() or not state_path.is_file():
            continue
        try:
            state = read_json(state_path)
            rows.append(
                {
                    "run_id": state.get("run_id", run_dir.name),
                    "status": state.get("status"),
                    "attempt": state.get("attempt", 1),
                    "retry_of": state.get("retry_of"),
                    "pid": state.get("pid"),
                    "last_heartbeat": state.get("last_heartbeat"),
                }
            )
        except (OSError, json.JSONDecodeError):
            rows.append({"run_id": run_dir.name, "status": "invalid"})
    return rows


def _stream_reader(
    stream: Any,
    log_path: Path,
    stream_name: str,
    capture: TailBuffer,
    journal: RuntimeJournal,
) -> None:
    total_chars = 0
    with log_path.open("w", encoding="utf-8", newline="") as log:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            log.write(chunk)
            log.flush()
            capture.append(chunk)
            total_chars += len(chunk)
            journal.event("stream_chunk", stream=stream_name, characters=len(chunk))
    journal.event("stream_closed", stream=stream_name, characters=total_chars)


def _terminate_process_tree(process: subprocess.Popen[str], journal: RuntimeJournal) -> None:
    if process.poll() is not None:
        return
    journal.event("termination_requested", pid=process.pid)
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            journal.event("taskkill_finished", returncode=result.returncode)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            journal.event("taskkill_failed", error=str(exc))
            try:
                process.terminate()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.terminate()
            except OSError:
                pass

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        journal.event("termination_escalated", pid=process.pid)
        if os.name == "nt":
            try:
                process.kill()
            except OSError:
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.kill()
                except OSError:
                    pass


def record_resource_snapshot(
    *,
    pid: int,
    resources_path: Path,
    summary: Dict[str, Any],
    journal: RuntimeJournal,
    include_gpu: bool,
) -> None:
    try:
        sample = sample_resources(pid, include_gpu=include_gpu)
        append_resource_sample(resources_path, sample)
    except Exception as exc:
        journal.event("resource_sample_failed", error=f"{type(exc).__name__}: {exc}")
        return
    process = sample.get("process") or {}
    accelerators = sample.get("accelerators") or {}
    summary["samples"] = int(summary.get("samples") or 0) + 1
    rss = process.get("rss_bytes")
    cpu = process.get("cpu_seconds")
    if isinstance(rss, int):
        summary["max_root_process_rss_bytes"] = max(int(summary.get("max_root_process_rss_bytes") or 0), rss)
    if isinstance(cpu, (int, float)):
        summary["max_root_process_cpu_seconds"] = max(float(summary.get("max_root_process_cpu_seconds") or 0.0), float(cpu))
    if accelerators.get("available"):
        summary["gpu_sampling_available"] = True
        peaks = summary.setdefault("max_device_gpu_memory_used_mib", {})
        for device in accelerators.get("devices") or []:
            key = str(device.get("uuid") or device.get("index"))
            used = device.get("memory_used_mib")
            if isinstance(used, (int, float)):
                peaks[key] = max(float(peaks.get(key) or 0.0), float(used))
    journal.event(
        "resource_sample",
        root_process_available=bool(process.get("available")),
        rss_bytes=rss,
        cpu_seconds=cpu,
        gpu_sampled=include_gpu,
        gpu_available=bool(accelerators.get("available")),
    )


def run_persistent_command(
    *,
    repo: Path,
    command: str,
    timeout: int,
    runtime_root: Path,
    shell_mode: str = "direct",
    run_id: Optional[str] = None,
    capture_limit: int = 1_048_576,
    heartbeat_interval: float = 1.0,
    model_adapter: Optional[Dict[str, Any]] = None,
    retry_of: Optional[str] = None,
    attempt: int = 1,
    monitor_gpu: bool = False,
) -> Dict[str, Any]:
    """Run a command with durable state, append-only events, and streamed logs."""

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if capture_limit < 0:
        raise ValueError("capture_limit must be non-negative")
    if attempt < 1:
        raise ValueError("attempt must be at least one")
    repo = Path(repo).resolve()
    runtime_root = Path(runtime_root).resolve()
    run_id = run_id or new_run_id()
    run_dir = runtime_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    started_monotonic = time.monotonic()
    spec = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "command": command,
        "cwd": str(repo),
        "timeout_seconds": timeout,
        "shell_mode": shell_mode,
        "capture_limit_characters": capture_limit,
        "model_adapter": model_adapter,
        "retry_of": retry_of,
        "attempt": attempt,
        "resource_monitoring": {
            "root_process": True,
            "nvidia_device_global": monitor_gpu,
        },
        "created_at": started_at,
    }
    atomic_write_json(run_dir / "spec.json", spec)
    state: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "attempt": attempt,
        "retry_of": retry_of,
        "status": "created",
        "created_at": started_at,
        "started_at": None,
        "finished_at": None,
        "last_heartbeat": started_at,
        "pid": None,
        "returncode": None,
        "timed_out": False,
        "cancelled": False,
        "launch_error": None,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "model_adapter": model_adapter,
        "resource_summary": {
            "scope": "root_process_and_optional_device_global",
            "samples": 0,
            "max_root_process_rss_bytes": 0,
            "max_root_process_cpu_seconds": 0.0,
            "gpu_sampling_available": False,
            "max_device_gpu_memory_used_mib": {},
        },
    }
    journal = RuntimeJournal(run_dir, state)
    journal.event("created")
    stdout_capture = TailBuffer(capture_limit)
    stderr_capture = TailBuffer(capture_limit)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    resources_path = run_dir / "resources.jsonl"
    stdout_path.touch()
    stderr_path.touch()
    resources_path.touch()

    try:
        argv = build_command(command, shell_mode)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            argv,
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except (FileNotFoundError, ShellSyntaxRequired, OSError, ValueError) as exc:
        finished_at = utc_now()
        journal.update(
            status="blocked",
            finished_at=finished_at,
            last_heartbeat=finished_at,
            launch_error=str(exc),
        )
        journal.event("launch_failed", error=str(exc))
        return _result_payload(journal.state, run_dir, stdout_capture, stderr_capture, shell_mode, started_monotonic)

    journal.event("started", pid=process.pid)
    journal.update(status="running", started_at=utc_now(), pid=process.pid, last_heartbeat=utc_now())
    resource_summary = journal.state["resource_summary"]
    record_resource_snapshot(
        pid=process.pid,
        resources_path=resources_path,
        summary=resource_summary,
        journal=journal,
        include_gpu=monitor_gpu,
    )
    journal.update(resource_summary=resource_summary)
    threads = [
        threading.Thread(
            target=_stream_reader,
            args=(process.stdout, stdout_path, "stdout", stdout_capture, journal),
            daemon=True,
        ),
        threading.Thread(
            target=_stream_reader,
            args=(process.stderr, stderr_path, "stderr", stderr_capture, journal),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    cancelled = False
    cancel_path = run_dir / "CANCEL"
    next_heartbeat = time.monotonic() + max(0.1, heartbeat_interval)
    next_gpu_sample = time.monotonic() + 5.0
    try:
        while process.poll() is None:
            now = time.monotonic()
            if cancel_path.exists():
                cancelled = True
                journal.event("cancel_detected", source="CANCEL")
                _terminate_process_tree(process, journal)
                break
            if timeout >= 0 and now - started_monotonic >= timeout:
                timed_out = True
                journal.event("timeout_detected", timeout_seconds=timeout)
                _terminate_process_tree(process, journal)
                break
            if now >= next_heartbeat:
                include_gpu = monitor_gpu and now >= next_gpu_sample
                record_resource_snapshot(
                    pid=process.pid,
                    resources_path=resources_path,
                    summary=resource_summary,
                    journal=journal,
                    include_gpu=include_gpu,
                )
                if include_gpu:
                    next_gpu_sample = now + 5.0
                journal.update(last_heartbeat=utc_now(), resource_summary=resource_summary)
                journal.event("heartbeat", pid=process.pid)
                next_heartbeat = now + max(0.1, heartbeat_interval)
            time.sleep(0.05)
    except KeyboardInterrupt:
        cancelled = True
        journal.event("cancel_detected", source="keyboard_interrupt")
        _terminate_process_tree(process, journal)

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process, journal)
        returncode = process.poll()
    for thread in threads:
        thread.join(timeout=5)

    if cancelled:
        status = "cancelled"
    elif timed_out:
        status = "timed_out"
    elif returncode == 0:
        status = "success"
    else:
        status = "failed"
    finished_at = utc_now()
    journal.update(
        status=status,
        finished_at=finished_at,
        last_heartbeat=finished_at,
        returncode=returncode,
        timed_out=timed_out,
        cancelled=cancelled,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        resource_summary=resource_summary,
    )
    journal.event("completed", status=status, returncode=returncode)
    return _result_payload(journal.state, run_dir, stdout_capture, stderr_capture, shell_mode, started_monotonic)


def _result_payload(
    state: Dict[str, Any],
    run_dir: Path,
    stdout_capture: TailBuffer,
    stderr_capture: TailBuffer,
    shell_mode: str,
    started_monotonic: float,
) -> Dict[str, Any]:
    return {
        "returncode": state.get("returncode"),
        "timed_out": bool(state.get("timed_out")),
        "cancelled": bool(state.get("cancelled")),
        "launch_error": state.get("launch_error"),
        "execution_mode": shell_mode,
        "stdout": stdout_capture.get(),
        "stderr": stderr_capture.get(),
        "stdout_truncated": stdout_capture.truncated,
        "stderr_truncated": stderr_capture.truncated,
        "runtime_run_id": state["run_id"],
        "runtime_dir": str(run_dir),
        "runtime_status": state["status"],
        "runtime_attempt": state.get("attempt", 1),
        "runtime_retry_of": state.get("retry_of"),
        "runtime_state_path": str(run_dir / "state.json"),
        "runtime_events_path": str(run_dir / "events.jsonl"),
        "stdout_log_path": str(run_dir / "stdout.log"),
        "stderr_log_path": str(run_dir / "stderr.log"),
        "resources_log_path": str(run_dir / "resources.jsonl"),
        "resource_summary": state.get("resource_summary", {}),
        "model_adapter": state.get("model_adapter"),
        "pid": state.get("pid"),
        "duration_seconds": round(time.monotonic() - started_monotonic, 6),
    }


def retry_run(
    *,
    runtime_root: Path,
    run_id: str,
    timeout: Optional[int] = None,
    allow_success_retry: bool = False,
) -> Dict[str, Any]:
    root = Path(runtime_root).resolve()
    parent_dir = root / run_id
    state_path = parent_dir / "state.json"
    spec_path = parent_dir / "spec.json"
    if not state_path.is_file() or not spec_path.is_file():
        raise FileNotFoundError(f"Unknown or incomplete runtime run: {run_id}")
    recovery = reconcile_run(parent_dir)
    state = read_json(state_path)
    status = str(state.get("status") or recovery.get("status"))
    if status in ACTIVE_STATES:
        raise RuntimeError(f"Run {run_id} is still active or orphaned ({status}); refusing duplicate execution")
    if status == "success" and not allow_success_retry:
        raise RuntimeError(f"Run {run_id} already succeeded; use allow_success_retry only when repetition is intentional")
    spec = read_json(spec_path)
    selected_timeout = int(timeout if timeout is not None else spec.get("timeout_seconds", 60))
    if selected_timeout <= 0:
        raise ValueError("retry timeout must be greater than zero")
    return run_persistent_command(
        repo=Path(spec["cwd"]),
        command=str(spec["command"]),
        timeout=selected_timeout,
        runtime_root=root,
        shell_mode=str(spec.get("shell_mode") or "direct"),
        capture_limit=int(spec.get("capture_limit_characters") or 1_048_576),
        model_adapter=spec.get("model_adapter"),
        retry_of=run_id,
        attempt=int(state.get("attempt") or 1) + 1,
        monitor_gpu=bool((spec.get("resource_monitoring") or {}).get("nvidia_device_global")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and recover persistent RigorPilot runtime runs.")
    parser.add_argument("--runtime-root", required=True, help="Runtime root containing per-run directories.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("list", help="List durable run states.")
    recover_parser = subparsers.add_parser("recover", help="Reconcile stale active states after a controller restart.")
    recover_parser.add_argument("--stale-after", type=float, default=30.0)
    cancel_parser = subparsers.add_parser("cancel", help="Write a cancellation request for an actively monitored run.")
    cancel_parser.add_argument("--run-id", required=True)
    retry_parser = subparsers.add_parser("retry", help="Explicitly retry a terminal run as a new attempt.")
    retry_parser.add_argument("--run-id", required=True)
    retry_parser.add_argument("--timeout", type=int)
    retry_parser.add_argument("--allow-success-retry", action="store_true")
    args = parser.parse_args()
    root = Path(args.runtime_root)
    if args.action == "recover" and args.stale_after < 0:
        parser.error("--stale-after must be non-negative")
    try:
        if args.action == "list":
            payload: Any = list_runs(root)
        elif args.action == "recover":
            payload = recover_runtime_root(root, args.stale_after)
        elif args.action == "cancel":
            payload = request_cancel(root, args.run_id)
        else:
            payload = retry_run(
                runtime_root=root,
                run_id=args.run_id,
                timeout=args.timeout,
                allow_success_retry=args.allow_success_retry,
            )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
