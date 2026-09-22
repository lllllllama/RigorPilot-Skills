#!/usr/bin/env python3
"""Regression for the fault comparison; fixtures execute real bounded processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rigorpilot-handoff-test-") as directory:
        output = Path(directory) / "report.json"
        result = subprocess.run([sys.executable, str(ROOT / "benchmarks/run_agent_handoff_benchmark.py"), "--output", str(output)],
                                cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["status"] == "passed" and report["model_calls"] == 0 and report["model_uplift"] is None
        assert len(report["cases"]) == 2
        for case in report["cases"]:
            assert all(case["checks"].values()), case
        print("ok: True; controlled timeout, success and duplicate-dispatch comparison passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
