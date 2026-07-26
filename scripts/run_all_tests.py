#!/usr/bin/env python3
"""Run validate_repo.py and every scripts/test_*.py, failing if any script fails.

Cross-platform test entrypoint for CI and local use. New test scripts are
picked up automatically — never hand-list tests in CI again.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    targets = [scripts_dir / "validate_repo.py"] + sorted(scripts_dir.glob("test_*.py"))

    failures: list[str] = []
    started = time.perf_counter()
    for target in targets:
        script_started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, str(target)],
            capture_output=True,
            text=True,
        )
        elapsed = time.perf_counter() - script_started
        if result.returncode == 0:
            print(f"PASS {target.name} ({elapsed:.1f}s)")
        else:
            failures.append(target.name)
            print(f"FAIL {target.name} ({elapsed:.1f}s)")
            tail = "\n".join((result.stdout + "\n" + result.stderr).strip().splitlines()[-15:])
            print(tail)

    total = time.perf_counter() - started
    print(f"\n{len(targets) - len(failures)}/{len(targets)} scripts passed in {total:.1f}s")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
