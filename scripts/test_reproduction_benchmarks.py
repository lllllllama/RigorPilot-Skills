#!/usr/bin/env python3
"""Offline smoke checks for the reviewed-selection and integrity benchmarks."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout.strip()


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-benchmark-tests-"))
    checks = 0
    try:
        integrity_output = temp_root / "integrity.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "benchmarks/run_source_integrity_benchmark.py"),
                "--counts", "25", "100",
                "--bytes-per-file", "32",
                "--output", str(integrity_output),
            ],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=30,
        )
        integrity = json.loads(integrity_output.read_text(encoding="utf-8"))
        if integrity.get("status") != "passed" or len(integrity.get("cases", [])) != 2:
            raise AssertionError("source-integrity benchmark smoke did not pass")
        if not all(item.get("change_detection_ok") for item in integrity["cases"]):
            raise AssertionError("source-integrity benchmark lost mutation detection")
        checks += 1

        origin = temp_root / "origin"
        origin.mkdir()
        (origin / "README.md").write_text(
            "# Fixture\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n",
            encoding="utf-8",
        )
        (origin / "evaluate.py").write_text("print('score=1')\n", encoding="utf-8")
        git(origin, "init")
        git(origin, "config", "user.email", "rigorpilot@example.com")
        git(origin, "config", "user.name", "RigorPilot Test")
        git(origin, "add", ".")
        git(origin, "commit", "-m", "fixture")
        commit = git(origin, "rev-parse", "HEAD")
        manifest = temp_root / "cases.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "cases": {
                        "local": {
                            "status": "ready",
                            "repository": str(origin),
                            "commit": commit,
                            "target_subdir": ".",
                            "orchestrator": {
                                "expected_command": "python evaluate.py",
                                "expected_goal": "evaluation",
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        selection_output = temp_root / "selection.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "benchmarks/run_reviewed_selection_suite.py"),
                "--cases", "local",
                "--manifest", str(manifest),
                "--output", str(selection_output),
                "--max-total-minutes", "1",
            ],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=30,
        )
        selection = json.loads(selection_output.read_text(encoding="utf-8"))
        row = selection["cases"][0]
        if selection.get("status") != "passed" or row.get("selected_command_id") != "cmd-01":
            raise AssertionError("reviewed-selection benchmark smoke did not pass")
        if not row.get("checks", {}).get("review_args_bound") or not row.get("checks", {}).get("no_repo_evidence_write"):
            raise AssertionError("reviewed-selection benchmark lost review/no-side-effect checks")
        checks += 1

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
