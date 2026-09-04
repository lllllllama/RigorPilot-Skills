#!/usr/bin/env python3
"""Durable, single-host task queue for reproducible research commands."""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from model_adapter import normalize_model_profile
from runtime_runner import (
    ACTIVE_STATES as RUNTIME_ACTIVE_STATES,
    TERMINAL_STATES as RUNTIME_TERMINAL_STATES,
    atomic_write_json,
    new_run_id,
    pid_is_alive,
    read_json,
    reconcile_run,
    request_cancel,
    run_persistent_command,
    utc_now,
)


SCHEMA_VERSION = "1.0"
JOB_TERMINAL_STATES = {
    "success",
    "failed",
    "timed_out",
    "cancelled",
    "blocked",
    "interrupted",
    "skipped",
}
JOB_ACTIVE_STATES = {"queued", "running", "orphaned"}
FAILURE_STATES = JOB_TERMINAL_STATES - {"success"}
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _queue_id() -> str:
    return f"queue-{uuid.uuid4().hex[:12]}"


def _job_id() -> str:
    return f"job-{uuid.uuid4().hex[:12]}"


def _read_optional_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return read_json(path)


class QueueLease:
    """Cross-process single-writer lease for queue mutations."""

    def __init__(self, queue_root: Path, purpose: str) -> None:
        self.queue_root = Path(queue_root).resolve()
        self.path = self.queue_root / "scheduler.lock.json"
        self.purpose = purpose
        self.lease_id = uuid.uuid4().hex
        self.payload: Dict[str, Any] = {}
        self.replaced_stale: Optional[Dict[str, Any]] = None

    def acquire(self) -> "QueueLease":
        self.queue_root.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                existing = _read_optional_json(self.path) or {}
                existing_pid = existing.get("pid")
                if isinstance(existing_pid, int) and pid_is_alive(existing_pid):
                    raise RuntimeError(
                        f"Queue already has an active writer (pid={existing_pid}, purpose={existing.get('purpose')})"
                    )
                self.replaced_stale = existing
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            self.payload = {
                "schema_version": SCHEMA_VERSION,
                "lease_id": self.lease_id,
                "pid": os.getpid(),
                "purpose": self.purpose,
                "acquired_at": utc_now(),
                "heartbeat_at": utc_now(),
            }
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(self.payload, indent=2, ensure_ascii=False) + "\n")
            return self
        raise RuntimeError("Could not acquire queue writer lease")

    def heartbeat(self) -> None:
        self.payload["heartbeat_at"] = utc_now()
        atomic_write_json(self.path, self.payload)

    def release(self) -> None:
        existing = _read_optional_json(self.path)
        if existing and existing.get("lease_id") == self.lease_id:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "QueueLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


