#!/usr/bin/env python3
"""Ensure the deterministic harness benchmark remains part of CI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    benchmark = repo_root / "benchmarks" / "run_golden_smoke.py"
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-golden-ci-"))
    try:
        output_path = temp_root / "golden_smoke.json"
        result = subprocess.run(
            [sys.executable, str(benchmark), "--output", str(output_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"golden smoke benchmark failed:\n{result.stdout}\n{result.stderr}")
        report = json.loads(output_path.read_text(encoding="utf-8"))
        summary = report["summary"]
        if summary["cases_total"] != 5 or summary["cases_passed"] != 5:
            raise AssertionError(f"unexpected golden benchmark summary: {summary}")
        if summary["false_result_matches"] != 0:
            raise AssertionError("golden benchmark detected a false result match")
        if summary["complete_evidence_bundles"] != 5 or summary["complete_runtime_bundles"] != 5:
            raise AssertionError("golden benchmark did not produce five complete evidence and runtime bundles")
        adapter_case = next(case for case in report["cases"] if case["name"] == "model_adapter_snapshot")
        if adapter_case["model_adapter_recorded"] != "golden-test-model":
            raise AssertionError("golden benchmark lost the model adapter snapshot")
        if report["api_calls"] != 0 or report["gpu_required"] is not False:
            raise AssertionError("golden benchmark lost its API-free, GPU-free contract")

        print("ok: True")
        print("checks: 10")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
