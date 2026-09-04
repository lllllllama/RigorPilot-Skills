#!/usr/bin/env python3
"""Regression checks for trusted vs explore training routing."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


TRAIN_SCRIPT = """\
from pathlib import Path
import time

Path("out-trained").mkdir(exist_ok=True)
print("batch_size=12 n_embd=128 train.py=196", flush=True)
print("Accuracy: 87/100 (87%)", flush=True)
for step in range(1, 9):
    loss = 1.0 / step
    acc = 0.70 + step * 0.01
    print(f"epoch=1 step={step} loss={loss:.4f} val_acc={acc:.4f}", flush=True)
    if step == 3:
        print("checkpoint=checkpoints/best.pt", flush=True)
    time.sleep(0.35)
"""


def write_repo(root: Path) -> None:
    (root / "README.md").write_text(
        "# Demo Research Repo\n\n"
        "## Sampling\n\n"
        "```bash\n"
        "python sample.py --out_dir=out-trained\n"
        "```\n\n"
        "## Training\n\n"
        "```bash\n"
        "python train.py --config configs/demo.yaml\n"
        "```\n",
        encoding="utf-8",
    )
    (root / "environment.yml").write_text("name: demo-env\ndependencies:\n  - python=3.10\n", encoding="utf-8")
    (root / "train.py").write_text(TRAIN_SCRIPT, encoding="utf-8")
    (root / "sample.py").write_text("print('sample')\n", encoding="utf-8")
    (root / "configs").mkdir()
    (root / "configs" / "demo.yaml").write_text("model: demo\n", encoding="utf-8")
    (root / "datasets").mkdir()


def run_case(orchestrator: Path, sample_repo: Path, temp_root: Path, lane: str) -> None:
    case_root = temp_root / lane
    repro_dir = case_root / "repro_outputs"
    result = subprocess.run(
        [
            sys.executable,
            str(orchestrator),
            "--repo",
            str(sample_repo),
            "--output-dir",
            str(repro_dir),
            "--run-selected",
            "--train-timeout",
            "1",
            "--lane",
            lane,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    train_status = json.loads((case_root / "train_outputs" / "status.json").read_text(encoding="utf-8"))

    if payload["selected_goal"] != "training":
        raise AssertionError(f"{lane} case failed to select the training goal")
    if payload["execution_skill"] != "run-train":
        raise AssertionError(f"{lane} case failed to switch execution_skill to run-train")
    if train_status["lane"] != lane:
        raise AssertionError(f"{lane} case failed to preserve the lane in train_outputs/status.json")
    if train_status["completed_steps"] < 1:
        raise AssertionError(f"{lane} case failed to parse any completed steps from the training log")
    if any(name in train_status["observed_metrics"] for name in {"batch_size", "n_embd", "train.py"}):
        raise AssertionError(f"{lane} case treated configuration values as scientific metrics")
    if train_status["observed_metrics"].get("accuracy") != 0.87:
        raise AssertionError(f"{lane} case failed to normalize a fraction accuracy metric")
    if train_status["full_training_command"] != "python train.py --config configs/demo.yaml":
        raise AssertionError(f"{lane} case failed to preserve the fuller training command")
    if "likely" not in (train_status["training_duration_hint"] or "") and "hours" not in (train_status["training_duration_hint"] or ""):
        raise AssertionError(f"{lane} case failed to emit a conservative training duration hint")

    if lane == "trusted":
        if payload["run_mode"] != "startup_verification":
            raise AssertionError("trusted case should stay in startup_verification mode")
        if not payload["requires_full_training_confirmation"]:
            raise AssertionError("trusted case should require explicit confirmation before fuller training")
        if train_status["stop_reason"] != "startup_verification_window_elapsed":
            raise AssertionError("trusted case should stop at the startup verification window")
        if "Estimated duration:" not in payload["next_action"]:
            raise AssertionError("trusted case should mention the expected fuller training duration in next_action")
    else:
        if payload["run_mode"] != "full_kickoff":
            raise AssertionError("explore case should switch directly to full_kickoff mode")
        if payload["requires_full_training_confirmation"]:
            raise AssertionError("explore case should not require trusted-lane confirmation")
        if train_status["stop_reason"] != "monitoring_window_elapsed":
            raise AssertionError("explore case should record the monitoring window timeout")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    orchestrator = repo_root / "skills" / "ai-research-reproduction" / "scripts" / "orchestrate_repro.py"

    temp_root = Path(tempfile.mkdtemp(prefix="codex-training-lanes-", dir=repo_root))
    try:
        sample_repo = temp_root / "sample_repo"
        sample_repo.mkdir()
        write_repo(sample_repo)

        run_case(orchestrator, sample_repo, temp_root, "trusted")
        shutil.rmtree(sample_repo / "out-trained")
        run_case(orchestrator, sample_repo, temp_root, "explore")

        print("ok: True")
        print("checks: 8")
        print("failures: 0")
        return 0
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    raise SystemExit(main())

