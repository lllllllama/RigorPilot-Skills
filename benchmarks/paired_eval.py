#!/usr/bin/env python3
"""Prepare a frozen A/B pilot and calibrate its graders without model calls.

No live model backend is implemented here. A requested budget is not an enforced
budget, and deterministic calibration is never counted as a model trial.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from paired_tasks import TASK_IDS, prepare_task, grade_task

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "research-workflow-pilot-v1"
MAX_BYTES = 32 * 1024**2
COMMON_PROMPT = """
Preserve the original README, scientific code, configuration and evaluation
criteria. You may run documented local preparation/evaluation commands and
create their data/results, but do not install packages, download assets, train
large models, or change scientific semantics. Do not inspect other trials or
operator control files. End with claim.json containing outcome (matched,
mismatched, or blocked), observed_metrics (an object), and a short reason.
Report actual limitations. A successful process alone does not prove a match.
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def load(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > 2 * 1024**2:
        raise ValueError(f"unsafe or oversized control file: {path.name}")
    def reject(value: str):
        raise ValueError(f"non-finite JSON: {value}")
    def unique(pairs: list[tuple]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(value))


def inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("out-of-scope relative path")
    result = root / path
    if result.is_symlink() or not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("path escapes campaign")
    return result


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in frozen input")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            result[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return result


def disk_gate(path: Path) -> None:
    total = sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())
    if total > MAX_BYTES or shutil.disk_usage(path).free < 1024**3:
        raise ValueError("campaign storage gate exceeded (32 MiB / 1 GiB free); evidence retained")


def implementation_hashes() -> dict[str, str]:
    return {relative: sha((ROOT / relative).read_bytes())
            for relative in ("benchmarks/paired_eval.py", "benchmarks/paired_tasks.py")}


