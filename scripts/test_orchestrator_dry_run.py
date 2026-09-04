#!/usr/bin/env python3
"""Regression checks for orchestrator dry-run planning."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def write_repo(root: Path) -> None:
    (root / "README.md").write_text(
        "# Demo Research Repo\n\n"
        "## Training\n\n"
        "```bash\n"
        "python train.py --config configs/demo.yaml\n"
        "```\n",
        encoding="utf-8",
    )
    (root / "train.py").write_text("print('train stub')\n", encoding="utf-8")
    (root / "environment.yml").write_text("name: demo-env\ndependencies:\n  - python=3.10\n", encoding="utf-8")
    (root / "configs").mkdir()
    (root / "configs" / "demo.yaml").write_text("model: demo\n", encoding="utf-8")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    orchestrator = repo_root / "skills" / "ai-research-reproduction" / "scripts" / "orchestrate_repro.py"

    temp_root = Path(tempfile.mkdtemp(prefix="codex-orchestrator-dry-run-", dir=repo_root))
    try:
        sample_repo = temp_root / "sample_repo"
        sample_repo.mkdir()
        write_repo(sample_repo)
        output_dir = temp_root / "repro_outputs"

        result = subprocess.run(
            [
                sys.executable,
                str(orchestrator),
                "--repo",
                str(sample_repo),
                "--output-dir",
                str(output_dir),
                "--include-analysis-pass",
                "--include-paper-gap",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        expected_chain = [
            "repo-intake-and-plan",
            "env-and-assets-bootstrap",
            "analyze-project",
            "run-train",
            "paper-context-resolver",
        ]

        if payload["selected_goal"] != "training":
            raise AssertionError("orchestrator failed to select training goal for the dry-run repo")
        if payload["execution_skill"] != "run-train":
            raise AssertionError("orchestrator failed to switch execution_skill to run-train")
        if payload["planned_skill_chain"] != expected_chain:
            raise AssertionError("orchestrator failed to emit the expected planned skill chain")
        stages = {item["stage"]: item for item in payload["stage_results"]}
        if stages.get("analyze-project", {}).get("status") != "success":
            raise AssertionError("orchestrator did not actually execute the requested analysis pass")
        if stages.get("run-train", {}).get("status") != "not_requested":
            raise AssertionError("orchestrator stage ledger confused a dry run with command execution")
        if stages.get("paper-context-resolver", {}).get("status") != "blocked":
            raise AssertionError("orchestrator did not expose the unresolved paper-context prerequisite")
        if not any("narrow paper question" in item for item in payload["human_decisions_required"]):
            raise AssertionError("orchestrator omitted the paper-context human review checkpoint")
        analysis_status = temp_root / "analysis_outputs" / "status.json"
        if not analysis_status.exists():
            raise AssertionError("orchestrator did not emit analysis_outputs/status.json")
        if "Planned skill chain" not in "\n".join(payload["command_notes"]):
            raise AssertionError("orchestrator command notes lost the planned chain trace")
        for rel in ["SUMMARY.md", "COMMANDS.md", "LOG.md", "status.json"]:
            if not (output_dir / rel).exists():
                raise AssertionError(f"orchestrator dry-run failed to emit {rel}")
        train_output_dir = temp_root / "train_outputs"
        for rel in ["SUMMARY.md", "COMMANDS.md", "LOG.md", "status.json"]:
            if not (train_output_dir / rel).exists():
                raise AssertionError(f"orchestrator dry-run failed to emit train_outputs/{rel}")
        if payload["setup_commands"][0]["command"] != "conda env create -f environment.yml":
            raise AssertionError("orchestrator failed to propagate the environment setup plan")
        if payload["setup_commands"][0]["platforms"] != ["windows", "macos", "linux"]:
            raise AssertionError("orchestrator failed to preserve setup command platform metadata")
        if payload["full_training_command"] != "python train.py --config configs/demo.yaml":
            raise AssertionError("orchestrator failed to preserve the fuller training command hint")
        if "hours" not in (payload["training_duration_hint"] or "") and "unknown" not in (payload["training_duration_hint"] or ""):
            raise AssertionError("orchestrator failed to surface a conservative training duration hint")
        if "Planned command:" not in payload["next_action"]:
            raise AssertionError("orchestrator failed to mention the fuller training command in next_action")

        prerequisite_repo = temp_root / "prerequisite_repo"
        prerequisite_repo.mkdir()
        cpu_command = (
            "python train.py config/train.py --device=cpu --compile=False "
            "--max_iters=20"
        )
        (prerequisite_repo / "README.md").write_text(
            "# GPT canary\n\n## Quick start\n\n```bash\n"
            "python sample.py --out_dir=out-trained\n"
            "python sample.py --init_from=gpt2-xl\n"
            "python train.py config/train.py\n"
            f"{cpu_command}\n"
            "```\n",
            encoding="utf-8",
        )
        (prerequisite_repo / "sample.py").write_text("print('sample')\n", encoding="utf-8")
        (prerequisite_repo / "train.py").write_text("print('train')\n", encoding="utf-8")
        (prerequisite_repo / "config").mkdir()
        (prerequisite_repo / "config" / "train.py").write_text("max_iters = 20\n", encoding="utf-8")
        prerequisite_result = subprocess.run(
            [
                sys.executable,
                str(orchestrator),
                "--repo",
                str(prerequisite_repo),
                "--output-dir",
                str(temp_root / "prerequisite_outputs"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        prerequisite_payload = json.loads(prerequisite_result.stdout)
        if prerequisite_payload["selected_goal"] != "training" or prerequisite_payload["documented_command"] != cpu_command:
            raise AssertionError(
                "orchestrator selected missing-checkpoint or large-download inference instead of bounded CPU training"
            )

        print("ok: True")
        print("checks: 17")
        print("failures: 0")
        return 0
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    raise SystemExit(main())

