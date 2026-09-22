#!/usr/bin/env python3
"""Run repository regression scripts, failing if any selected script fails.

Cross-platform test entrypoint for CI and local use. New test scripts are
picked up automatically — never hand-list tests in CI again.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


CORE_TESTS = [
    "test_agent_skills_spec.py",
    "test_command_execution_portability.py",
    "test_first_use_basics.py",
    "test_first_use_verifier.py",
    "test_operating_principles_structure.py",
    "test_orchestrator_dry_run.py",
    "test_readme_annotation.py",
    "test_readme_selection.py",
    "test_reproduction_command_selection.py",
    "test_reproduction_default_paths.py",
    "test_reproduction_fast_path.py",
    "test_reproduction_metric_verification.py",
    "test_reproduction_verifier_contract.py",
    "test_runtime_atomic_write.py",
    "test_runtime_recovery.py",
    "test_runtime_runner.py",
    "test_setup_planning.py",
    "test_single_skill_install.py",
    "test_skill_registry.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core",
        action="store_true",
        help="Run the high-signal reproduction/installation regression subset for local iteration; CI and release checks should run the full suite.",
    )
    args = parser.parse_args()
    scripts_dir = Path(__file__).resolve().parent
    if args.core:
        targets = [scripts_dir / "validate_repo.py", *(scripts_dir / name for name in CORE_TESTS)]
    else:
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
            print(f"PASS {target.name} ({elapsed:.1f}s)", flush=True)
        else:
            failures.append(target.name)
            print(f"FAIL {target.name} ({elapsed:.1f}s)", flush=True)
            # The last traceback may be secondary; retain every failed test
            # in CI logs so the first/root error can actually be diagnosed.
            print((result.stdout + "\n" + result.stderr).strip(), flush=True)

    total = time.perf_counter() - started
    label = "core scripts" if args.core else "scripts"
    print(f"\n{len(targets) - len(failures)}/{len(targets)} {label} passed in {total:.1f}s")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
