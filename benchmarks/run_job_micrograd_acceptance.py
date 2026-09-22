#!/usr/bin/env python3
"""Installed-layout micrograd handoff acceptance using retained pinned source.

No model calls, downloads, training, or installation of target dependencies.
The report embeds original test stdout and independent grader observations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "benchmark_outputs/real_client/20260920/B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Existing Python with torch and pytest; never installs them.")
    parser.add_argument("--output", default="tmp/job-micrograd.json")
    args = parser.parse_args()
    python = shutil.which(args.python)
    if not python:
        parser.error("--python must name an existing executable")
    temporary = Path(tempfile.mkdtemp(prefix="rigorpilot-installed-job-"))
    repo, installed = temporary / "repo", temporary / "installed/ai-research-reproduction"
    report = {"schema_version": "1.0", "benchmark": "installed-job-micrograd", "model_calls": 0, "model_uplift": None,
              "generated_at": datetime.now(timezone.utc).isoformat(), "status": "failed", "checks": {}}
    env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL"))}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", RIGORPILOT_LESSONS="0", CUDA_VISIBLE_DEVICES="-1",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="-p no:cacheprovider")
    env["PATH"] = str(Path(python).parent) + os.pathsep + env.get("PATH", "")

    def call(argv, timeout=30):
        result = subprocess.run(argv, cwd=temporary, env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        return result.returncode, json.loads(result.stdout)

    try:
        baseline = json.loads((SOURCE / "BASELINE.json").read_text(encoding="utf-8"))
        repo.mkdir()
        for name, expected in baseline["originals"].items():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("invalid retained source path")
            content = (SOURCE / "repo" / name).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError("retained pinned source does not match its baseline")
            destination = repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        baseline_path = temporary / "BASELINE.json"
        baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        for argv in (["git", "init"], ["git", "add", "."]):
            subprocess.run(argv, cwd=repo, env=env, check=True, capture_output=True)
        shutil.copytree(ROOT / "skills/ai-research-reproduction", installed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        report["source"] = {"commit": baseline["commit"], "origin": "retained_upstream_bytes_verified_against_baseline",
                            "original_sha256": baseline["originals"]}
        report["skill_snapshot"] = {p.relative_to(installed).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in installed.rglob("*") if p.is_file()}
        code, doctor = call([python, str(installed / "scripts/doctor.py"), "--repo", str(repo),
                             "--require-module", "torch", "--require-module", "pytest"])
        report["doctor"] = doctor
        if code or doctor.get("ok") is not True:
            raise ValueError("required existing target dependencies unavailable")
        _, plan = call([python, str(installed / "scripts/orchestrate_repro.py"), "--repo", str(repo),
                         "--plan-only", "--include-agent-handoff", "--timeout", "30", "--source-adjacent-readme", "--user-language", "zh-CN"])
        report["selected_command"] = plan.get("documented_command")
        started = time.monotonic()
        _, receipt = call(plan["agent_handoff"]["start_argv"], timeout=10)
        report["start_return_seconds"] = round(time.monotonic() - started, 3)
        deadline = time.monotonic() + 150
        final = receipt
        while not final["terminal"] and time.monotonic() < deadline:
            time.sleep(0.5)
            _, final = call(receipt["status_argv"], timeout=10)
        report["job"] = final
        report["wall_seconds"] = round(time.monotonic() - started, 3)
        output = repo / "repro_outputs"
        grade_path = temporary / "GRADE.json"
        result = subprocess.run([python, str(ROOT / "benchmarks/check_first_use.py"), "--baseline", str(baseline_path),
                                 "--repo", str(repo), "--output-dir", str(output), "--expected-stdout", "2 passed", "--report", str(grade_path)],
                                env=env, cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=30)
        grade = json.loads(grade_path.read_text(encoding="utf-8")) if grade_path.is_file() else {"ok": False}
        report["independent_grader"] = grade
        stdout_files = list((output / "_runtime").glob("*/stdout.log"))
        report["original_test_stdout"] = stdout_files[0].read_text(encoding="utf-8") if stdout_files else ""
        checks = {
            "readme_target_selected": plan.get("documented_command") == "python -m pytest",
            "returned_job_receipt": receipt.get("job_id") == final.get("job_id") and not receipt["terminal"],
            "supervisor_completed": final.get("lifecycle") == "completed",
            "receipt_identity_checked": final.get("identity_checked") is True,
            "job_acceptance": (final.get("result") or {}).get("accepted") is True,
            "independent_original_tests_and_fidelity": result.returncode == 0 and grade.get("ok") is True,
            "original_stdout_two_passed": "2 passed" in report["original_test_stdout"],
        }
        report["checks"] = checks
        report["status"] = "passed" if all(checks.values()) else "failed"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "summary": str(exc)}
    finally:
        report["scope"] = "One local installed-layout task using existing CPU dependencies, no live model; not automatic skill discovery, remote installer, or model uplift."
        output_path = (ROOT / args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if report["status"] == "passed":
            def writable(function, name, _error):
                os.chmod(name, 0o700)
                function(name)
            shutil.rmtree(temporary, onerror=writable)
        else:
            print("retained_failed_workspace:", temporary)
    print(json.dumps({key: report.get(key) for key in ("status", "checks", "start_return_seconds", "wall_seconds", "error")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
