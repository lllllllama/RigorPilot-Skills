#!/usr/bin/env python3
"""Run the installed skill's real runtime, with independent evidence checks.

Deterministic functional acceptance, NOT an A/B model experiment. No downloads,
model calls, GPU jobs or package installation. Optional micrograd uses existing
torch/pytest and the hash-verified upstream archive retained in this project.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from check_first_use import grade as grade_evidence, recorded_path, read_bytes
from paired_eval import disk_gate, inventory, load, python_environment, sha, write_new
from paired_tasks import prepare_task, _linear_artifacts

ROOT = Path(__file__).resolve().parents[1]
CASES = ("missing_asset", "matching_metric", "wrong_metric")


def verify_case(case: str, repo: Path, evidence: Path) -> dict:
    """Check exact positive/negative outcomes, independently of product summaries.

    Unlike the success-only first-use grader, a negative case must both fail for
    the specified reason AND truthfully report failure. It cannot pass merely
    because some error occurred. No model-generated grading is involved.
    """
    try:
        if case not in (*CASES, "micrograd"):
            raise ValueError("Unknown acceptance case")
        status = load(evidence / "status.json")
        runtime = status["runtime"]
        run_id = runtime["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("Invalid run_id")
        directory = evidence / "_runtime" / run_id
        files = {}
        for key, name in (("state_path", "state.json"), ("events_path", "events.jsonl"),
                          ("stdout_log_path", "stdout.log"), ("stderr_log_path", "stderr.log")):
            path = recorded_path(runtime[key], evidence, (evidence,))
            if path != (directory / name).resolve():
                raise ValueError("Runtime path disagrees with run_id")
            files[name] = path
        state, spec = load(files["state.json"]), load(directory / "spec.json")
        failed = case == "missing_asset"
        execution = "failed" if failed else "success"
        if (state.get("run_id") != run_id or spec.get("run_id") != run_id or
                state.get("status") != execution or runtime.get("status") != execution or
                type(state.get("returncode")) is not int or (state["returncode"] != 0) != failed):
            raise ValueError("Runtime terminal outcome disagrees with case")
        if not state.get("finished_at") or any(state.get(key) for key in ("cancelled", "timed_out", "launch_error")):
            raise ValueError("Missing completion or interrupted runtime")
        if runtime.get("cancelled") or spec.get("command") != status.get("documented_command"):
            raise ValueError("Reported execution disagrees with actual runtime")
        if Path(spec["cwd"]).resolve() != repo.resolve() or Path(status["target_repo"]).resolve() != repo.resolve():
            raise ValueError("Wrong execution directory")
        events = [json.loads(line) for line in read_bytes(files["events.jsonl"]).decode("utf-8").splitlines() if line.strip()]
        if (not events or any(not isinstance(event, dict) for event in events) or
                events[-1].get("type") != "completed" or
                events[-1].get("data", {}).get("status") != execution or
                events[-1].get("data", {}).get("returncode") != state["returncode"]):
            raise ValueError("Completion event missing or inconsistent")
        stdout = read_bytes(files["stdout.log"]).decode("utf-8", errors="replace")
        stderr = read_bytes(files["stderr.log"]).decode("utf-8", errors="replace")
        expected_overall = "partial" if case in ("missing_asset", "wrong_metric") else "success"
        expected_metric = {"missing_asset": "mismatched", "wrong_metric": "mismatched",
                           "matching_metric": "matched", "micrograd": "not_evaluated"}[case]
        if (status.get("status") != expected_overall or
                status.get("documented_command_status") != ("partial" if failed else "success") or
                status.get("result_match", {}).get("status") != expected_metric):
            raise ValueError("Reported task/metric outcome disagrees with expected case")
        observed = None
        if case == "micrograd":
            if "2 passed" not in stdout:
                raise ValueError("Original micrograd tests did not both pass")
        else:
            if spec["command"] != "python evaluate.py":
                raise ValueError("Unexpected fixture command")
            if failed:
                if ((repo / "data/samples.csv").exists() or (repo / "results").exists() or
                        "FileNotFoundError" not in stderr or "samples.csv" not in stderr or
                        status.get("observed_metrics")):
                    raise ValueError("Not the expected missing-asset failure")
            else:
                observed = _linear_artifacts("missing_asset" if case == "matching_metric" else case, repo)
                expected = 0.0 if case == "matching_metric" else 1.0
                if observed != expected or status.get("observed_metrics", {}).get("mse") != observed or f"mse={observed}" not in stdout:
                    raise ValueError("Independent prediction/MSE check disagrees with report or log")
            comparison = status["result_match"]["comparisons"]
            if (len(comparison) != 1 or comparison[0].get("metric") != "mse" or
                    comparison[0].get("expected") != 0 or comparison[0].get("observed") != observed or
                    comparison[0].get("within_tolerance") is not (case == "matching_metric") or
                    status["result_match"].get("absolute_tolerance") != 1e-12):
                raise ValueError("Expected metric or tolerance was changed")
        return {"ok": True, "runtime_status": execution, "returncode": state["returncode"],
                "task_status": expected_overall, "metric_status": expected_metric, "independent_mse": observed,
                "stdout_sha256": sha(read_bytes(files["stdout.log"])),
                "stderr_sha256": sha(read_bytes(files["stderr.log"]))}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"ok": False, "error": str(error)}


def run(output: Path, python: str, include_micrograd: bool = False) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("Use a fresh output directory; previous evidence is never overwritten")
    output = output.resolve()
    environment = python_environment(python)
    if include_micrograd and not all(environment["packages"].get(name) for name in ("torch", "pytest")):
        raise ValueError("micrograd requires existing torch/pytest; no installation attempted")
    executable = environment["requested_executable"]
    output.mkdir(parents=True)
    disk_gate(output)
    installed = output / "installed/ai-research-reproduction"
    source = ROOT / "skills/ai-research-reproduction"
    source_hashes = inventory(source)
    shutil.copytree(source, installed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if inventory(installed) != source_hashes:
        raise ValueError("Installed skill differs from source snapshot")
    schedule = (*CASES, "micrograd") if include_micrograd else CASES
    write_new(output / "START.json", {"created_at": datetime.now(timezone.utc).isoformat(),
              "protocol": "installed-skill-functional-acceptance-v1", "cases": schedule,
              "environment": environment, "skill_files": source_hashes,
              "implementation_files": {name: sha((ROOT / name).read_bytes()) for name in (
                  "benchmarks/run_skill_acceptance.py", "benchmarks/check_first_use.py", "benchmarks/paired_tasks.py",
                  "benchmarks/paired_eval.py")},
              "installation": "local_skill_directory_copy_not_remote_installer"})
    child_env = {key: value for key, value in os.environ.items()
                 if not any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL"))}
    child_env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", RIGORPILOT_LESSONS="0",
                     PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="-p no:cacheprovider", CUDA_VISIBLE_DEVICES="")
    child_env["PATH"] = str(Path(executable).parent) + os.pathsep + child_env.get("PATH", "")
    rows = []

    def execute(argv, cwd, directory):
        directory.mkdir(parents=True, exist_ok=False)
        started = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=cwd, env=child_env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=60)
        except subprocess.TimeoutExpired:
            write_new(directory / "ERROR.json", {"reason": "acceptance_process_timeout", "timeout_seconds": 60})
            raise
        (directory / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (directory / "stderr.log").write_text(result.stderr, encoding="utf-8")
        receipt = {"argv": argv, "cwd": str(cwd), "returncode": result.returncode,
                   "seconds": round(time.monotonic() - started, 3)}
        write_new(directory / "RECEIPT.json", receipt)
        return result, receipt

    for case in schedule:
        disk_gate(output)
        base = output / case
        task = prepare_task("missing_asset" if case == "matching_metric" else case, base / "repo", ROOT)
        repo, evidence = base / "repo", base / "evidence"
        baseline = base / "BASELINE.json"
        write_new(baseline, {"originals": task["immutable_sha256"], "origin": task["origin"]})
        if case == "matching_metric":
            # Explicit fixture preparation is recorded, never attributed to an agent.
            prepared, _ = execute([executable, "prepare_data.py"], repo, base / "operator-preparation")
            if prepared.returncode:
                raise ValueError("Documented local fixture preparation failed")
        if (repo / "results").exists():
            raise ValueError("Result directory must be absent before this run")
        command = [executable, str(installed / "scripts/orchestrate_repro.py"), "--repo", str(repo),
                   "--output-dir", str(evidence), "--run-selected", "--source-adjacent-readme",
                   "--user-language", "zh-CN", "--timeout", "30", "--no-gpu-monitor"]
        if case != "micrograd":
            command += ["--expected-metric", "mse=0", "--metric-absolute-tolerance", "0.000000000001"]
        process, receipt = execute(command, base, base / "invocation")
        if process.returncode:
            raise ValueError("Skill failed to write its evidence bundle; inspect invocation logs")
        status = load(evidence / "status.json")
        check = grade_evidence(baseline, repo, evidence, None if case == "missing_asset" else
                               ("2 passed" if case == "micrograd" else "mse="))
        write_new(base / "CHECK.json", check)
        actual = status.get("overall_status", status.get("status"))
        metric_status = status.get("result_match", {}).get("status")
        case_check = verify_case(case, repo, evidence)
        artifact_checks = {key: check["checks"][key] for key in ("original_files", "readme_fidelity_and_links", "status_file")}
        fidelity = all(item["ok"] for item in artifact_checks.values())
        # CHECK.json remains the unchanged success-only grader, including its
        # expected rejection of negative outcomes. Never relax it for a green run.
        success_case = case in ("matching_metric", "micrograd")
        passed = fidelity and case_check["ok"] and (not success_case or check["ok"])
        write_new(base / "ACCEPTANCE.json", {"ok": passed, "artifact_checks": artifact_checks,
                  "case_check": case_check, "success_only_grader_applicable": success_case,
                  "success_only_grader": "CHECK.json"})
        row = {"case": case, "origin": task["origin"], "passed": bool(passed),
               "task_status": actual, "metric_status": metric_status,
               "runtime_success": status.get("runtime", {}).get("status") == "success",
               "source_and_readme_verified": fidelity, "seconds": receipt["seconds"],
               "readme": f"{case}/repo/RIGORPILOT_README.md", "check": f"{case}/ACCEPTANCE.json",
               "status": f"{case}/evidence/status.json"}
        rows.append(row)
        write_new(base / "RESULT.json", row)
    if inventory(installed) != source_hashes:
        raise ValueError("Skill package changed during acceptance")
    report = {"protocol": "installed-skill-functional-acceptance-v1", "ok": all(row["passed"] for row in rows),
              "passed": sum(row["passed"] for row in rows), "total": len(rows), "rows": rows,
              "model_calls": 0, "model_effect": None, "scope": "deterministic_runtime_acceptance_not_model_gain",
              "limitations": ["Local installed-layout copy, not remote installation or automatic skill discovery.",
                              "Prepared actions are scripted; no agent decision or A/B advantage is measured.",
                              "micrograd uses a hash-verified archive and existing dependencies, not cold setup.",
                              "Hash/log checks assume a trusted operator and do not prove scientific generalization."]}
    write_new(output / "REPORT.json", report)
    disk_gate(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--include-micrograd", action="store_true")
    args = parser.parse_args()
    try:
        report = run(args.output, args.python, args.include_micrograd)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "evidence_retained": str(args.output)}))
        return 1
    print(json.dumps({"ok": report["ok"], "passed": report["passed"], "total": report["total"],
                      "report": str(args.output / "REPORT.json"), "model_effect": None}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
