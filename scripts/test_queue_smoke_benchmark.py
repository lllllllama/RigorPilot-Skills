#!/usr/bin/env python3
"""Keep the durable queue smoke benchmark in the regression suite."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    benchmark = repo_root / "benchmarks" / "run_queue_smoke.py"
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-queue-smoke-ci-"))
    try:
        output_path = temp_root / "queue_smoke.json"
        result = subprocess.run(
            [sys.executable, str(benchmark), "--output", str(output_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"queue smoke benchmark failed:\n{result.stdout}\n{result.stderr}")
        report = json.loads(output_path.read_text(encoding="utf-8"))
        summary = report["summary"]
        if summary["cases_total"] != 5 or summary["cases_passed"] != 5:
            raise AssertionError(f"unexpected queue benchmark summary: {summary}")
        if summary["launched_jobs"] != 4 or summary["complete_runtime_bundles"] != 4:
            raise AssertionError("queue benchmark lost complete runtime evidence")
        if report["scheduler"]["peak_running_jobs"] != 2:
            raise AssertionError("queue benchmark did not exercise concurrency")
        if report["resource_budget_semantics"] != "request-based-admission-not-os-enforcement":
            raise AssertionError("queue benchmark overstated resource enforcement")
        if report["api_calls"] != 0 or report["gpu_required"] is not False:
            raise AssertionError("queue benchmark lost its API-free, GPU-free contract")

        print("ok: True")
        print("checks: 9")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