class QueueStore:
    """Thread-safe atomic queue state plus an append-only transition journal."""

    def __init__(self, queue_root: Path) -> None:
        self.root = Path(queue_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "queue.json"
        self.events_path = self.root / "events.jsonl"
        self.control_root = self.root / "control" / "cancel"
        self.lock = threading.RLock()
        if self.state_path.is_file():
            self.state = read_json(self.state_path)
        else:
            now = utc_now()
            self.state = {
                "schema_version": SCHEMA_VERSION,
                "queue_id": _queue_id(),
                "created_at": now,
                "updated_at": now,
                "event_sequence": 0,
                "scheduler": {"status": "idle"},
                "jobs": [],
            }
            self.persist()

    def persist(self) -> None:
        with self.lock:
            self.state["updated_at"] = utc_now()
            atomic_write_json(self.state_path, self.state)

    def event(self, event_type: str, **data: Any) -> None:
        with self.lock:
            sequence = int(self.state.get("event_sequence") or 0) + 1
            self.state["event_sequence"] = sequence
            payload = {
                "schema_version": SCHEMA_VERSION,
                "sequence": sequence,
                "timestamp": utc_now(),
                "type": event_type,
                "data": data,
            }
            self.persist()
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def jobs(self) -> list[Dict[str, Any]]:
        return self.state.setdefault("jobs", [])

    def job(self, job_id: str) -> Dict[str, Any]:
        for job in self.jobs():
            if job.get("job_id") == job_id:
                return job
        raise KeyError(f"Unknown queue job: {job_id}")

    def transition(self, job: Dict[str, Any], status: str, reason: Optional[str] = None, **changes: Any) -> None:
        previous = job.get("status")
        job.update(changes)
        job["status"] = status
        job["updated_at"] = utc_now()
        if reason is not None:
            job["reason"] = reason
        self.event(
            "job_transition",
            job_id=job["job_id"],
            previous_status=previous,
            status=status,
            reason=reason,
            runtime_run_id=job.get("runtime_run_id"),
        )


def _normalize_resources(value: Any) -> Dict[str, int]:
    resources = value if isinstance(value, dict) else {}
    result = {
        "cpu_slots": int(resources.get("cpu_slots", 1)),
        "gpu_slots": int(resources.get("gpu_slots", 0)),
        "memory_mib": int(resources.get("memory_mib", 0)),
    }
    if result["cpu_slots"] < 1 or result["gpu_slots"] < 0 or result["memory_mib"] < 0:
        raise ValueError("resource_request requires cpu_slots >= 1 and non-negative gpu_slots/memory_mib")
    return result


def normalize_job_spec(spec: Dict[str, Any], queue_root: Path) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("Each job spec must be a JSON object")
    job_id = str(spec.get("job_id") or _job_id())
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError(f"Invalid job_id: {job_id!r}")
    command = str(spec.get("command") or "").strip()
    if not command:
        raise ValueError(f"Job {job_id} requires a non-empty command")
    cwd = Path(spec.get("cwd") or ".").expanduser().resolve()
    timeout = int(spec.get("timeout_seconds", 300))
    if timeout <= 0:
        raise ValueError(f"Job {job_id} timeout_seconds must be greater than zero")
    shell_mode = str(spec.get("shell_mode") or "direct")
    if shell_mode not in {"direct", "native"}:
        raise ValueError(f"Job {job_id} has unsupported shell_mode: {shell_mode}")
    lane = str(spec.get("lane") or "trusted")
    if lane not in {"trusted", "explore"}:
        raise ValueError(f"Job {job_id} has unsupported lane: {lane}")
    dependencies = [str(value) for value in (spec.get("depends_on") or [])]
    if job_id in dependencies or any(not JOB_ID_RE.fullmatch(value) for value in dependencies):
        raise ValueError(f"Job {job_id} has invalid dependencies")
    created_at = utc_now()
    runtime_root = Path(spec.get("runtime_root") or (Path(queue_root) / "runtime")).expanduser().resolve()
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "command": command,
        "cwd": str(cwd),
        "lane": lane,
        "timeout_seconds": timeout,
        "shell_mode": shell_mode,
        "priority": int(spec.get("priority", 0)),
        "depends_on": dependencies,
        "resource_request": _normalize_resources(spec.get("resource_request")),
        "runtime_root": str(runtime_root),
        "monitor_gpu": bool(spec.get("monitor_gpu", False)),
        "model_adapter": normalize_model_profile(spec["model_adapter"]) if spec.get("model_adapter") is not None else None,
        "metadata": spec.get("metadata") if isinstance(spec.get("metadata"), dict) else {},
        "attempt": int(spec.get("attempt", 1)),
        "parent_job_id": spec.get("parent_job_id"),
        "retry_of_runtime_run_id": spec.get("retry_of_runtime_run_id"),
        "status": "queued",
        "reason": None,
        "runtime_run_id": None,
        "created_at": created_at,
        "updated_at": created_at,
        "started_at": None,
        "finished_at": None,
        "result": None,
    }


