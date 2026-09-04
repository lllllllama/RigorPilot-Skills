#!/usr/bin/env python3
"""Exercise durable queue scheduling, admission, recovery, and retry lineage."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import run_persistent_command  # noqa: E402
from task_queue import (  # noqa: E402
    QueueStore,
    add_jobs,
    list_jobs,
    reconcile_queue,
    request_job_cancel,
    retry_job,
    run_queue,
)


def command_for(*parts: str) -> str:
    values = [str(part) for part in parts]
    return subprocess.list2cmdline(values) if os.name == "nt" else shlex.join(values)


def assert_runtime_complete(job: dict) -> None:
    runtime_dir = Path(job["result"]["runtime_dir"])
    required = {"spec.json", "state.json", "events.jsonl", "resources.jsonl", "stdout.log", "stderr.log"}
    present = {path.name for path in runtime_dir.iterdir() if path.is_file()}
    if not required.issubset(present):
        raise AssertionError(f"incomplete runtime bundle for {job['job_id']}: {sorted(required - present)}")


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-queue-test-"))
    checks = 0
    try:
        worker = temp_root / "worker.py"
        worker.write_text(
            "import pathlib, sys, time\n"
            "target = pathlib.Path(sys.argv[1])\n"
            "time.sleep(float(sys.argv[2]))\n"
            "target.write_text(sys.argv[3], encoding='utf-8')\n"
            "raise SystemExit(int(sys.argv[4]))\n",
            encoding="utf-8",
        )
        queue_root = temp_root / "queue"
        outputs = temp_root / "outputs"
        outputs.mkdir()

        def spec(job_id: str, delay: float, exit_code: int = 0, **extra: object) -> dict:
            payload = {
                "job_id": job_id,
                "command": command_for(sys.executable, str(worker), str(outputs / f"{job_id}.txt"), str(delay), job_id, str(exit_code)),
                "cwd": str(temp_root),
                "timeout_seconds": 10,
                "resource_request": {"cpu_slots": 1, "gpu_slots": 0, "memory_mib": 32},
            }
            payload.update(extra)
            return payload

        add_jobs(
            queue_root,
            [
                spec("parallel-a", 0.25, priority=10),
                spec("parallel-b", 0.25, priority=10),
                spec("after-both", 0.01, priority=5, depends_on=["parallel-a", "parallel-b"]),
                spec("intentional-failure", 0.01, exit_code=7),
                spec("after-failure", 0.01, depends_on=["intentional-failure"]),
                spec(
                    "oversized-gpu",
                    0.01,
                    resource_request={"cpu_slots": 1, "gpu_slots": 1, "memory_mib": 32},
                ),
            ],
        )
        summary = run_queue(queue_root, max_workers=2, cpu_slots=2, gpu_slots=0, memory_mib=64)
        jobs = {job["job_id"]: job for job in QueueStore(queue_root).jobs()}
        expected = {
            "parallel-a": "success",
            "parallel-b": "success",
            "after-both": "success",
            "intentional-failure": "failed",
            "after-failure": "skipped",
            "oversized-gpu": "blocked",
        }
        actual = {job_id: jobs[job_id]["status"] for job_id in expected}
        if actual != expected:
            raise AssertionError(f"unexpected queue states: {actual}")
        checks += 1
        if summary["status"] != "degraded" or summary["peak_running_jobs"] != 2:
            raise AssertionError(f"queue did not expose admitted concurrency: {summary}")
        checks += 1
        if not (outputs / "after-both.txt").is_file() or (outputs / "after-failure.txt").exists():
            raise AssertionError("dependency gating did not preserve success/failure semantics")
        checks += 1
        for job_id in ("parallel-a", "parallel-b", "after-both", "intentional-failure"):
            assert_runtime_complete(jobs[job_id])
        checks += 4
        if jobs["oversized-gpu"]["reason"] != "resource-request-exceeds-budget":
            raise AssertionError("oversized resource request was not explicitly blocked")
        checks += 1
        queue_events = [json.loads(line) for line in (queue_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        sequences = [event["sequence"] for event in queue_events]
        if sequences != list(range(1, len(sequences) + 1)):
            raise AssertionError("queue event journal is not monotonically sequenced")
        checks += 1

        try:
            retry_job(queue_root, "parallel-a")
        except RuntimeError:
            checks += 1
        else:
            raise AssertionError("successful job repeated without explicit authorization")
        retry = retry_job(queue_root, "parallel-a", new_job_id="parallel-a-repeat", allow_success_retry=True)
        if retry["attempt"] != 2 or retry["parent_job_id"] != "parallel-a":
            raise AssertionError("retry lineage was not preserved")
        checks += 1
        retry_summary = run_queue(queue_root, max_workers=1, cpu_slots=1, memory_mib=32)
        retry_state = QueueStore(queue_root).job("parallel-a-repeat")
        if retry_state["status"] != "success" or retry_summary["counts"].get("success") != 4:
            raise AssertionError("explicit repeat did not execute as a new successful job")
        checks += 1
        retry_runtime_state = json.loads(
            (Path(retry_state["result"]["runtime_dir"]) / "state.json").read_text(encoding="utf-8")
        )
        if retry_runtime_state["retry_of"] != jobs["parallel-a"]["runtime_run_id"]:
            raise AssertionError("job retry lineage did not propagate into the Runtime record")
        checks += 1

        try:
            add_jobs(
                temp_root / "unsafe-model-queue",
                [
                    spec(
                        "unsafe-model",
                        0.01,
                        model_adapter={
                            "adapter_id": "unsafe",
                            "provider": "test",
                            "model": "test-model",
                            "api_key": "must-not-persist",
                        },
                    )
                ],
            )
        except ValueError:
            checks += 1
        else:
            raise AssertionError("queue accepted an inline model credential")

        cycle_root = temp_root / "cycle-queue"
        add_jobs(
            cycle_root,
            [
                spec("cycle-a", 0.01, depends_on=["cycle-b"]),
                spec("cycle-b", 0.01, depends_on=["cycle-a"]),
                spec("missing-dep", 0.01, depends_on=["not-present"]),
            ],
        )
        run_queue(cycle_root, max_workers=1, cpu_slots=1, memory_mib=32)
        cycle_jobs = {job["job_id"]: job for job in QueueStore(cycle_root).jobs()}
        if cycle_jobs["cycle-a"]["reason"] != "dependency-cycle" or cycle_jobs["cycle-b"]["reason"] != "dependency-cycle":
            raise AssertionError("dependency cycle was not blocked")
        checks += 1
        if cycle_jobs["missing-dep"]["reason"] != "missing-dependencies":
            raise AssertionError("missing dependency was not blocked")
        checks += 1

        cancel_root = temp_root / "cancel-queue"
        add_jobs(cancel_root, [spec("cancel-before-start", 0.01)])
        cancel_response = request_job_cancel(cancel_root, "cancel-before-start")
        run_queue(cancel_root, max_workers=1, cpu_slots=1, memory_mib=32)
        if not cancel_response["cancel_requested"] or QueueStore(cancel_root).job("cancel-before-start")["status"] != "cancelled":
            raise AssertionError("durable queued cancellation was not applied")
        checks += 1

        recovery_root = temp_root / "recovery-queue"
        recovered_output = outputs / "recovered.txt"
        added = add_jobs(recovery_root, [spec("recover-success", 0.01), spec("recover-missing", 0.01)])
        recovered_run_id = "completed-before-controller-restart"
        run_persistent_command(
            repo=temp_root,
            command=command_for(sys.executable, str(worker), str(recovered_output), "0.01", "recovered", "0"),
            timeout=10,
            runtime_root=Path(added[0]["runtime_root"]),
            run_id=recovered_run_id,
        )
        recovery_store = QueueStore(recovery_root)
        recovered_job = recovery_store.job("recover-success")
        recovered_job.update(status="running", runtime_run_id=recovered_run_id, started_at=recovered_job["created_at"])
        missing_job = recovery_store.job("recover-missing")
        missing_job.update(status="running", runtime_run_id="never-created", started_at=missing_job["created_at"])
        recovery_store.persist()
        recovery = reconcile_queue(recovery_root)
        recovered_states = {row["job_id"]: row["status"] for row in recovery["recovered"]}
        if recovered_states != {"recover-success": "success", "recover-missing": "interrupted"}:
            raise AssertionError(f"restart reconciliation was incorrect: {recovered_states}")
        checks += 1
        if len(QueueStore(recovery_root).jobs()) != 2:
            raise AssertionError("recovery silently created duplicate work")
        checks += 1

        cli = subprocess.run(
            [sys.executable, str(SHARED_SCRIPTS / "task_queue.py"), "--queue-root", str(queue_root), "list"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if cli.returncode != 0 or json.loads(cli.stdout)["queue_id"] != list_jobs(queue_root)["queue_id"]:
            raise AssertionError(f"queue CLI list failed:\n{cli.stdout}\n{cli.stderr}")
        checks += 1

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
