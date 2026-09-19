#!/usr/bin/env python3
"""Ensure the reproduction CLI keeps default evidence beside the target repo."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "skills/ai-research-reproduction/scripts/orchestrate_repro.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-default-paths-"))
    try:
        repo = temp_root / "target-repo"
        caller = temp_root / "external-caller"
        repo.mkdir()
        caller.mkdir()
        (repo / "README.md").write_text(
            "# Default path fixture\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n",
            encoding="utf-8",
        )
        (repo / "evaluate.py").write_text("print('score=1.0')\n", encoding="utf-8")
        git(repo, "init")
        git(repo, "config", "user.email", "rigorpilot@example.com")
        git(repo, "config", "user.name", "RigorPilot Test")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "fixture")

        env = dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0")
        base = [sys.executable, str(ORCHESTRATOR), "--repo", str(repo), "--agent-output"]

        plan = subprocess.run(
            [*base, "--plan-only"], cwd=caller, env=env, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        plan_payload = json.loads(plan.stdout)
        if plan_payload.get("mode") != "plan_only":
            raise AssertionError("plan-only did not return the compact planning payload")
        if (repo / "repro_outputs").exists() or (caller / "repro_outputs").exists():
            raise AssertionError("plan-only unexpectedly wrote a default evidence directory")

        run = subprocess.run(
            [*base, "--run-selected", "--expected-metric", "score=1.0", "--no-gpu-monitor"],
            cwd=caller, env=env, check=True, capture_output=True, text=True, encoding="utf-8",
        )
        payload = json.loads(run.stdout)
        output = repo / "repro_outputs"
        if payload.get("status") != "success" or payload.get("result_match") != "matched":
            raise AssertionError(f"default-path execution failed: {payload}")
        if not (output / "status.json").is_file() or not (output / "evidence_manifest.json").is_file():
            raise AssertionError("default evidence was not written under <repo>/repro_outputs")
        if (caller / "repro_outputs").exists():
            raise AssertionError("default evidence leaked into the caller working directory")
        if Path(payload["evidence"]["status"]).resolve() != (output / "status.json").resolve():
            raise AssertionError("compact payload reported the wrong default evidence path")

        verify = subprocess.run(
            [*base, "--verify-output"], cwd=caller, env=env, check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        verification = json.loads(verify.stdout)
        if verification.get("mode") != "verify_only" or verification.get("evidence_valid") is not True:
            raise AssertionError(f"default-path verification failed: {verification}")

        print("ok: True")
        print("checks: 4")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
