#!/usr/bin/env python3
"""Regression checks for the annotated-README renderer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


README = """# Demo Research Repo

A small demo repository.

## Install

```bash
pip install -r requirements.txt
```

## Data Preparation

```bash
python tools/prepare_data.py --root data/demo
```

## Evaluation

```bash
# run the documented evaluation
python eval.py --config configs/demo.yaml
```

## Training

```bash
python train.py --config configs/demo.yaml
```

## License

MIT.
"""


def build_context(status: str, user_language: str) -> dict:
    return {
        "user_language": user_language,
        "lane": "trusted",
        "selected_goal": "evaluation",
        "status": status,
        "documented_command": "python eval.py --config configs/demo.yaml",
        "documented_command_section": "Evaluation",
        "main_blocker": "Selected documented command exited with code 1." if status != "success" else "None.",
        "best_metric": {"name": "miou", "value": 79.4},
        "observed_metrics": {"miou": 79.4, "acc": 93.1},
        "result_match": {
            "status": "matched",
            "absolute_tolerance": 0.1,
            "comparisons": [
                {
                    "metric": "miou",
                    "expected": 79.4,
                    "observed": 79.4,
                    "absolute_error": 0.0,
                    "within_tolerance": True,
                }
            ],
        },
        "completed_steps": 0,
        "requires_full_training_confirmation": False,
        "local_dataset_present": False,
        "execution_log": ["STDERR:\nFileNotFoundError: checkpoint not found: checkpoints/demo.pth"],
        "next_action": "Prepare environment and assets, then retry the documented command.",
        "readme_commands": [
            {"command": "pip install -r requirements.txt", "section": "Install", "kind": "setup", "category": "env"},
            {"command": "python tools/prepare_data.py --root data/demo", "section": "Data Preparation", "kind": "asset", "category": "env"},
            {"command": "python eval.py --config configs/demo.yaml", "section": "Evaluation", "kind": "run", "category": "evaluation"},
            {"command": "python train.py --config configs/demo.yaml", "section": "Training", "kind": "run", "category": "training"},
        ],
    }


def assert_original_preserved(annotated: str) -> None:
    annotated_lines = annotated.splitlines()
    cursor = 0
    for line in README.splitlines():
        while cursor < len(annotated_lines) and annotated_lines[cursor] != line:
            cursor += 1
        if cursor >= len(annotated_lines):
            raise AssertionError(f"annotated README lost or reordered the original line: {line!r}")
        cursor += 1


def assert_one_annotation_per_heading(annotated: str) -> None:
    headings = [
        "# Demo Research Repo",
        "## Install",
        "## Data Preparation",
        "## Evaluation",
        "## Training",
        "## License",
    ]
    positions = [annotated.index(heading) for heading in headings]
    for index, heading in enumerate(headings):
        end = positions[index + 1] if index + 1 < len(positions) else len(annotated)
        section = annotated[positions[index]:end]
        count = section.count('rigorpilot:repro:begin kind="section"')
        if count != 1:
            raise AssertionError(f"heading {heading!r} has {count} annotation blocks instead of exactly one")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    renderer = repo_root / "skills" / "ai-research-reproduction" / "scripts" / "annotate_readme.py"
    temp_root = Path(tempfile.mkdtemp(prefix="codex-readme-annotation-", dir=repo_root))
    checks = 0
    try:
        readme_path = temp_root / "README.md"
        readme_path.write_text(README, encoding="utf-8")

        for status, admonition in [("success", "[!TIP]"), ("partial", "[!WARNING]"), ("blocked", "[!CAUTION]")]:
            context_path = temp_root / f"context-{status}.json"
            context_path.write_text(json.dumps(build_context(status, "en")), encoding="utf-8")
            output_path = temp_root / f"annotated-{status}.md"
            subprocess.run(
                [
                    sys.executable,
                    str(renderer),
                    "--readme",
                    str(readme_path),
                    "--context-json",
                    str(context_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            annotated = output_path.read_text(encoding="utf-8")
            assert_original_preserved(annotated)
            checks += 1
            assert_one_annotation_per_heading(annotated)
            checks += 1
            stripped_path = temp_root / f"stripped-{status}.md"
            subprocess.run(
                [
                    sys.executable,
                    str(renderer),
                    "strip",
                    "--input",
                    str(output_path),
                    "--output",
                    str(stripped_path),
                    "--against",
                    str(readme_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if stripped_path.read_bytes() != readme_path.read_bytes():
                raise AssertionError("stripping annotations did not restore the exact source README bytes")
            checks += 1
            evaluation_tail = annotated.split("## Evaluation", 1)[1].split("## License", 1)[0]
            if admonition not in evaluation_tail:
                raise AssertionError(f"{status} run did not annotate the Evaluation section with {admonition}")
            checks += 1

        annotated = (temp_root / "annotated-success.md").read_text(encoding="utf-8")
        install_tail = annotated.split("## Install", 1)[1].split("## Data Preparation", 1)[0]
        if "[!NOTE]" not in install_tail or "pip install -r requirements.txt" not in install_tail:
            raise AssertionError("setup-only section lost its informational annotation or command list")
        checks += 1
        data_tail = annotated.split("## Data Preparation", 1)[1].split("## Evaluation", 1)[0]
        if "[!WARNING]" not in data_tail:
            raise AssertionError("missing local dataset did not raise a data-readiness warning")
        checks += 1
        training_tail = annotated.split("## Training", 1)[1].split("## License", 1)[0]
        if "[!IMPORTANT]" not in training_tail:
            raise AssertionError("trusted-lane training section lost its authorization-required annotation")
        checks += 1
        partial = (temp_root / "annotated-partial.md").read_text(encoding="utf-8")
        if "FileNotFoundError: checkpoint not found" not in partial:
            raise AssertionError("partial run lost the error excerpt")
        checks += 1
        if "Observed metrics:" not in partial or "miou=79.4" not in partial:
            raise AssertionError("partial run lost its actually observed metrics")
        checks += 1
        license_tail = annotated.split("## License", 1)[1]
        if "⚪" not in license_tail:
            raise AssertionError("read-only section lost its neutral annotation")
        checks += 1
        if "SUMMARY.md" not in annotated or "status.json" not in annotated:
            raise AssertionError("annotations lost the evidence links")
        checks += 1
        if annotated.count("# run the documented evaluation") != 1:
            raise AssertionError("fenced comment line was duplicated or dropped")
        checks += 1
        if "Section coverage:" not in annotated or "🟢 1" not in annotated:
            raise AssertionError("header lost the section-coverage scoreboard")
        checks += 1
        if "score 0." not in annotated:
            raise AssertionError("header lost the weighted reproduction score")
        checks += 1
        if "tier: result-match" not in annotated:
            raise AssertionError("verified metric match lost its result-match evidence tier")
        checks += 1

        unverified_context = build_context("success", "en")
        unverified_context["result_match"] = {
            "status": "not_evaluated",
            "reason": "No explicit expected metrics were supplied.",
            "comparisons": [],
        }
        unverified_context_path = temp_root / "context-unverified.json"
        unverified_context_path.write_text(json.dumps(unverified_context), encoding="utf-8")
        unverified_output_path = temp_root / "annotated-unverified.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "--readme",
                str(readme_path),
                "--context-json",
                str(unverified_context_path),
                "--output",
                str(unverified_output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        unverified = unverified_output_path.read_text(encoding="utf-8")
        unverified_evaluation = unverified.split("## Evaluation", 1)[1].split("## Training", 1)[0]
        if "tier: result-match" in unverified_evaluation or "tier: execution" not in unverified_evaluation:
            raise AssertionError("observed metrics without an explicit expectation were mislabeled as result-match")
        if "not evaluated because no explicit expected metrics" not in unverified_evaluation:
            raise AssertionError("unverified metric result lost its explicit not-evaluated explanation")
        checks += 2

        mismatched_context = build_context("success", "en")
        mismatched_context["result_match"] = {
            "status": "mismatched",
            "absolute_tolerance": 0.1,
            "comparisons": [
                {
                    "metric": "miou",
                    "expected": 80.0,
                    "observed": 79.4,
                    "absolute_error": 0.6,
                    "within_tolerance": False,
                }
            ],
        }
        mismatched_context_path = temp_root / "context-mismatched.json"
        mismatched_context_path.write_text(json.dumps(mismatched_context), encoding="utf-8")
        mismatched_output_path = temp_root / "annotated-mismatched.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "--readme",
                str(readme_path),
                "--context-json",
                str(mismatched_context_path),
                "--output",
                str(mismatched_output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        mismatched = mismatched_output_path.read_text(encoding="utf-8")
        mismatched_evaluation = mismatched.split("## Evaluation", 1)[1].split("## Training", 1)[0]
        if "[!WARNING]" not in mismatched_evaluation or "tier: result-match" in mismatched_evaluation:
            raise AssertionError("metric mismatch was not downgraded to a warning execution result")
        checks += 1
        if "tier: code-development" not in annotated:
            raise AssertionError("planned-only sections lost their code-development evidence tier")
        checks += 1

        crlf_source = b"\xef\xbb\xbf" + README.rstrip("\n").replace("\n", "\r\n").encode("utf-8")
        crlf_readme = temp_root / "README-crlf-bom.md"
        crlf_readme.write_bytes(crlf_source)
        crlf_output = temp_root / "annotated-crlf-bom.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "annotate",
                "--readme",
                str(crlf_readme),
                "--context-json",
                str(context_path),
                "--output",
                str(crlf_output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        crlf_stripped = temp_root / "stripped-crlf-bom.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "strip",
                "--input",
                str(crlf_output),
                "--output",
                str(crlf_stripped),
                "--against",
                str(crlf_readme),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if crlf_stripped.read_bytes() != crlf_source:
            raise AssertionError("CRLF/BOM/no-final-newline source did not round-trip byte-for-byte")
        checks += 1

        media_markup_source = (
            "# Media\n\n![plot](assets/plot.png)\n\n"
            "<video controls poster=\"assets/poster.jpg\">\n"
            "  <source src=\"assets/demo.mp4\" type=\"video/mp4\">\n"
            "</video>\n"
        )
        media_markup_readme = temp_root / "README-media-markup.md"
        media_markup_readme.write_text(media_markup_source, encoding="utf-8")
        media_markup_output = temp_root / "ANNOTATED_README-media-markup.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "annotate",
                "--readme",
                str(media_markup_readme),
                "--context-json",
                str(context_path),
                "--output",
                str(media_markup_output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        media_annotated = media_markup_output.read_text(encoding="utf-8")
        for original_line in [
            "![plot](assets/plot.png)",
            '<video controls poster="assets/poster.jpg">',
            '  <source src="assets/demo.mp4" type="video/mp4">',
        ]:
            if media_annotated.count(original_line) != 1:
                raise AssertionError(f"README media markup was omitted, duplicated, or rewritten: {original_line}")
        checks += 1
        media_stripped = temp_root / "README-media-markup-restored.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "strip",
                "--input",
                str(media_markup_output),
                "--output",
                str(media_stripped),
                "--against",
                str(media_markup_readme),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if media_stripped.read_bytes() != media_markup_readme.read_bytes():
            raise AssertionError("README media markup did not survive the exact byte round trip")
        checks += 1

        fence_block = annotated.split("## Evaluation", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
        if "[!" in fence_block:
            raise AssertionError("annotation leaked inside a fenced code block")
        checks += 1

        zh_context_path = temp_root / "context-zh.json"
        zh_context_path.write_text(json.dumps(build_context("success", "zh")), encoding="utf-8")
        zh_output_path = temp_root / "annotated-zh.md"
        subprocess.run(
            [
                sys.executable,
                str(renderer),
                "--readme",
                str(readme_path),
                "--context-json",
                str(zh_context_path),
                "--output",
                str(zh_output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        zh_annotated = zh_output_path.read_text(encoding="utf-8")
        assert_original_preserved(zh_annotated)
        if "执行成功" not in zh_annotated:
            raise AssertionError("zh rendering lost the localized success annotation")
        checks += 2

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    raise SystemExit(main())