def add_jobs(queue_root: Path, specs: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    with QueueLease(queue_root, "add") as lease:
        store = QueueStore(queue_root)
        existing_ids = {job["job_id"] for job in store.jobs()}
        normalized = [normalize_job_spec(spec, store.root) for spec in specs]
        new_ids = [job["job_id"] for job in normalized]
        if len(new_ids) != len(set(new_ids)) or existing_ids.intersection(new_ids):
            raise ValueError("job_id values must be unique within the queue")
        store.jobs().extend(normalized)
        store.event("jobs_added", job_ids=new_ids)
        if lease.replaced_stale is not None:
            store.event("stale_lease_replaced", prior=lease.replaced_stale)
        return normalized


def list_jobs(queue_root: Path) -> Dict[str, Any]:
    store = QueueStore(queue_root)
    return {
        "queue_id": store.state["queue_id"],
        "scheduler": store.state.get("scheduler", {}),
        "jobs": [
            {
                "job_id": job["job_id"],
                "status": job["status"],
                "priority": job["priority"],
                "depends_on": job["depends_on"],
                "attempt": job.get("attempt", 1),
                "parent_job_id": job.get("parent_job_id"),
                "retry_of_runtime_run_id": job.get("retry_of_runtime_run_id"),
                "runtime_run_id": job.get("runtime_run_id"),
                "reason": job.get("reason"),
            }
            for job in store.jobs()
        ],
    }


def request_job_cancel(queue_root: Path, job_id: str) -> Dict[str, Any]:
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError(f"Invalid job_id: {job_id!r}")
    store = QueueStore(queue_root)
    job = store.job(job_id)
    if job["status"] in JOB_TERMINAL_STATES:
        return {"job_id": job_id, "status": job["status"], "cancel_requested": False}
    store.control_root.mkdir(parents=True, exist_ok=True)
    marker = store.control_root / job_id
    marker.touch()
    return {"job_id": job_id, "status": job["status"], "cancel_requested": True}


def _runtime_state(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    run_id = job.get("runtime_run_id")
    if not run_id:
        return None
    state_path = Path(job["runtime_root"]) / str(run_id) / "state.json"
    if not state_path.is_file():
        return None
    return read_json(state_path)


def reconcile_queue(queue_root: Path, stale_after_seconds: float = 0.0) -> Dict[str, Any]:
    if stale_after_seconds < 0:
        raise ValueError("stale_after_seconds must be non-negative")
    with QueueLease(queue_root, "recover") as lease:
        store = QueueStore(queue_root)
        recovered: list[Dict[str, Any]] = []
        for job in store.jobs():
            if job.get("status") not in {"running", "orphaned"}:
                continue
            run_id = job.get("runtime_run_id")
            run_dir = Path(job["runtime_root"]) / str(run_id) if run_id else None
            if not run_dir or not (run_dir / "state.json").is_file():
                store.transition(job, "interrupted", "missing-runtime-state", finished_at=utc_now())
            else:
                runtime = reconcile_run(run_dir, stale_after_seconds=stale_after_seconds)
                runtime_status = str(runtime.get("status") or "interrupted")
                if runtime_status in RUNTIME_TERMINAL_STATES:
                    store.transition(job, runtime_status, f"runtime-{runtime_status}", finished_at=utc_now())
                else:
                    store.transition(job, "orphaned", f"runtime-{runtime_status}")
            recovered.append({"job_id": job["job_id"], "status": job["status"], "reason": job.get("reason")})
        if lease.replaced_stale is not None:
            store.event("stale_lease_replaced", prior=lease.replaced_stale)
        return {"queue_id": store.state["queue_id"], "recovered": recovered}


def retry_job(
    queue_root: Path,
    job_id: str,
    new_job_id: Optional[str] = None,
    allow_success_retry: bool = False,
) -> Dict[str, Any]:
    with QueueLease(queue_root, "retry"):
        store = QueueStore(queue_root)
        parent = store.job(job_id)
        status = parent.get("status")
        if status not in JOB_TERMINAL_STATES:
            raise RuntimeError(f"Job {job_id} is still active ({status}); refusing duplicate execution")
        if status == "success" and not allow_success_retry:
            raise RuntimeError(f"Job {job_id} already succeeded; intentional repetition requires allow_success_retry")
        child_id = new_job_id or f"{job_id}-r{int(parent.get('attempt') or 1) + 1}-{uuid.uuid4().hex[:4]}"
        spec = {
            key: parent.get(key)
            for key in (
                "command",
                "cwd",
                "lane",
                "timeout_seconds",
                "shell_mode",
                "priority",
                "depends_on",
                "resource_request",
                "runtime_root",
                "monitor_gpu",
                "model_adapter",
                "metadata",
                "retry_of_runtime_run_id",
            )
        }
        spec.update(
            job_id=child_id,
            attempt=int(parent.get("attempt") or 1) + 1,
            parent_job_id=job_id,
            retry_of_runtime_run_id=parent.get("runtime_run_id"),
        )
        child = normalize_job_spec(spec, store.root)
        if any(job["job_id"] == child["job_id"] for job in store.jobs()):
            raise ValueError(f"Duplicate job_id: {child['job_id']}")
        store.jobs().append(child)
        store.event("job_retry_created", job_id=child["job_id"], parent_job_id=job_id, attempt=child["attempt"])
        return child


def _cycle_members(jobs: list[Dict[str, Any]]) -> set[str]:
    graph = {job["job_id"]: [dep for dep in job["depends_on"] if dep in {row["job_id"] for row in jobs}] for job in jobs}
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle.update(path[path.index(node) :])
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for dependency in graph[node]:
            visit(dependency, path)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [])
    return cycle


def _fits(request: Dict[str, int], available: Dict[str, int]) -> bool:
    return all(request[key] <= available[key] for key in ("cpu_slots", "gpu_slots", "memory_mib"))


def _execute_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return run_persistent_command(
        repo=Path(job["cwd"]),
        command=job["command"],
        timeout=int(job["timeout_seconds"]),
        runtime_root=Path(job["runtime_root"]),
        shell_mode=job["shell_mode"],
        run_id=job["runtime_run_id"],
        model_adapter=job.get("model_adapter"),
        retry_of=job.get("retry_of_runtime_run_id"),
        attempt=int(job.get("attempt") or 1),
        monitor_gpu=bool(job.get("monitor_gpu")),
    )


def _summary(store: QueueStore, peak_running_jobs: int) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for job in store.jobs():
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    unfinished = sum(counts.get(status, 0) for status in JOB_ACTIVE_STATES)
    unsuccessful = sum(counts.get(status, 0) for status in FAILURE_STATES)
    if unfinished:
        status = "incomplete"
    elif unsuccessful:
        status = "degraded"
    else:
        status = "success"
    return {
        "queue_id": store.state["queue_id"],
        "status": status,
        "counts": counts,
        "jobs_total": len(store.jobs()),
        "peak_running_jobs": peak_running_jobs,
        "queue_state_path": str(store.state_path),
        "queue_events_path": str(store.events_path),
    }


def run_queue(
    queue_root: Path,
    *,
    max_workers: int = 1,
    cpu_slots: Optional[int] = None,
    gpu_slots: int = 0,
    memory_mib: int = 0,
    fail_fast: bool = False,
) -> Dict[str, Any]:
    if max_workers < 1:
        raise ValueError("max_workers must be at least one")
    totals = {
        "cpu_slots": int(max_workers if cpu_slots is None else cpu_slots),
        "gpu_slots": int(gpu_slots),
        "memory_mib": int(memory_mib),
    }
    if totals["cpu_slots"] < 1 or totals["gpu_slots"] < 0 or totals["memory_mib"] < 0:
        raise ValueError("queue budgets require cpu_slots >= 1 and non-negative gpu_slots/memory_mib")

    with QueueLease(queue_root, "run") as lease:
        store = QueueStore(queue_root)
        if lease.replaced_stale is not None:
            store.event("stale_lease_replaced", prior=lease.replaced_stale)
        # A restarted scheduler cannot safely reattach to a prior controller's
        # monitoring loop. Reconcile immediately and never duplicate it.
        for job in store.jobs():
            if job.get("status") not in {"running", "orphaned"}:
                continue
            run_id = job.get("runtime_run_id")
            run_dir = Path(job["runtime_root"]) / str(run_id) if run_id else None
            if not run_dir or not (run_dir / "state.json").is_file():
                store.transition(job, "interrupted", "missing-runtime-state", finished_at=utc_now())
                continue
            runtime = reconcile_run(run_dir, stale_after_seconds=0.0)
            runtime_status = str(runtime.get("status") or "interrupted")
            if runtime_status in RUNTIME_TERMINAL_STATES:
                store.transition(job, runtime_status, f"runtime-{runtime_status}", finished_at=utc_now())
            else:
                store.transition(job, "orphaned", f"runtime-{runtime_status}")

        jobs_by_id = {job["job_id"]: job for job in store.jobs()}
        for job in store.jobs():
            missing = [dep for dep in job["depends_on"] if dep not in jobs_by_id]
            if job["status"] == "queued" and missing:
                store.transition(job, "blocked", "missing-dependencies", finished_at=utc_now(), missing_dependencies=missing)
        for job_id in _cycle_members(store.jobs()):
            job = jobs_by_id[job_id]
            if job["status"] == "queued":
                store.transition(job, "blocked", "dependency-cycle", finished_at=utc_now())
        for job in store.jobs():
            if job["status"] == "queued" and not _fits(job["resource_request"], totals):
                store.transition(
                    job,
                    "blocked",
                    "resource-request-exceeds-budget",
                    finished_at=utc_now(),
                    scheduler_budget=totals,
                )

        scheduler_id = lease.lease_id
        store.state["scheduler"] = {
            "status": "running",
            "scheduler_id": scheduler_id,
            "pid": os.getpid(),
            "started_at": utc_now(),
            "heartbeat_at": utc_now(),
            "max_workers": max_workers,
            "resource_budget": totals,
            "resource_semantics": "request-based-admission-not-os-enforcement",
            "fail_fast": fail_fast,
        }
        store.event("scheduler_started", scheduler_id=scheduler_id, resource_budget=totals, max_workers=max_workers)

        available = totals.copy()
        futures: Dict[Future[Dict[str, Any]], Dict[str, Any]] = {}
        peak_running_jobs = 0
        failure_seen = any(job["status"] in FAILURE_STATES for job in store.jobs())
        last_heartbeat = 0.0

        try:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rigorpilot-job") as executor:
                while True:
                    now = time.monotonic()
                    if now - last_heartbeat >= 1.0:
                        lease.heartbeat()
                        store.state["scheduler"]["heartbeat_at"] = utc_now()
                        store.persist()
                        last_heartbeat = now

                    for job in store.jobs():
                        marker = store.control_root / job["job_id"]
                        if not marker.exists():
                            continue
                        if job["status"] == "queued":
                            store.transition(job, "cancelled", "cancel-requested-before-start", finished_at=utc_now())
                        elif job["status"] == "running" and job.get("runtime_run_id"):
                            response = request_cancel(Path(job["runtime_root"]), job["runtime_run_id"])
                            job["cancel_requested_at"] = utc_now()
                            job["cancel_response"] = response
                            store.event("running_job_cancel_requested", job_id=job["job_id"], response=response)
                        elif job["status"] == "orphaned":
                            store.event("orphaned_job_cancel_rejected", job_id=job["job_id"])
                        try:
                            marker.unlink()
                        except FileNotFoundError:
                            pass

                    done = [future for future in futures if future.done()]
                    for future in done:
                        job = futures.pop(future)
                        request = job["resource_request"]
                        for key in available:
                            available[key] += request[key]
                        try:
                            result = future.result()
                            runtime_status = str(result.get("runtime_status") or "failed")
                            job["result"] = {
                                "returncode": result.get("returncode"),
                                "timed_out": result.get("timed_out"),
                                "cancelled": result.get("cancelled"),
                                "runtime_dir": result.get("runtime_dir"),
                                "resource_summary": result.get("resource_summary"),
                            }
                            store.transition(job, runtime_status, f"runtime-{runtime_status}", finished_at=utc_now())
                        except Exception as exc:
                            store.transition(
                                job,
                                "failed",
                                "scheduler-worker-error",
                                finished_at=utc_now(),
                                scheduler_error=f"{type(exc).__name__}: {exc}",
                            )
                        if job["status"] in FAILURE_STATES:
                            failure_seen = True

                    for job in store.jobs():
                        if job["status"] != "queued":
                            continue
                        dependency_states = [jobs_by_id[dep]["status"] for dep in job["depends_on"]]
                        if any(status in FAILURE_STATES for status in dependency_states):
                            store.transition(job, "skipped", "dependency-did-not-succeed", finished_at=utc_now())
                            failure_seen = True

                    if fail_fast and failure_seen:
                        for job in store.jobs():
                            if job["status"] == "queued":
                                store.transition(job, "skipped", "fail-fast", finished_at=utc_now())

                    launched = False
                    candidates = sorted(
                        (job for job in store.jobs() if job["status"] == "queued"),
                        key=lambda item: (-int(item["priority"]), item["created_at"], item["job_id"]),
                    )
                    for job in candidates:
                        if len(futures) >= max_workers:
                            break
                        if not all(jobs_by_id[dep]["status"] == "success" for dep in job["depends_on"]):
                            continue
                        request = job["resource_request"]
                        if not _fits(request, available):
                            continue
                        for key in available:
                            available[key] -= request[key]
                        job["runtime_run_id"] = new_run_id()
                        store.transition(job, "running", started_at=utc_now())
                        futures[executor.submit(_execute_job, dict(job))] = job
                        peak_running_jobs = max(peak_running_jobs, len(futures))
                        launched = True

                    active_or_queued = [job for job in store.jobs() if job["status"] in {"queued", "running"}]
                    if not active_or_queued:
                        break
                    if not launched:
                        if futures:
                            wait(list(futures), timeout=0.2, return_when=FIRST_COMPLETED)
                        else:
                            # Any remaining queued job is waiting on an orphaned
                            # or otherwise non-terminal dependency and must not spin.
                            for job in store.jobs():
                                if job["status"] == "queued":
                                    store.transition(job, "blocked", "dependency-not-runnable", finished_at=utc_now())
                            break
        except KeyboardInterrupt:
            for job in store.jobs():
                if job["status"] == "running" and job.get("runtime_run_id"):
                    request_cancel(Path(job["runtime_root"]), job["runtime_run_id"])
            store.event("scheduler_interrupt", scheduler_id=scheduler_id)
            raise
        finally:
            summary = _summary(store, peak_running_jobs)
            store.state["scheduler"].update(
                status="idle",
                finished_at=utc_now(),
                result_status=summary["status"],
                peak_running_jobs=peak_running_jobs,
            )
            store.event("scheduler_finished", scheduler_id=scheduler_id, summary=summary)
        return _summary(store, peak_running_jobs)


def _load_specs(path: Path) -> list[Dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        return payload["jobs"]
    if isinstance(payload, dict):
        return [payload]
    raise ValueError("Job spec JSON must be an object, an array, or an object containing jobs[]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage a durable single-host RigorPilot research task queue.")
    parser.add_argument("--queue-root", required=True)
    subparsers = parser.add_subparsers(dest="action", required=True)
    add_parser = subparsers.add_parser("add", help="Add one or more jobs from JSON.")
    add_parser.add_argument("--spec-json", required=True)
    subparsers.add_parser("list", help="List durable queue state.")
    run_parser = subparsers.add_parser("run", help="Run schedulable jobs under explicit admission budgets.")
    run_parser.add_argument("--max-workers", type=int, default=1)
    run_parser.add_argument("--cpu-slots", type=int)
    run_parser.add_argument("--gpu-slots", type=int, default=0)
    run_parser.add_argument("--memory-mib", type=int, default=0)
    run_parser.add_argument("--fail-fast", action="store_true")
    recover_parser = subparsers.add_parser("recover", help="Reconcile jobs left active after controller exit.")
    recover_parser.add_argument("--stale-after", type=float, default=0.0)
    cancel_parser = subparsers.add_parser("cancel", help="Create a durable cancellation request.")
    cancel_parser.add_argument("--job-id", required=True)
    retry_parser = subparsers.add_parser("retry", help="Explicitly clone a terminal job as a new attempt.")
    retry_parser.add_argument("--job-id", required=True)
    retry_parser.add_argument("--new-job-id")
    retry_parser.add_argument("--allow-success-retry", action="store_true")
    args = parser.parse_args()
    root = Path(args.queue_root)
    try:
        if args.action == "add":
            payload: Any = add_jobs(root, _load_specs(Path(args.spec_json)))
        elif args.action == "list":
            payload = list_jobs(root)
        elif args.action == "run":
            payload = run_queue(
                root,
                max_workers=args.max_workers,
                cpu_slots=args.cpu_slots,
                gpu_slots=args.gpu_slots,
                memory_mib=args.memory_mib,
                fail_fast=args.fail_fast,
            )
        elif args.action == "recover":
            payload = reconcile_queue(root, args.stale_after)
        elif args.action == "cancel":
            payload = request_job_cancel(root, args.job_id)
        else:
            payload = retry_job(root, args.job_id, args.new_job_id, args.allow_success_retry)
    except (FileNotFoundError, KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.action == "run" and payload.get("status") != "success":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