def python_environment(executable: str) -> dict:
    resolved = shutil.which(executable)
    if resolved is None:
        raise ValueError("selected Python executable is unavailable")
    code = (
        "import importlib.metadata as m,json,sys; p={}; "
        "exec('for n in (\"torch\",\"pytest\"):\\n try: p[n]=m.version(n)\\n except m.PackageNotFoundError: p[n]=None'); "
        "print(json.dumps(dict(executable=sys.executable,version=sys.version,packages=p)))"
    )
    result = subprocess.run([resolved, "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=20)
    if result.returncode:
        raise ValueError("Python metadata probe failed; no installation attempted")
    value = json.loads(result.stdout)
    value["requested_executable"] = str(Path(resolved).absolute())
    value["dependency_scope"] = "existing environment; metadata probe only; no cold installation"
    return value


def prepare(campaign: Path, python: str) -> dict:
    campaign = campaign.absolute()
    if campaign.exists() or campaign.is_symlink():
        raise ValueError("prepare requires a fresh directory; existing evidence is never replaced")
    environment = python_environment(python)
    campaign.mkdir(parents=True)
    disk_gate(campaign)
    slots = []
    skill_source = ROOT / "skills/ai-research-reproduction"
    skill_hashes = inventory(skill_source)
    if not skill_hashes or not (skill_source / "SKILL.md").is_file():
        raise ValueError("main skill package is missing")
    implementation = implementation_hashes()
    for task_id in TASK_IDS:
        for arm in ("A", "B"):
            slot_id = f"{task_id}-{arm}-r1"
            workspace = campaign / "workspaces" / slot_id
            workspace.mkdir(parents=True)
            task = prepare_task(task_id, workspace / "repo", ROOT)
            prompt = task["goal_en"] + "\n" + COMMON_PROMPT
            if arm == "B":
                shutil.copytree(skill_source, workspace / ".agents/skills/ai-research-reproduction",
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                prompt += "\nUse the installed ai-research-reproduction skill in .agents/skills/ai-research-reproduction.\n"
            # Only the task brief and repository are agent input, not this control manifest.
            with (workspace / "TASK.md").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(prompt)
            slots.append({"slot_id": slot_id, "task_id": task_id, "arm": arm, "repeat": 1,
                          "workspace": workspace.relative_to(campaign).as_posix(), "task": task,
                          "prompt_sha256": sha(prompt.encode("utf-8")), "initial_status": "not_run"})
    manifest = {
        "schema_version": "1.0", "protocol_id": PROTOCOL, "created_at": datetime.now(timezone.utc).isoformat(),
        "phase": "prepared_not_executed", "split": "development", "planned_live_slots": slots,
        "comparison_kind": "end_to_end_skill_package", "comparison_boundary":
            "B includes skill instructions and bundled helpers; this is not a prompt-only causal ablation.",
        "environment": environment, "environment_sha256": sha(encoded(environment)),
        "skill_sha256": sha(encoded(skill_hashes)), "skill_files": skill_hashes,
        "implementation_files": implementation, "implementation_sha256": sha(encoded(implementation)),
        "budget": {"status": "not_configured", "enforcement": "not_enforced", "subscription_balance": None},
        "model": None, "live_backend": "not_implemented", "limits": {"workspace_bytes": MAX_BYTES},
        "integrity_boundary": "Operator-controlled hash files detect accidental changes, not coordinated forgery or OS isolation.",
    }
    path = campaign / "control/manifest.json"
    write_new(path, manifest)
    write_new(campaign / "control/freeze.json", {"protocol_sha256": sha(path.read_bytes())})
    disk_gate(campaign)
    return {"campaign": str(campaign), "planned_live_trials": len(slots), "live_trials_started": 0,
            "protocol_sha256": sha(path.read_bytes()), "model_calls": 0}


def frozen(campaign: Path) -> dict:
    path = campaign / "control/manifest.json"
    manifest = load(path)
    if sha(path.read_bytes()) != load(campaign / "control/freeze.json")["protocol_sha256"]:
        raise ValueError("frozen protocol changed; create a new campaign")
    if manifest.get("protocol_id") != PROTOCOL:
        raise ValueError("unsupported protocol")
    expected = {f"{task}-{arm}-r1" for task in TASK_IDS for arm in ("A", "B")}
    slots = manifest.get("planned_live_slots", [])
    if len(slots) != 6 or {item["slot_id"] for item in slots} != expected:
        raise ValueError("frozen six-slot schedule is incomplete or duplicated")
    pairs = {}
    for slot in slots:
        if (slot["arm"] not in ("A", "B") or slot["task_id"] not in TASK_IDS
                or slot["repeat"] != 1 or slot["task"]["task_id"] != slot["task_id"]
                or slot["slot_id"] != f"{slot['task_id']}-{slot['arm']}-r1"
                or slot["workspace"] != f"workspaces/{slot['slot_id']}"):
            raise ValueError("frozen slot identity is inconsistent")
        previous = pairs.setdefault(slot["task_id"], slot["task"])
        if previous != slot["task"]:
            raise ValueError("paired task inputs differ")
    for field, values in (("environment_sha256", "environment"), ("skill_sha256", "skill_files"),
                          ("implementation_sha256", "implementation_files")):
        if sha(encoded(manifest[values])) != manifest[field]:
            raise ValueError(f"inconsistent frozen identity: {field}")
    if manifest["implementation_files"] != implementation_hashes():
        raise ValueError("executor or grader changed since freeze; create a new campaign")
    return manifest


def preflight(campaign: Path, configuration: Path | None = None) -> dict:
    manifest = frozen(campaign)
    problems = []
    for slot in manifest["planned_live_slots"]:
        workspace = inside(campaign, slot["workspace"])
        if sha((workspace / "TASK.md").read_bytes()) != slot["prompt_sha256"]:
            problems.append(f"changed task prompt: {slot['slot_id']}")
        repo = workspace / "repo"
        actual = inventory(repo)
        if actual != slot["task"]["immutable_sha256"]:
            problems.append(f"changed/non-fresh repository: {slot['slot_id']}")
        installed = workspace / ".agents/skills/ai-research-reproduction"
        if slot["arm"] == "B" and inventory(installed) != manifest["skill_files"]:
            problems.append(f"changed/missing skill: {slot['slot_id']}")
        if slot["arm"] == "A" and (workspace / ".agents").exists():
            problems.append(f"skill contamination in baseline: {slot['slot_id']}")
    environment = python_environment(manifest["environment"]["requested_executable"])
    if environment != manifest["environment"]:
        problems.append("selected Python environment changed")
    if not all(environment["packages"].get(name) for name in ("torch", "pytest")):
        problems.append("micrograd requires existing torch and pytest; no automatic installation")
    config = load(configuration) if configuration is not None else {}
    required = {"provider", "model", "revision", "max_total_tokens", "max_tokens_per_trial", "max_seconds_per_trial"}
    configuration_errors = []
    if set(config) != required:
        configuration_errors.append("explicit provider/model/revision and total/per-trial token/time limits are required (no extra fields)")
    for field in ("provider", "model", "revision"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            configuration_errors.append(f"missing explicit {field}")
    for field in ("max_total_tokens", "max_tokens_per_trial", "max_seconds_per_trial"):
        if type(config.get(field)) is not int or config[field] <= 0:
            configuration_errors.append(f"{field} must be a positive integer")
    if not configuration_errors and config["max_total_tokens"] < 6 * config["max_tokens_per_trial"]:
        configuration_errors.append("total tokens cannot reserve the same per-trial cap for all six planned slots")
    disk_gate(campaign)
    return {"phase": "preflight_only", "input_ready": not problems,
            "configuration_ready": not configuration_errors, "problems": problems,
            "configuration_errors": configuration_errors, "live_execution_ready": False,
            "budget_enforcement": "not_enforced", "budget_compliant": None,
            "reason": "No generic live executor is implemented; configuration validation cannot enforce usage or spending.",
            "isolation": "Fresh directories and a prompt restriction only; client/global-skill contamination still needs an isolated live executor.",
            "model_calls": 0}


def execute_step(step: dict, repo: Path, attempt: Path, python: str, *, timeout_seconds: float = 45) -> dict:
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 45):
        raise ValueError("command timeout must be positive and at most 45 seconds")
    argv = [python if item == "python" else item.replace("{attempt}", str(attempt)) for item in step["argv"]]
    # Reviewed local fixture commands only. No shell, provider transport or dependency installation.
    environment = {key: value for key, value in os.environ.items()
                   if not any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL"))}
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       PYTEST_ADDOPTS="-p no:cacheprovider", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", CUDA_VISIBLE_DEVICES="",
                       PATH=str(Path(python).parent) + os.pathsep + environment.get("PATH", ""), RIGORPILOT_LESSONS="0")
    start = time.monotonic()
    try:
        process = subprocess.run(argv, cwd=repo, env=environment, capture_output=True, timeout=timeout_seconds)
        returncode, stdout, stderr = process.returncode, process.stdout, process.stderr
        outcome = "completed"
    except subprocess.TimeoutExpired as error:
        returncode, stdout, stderr = None, error.stdout or b"", error.stderr or b""
        outcome = "timed_out"
    log_dir = attempt / "steps" / step["id"]
    log_dir.mkdir(parents=True)
    for name, data in (("stdout.log", stdout), ("stderr.log", stderr)):
        with (log_dir / name).open("xb") as stream:
            stream.write(data)
    record = {"step_id": step["id"], "argv": argv, "cwd": str(repo), "returncode": returncode,
              "stdout": stdout.decode("utf-8", errors="replace"), "stderr": stderr.decode("utf-8", errors="replace"),
              "outcome": outcome, "elapsed_seconds": round(time.monotonic() - start, 6),
              "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr), "source": step["source"],
              "timeout_seconds": timeout_seconds}
    write_new(log_dir / "receipt.json", record)
    return record


def calibrate(campaign: Path, task_ids: list[str]) -> dict:
    manifest = frozen(campaign)
    if not task_ids or len(task_ids) != len(set(task_ids)) or any(item not in TASK_IDS for item in task_ids):
        raise ValueError("calibration requires unique supported tasks")
    disk_gate(campaign)
    environment = python_environment(manifest["environment"]["requested_executable"])
    if environment != manifest["environment"]:
        raise ValueError("environment changed; create a fresh campaign")
    run_id = "calibration-" + uuid.uuid4().hex[:12]
    base = campaign / "calibration" / run_id
    base.mkdir(parents=True)
    write_new(base / "START.json", {"run_id": run_id, "task_ids": task_ids,
                                   "mode": "offline_calibration", "model_calls": 0})
    rows = []
    for task_id in task_ids:
        attempt = base / task_id
        attempt.mkdir()
        repo = attempt / "repo"
        task = prepare_task(task_id, repo, ROOT)
        expected = next(slot["task"] for slot in manifest["planned_live_slots"] if slot["task_id"] == task_id)
        if task != expected:
            raise ValueError("task generator or source changed since freeze; create a new campaign")
        if task_id == "micrograd" and not all(environment["packages"].get(name) for name in ("torch", "pytest")):
            rows.append({"task_id": task_id, "status": "not_run", "reason": "required dependencies unavailable", "passed": False})
            continue
        executions = []
        for step in task["commands"]:
            disk_gate(campaign)
            record = execute_step(step, repo, attempt, environment["requested_executable"])
            executions.append(record)
            if record["returncode"] != 0:
                break
        # Deliberately scripted claims calibrate the grader, never simulate measured model behavior.
        claim = {"outcome": "mismatched" if task_id == "wrong_metric" else "matched",
                 "observed_metrics": {} if task_id == "micrograd" else {"mse": 1.0 if task_id == "wrong_metric" else 0.0},
                 "reason": "Scripted grader calibration; not a model response."}
        result = grade_task(task_id, repo, task, executions, claim, attempt)
        write_new(attempt / "CLAIM.json", claim)
        write_new(attempt / "GRADE.json", result)
        rows.append({"task_id": task_id, "status": "completed", "passed": result["correct_handling"],
                     "grade": result, "path": attempt.relative_to(campaign).as_posix()})
        disk_gate(campaign)
    report = {"mode": "offline_calibration", "run_id": run_id, "rows": rows,
              "protocol_sha256": load(campaign / "control/freeze.json")["protocol_sha256"],
              "grader_sha256": sha((ROOT / "benchmarks/paired_tasks.py").read_bytes()),
              "model_calls": 0, "live_trial_count": 0,
              "claim_origin": "scripted; does not measure agent decisions or A/B effects"}
    write_new(base / "REPORT.json", report)
    return {"path": str(base / "REPORT.json"), "mode": report["mode"], "calibrated_tasks": len(rows),
            "passed": sum(bool(row["passed"]) for row in rows), "live_trials_started": 0, "model_calls": 0}


def summarize(campaign: Path) -> dict:
    manifest = frozen(campaign)
    calibration = []
    for directory in sorted((campaign / "calibration").glob("*")):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("unexpected calibration entry; evidence retained for review")
        if (directory / "REPORT.json").is_file():
            item = load(directory / "REPORT.json")
            if item["mode"] != "offline_calibration" or item["live_trial_count"] != 0:
                raise ValueError("non-calibration report cannot be imported as model evidence")
            calibration.append({"run_id": item["run_id"], "status": "completed", "tasks": len(item["rows"]),
                                "passed": sum(bool(row["passed"]) for row in item["rows"])})
        else:
            calibration.append({"run_id": directory.name, "status": "incomplete", "tasks": None,
                                "passed": None, "reason": "Missing REPORT.json; retained for inspection, not a pass."})
    return {"protocol_id": PROTOCOL, "phase": "prepared_not_live_evaluated",
            "planned_live_trials": 6, "live_trials_started": 0, "live_trials_not_run": 6,
            "live_completion_rate": None, "paired_effect": None, "tokens_used": None, "cost": None,
            "budget_compliant": None, "budget_enforcement": "not_enforced",
            "slots": [{"slot_id": slot["slot_id"], "status": "not_run"} for slot in manifest["planned_live_slots"]],
            "offline_calibrations": calibration,
            "limitations": ["No live executor, model trial, provider failure or model usage was measured by this kit.",
                            "Do not treat calibration passes as model success rates or discard planned slots.",
                            "A/B includes the skill package, not just its prompt; future tools/permissions/environment must be audited."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--python", default=sys.executable, help="Existing Python; no dependency installation")
    for name in ("preflight", "calibrate", "summarize"):
        command = sub.add_parser(name)
        command.add_argument("--campaign", type=Path, required=True)
        if name == "preflight":
            command.add_argument("--configuration", type=Path)
        elif name == "calibrate":
            command.add_argument("--tasks", nargs="+", choices=TASK_IDS, default=list(TASK_IDS))
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.output, args.python)
        elif args.command == "preflight":
            result = preflight(args.campaign.resolve(), args.configuration)
        elif args.command == "calibrate":
            if len(args.tasks) != len(set(args.tasks)):
                raise ValueError("duplicate calibration tasks")
            result = calibrate(args.campaign.resolve(), args.tasks)
        else:
            result = summarize(args.campaign.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command == "preflight":
            return 0 if result["input_ready"] and result["configuration_ready"] else 1
        if args.command == "calibrate":
            return int(result["passed"] != result["calibrated_tasks"])
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error), "model_calls": 0}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
