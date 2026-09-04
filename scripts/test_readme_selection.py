#!/usr/bin/env python3
"""Regression checks for README command extraction and selection heuristics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def run_extract(script: Path, readme_text: str, companion_files: Dict[str, str] | None = None) -> Dict[str, Any]:
    temp_path = script.parent / ".tmp_readme_selection.md"
    temp_path.write_text(readme_text, encoding="utf-8")
    written: List[Path] = []
    try:
        for relative, content in (companion_files or {}).items():
            companion = script.parent / relative
            if companion.exists():
                raise AssertionError(f"refusing to overwrite test companion: {companion}")
            companion.parent.mkdir(parents=True, exist_ok=True)
            companion.write_text(content, encoding="utf-8")
            written.append(companion)
        result = subprocess.run(
            [sys.executable, str(script), "--readme", str(temp_path), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)
    finally:
        if temp_path.exists():
            temp_path.unlink()
        for companion in written:
            companion.unlink()


def command_score(command: Dict[str, Any]) -> int:
    text = str(command.get("command", "")).lower()
    kind = command.get("kind", "run")
    section = str(command.get("section") or "").lower()
    score = {"run": 40, "smoke": 30, "asset": 10, "setup": 0}.get(kind, 0)
    if any(token in text for token in ["python ", "python3 ", "./", "whisper "]):
        score += 8
    if any(token in text for token in ["txt2img", "img2img", "amg.py", "transcribe", "infer", "eval"]):
        score += 8
    if any(token in section for token in ["usage", "demo", "example", "inference", "evaluation", "text-to-image", "image-to-image"]):
        score += 6
    if any(token in section for token in ["install", "installation", "setup", "environment"]):
        score -= 6
    if "<" in text and ">" in text:
        score -= 10
    if text.startswith(("pip install", "conda install", "conda env create", "conda activate", "git clone", "cd ")):
        score -= 12
    return score


def choose_goal(commands: List[Dict[str, Any]]) -> str:
    priority = ["inference", "evaluation", "training", "other"]
    for category in priority:
        candidates = [item for item in commands if item.get("category") == category]
        if candidates:
            best = max(candidates, key=command_score)
            return str(best.get("command", ""))
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run README extraction and selection regression tests.")
    parser.add_argument(
        "--cases",
        default="tests/readme_selection_cases.json",
        help="Path to README selection cases JSON.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    extract_script = repo_root / "skills" / "repo-intake-and-plan" / "scripts" / "extract_commands.py"
    payload = json.loads((repo_root / args.cases).read_text(encoding="utf-8"))

    failures: List[str] = []
    for case in payload["cases"]:
        extracted = run_extract(extract_script, case["readme"])
        selected = choose_goal(extracted["commands"])
        if selected != case["expected_command"]:
            failures.append(f"{case['id']}: expected `{case['expected_command']}`, got `{selected}`")

    # Real-repo patterns (nanoGPT, dinov2): entrypoint-first classification and
    # backslash-continuation joining.
    nanogpt_readme = (
        "# Demo\n\n## Quick start\n\n```bash\n"
        "python train.py config/train_shakespeare_char.py --device=cpu --eval_iters=20\n"
        "```\n"
    )
    extracted = run_extract(extract_script, nanogpt_readme)
    if not extracted["commands"] or extracted["commands"][0]["category"] != "training":
        failures.append("nanogpt-pattern: train.py with --eval_iters must classify as training, not evaluation")

    micrograd_readme = (
        "# micrograd\n\n## Running tests\n\n```bash\n"
        "python -m pytest\n"
        "```\n"
    )
    extracted = run_extract(extract_script, micrograd_readme)
    if not extracted["commands"] or extracted["commands"][0]["category"] != "evaluation":
        failures.append("micrograd-pattern: pytest under Running tests must classify as evaluation")

    ambiguous_training_readme = (
        "# Basic Example\n\n```bash\n"
        "pip install -r requirements.txt\n"
        "python main.py\n"
        "```\n"
    )
    ambiguous_training_script = (
        "def train(model, optimizer, train_loader):\n"
        "    model.train()\n"
        "    for data, target in train_loader:\n"
        "        loss = model(data).sum()\n"
        "        loss.backward()\n"
        "        optimizer.step()\n"
    )
    extracted = run_extract(
        extract_script,
        ambiguous_training_readme,
        {"main.py": ambiguous_training_script},
    )
    main_command = next((item for item in extracted["commands"] if item["command"] == "python main.py"), None)
    setup_command = next(
        (item for item in extracted["commands"] if item["command"] == "pip install -r requirements.txt"),
        None,
    )
    if not setup_command or setup_command["kind"] != "setup" or setup_command["category"] != "other":
        failures.append("command-syntax: pip install under a generic Example heading must remain setup/other")
    if not main_command or main_command["category"] != "training":
        failures.append("entrypoint-structure: ambiguous main.py with optimizer/backward must classify as training")
    elif main_command.get("classification_source") != "entrypoint-structure":
        failures.append("entrypoint-structure: training promotion must expose its evidence source")

    dinov2_readme = (
        "# Demo\n\n## Evaluation\n\n```bash\n"
        "python dinov2/run/eval/linear.py \\\n"
        "    --config-file dinov2/configs/eval/vitg14_pretrain.yaml \\\n"
        "    --pretrained-weights checkpoints/dinov2_vitg14_pretrain.pth\n"
        "```\n"
    )
    extracted = run_extract(extract_script, dinov2_readme)
    joined = extracted["commands"][0]["command"] if extracted["commands"] else ""
    if "--config-file" not in joined or "--pretrained-weights" not in joined or joined.endswith("\\"):
        failures.append("dinov2-pattern: backslash-continued command was not joined into one runnable command")

    print(f"ok: {not failures}")
    print(f"cases: {len(payload['cases'])}")
    print(f"failures: {len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
