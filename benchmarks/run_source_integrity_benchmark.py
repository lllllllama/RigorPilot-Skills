#!/usr/bin/env python3
"""Measure source-integrity snapshot cost on synthetic Git repositories."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills/ai-research-reproduction/scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
from orchestrate_repro import compare_source_snapshots, tracked_source_snapshot  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timed_snapshot(repo: Path) -> tuple[dict, float, int]:
    tracemalloc.start()
    started = time.perf_counter()
    snapshot = tracked_source_snapshot(repo)
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return snapshot, elapsed, peak


def build_repo(root: Path, count: int, bytes_per_file: int) -> Path:
    repo = root / f"repo-{count}"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    payload = ("x" * max(1, bytes_per_file - 1) + "\n").encode("utf-8")
    for index in range(count):
        path = repo / "src" / f"d{index // 1000:03d}" / f"file_{index:06d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    subprocess.run(["git", "-C", str(repo), "add", "src"], check=True, capture_output=True)
    return repo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", nargs="+", type=int, default=[1000, 10000], help="Tracked file counts to measure.")
    parser.add_argument("--bytes-per-file", type=int, default=128)
    parser.add_argument("--output", default="benchmark_outputs/source_integrity_latest.json")
    args = parser.parse_args()
    if any(value <= 0 for value in args.counts) or args.bytes_per_file <= 0:
        parser.error("counts and bytes-per-file must be positive")
    if len(set(args.counts)) != len(args.counts):
        parser.error("duplicate file counts are not allowed")

    temp = Path(tempfile.mkdtemp(prefix="rigorpilot-integrity-benchmark-"))
    started = time.monotonic()
    rows: list[dict] = []
    try:
        for count in args.counts:
            case_started = time.monotonic()
            repo = build_repo(temp, count, args.bytes_per_file)
            before, before_seconds, before_peak = timed_snapshot(repo)
            changed = repo / "src" / "d000" / "file_000000.py"
            changed.write_text("changed = True\n", encoding="utf-8")
            added = repo / "generated_override.py"
            added.write_text("FLAG = 1\n", encoding="utf-8")
            after, after_seconds, after_peak = timed_snapshot(repo)
            comparison = compare_source_snapshots(before, after)
            verify, verify_seconds, verify_peak = timed_snapshot(repo)
            detected = (
                comparison.get("unchanged") is False
                and "src/d000/file_000000.py" in comparison.get("changed_tracked_files", [])
                and "generated_override.py" in comparison.get("unexpected_added_source_files", [])
                and verify.get("snapshot_sha256") == after.get("snapshot_sha256")
            )
            rows.append(
                {
                    "tracked_files": count,
                    "bytes_per_file": args.bytes_per_file,
                    "approx_tracked_bytes": count * args.bytes_per_file,
                    "before_snapshot_seconds": round(before_seconds, 6),
                    "after_snapshot_seconds": round(after_seconds, 6),
                    "verify_snapshot_seconds": round(verify_seconds, 6),
                    "python_tracemalloc_peak_bytes": max(before_peak, after_peak, verify_peak),
                    "change_detection_ok": detected,
                    "case_wall_seconds": round(time.monotonic() - case_started, 3),
                }
            )
            print(f"{count}: snapshot={before_seconds:.3f}s verify={verify_seconds:.3f}s detected={detected}")
        report = {
            "schema_version": "1.0",
            "benchmark": "rigorpilot-source-integrity",
            "generated_at": utc_now(),
            "status": "passed" if all(row["change_detection_ok"] for row in rows) else "failed",
            "measurement_scope": "Synthetic tracked text files; tracemalloc covers Python allocations, not total process RSS or filesystem cache.",
            "wall_duration_seconds": round(time.monotonic() - started, 3),
            "cases": rows,
        }
        output = (ROOT / args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 0 if report["status"] == "passed" else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
