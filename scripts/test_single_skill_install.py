#!/usr/bin/env python3
"""Verify the main skill works after only its directory is installed."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def write_target_repo(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "README.md").write_text(
        "# 已安装 Skill Canary 🛠️\n\n"
        "## Evaluation\n\n"
        "```bash\npython evaluate.py\n```\n",
        encoding="utf-8",
    )
    (root / "evaluate.py").write_text("print('accuracy=0.91')\n", encoding="utf-8")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sync_script = repo_root / "scripts" / "sync_reproduction_bundle.py"
    check = subprocess.run([sys.executable, str(sync_script), "--check"], capture_output=True, text=True)
    if check.returncode != 0:
        raise AssertionError(f"self-contained bundle is stale:\n{check.stdout}\n{check.stderr}")

    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-single-install-"))
    try:
        installed_skill = temp_root / "agent-home" / "skills" / "ai-research-reproduction"
        shutil.copytree(repo_root / "skills" / "ai-research-reproduction", installed_skill)
        bundled_queue = installed_skill / "_bundled" / "shared" / "scripts" / "task_queue.py"
        queue_canary = subprocess.run(
            [sys.executable, str(bundled_queue), "--queue-root", str(temp_root / "queue-canary"), "list"],
            cwd=temp_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if queue_canary.returncode != 0 or "queue_id" not in json.loads(queue_canary.stdout):
            raise AssertionError(f"single-skill queue runtime failed:\n{queue_canary.stdout}\n{queue_canary.stderr}")
        target_repo = temp_root / "target-repo"
        write_target_repo(target_repo)
        output_dir = temp_root / "outputs" / "repro_outputs"
        model_profile = temp_root / "model-profile.json"
        model_profile.write_text(
            json.dumps(
                {
                    "adapter_id": "single-install-canary",
                    "provider": "host",
                    "model": "test-model",
                    "capabilities": ["structured_output"],
                }
            ),
            encoding="utf-8",
        )
        orchestrator = installed_skill / "scripts" / "orchestrate_repro.py"
        result = subprocess.run(
            [
                sys.executable,
                str(orchestrator),
                "--repo",
                str(target_repo),
                "--output-dir",
                str(output_dir),
                "--run-selected",
                "--include-analysis-pass",
                "--expected-metric",
                "accuracy=0.91",
                "--model-profile-json",
                str(model_profile),
                "--require-model-capability",
                "structured_output",
            ],
            cwd=temp_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"single-skill install failed:\n{result.stdout}\n{result.stderr}")
        payload = json.loads(result.stdout)
        if payload["status"] != "success":
            raise AssertionError(f"installed skill did not execute successfully: {payload['status']}")
        if payload["result_match"]["status"] != "matched":
            raise AssertionError("installed skill lost explicit metric matching")
        runtime = payload.get("runtime_dir")
        if not runtime or not Path(runtime).is_dir():
            raise AssertionError("installed skill did not persist runtime evidence")
        runtime_files = {path.name for path in Path(runtime).iterdir() if path.is_file()}
        if not {"spec.json", "state.json", "events.jsonl", "resources.jsonl", "stdout.log", "stderr.log"}.issubset(runtime_files):
            raise AssertionError("installed skill runtime evidence is incomplete")
        status_payload = json.loads((output_dir / "status.json").read_text(encoding="utf-8"))
        if status_payload.get("runtime", {}).get("status") != "success":
            raise AssertionError("status.json did not expose the runtime terminal state")
        if status_payload.get("model_adapter", {}).get("model") != "test-model":
            raise AssertionError("single-skill install lost the normalized model adapter snapshot")
        stages = {item["stage"]: item["status"] for item in payload["stage_results"]}
        if stages.get("analyze-project") != "success":
            raise AssertionError("installed skill could not run its bundled analysis stage")
        required = {
            "SUMMARY.md",
            "COMMANDS.md",
            "LOG.md",
            "SCIENTIFIC_CHANGELOG.md",
            "COMPARABILITY_REPORT.md",
            "status.json",
            "ANNOTATED_README.md",
        }
        missing = required - {path.name for path in output_dir.iterdir() if path.is_file()}
        if missing:
            raise AssertionError(f"installed skill omitted evidence files: {sorted(missing)}")

        print("ok: True")
        print("checks: 13")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
