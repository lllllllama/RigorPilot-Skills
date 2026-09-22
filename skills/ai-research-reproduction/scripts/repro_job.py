#!/usr/bin/env python3
"""Short-call, at-most-once handoff to the existing reproduction orchestrator.

One output directory owns one bounded job. This is a local supervisor, not a
daemon, a sandbox, a distributed exactly-once service, or a model backend.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
from typing import Any

import orchestrate_repro as orchestrator
from runtime_runner import atomic_write_json, pid_is_alive, request_cancel


CONTROL = ".repro_job"
FINALIZATION_GRACE_SECONDS = 60
PREFLIGHT_SECONDS = 30
VERIFY_SECONDS = 30
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}
STATES = TERMINAL | {"queued", "working"}
SCRIPT = Path(__file__).resolve()
ORCHESTRATOR = SCRIPT.with_name("orchestrate_repro.py")


class JobError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def no_symlinks(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise JobError("unsafe_job_path", "Job control files must not be accessed through symlinks.")


def read_object(path: Path) -> dict[str, Any]:
    no_symlinks(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise JobError("invalid_job_record", "Job JSON exceeds the 2 MiB control-record limit.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise JobError("invalid_job_record", "Expected a JSON object in a job control record.")
    return value


def resolve_output(raw: str) -> Path:
    path = Path(os.path.abspath(raw))
    no_symlinks(path)
    return path.resolve()


def read_job(output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    control = output / CONTROL
    request = read_object(control / "request.json")
    state = read_object(control / "state.json")
    if (request.get("schema_version") != "1.0" or type(request.get("timeout")) is not int
            or not 1 <= request["timeout"] <= 86400
            or any(not isinstance(request.get(key), str) for key in ("repo", "output_dir", "python", "command_id", "plan_fingerprint", "user_language"))
            or not isinstance(request.get("expected_metric"), list)
            or not isinstance(state.get("lifecycle"), str)
            or state.get("schema_version") != "1.0" or state.get("lifecycle") not in STATES
            or not isinstance(state.get("updated_at"), str)
            or (state.get("worker_pid") is not None and type(state["worker_pid"]) is not int)
            or (state.get("result") is not None and not isinstance(state["result"], dict))
            or not re.fullmatch(r"[0-9a-f]{32}", str(state.get("job_id", "")))
            or state.get("request_sha256") != digest(request)
            or request.get("output_dir") != str(output)):
        raise JobError("invalid_job_record", "Job identity, state, or frozen request is inconsistent; do not replay.")
    return request, state


def status(output: Path, expected_job_id: str = "") -> dict[str, Any]:
    _request, state = read_job(output)
    if expected_job_id and state["job_id"] != expected_job_id:
        raise JobError("job_identity_mismatch", "This output directory no longer belongs to the expected job. Do not accept or cancel a replacement job.")
    result = dict(state)
    if state["lifecycle"] not in TERMINAL:
        pid = state.get("worker_pid")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(state["updated_at"])).total_seconds()
        if type(pid) is int and pid > 0 and not pid_is_alive(pid):
            result.update(lifecycle="interrupted", error={
                "code": "worker_lost", "summary": "Supervisor is no longer observable; inspect retained runtime, do not replay."})
        elif (not pid and age > 10) or age > 120:
            result.update(lifecycle="interrupted", error={
                "code": "worker_unconfirmed", "summary": "Stale or missing supervisor heartbeat; execution may still exist. Do not replay."})
    result.update(
        output_dir=str(output),
        terminal=result["lifecycle"] in TERMINAL,
        cancel_requested=(output / CONTROL / "CANCEL").exists(),
        automatic_replay_allowed=False,
        poll_after_seconds=2 if result["lifecycle"] not in TERMINAL else None,
        verification_is_completion_snapshot=True,
        identity_checked=bool(expected_job_id),
        status_argv=[sys.executable, str(SCRIPT), "status", "--output-dir", str(output), "--job-id", state["job_id"]],
        cancel_argv=[sys.executable, str(SCRIPT), "cancel", "--output-dir", str(output), "--job-id", state["job_id"]],
    )
    return result


def make_request(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    output = resolve_output(args.output_dir or str(repo / "repro_outputs"))
    if not repo.is_dir() or repo == output or repo.is_relative_to(output):
        raise JobError("invalid_job_path", "Use an existing repository and a distinct evidence directory, not its ancestor.")
    if not re.fullmatch(r"cmd-[0-9]+", args.command_id):
        raise JobError("invalid_command_id", "Use a cmd-XX identifier from a reviewed plan, not shell text.")
    if not re.fullmatch(r"[0-9a-f]{64}", args.plan_fingerprint):
        raise JobError("invalid_plan_fingerprint", "Use the 64-character fingerprint returned by --plan-only.")
    if not 1 <= args.timeout <= 86400:
        raise JobError("invalid_timeout", "Target timeout must be between 1 and 86400 seconds.")
    if not math.isfinite(args.metric_absolute_tolerance) or args.metric_absolute_tolerance < 0:
        raise JobError("invalid_metric_tolerance", "Metric tolerance must be finite and non-negative.")
    orchestrator.parse_expected_metrics(args.expected_metric)
    return {
        "schema_version": "1.0", "repo": str(repo), "output_dir": str(output),
        "python": os.path.abspath(sys.executable),
        "command_id": args.command_id, "plan_fingerprint": args.plan_fingerprint,
        "timeout": args.timeout, "shell_mode": args.shell_mode,
        "user_language": args.user_language, "source_adjacent_readme": args.source_adjacent_readme,
        "expected_metric": sorted(args.expected_metric),
        "metric_absolute_tolerance": args.metric_absolute_tolerance,
        "finalization_grace_seconds": FINALIZATION_GRACE_SECONDS,
        "python_output_unbuffered": True,
    }


def start(request: dict[str, Any]) -> dict[str, Any]:
    output = Path(request["output_dir"])
    control = output / CONTROL
    request_hash = digest(request)
    no_symlinks(control)
    if control.is_dir():
        old_request, _state = read_job(output)
        if digest(old_request) != request_hash:
            raise JobError("job_conflict", "This evidence directory belongs to a different frozen request; choose a new directory.")
        return {**status(output), "reused": True}
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise JobError("output_not_empty", "A new job requires an empty evidence directory; existing evidence will not be replaced.")
    try:
        control.mkdir()  # Atomic ownership claim; a simultaneous caller must never spawn a second worker.
    except FileExistsError:
        raise JobError("job_initializing", "Another start owns this directory. Query status; do not launch another output implicitly.")
    state = {
        "schema_version": "1.0", "job_id": uuid.uuid4().hex,
        "request_sha256": request_hash, "lifecycle": "queued", "phase": "handoff",
        "created_at": now(), "updated_at": now(), "worker_pid": None,
        "result": None, "error": None,
    }
    atomic_write_json(control / "request.json", request)
    atomic_write_json(control / "state.json", state)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        # No inherited pipes and no shell; intentionally retain any host sandbox/job restrictions.
        with (control / "worker.log").open("ab") as log:
            subprocess.Popen(
                [request["python"], str(SCRIPT), "_work", "--output-dir", str(output),
                 "--job-id", state["job_id"], "--request-sha256", request_hash],
                cwd=request["repo"], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                close_fds=True, creationflags=flags, start_new_session=os.name != "nt",
            )
    except OSError:
        state.update(lifecycle="failed", updated_at=now(), error={
            "code": "worker_launch_failed", "summary": "Supervisor launch failed; receipt retained and not replayed."})
        atomic_write_json(control / "state.json", state)
    return {**status(output), "reused": False}


def cancel(output: Path, expected_job_id: str = "") -> dict[str, Any]:
    current = status(output, expected_job_id)
    if current["terminal"]:
        return current
    marker = output / CONTROL / "CANCEL"
    no_symlinks(marker)
    marker.touch(exist_ok=True)
    return {**current, "cancel_requested": True, "cancellation_is_cooperative": True}


def stop_owned_process(process: subprocess.Popen) -> None:
    """Last-resort watchdog, never a success path or PID-based replay mechanism."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def worker(output: Path, job_id: str, request_hash: str) -> int:
    request, state = read_job(output)
    control = output / CONTROL
    if state["job_id"] != job_id or digest(request) != request_hash:
        raise JobError("job_identity_mismatch", "The worker launch does not match its frozen request.")
    no_symlinks(control / "worker.claim")
    try:
        with (control / "worker.claim").open("x", encoding="utf-8") as claim:
            claim.write(job_id)
    except FileExistsError:
        raise JobError("worker_already_claimed", "This job already dispatched or may have dispatched; replay is forbidden.")

    def update(**changes: Any) -> None:
        state.update(changes, updated_at=now(), worker_pid=os.getpid())
        atomic_write_json(control / "state.json", state)

    def invoke(argv: list[str], phase: str, budget: int) -> tuple[int, dict[str, Any]]:
        update(lifecycle="working", phase=phase)
        stdout = control / f"{phase}.stdout.json"
        stderr = control / f"{phase}.stderr.log"
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with stdout.open("wb") as out, stderr.open("wb") as err:
            proc = subprocess.Popen(argv, cwd=request["repo"], env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, creationflags=flags, start_new_session=os.name != "nt")
            deadline = time.monotonic() + budget
            heartbeat = 0.0
            try:
                while proc.poll() is None:
                    if phase == "execution" and (control / "CANCEL").exists():
                        # Do not terminate the writer. Ask its existing runtime to clean up and finalize.
                        for path in (output / "_runtime").glob("*/state.json"):
                            no_symlinks(path)
                            request_cancel(output / "_runtime", path.parent.name)
                    if time.monotonic() >= deadline:
                        stop_owned_process(proc)
                        raise JobError("supervisor_deadline", "Lifecycle budget expired; evidence may be incomplete. Inspect, do not replay.")
                    if time.monotonic() >= heartbeat:
                        update(controller_pid=proc.pid)
                        heartbeat = time.monotonic() + 1
                    time.sleep(0.1)
            finally:
                if proc.poll() is None:
                    stop_owned_process(proc)
        try:
            payload = read_object(stdout)
        except (ValueError, OSError):
            payload = {}
        return proc.returncode, payload

    try:
        update(lifecycle="working", phase="preflight")
        if (control / "CANCEL").exists():
            update(lifecycle="cancelled", phase="finished")
            return 0
        base = [request["python"], str(ORCHESTRATOR), "--repo", request["repo"],
                "--output-dir", str(output), "--command-id", request["command_id"],
                "--plan-fingerprint", request["plan_fingerprint"], "--timeout", str(request["timeout"]),
                "--shell-mode", request["shell_mode"], "--agent-output", "--no-gpu-monitor",
                "--user-language", request["user_language"]]
        code, plan = invoke([*base, "--plan-only"], "planning", PREFLIGHT_SECONDS)
        if code != 0 or plan.get("mode") != "plan_only":
            error = plan.get("error") or {"code": "plan_failed", "summary": "Read-only preflight failed; see retained planning logs."}
            update(lifecycle="failed", phase="finished", error=error)
            return 1
        if plan.get("selected_goal") == "training":
            raise JobError("training_job_not_supported", "This short-call entrypoint covers inference/evaluation only; use the reviewed training lane.")
        if (control / "CANCEL").exists():
            update(lifecycle="cancelled", phase="finished")
            return 0
        extra: list[str] = []
        for metric in request["expected_metric"]:
            extra += ["--expected-metric", metric]
        extra += ["--metric-absolute-tolerance", str(request["metric_absolute_tolerance"])]
        if request["source_adjacent_readme"]:
            extra += ["--source-adjacent-readme"]
        code, execution = invoke([*base, "--run-selected", *extra], "execution",
                                 request["timeout"] + FINALIZATION_GRACE_SECONDS)
        vcode, verification = invoke(
            [request["python"], str(ORCHESTRATOR), "--repo", request["repo"],
             "--output-dir", str(output), "--verify-output", "--agent-output"], "verification", VERIFY_SECONDS)
        accepted = (
            code == 0 and vcode == 0 and verification.get("evidence_valid") is True
            and verification.get("task_status") == "success" and verification.get("runtime_status") == "success"
            and verification.get("result_match") != "mismatched"
            and (verification.get("source_integrity") or {}).get("unchanged") is True
            and (verification.get("evidence_manifest") or {}).get("coverage") == "complete_manifest_v1_1"
            and (not request["source_adjacent_readme"] or (execution.get("source_adjacent_readme") or {}).get("status") == "written")
        )
        update(lifecycle="completed", phase="finished", result={
            "accepted": accepted, "task_status": verification.get("task_status"),
            "runtime_status": verification.get("runtime_status"), "evidence_valid": verification.get("evidence_valid") is True,
            "result_match": verification.get("result_match"), "execution_exit_code": code,
            "verification_exit_code": vcode, "error": execution.get("error") or verification.get("error"),
            "verification_path": str(control / "verification.stdout.json"), "verified_at": now(),
        })
        return 0
    except Exception as exc:
        traceback.print_exc()  # Local diagnostic only; reports expose the allowlisted exception class below.
        update(lifecycle="failed", phase="finished", error={
            "code": exc.code if isinstance(exc, JobError) else "worker_error",
            "summary": str(exc) if isinstance(exc, JobError) else f"Supervisor failed ({type(exc).__name__}); inspect retained logs, do not replay.",
        })
        return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    launch = commands.add_parser("start", help="Claim one frozen request and return promptly; acceptance is not implied.")
    launch.add_argument("--repo", required=True)
    launch.add_argument("--output-dir", default="")
    launch.add_argument("--command-id", required=True)
    launch.add_argument("--plan-fingerprint", required=True)
    launch.add_argument("--timeout", type=int, required=True)
    launch.add_argument("--shell-mode", choices=["direct", "native"], default="direct")
    launch.add_argument("--user-language", default="en")
    launch.add_argument("--source-adjacent-readme", action="store_true")
    launch.add_argument("--expected-metric", action="append", default=[])
    launch.add_argument("--metric-absolute-tolerance", type=float, default=0.0)
    for name in ("status", "cancel", "_work"):
        command = commands.add_parser(name, help="Internal worker" if name == "_work" else f"{name.title()} one existing job; never replay it.")
        command.add_argument("--output-dir", required=True)
        if name == "_work":
            command.add_argument("--job-id", required=True)
            command.add_argument("--request-sha256", required=True)
        else:
            command.add_argument("--job-id", default="", help="Expected job identity from the start receipt; rejects a replaced output directory.")
    args = parser.parse_args()
    try:
        if args.action == "start":
            payload = start(make_request(args))
        elif args.action == "_work":
            return worker(resolve_output(args.output_dir), args.job_id, args.request_sha256)
        else:
            output = resolve_output(args.output_dir)
            payload = cancel(output, args.job_id) if args.action == "cancel" else status(output, args.job_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"schema_version": "1.0", "error": {
            "code": exc.code if isinstance(exc, JobError) else "job_control_error",
            "summary": str(exc) if isinstance(exc, JobError) else f"Unable to read or operate this job ({type(exc).__name__}). Inspect the existing directory; do not replay.",
        }, "automatic_replay_allowed": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
