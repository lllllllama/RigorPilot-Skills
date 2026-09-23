#!/usr/bin/env python3
"""Run regression scripts with durable logs and bounded execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


CORE_TESTS = [
    "test_agent_skills_spec.py", "test_command_execution_portability.py",
    "test_first_use_basics.py", "test_first_use_verifier.py",
    "test_operating_principles_structure.py", "test_orchestrator_dry_run.py",
    "test_readme_annotation.py", "test_readme_selection.py",
    "test_reproduction_command_selection.py", "test_reproduction_default_paths.py",
    "test_reproduction_fast_path.py", "test_reproduction_metric_verification.py",
    "test_reproduction_verifier_contract.py", "test_runtime_atomic_write.py",
    "test_runtime_recovery.py", "test_runtime_runner.py", "test_setup_planning.py",
    "test_single_skill_install.py", "test_skill_registry.py",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(root: Path, *args: str) -> bytes | None:
    try:
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_snapshot(root: Path) -> str | None:
    included = ("scripts", "skills", "shared", "references", "benchmarks", "README.md", "README.zh-CN.md", "requirements-dev.txt", ".github/workflows/validate.yml")
    paths = _git(root, "ls-files", "-z", "--", *included)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *included)
    if paths is None or untracked is None:
        return None
    digest = hashlib.sha256()
    for raw in sorted(set(filter(None, (paths + untracked).split(b"\0")))):
        path = root / os.fsdecode(raw)
        digest.update(raw + b"\0")
        if path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _terminate_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", action="store_true", help="Run the existing high-signal subset")
    parser.add_argument("--list", action="store_true", help="List selected scripts without running them")
    parser.add_argument("--report", type=Path, help="Write JSON report here; logs go in a sibling directory")
    parser.add_argument("--timeout-seconds", type=float, default=480, help="Per-script time limit (default: 480)")
    parser.add_argument("--scripts-dir", type=Path, default=Path(__file__).resolve().parent, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be finite and positive")
    scripts_dir = args.scripts_dir.resolve()
    if args.core:
        targets = [scripts_dir / "validate_repo.py", *(scripts_dir / name for name in CORE_TESTS)]
    else:
        targets = [scripts_dir / "validate_repo.py"] + sorted(scripts_dir.glob("test_*.py"))
    if args.list:
        for target in targets:
            print(target.name)
        return 0

    root = Path(__file__).resolve().parents[1]
    report = args.report.resolve() if args.report else Path(tempfile.mkdtemp(prefix="rigorpilot-regression-")) / "report.json"
    log_dir = report.parent / (report.stem + "_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0", "suite": "core" if args.core else "full",
        "tested_commit": (_git(root, "rev-parse", "HEAD") or b"").decode("ascii", errors="replace").strip() or None,
        "source_snapshot_sha256": _source_snapshot(root), "status": "running",
        "started_at": _utc_now(), "finished_at": None,
        "selected_count": len(targets), "completed_count": 0, "active_test": None,
        "timeout_seconds": args.timeout_seconds, "results": [],
    }
    _write_report(report, payload)
    print(f"report: {report}", flush=True)
    suite_started = time.perf_counter()
    interrupted = False
    for target in targets:
        log_path = log_dir / f"{target.stem}.log"
        payload["active_test"] = target.name
        _write_report(report, payload)
        started = time.perf_counter()
        status = "failed"
        exit_code = None
        process = None
        try:
            with log_path.open("wb") as log:
                if not target.is_file():
                    log.write(f"Missing test script: {target}\n".encode("utf-8"))
                else:
                    process = subprocess.Popen(
                        [sys.executable, str(target)], cwd=str(root), stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                        start_new_session=os.name != "nt",
                    )
                    try:
                        exit_code = process.wait(timeout=args.timeout_seconds)
                        status = "passed" if exit_code == 0 else "failed"
                    except subprocess.TimeoutExpired:
                        status = "timed_out"
                        _terminate_tree(process)
                        log.write(f"\nTIMEOUT after {args.timeout_seconds} seconds\n".encode("utf-8"))
        except KeyboardInterrupt:
            interrupted = True
            status = "interrupted"
            if process is not None:
                _terminate_tree(process)
        except OSError as exc:
            with log_path.open("ab") as log:
                log.write(f"\nRunner error: {exc}\n".encode("utf-8", errors="replace"))
        elapsed = time.perf_counter() - started
        row = {
            "script": target.name, "status": status, "exit_code": exit_code,
            "duration_seconds": round(elapsed, 3), "log_path": str(log_path.relative_to(report.parent)).replace("\\", "/"),
        }
        payload["results"].append(row)
        payload["completed_count"] = len(payload["results"])
        payload["active_test"] = None
        _write_report(report, payload)
        print(f"{status.upper()} {target.name} ({elapsed:.1f}s); log: {log_path}", flush=True)
        if interrupted:
            break

    failures = [row["script"] for row in payload["results"] if row["status"] != "passed"]
    payload["status"] = "interrupted" if interrupted else "failed" if failures else "passed"
    payload["finished_at"] = _utc_now()
    _write_report(report, payload)
    print(f"\n{payload['completed_count'] - len(failures)}/{payload['selected_count']} {payload['suite']} scripts passed in {time.perf_counter() - suite_started:.1f}s")
    if failures:
        print("failed: " + ", ".join(failures))
    return 0 if payload["status"] == "passed" else 130 if interrupted else 1


if __name__ == "__main__":
    raise SystemExit(main())
