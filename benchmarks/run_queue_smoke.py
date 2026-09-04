#!/usr/bin/env python3
"""Deterministic API-free smoke benchmark for the local research task queue."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
sys.path.insert(0, str(SHARED_SCRIPTS))

from task_queue import QueueStore, add_jobs, run_queue  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def command_for(*parts: str) -> str:
    values = [str(part) for part in parts]
    return subprocess.list2cmdline(values) if os.name == "nt" else shlex.join(values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="benchmark_outputs/queue_smoke.json")
    args = parser.parse_args()
    output_path = Path(args.output).expanduser().resolve()
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-queue-smoke-"))
    try:
        worker = temp_root / "worker.py"
        worker.write_text(
            "import pathlib, sys, time\n"
            "time.sleep(float(sys.argv[2]))\n"
            "pathlib.Path(sys.argv[1]).write_text(sys.argv[3], encoding='utf-8')\n"
            "raise SystemExit(int(sys.argv[4]))\n",
            encoding="utf-8",
        )
        artifacts = temp_root / "artifacts"
        artifacts.mkdir()
        queue_root = temp_root / "queue"

        def job(job_id: str, delay: float, exit_code: int = 0, **extra: object) -> dict:
            payload = {
                "job_id": job_id,
                "command": command_for(
                    sys.executable,
                    str(worker),
                    str(artifacts / f"{job_id}.txt"),
                    str(delay),
                    job_id,
                    str(exit_code),
                ),
                "cwd": str(temp_root),
                "timeout_seconds": 10,
                "resource_request": {"cpu_slots": 1, "gpu_slots": 0, "memory_mib": 16},
            }
            payload.update(extra)
            return payload

        add_jobs(
            queue_root,
            [
                job("parallel-a", 0.2, priority=10),
                job("parallel-b", 0.2, priority=10),
                job("dependent", 0.01, priority=5, depends_on=["parallel-a", "parallel-b"]),
                job("failure", 0.01, exit_code=9),
                job("failure-dependent", 0.01, depends_on=["failure"]),
                job(
                    "over-budget",
                    0.01,
                    resource_request={"cpu_slots": 1, "gpu_slots": 1, "memory_mib": 16},
                ),
            ],
        )
        scheduler = run_queue(queue_root, max_workers=2, cpu_slots=2, gpu_slots=0, memory_mib=32)
        jobs = {row["job_id"]: row for row in QueueStore(queue_root).jobs()}
        launched = [row for row in jobs.values() if row.get("runtime_run_id")]
        complete_runtime_bundles = 0
        for row in launched:
            runtime_dir = Path(row["result"]["runtime_dir"])
            required = {"spec.json", "state.json", "events.jsonl", "resources.jsonl", "stdout.log", "stderr.log"}
            if required.issubset({path.name for path in runtime_dir.iterdir() if path.is_file()}):
                complete_runtime_bundles += 1

        cases = [
            {
                "name": "concurrency_admission",
                "passed": scheduler["peak_running_jobs"] == 2,
                "observed_peak_running_jobs": scheduler["peak_running_jobs"],
            },
            {
                "name": "dependency_gate",
                "passed": jobs["dependent"]["status"] == "success" and (artifacts / "dependent.txt").is_file(),
                "status": jobs["dependent"]["status"],
            },
            {
                "name": "failure_isolation",
                "passed": jobs["failure"]["status"] == "failed"
                and jobs["failure-dependent"]["status"] == "skipped"
                and not (artifacts / "failure-dependent.txt").exists(),
                "failure_status": jobs["failure"]["status"],
                "dependent_status": jobs["failure-dependent"]["status"],
            },
            {
                "name": "resource_admission",
                "passed": jobs["over-budget"]["status"] == "blocked"
                and jobs["over-budget"]["reason"] == "resource-request-exceeds-budget",
                "status": jobs["over-budget"]["status"],
                "reason": jobs["over-budget"]["reason"],
            },
            {
                "name": "durable_runtime_evidence",
                "passed": complete_runtime_bundles == len(launched) == 4,
                "launched_jobs": len(launched),
                "complete_runtime_bundles": complete_runtime_bundles,
            },
        ]
        public_scheduler = {
            key: scheduler[key]
            for key in ("status", "counts", "jobs_total", "peak_running_jobs")
        }
        report = {
            "schema_version": "1.0",
            "benchmark": "rigorpilot-queue-smoke",
            "generated_at": utc_now(),
            "api_calls": 0,
            "gpu_required": False,
            "resource_budget_semantics": "request-based-admission-not-os-enforcement",
            "scheduler": public_scheduler,
            "summary": {
                "cases_total": len(cases),
                "cases_passed": sum(1 for case in cases if case["passed"]),
                "launched_jobs": len(launched),
                "complete_runtime_bundles": complete_runtime_bundles,
            },
            "cases": cases,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["summary"]["cases_passed"] == report["summary"]["cases_total"] else 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
