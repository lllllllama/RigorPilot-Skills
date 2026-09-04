#!/usr/bin/env python3
"""Run an explicit, sequential set of pinned external benchmark cases."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compact_result(report: dict[str, Any]) -> dict[str, Any]:
    source = report.get("source") or {}
    limits = report.get("limits") or {}
    selection = report.get("selection") or {}
    execution = report.get("execution") or {}
    evidence = report.get("evidence") or {}
    archive = evidence.get("archive") or {}
    readme_fidelity = evidence.get("readme_fidelity") or {}
    identity = report.get("identity") or {}
    return {
        "generated_at": report.get("generated_at"),
        "case": report.get("case"),
        "status": report.get("status"),
        "commit": source.get("actual_commit"),
        "harness_sha256": identity.get("harness_sha256"),
        "case_sha256": identity.get("case_sha256"),
        "tier": (report.get("scope") or {}).get("tier"),
        "selected_goal": selection.get("actual_goal"),
        "selected_command": selection.get("actual_command"),
        "execution_requested": execution.get("requested"),
        "execution_status": execution.get("actual_status"),
        "dimensions": report.get("dimensions") or {},
        "wall_duration_seconds": report.get("wall_duration_seconds"),
        "peak_workspace_bytes": limits.get("peak_workspace_bytes"),
        "evidence_archive_bytes": archive.get("total_bytes"),
        "readme_fidelity": readme_fidelity,
        "showcase": report.get("showcase"),
        "workspace_cleanup": (report.get("scope") or {}).get("workspace_cleanup"),
        "main_blocker": report.get("main_blocker"),
    }


def append_history(path: Path, rows: list[dict[str, Any]], suite_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps({"suite_id": suite_id, **row}, ensure_ascii=False) + "\n")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", required=True, help="Explicit ordered case names; no run-all default.")
    parser.add_argument("--manifest", default="benchmarks/external_cases.json")
    parser.add_argument("--output", default="benchmark_outputs/external_suite_latest.json")
    parser.add_argument("--history", default="benchmark_outputs/external_suite_history.jsonl")
    parser.add_argument("--max-total-minutes", type=float, default=15.0)
    parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    parser.add_argument("--showcase-root", help="Retain tracked repository snapshots for browsable README examples.")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    if args.max_total_minutes <= 0 or args.min_free_disk_gb < 0:
        parser.error("time and disk limits must be positive")
    if len(set(args.cases)) != len(args.cases):
        parser.error("duplicate case names are not allowed")

    runner = REPO_ROOT / "benchmarks" / "run_external_reproduction.py"
    manifest = Path(args.manifest).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    history = Path(args.history).expanduser().resolve()
    suite_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = time.monotonic()
    initial_free = shutil.disk_usage(REPO_ROOT).free
    rows: list[dict[str, Any]] = []
    stopped_reason = None

    for case in args.cases:
        elapsed = time.monotonic() - started
        if elapsed >= args.max_total_minutes * 60:
            stopped_reason = "suite time budget exhausted before the next case"
            break
        if shutil.disk_usage(REPO_ROOT).free < args.min_free_disk_gb * 1024**3:
            stopped_reason = "suite free-disk safety floor reached"
            break
        case_output = output.parent / f"external_{case}.json"
        command = [
            sys.executable,
            str(runner),
            "--case",
            case,
            "--manifest",
            str(manifest),
            "--output",
            str(case_output),
            "--min-free-disk-gb",
            str(args.min_free_disk_gb),
        ]
        if args.showcase_root:
            command.extend(["--showcase-root", str(Path(args.showcase_root).expanduser().resolve())])
        remaining = max(1, int(args.max_total_minutes * 60 - elapsed))
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=remaining,
                check=False,
            )
        except subprocess.TimeoutExpired:
            rows.append({"generated_at": utc_now(), "case": case, "status": "failed", "main_blocker": "suite time budget exhausted during case"})
            stopped_reason = "suite time budget exhausted during case"
            break
        if case_output.is_file():
            report = json.loads(case_output.read_text(encoding="utf-8"))
            row = compact_result(report)
        else:
            row = {
                "generated_at": utc_now(),
                "case": case,
                "status": "failed",
                "main_blocker": f"runner exited {completed.returncode} without a report",
            }
        row["runner_returncode"] = completed.returncode
        rows.append(row)
        print(f"{case}: {row['status']} ({row.get('wall_duration_seconds', 0)}s)")
        if args.fail_fast and row["status"] != "passed":
            stopped_reason = f"fail-fast after {case}"
            break

    passed = sum(row.get("status") == "passed" for row in rows)
    suite = {
        "schema_version": "1.0",
        "benchmark": "rigorpilot-external-suite",
        "suite_id": suite_id,
        "generated_at": utc_now(),
        "requested_cases": args.cases,
        "completed_cases": [row["case"] for row in rows],
        "status": "passed" if len(rows) == len(args.cases) and passed == len(rows) else "failed",
        "passed": passed,
        "failed": len(rows) - passed,
        "stopped_reason": stopped_reason,
        "wall_duration_seconds": round(time.monotonic() - started, 6),
        "initial_free_disk_bytes": initial_free,
        "final_free_disk_bytes": shutil.disk_usage(REPO_ROOT).free,
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    append_history(history, rows, suite_id)
    print(json.dumps({key: suite[key] for key in ["status", "passed", "failed", "wall_duration_seconds", "stopped_reason"]}, ensure_ascii=False))
    return 0 if suite["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
