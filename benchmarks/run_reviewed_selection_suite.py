#!/usr/bin/env python3
"""Check reviewed command planning on pinned real repositories without execution."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "skills/ai-research-reproduction/scripts/orchestrate_repro.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_case(case: dict, root: Path) -> Path:
    repo = root / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, timeout=30)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "core.autocrlf=false", "fetch", "--depth", "1", case["repository"], case["commit"]],
        check=True, capture_output=True, timeout=120,
    )
    subprocess.run(
        ["git", "-C", str(repo), "-c", "core.autocrlf=false", "checkout", "--detach", "FETCH_HEAD"],
        check=True, capture_output=True, timeout=30,
    )
    return repo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", required=True, help="Explicit pinned case names; no implicit run-all mode.")
    parser.add_argument("--manifest", default="benchmarks/external_cases.json")
    parser.add_argument("--output", default="benchmark_outputs/reviewed_selection_latest.json")
    parser.add_argument("--max-total-minutes", type=float, default=5.0)
    args = parser.parse_args()
    if args.max_total_minutes <= 0:
        parser.error("--max-total-minutes must be positive")
    if len(set(args.cases)) != len(args.cases):
        parser.error("duplicate case names are not allowed")

    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8-sig"))
    all_cases = manifest.get("cases", {})
    unknown = [name for name in args.cases if name not in all_cases]
    if unknown:
        parser.error("unknown cases: " + ", ".join(unknown))

    started = time.monotonic()
    rows: list[dict] = []
    for name in args.cases:
        if time.monotonic() - started >= args.max_total_minutes * 60:
            rows.append({"case": name, "status": "blocked", "reason": "suite_time_budget_exhausted"})
            break
        case = all_cases[name]
        commit = str(case.get("commit") or "")
        if case.get("status") != "ready" or not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            rows.append({"case": name, "status": "failed", "reason": "case_not_ready_or_commit_not_pinned"})
            continue
        orchestration = case.get("orchestrator", {})
        temp = Path(tempfile.mkdtemp(prefix=f"rigorpilot-selection-{name}-"))
        case_started = time.monotonic()
        try:
            repo = fetch_case(case, temp)
            target = (repo / str(case.get("target_subdir") or ".")).resolve()
            try:
                target.relative_to(repo.resolve())
            except ValueError as exc:
                raise ValueError("target_subdir escapes the pinned checkout") from exc
            if not target.is_dir():
                raise ValueError("target_subdir is not an existing directory in the pinned checkout")
            process = subprocess.run(
                [
                    sys.executable, str(ORCHESTRATOR), "--repo", str(target),
                    "--plan-only", "--agent-output",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            try:
                plan = json.loads(process.stdout)
            except json.JSONDecodeError:
                plan = {}
            expected_command = orchestration.get("expected_command")
            expected_goal = orchestration.get("expected_goal")
            candidates = plan.get("command_candidates") or []
            selected_id = plan.get("selected_command_id")
            selected_candidate = next((item for item in candidates if item.get("id") == selected_id), None)
            checks = {
                "process_ok": process.returncode == 0,
                "plan_only": plan.get("mode") == "plan_only",
                "command_match": plan.get("documented_command") == expected_command,
                "goal_match": plan.get("selected_goal") == expected_goal,
                "selected_id_present": isinstance(selected_id, str) and selected_id.startswith("cmd-"),
                "selected_candidate_present": selected_candidate is not None,
                "fingerprint_present": isinstance(plan.get("selection_fingerprint"), str) and len(plan.get("selection_fingerprint", "")) == 64,
                "review_args_bound": plan.get("reviewed_run_args") == [
                    "--run-selected", "--command-id", selected_id,
                    "--plan-fingerprint", plan.get("selection_fingerprint"),
                ],
                "no_repo_evidence_write": not (target / "repro_outputs").exists(),
            }
            status = "passed" if all(checks.values()) else "failed"
            rows.append(
                {
                    "case": name,
                    "status": status,
                    "repository": case.get("repository"),
                    "commit": case.get("commit"),
                    "expected_command": expected_command,
                    "actual_command": plan.get("documented_command"),
                    "selected_goal": plan.get("selected_goal"),
                    "selected_command_id": selected_id,
                    "candidate_count": len(candidates),
                    "selection_fingerprint": plan.get("selection_fingerprint"),
                    "checks": checks,
                    "duration_seconds": round(time.monotonic() - case_started, 3),
                }
            )
            print(f"{name}: {status} ({rows[-1]['duration_seconds']}s)")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            rows.append({
                "case": name,
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
                "duration_seconds": round(time.monotonic() - case_started, 3),
            })
            print(f"{name}: failed")
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    passed = sum(row.get("status") == "passed" for row in rows)
    report = {
        "schema_version": "1.0",
        "benchmark": "rigorpilot-reviewed-selection-suite",
        "generated_at": utc_now(),
        "requested_cases": args.cases,
        "status": "passed" if len(rows) == len(args.cases) and passed == len(rows) else "failed",
        "passed": passed,
        "failed": len(rows) - passed,
        "wall_duration_seconds": round(time.monotonic() - started, 3),
        "scope": "Pinned real-repository README planning only; no target command execution, dependency installation, model call, or training.",
        "cases": rows,
    }
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "passed", "failed", "wall_duration_seconds")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
