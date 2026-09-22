#!/usr/bin/env python3
"""Controlled short-call fault experiment with real processes, not a model A/B."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/ai-research-reproduction/scripts"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", RIGORPILOT_LESSONS="0")
README = "# Handoff fixture\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n"


def run_json(argv: list[str], cwd: Path, timeout=20) -> dict:
    result = subprocess.run(argv, cwd=cwd, env=ENV, capture_output=True, text=True,
                            encoding="utf-8", timeout=timeout, check=True)
    return json.loads(result.stdout)


def fixture(path: Path, duration: float) -> None:
    path.mkdir(parents=True)
    (path / "README.md").write_text(README, encoding="utf-8")
    source = ("from pathlib import Path\nimport time\n"
              "p=Path('execution_count.txt')\np.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
              f"print('started', flush=True)\ntime.sleep({duration})\nprint('score=1.0', flush=True)\n")
    (path / "evaluate.py").write_text(source, encoding="utf-8")
    for args in (["init"], ["config", "user.email", "benchmark@example.invalid"], ["config", "user.name", "Benchmark"],
                 ["add", "."], ["commit", "-m", "fixture"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, env=ENV)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="tmp/agent-handoff.json")
    args = parser.parse_args()
    temp = Path(tempfile.mkdtemp(prefix="rigorpilot-handoff-benchmark-"))
    rows = []
    try:
        for name, target_timeout, duration, expected_runtime in (
            ("timeout_finalization", 1, 3.0, "timed_out"),
            ("success_after_client_return", 5, 2.0, "success"),
        ):
            arms = {}
            for arm in ("direct_short_wrapper", "receipt_and_poll"):
                repo = temp / name / arm / "repo"
                fixture(repo, duration)
                output = repo / "repro_outputs"
                base = [sys.executable, str(SCRIPTS / "orchestrate_repro.py"), "--repo", str(repo),
                        "--timeout", str(target_timeout), "--no-gpu-monitor", "--agent-output"]
                plan = run_json([*base, "--plan-only", "--include-agent-handoff"], temp)
                start = time.monotonic()
                if arm == "direct_short_wrapper":
                    wrapper_timeout = 1
                    with (repo.parent / "wrapper.stdout.log").open("wb") as out, (repo.parent / "wrapper.stderr.log").open("wb") as err:
                        try:
                            proc = subprocess.run([*base, "--run-selected", "--command-id", plan["selected_command_id"],
                                                   "--plan-fingerprint", plan["selection_fingerprint"]],
                                                  cwd=temp, env=ENV, stdout=out, stderr=err, timeout=wrapper_timeout)
                            expired, exit_code = False, proc.returncode
                        except subprocess.TimeoutExpired:
                            expired, exit_code = True, None
                    arms[arm] = {
                        "outer_call_seconds": round(time.monotonic() - start, 3), "wrapper_timeout_seconds": wrapper_timeout,
                        "wrapper_expired": expired, "exit_code": exit_code,
                        "status_written_at_return": (output / "status.json").is_file(),
                    }
                    # The trusted fixture has a finite sleep and exits on its own.
                    # Preserve interruption evidence; do not replay or fabricate a terminal runtime.
                    time.sleep(duration + 1)
                    arms[arm]["status_written_after_fixture_exit"] = (output / "status.json").is_file()
                else:
                    launch = plan["agent_handoff"]["start_argv"]
                    receipt = run_json(launch, temp, timeout=5)
                    return_seconds = time.monotonic() - start
                    repeated = run_json(launch, temp, timeout=5)
                    deadline = time.monotonic() + 45
                    final = receipt
                    while not final["terminal"] and time.monotonic() < deadline:
                        time.sleep(0.2)
                        final = run_json(receipt["status_argv"], temp, timeout=5)
                    count = (repo / "execution_count.txt").read_text() if (repo / "execution_count.txt").is_file() else "0"
                    result = final.get("result") or {}
                    arms[arm] = {
                        "outer_call_seconds": round(return_seconds, 3), "returned_before_terminal": not receipt["terminal"],
                        "same_job_on_resubmission": receipt["job_id"] == repeated["job_id"] and repeated["reused"],
                        "execution_count": int(count), "lifecycle": final["lifecycle"],
                        "identity_checked": final.get("identity_checked") is True,
                        "status_written": (output / "status.json").is_file(), "result": result,
                        "wall_seconds": round(time.monotonic() - start, 3),
                    }
                    stdout_files = list((output / "_runtime").glob("*/stdout.log"))
                    arms[arm]["target_stdout"] = stdout_files[0].read_text(encoding="utf-8") if stdout_files else ""
                arms[arm]["source_sha256"] = hashlib.sha256((repo / "evaluate.py").read_bytes()).hexdigest()
            receipt = arms["receipt_and_poll"]
            checks = {
                "identical_fixture_source": arms["direct_short_wrapper"]["source_sha256"] == receipt["source_sha256"],
                "direct_interruption_observed": arms["direct_short_wrapper"]["wrapper_expired"],
                "direct_missing_terminal_evidence": not arms["direct_short_wrapper"]["status_written_after_fixture_exit"],
                "short_call_handoff": receipt["returned_before_terminal"],
                "no_duplicate_execution": receipt["same_job_on_resubmission"] and receipt["execution_count"] == 1,
                "receipt_identity_checked": receipt["identity_checked"],
                "complete_evidence": receipt["status_written"] and receipt["result"].get("evidence_valid") is True,
                "correct_runtime": receipt["result"].get("runtime_status") == expected_runtime,
                "honest_acceptance": receipt["result"].get("accepted") is (expected_runtime == "success"),
            }
            rows.append({"case": name, "target_timeout_seconds": target_timeout, "fixture_sleep_seconds": duration,
                         "checks": checks, "arms": arms, "passed": all(checks.values())})
            print(f"{name}: {'passed' if rows[-1]['passed'] else 'failed'}", flush=True)
        report = {
            "schema_version": "1.0", "benchmark": "agent-handoff-fault-comparison", "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "scripted control, synthetic fixtures, real local subprocesses; not a model-value or throughput benchmark",
            "model_calls": 0, "model_uplift": None,
            "host": {"platform": platform.system(), "python": platform.python_version()},
            "implementation_sha256": {name: hashlib.sha256((SCRIPTS / name).read_bytes()).hexdigest()
                                       for name in ("repro_job.py", "orchestrate_repro.py")},
            "shared_runtime_sha256": {name: hashlib.sha256((ROOT / "shared/scripts" / name).read_bytes()).hexdigest()
                                       for name in ("runtime_runner.py", "command_utils.py")},
            "status": "passed" if all(row["passed"] for row in rows) else "failed", "cases": rows,
        }
        output = (ROOT / args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "cases": len(rows), "model_calls": 0}))
        return 0 if report["status"] == "passed" else 1
    finally:
        def writable(function, name, _error):
            os.chmod(name, 0o700)
            function(name)
        shutil.rmtree(temp, onerror=writable)


if __name__ == "__main__":
    raise SystemExit(main())
