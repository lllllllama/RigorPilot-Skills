#!/usr/bin/env python3
"""Regression checks for the short agent-facing reproduction path."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "skills/ai-research-reproduction/scripts/orchestrate_repro.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def initialize_repo(repo: Path, command: str, files: dict[str, str]) -> None:
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(
        "# Fast path fixture\n\n## Evaluation\n\n```bash\n" + command + "\n```\n",
        encoding="utf-8",
    )
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "init")
    git(repo, "config", "user.email", "rigorpilot@example.com")
    git(repo, "config", "user.name", "RigorPilot Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")


def run(repo: Path, output: Path, *extra: str) -> tuple[dict, subprocess.CompletedProcess[str]]:
    process = subprocess.run(
        [sys.executable, str(ORCHESTRATOR), "--repo", str(repo), "--output-dir", str(output), *extra],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0"),
    )
    return json.loads(process.stdout), process


def run_allow_failure(repo: Path, output: Path, *extra: str) -> tuple[dict, subprocess.CompletedProcess[str]]:
    process = subprocess.run(
        [sys.executable, str(ORCHESTRATOR), "--repo", str(repo), "--output-dir", str(output), *extra],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0"),
    )
    return json.loads(process.stdout), process


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-fast-path-", dir=ROOT))
    checks = 0
    try:
        repo = temp_root / "clean-repo"
        output = temp_root / "clean-output"
        initialize_repo(repo, "python evaluate.py", {"evaluate.py": "print('score=1.0')\n"})

        plan, _ = run(repo, output, "--plan-only", "--agent-output")
        if plan["mode"] != "plan_only" or plan["documented_command"] != "python evaluate.py":
            raise AssertionError("plan-only did not expose the selected documented command")
        if "agent_handoff" in plan:
            raise AssertionError("ordinary plan unexpectedly exposed the optional short-call handoff")
        if any(plan["plan_side_effects"].values()) or output.exists() or (temp_root / "artifacts").exists():
            raise AssertionError("plan-only wrote evidence or claimed execution side effects")
        checks += 1

        handoff_plan, _ = run(repo, output, "--plan-only", "--agent-output", "--include-agent-handoff")
        if handoff_plan["selected_command_id"] != plan["selected_command_id"] or handoff_plan["selection_fingerprint"] != plan["selection_fingerprint"]:
            raise AssertionError("requesting the optional handoff changed reviewed target identity")
        if not isinstance(handoff_plan.get("agent_handoff"), dict):
            raise AssertionError("explicit short-call planning did not return handoff argv")
        checks += 1

        invalid_handoff = subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "--repo", str(repo), "--include-agent-handoff"],
            check=False, capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0"),
        )
        if invalid_handoff.returncode != 2 or "--include-agent-handoff requires --plan-only" not in invalid_handoff.stderr:
            raise AssertionError("handoff opt-in was accepted outside plan-only mode")
        checks += 1

        compact, process = run(
            repo,
            output,
            "--run-selected",
            "--agent-output",
            "--expected-metric",
            "score=1.0",
            "--no-gpu-monitor",
        )
        if compact["status"] != "success" or compact["result_match"] != "matched":
            raise AssertionError("compact agent result lost successful metric verification")
        if len(process.stdout) > 6000:
            raise AssertionError("agent-facing stdout is unexpectedly large")
        integrity = compact["source_integrity"]
        if integrity.get("status") != "verified" or integrity.get("unchanged") is not True:
            raise AssertionError("clean target execution did not verify tracked-source integrity")
        if not Path(compact["evidence"]["invocation"]).is_file():
            raise AssertionError("fast path did not persist invocation.json")
        persisted = json.loads((output / "status.json").read_text(encoding="utf-8"))
        if persisted.get("source_integrity") != integrity or persisted.get("invocation_path") != compact["evidence"]["invocation"]:
            raise AssertionError("status.json lost fast-path integrity/invocation fields")
        checks += 1

        verified, _ = run(repo, output, "--verify-output", "--agent-output")
        if verified.get("mode") != "verify_only" or verified.get("evidence_valid") is not True:
            raise AssertionError(f"verify-only rejected a valid bundle: {verified}")
        if not all(verified.get("checks", {}).values()):
            raise AssertionError("verify-only did not pass every compact evidence check")
        checks += 1

        (output / "SUMMARY.md").write_text(
            (output / "SUMMARY.md").read_text(encoding="utf-8") + "\nTampered after the run.\n",
            encoding="utf-8",
        )
        tampered, tampered_process = run_allow_failure(repo, output, "--verify-output", "--agent-output")
        if tampered_process.returncode == 0 or tampered.get("evidence_valid") is not False:
            raise AssertionError("verify-only did not fail closed for tampered evidence")
        if tampered.get("checks", {}).get("evidence_manifest") is not False:
            raise AssertionError("evidence manifest did not identify the tampered bundle")
        if tampered.get("error", {}).get("code") != "evidence_tampered":
            raise AssertionError("tampered evidence did not expose the stable evidence_tampered code")
        checks += 1

        mutating_repo = temp_root / "mutating-repo"
        mutating_output = temp_root / "mutating-output"
        initialize_repo(
            mutating_repo,
            "python mutate.py",
            {
                "mutate.py": "from pathlib import Path\nPath('tracked.txt').write_text('changed\\n', encoding='utf-8')\nprint('done=1')\n",
                "tracked.txt": "original\n",
            },
        )
        changed, _ = run(mutating_repo, mutating_output, "--run-selected", "--agent-output", "--no-gpu-monitor")
        if changed["status"] != "partial" or changed["source_integrity"].get("unchanged") is not False:
            raise AssertionError("tracked-source mutation was not downgraded for review")
        if "tracked.txt" not in changed["source_integrity"].get("changed_files", []):
            raise AssertionError("tracked-source mutation did not identify the changed file")
        if changed.get("error", {}).get("code") != "source_modified":
            raise AssertionError("tracked-source mutation did not expose source_modified")
        checks += 1

        untracked_repo = temp_root / "untracked-repo"
        untracked_output = temp_root / "untracked-output"
        initialize_repo(
            untracked_repo,
            "python create_source.py",
            {
                "create_source.py": (
                    "from pathlib import Path\n"
                    "Path('generated_override.py').write_text('FLAG = 1\\n', encoding='utf-8')\n"
                    "print('done=1')\n"
                ),
            },
        )
        untracked, _ = run(
            untracked_repo,
            untracked_output,
            "--run-selected",
            "--agent-output",
            "--no-gpu-monitor",
        )
        if untracked["status"] != "partial" or untracked["source_integrity"].get("unchanged") is not False:
            raise AssertionError("new untracked source file was not downgraded for review")
        if "generated_override.py" not in untracked["source_integrity"].get("unexpected_added_source_files", []):
            raise AssertionError("new untracked source file was not identified")
        if untracked.get("error", {}).get("code") != "source_modified":
            raise AssertionError("new untracked source did not expose source_modified")
        checks += 1

        predirty_repo = temp_root / "predirty-repo"
        predirty_output = temp_root / "predirty-output"
        initialize_repo(
            predirty_repo,
            "python mutate_dirty.py",
            {
                "mutate_dirty.py": "from pathlib import Path\nPath('tracked.txt').write_text('after-run\\n', encoding='utf-8')\nprint('done=1')\n",
                "tracked.txt": "committed\n",
            },
        )
        (predirty_repo / "tracked.txt").write_text("dirty-before-run\n", encoding="utf-8")
        predirty, _ = run(
            predirty_repo,
            predirty_output,
            "--run-selected",
            "--agent-output",
            "--no-gpu-monitor",
        )
        if predirty["source_integrity"].get("unchanged") is not False:
            raise AssertionError("mutation of an already-dirty tracked file was missed")
        if "tracked.txt" not in predirty["source_integrity"].get("changed_tracked_files", []):
            raise AssertionError("already-dirty tracked mutation did not identify the changed file")
        if predirty.get("error", {}).get("code") != "source_modified":
            raise AssertionError("already-dirty tracked mutation did not expose source_modified")
        checks += 1

        interrupted_repo = temp_root / "interrupted-repo"
        interrupted_output = temp_root / "interrupted-output"
        initialize_repo(interrupted_repo, "python evaluate.py", {"evaluate.py": "print('score=1.0')\n"})
        state_path = interrupted_output / "_runtime/interrupted-run/state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "run_id": "interrupted-run",
                    "status": "running",
                    "started_at": "2026-09-21T00:00:00Z",
                    "last_heartbeat": "2026-09-21T00:00:05Z",
                }
            ),
            encoding="utf-8",
        )
        interrupted, interrupted_process = run_allow_failure(
            interrupted_repo, interrupted_output, "--verify-output", "--agent-output"
        )
        if interrupted_process.returncode == 0 or interrupted.get("evidence_valid") is not False:
            raise AssertionError("verify-only accepted an incomplete runtime without status.json")
        if interrupted.get("error", {}).get("code") != "runtime_incomplete_without_status":
            raise AssertionError("incomplete runtime did not expose the stable interruption code")
        if interrupted.get("runtime", {}).get("status") != "running":
            raise AssertionError("incomplete runtime diagnosis lost the retained runtime state")
        checks += 1

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
