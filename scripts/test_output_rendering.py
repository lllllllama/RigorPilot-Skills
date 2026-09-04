#!/usr/bin/env python3
"""Regression checks for rendered output files."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict


def write_context(path: Path) -> Dict[str, object]:
    context = {
        "schema_version": "1.0",
        "generated_at": "2026-03-30T00:00:00Z",
        "user_language": "en",
        "target_repo": "D:/demo/repo",
        "readme_first": True,
        "selected_goal": "inference",
        "goal_priority": "inference",
        "status": "partial",
        "documented_command_status": "partial",
        "documented_command": "python demo.py --prompt test",
        "documented_command_kind": "run",
        "documented_command_source": "code_block",
        "documented_command_section": "Usage",
        "evidence_level": "mixed",
        "result_summary": "Selected `inference` from README evidence.",
        "main_blocker": "The documented command exited with code 1.",
        "next_action": "Prepare environment and assets, then retry the documented command.",
        "next_safe_action": "Review the blocker and confirm the next documented verification step.",
        "setup_commands": [{"label": "adapted", "command": "conda env create -f environment.yml", "platforms": ["windows", "macos", "linux"]}],
        "asset_commands": [{"label": "inferred", "command": "# placeholder asset step"}],
        "run_commands": [{"label": "documented", "command": "python demo.py --prompt test"}],
        "verification_commands": [{"label": "inferred", "command": "# placeholder verification step"}],
        "command_notes": [
            "README path: D:/demo/repo/README.md",
            "Main run label: documented from README (code_block), section `Usage`",
        ],
        "timeline": ["Scanned repository structure and key metadata files."],
        "assumptions": ["README remains the primary source of truth."],
        "unverified_inferences": ["Conda environment name still needs confirmation from repo docs."],
        "evidence": ["Detected files: README.md"],
        "protocol_deviations": ["No protocol deviation was applied during this run."],
        "human_decisions_required": ["Confirm whether the documented command should be retried after the path fix."],
        "observed_metrics": {"miou": 79.4},
        "best_metric": {"name": "miou", "value": 79.4},
        "result_match": {
            "status": "not_evaluated",
            "reason": "No explicit expected metrics were supplied.",
            "comparisons": [],
        },
        "artifact_provenance": [
            {"artifact": "readme", "source": "D:/demo/repo/README.md", "kind": "repo_file"},
            {"artifact": "output_dir", "source": "repro_outputs/", "kind": "generated"},
        ],
        "blockers": ["The documented command exited with code 1."],
        "notes": [],
        "patches_applied": True,
        "patch_branch": "repro/2026-03-30-demo",
        "readme_fidelity": "clarified",
        "highest_patch_risk": "low",
        "verified_commits": [
            {
                "commit": "abc1234",
                "summary": "adjust path handling for documented eval command",
                "files": ["configs/demo.yaml", "scripts/eval.py"],
                "why": ["The README command expected a repo-relative config path on Windows."],
                "verification": ["Re-ran `python demo.py --prompt test` and confirmed config loading passed."],
                "risk": "low",
                "readme_fidelity_effect": "clarified",
            }
        ],
        "validation_summary": "After the patch, the documented command moved past the original config-loading failure.",
        "patch_notes": ["Patch stayed within documented command semantics."],
    }
    path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    return context


def assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"Missing `{needle}` in {label}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    writer = repo_root / "skills" / "minimal-run-and-audit" / "scripts" / "write_outputs.py"

    temp_root = Path(tempfile.mkdtemp(prefix="codex-output-render-", dir=repo_root))
    try:
        context_path = temp_root / "context.json"
        output_dir = temp_root / "repro_outputs"
        write_context(context_path)

        subprocess.run(
            [sys.executable, str(writer), "--context-json", str(context_path), "--output-dir", str(output_dir)],
            check=True,
            capture_output=True,
            text=True,
        )

        commands = (output_dir / "COMMANDS.md").read_text(encoding="utf-8")
        summary = (output_dir / "SUMMARY.md").read_text(encoding="utf-8")
        log = (output_dir / "LOG.md").read_text(encoding="utf-8")
        patches = (output_dir / "PATCHES.md").read_text(encoding="utf-8")
        scientific_changelog = (output_dir / "SCIENTIFIC_CHANGELOG.md").read_text(encoding="utf-8")
        comparability_report = (output_dir / "COMPARABILITY_REPORT.md").read_text(encoding="utf-8")
        status = json.loads((output_dir / "status.json").read_text(encoding="utf-8"))

        assert_contains(commands, "# Commands", "COMMANDS.md")
        assert_contains(commands, "# [adapted]", "COMMANDS.md")
        assert_contains(commands, "# platforms: windows, macos, linux", "COMMANDS.md")
        assert_contains(commands, "# [documented]", "COMMANDS.md")
        assert_contains(commands, "# [inferred]", "COMMANDS.md")
        assert_contains(summary, "# Reproduction Summary", "SUMMARY.md")
        assert_contains(summary, "Patches applied", "SUMMARY.md")
        assert_contains(summary, "repro/2026-03-30-demo", "SUMMARY.md")
        assert_contains(log, "# Reproduction Log", "LOG.md")
        assert_contains(log, "## Command provenance", "LOG.md")
        assert_contains(log, "## Unverified inferences", "LOG.md")
        assert_contains(log, "## Human review checkpoints", "LOG.md")
        assert_contains(log, "## Observed metrics", "LOG.md")
        assert_contains(log, "## Result comparison", "LOG.md")
        assert_contains(log, "## Next safe action", "LOG.md")
        assert_contains(patches, "# Patch Record", "PATCHES.md")
        assert_contains(patches, "Highest patch risk", "PATCHES.md")
        assert_contains(patches, "configs/demo.yaml", "PATCHES.md")
        assert_contains(patches, "documented eval command", "PATCHES.md")
        assert_contains(scientific_changelog, "# Scientific Changelog", "SCIENTIFIC_CHANGELOG.md")
        assert_contains(scientific_changelog, "Engineering fixes", "SCIENTIFIC_CHANGELOG.md")
        assert_contains(scientific_changelog, "configs/demo.yaml", "SCIENTIFIC_CHANGELOG.md")
        assert_contains(comparability_report, "# Comparability Report", "COMPARABILITY_REPORT.md")
        assert_contains(comparability_report, "README documented command", "COMPARABILITY_REPORT.md")
        assert_contains(comparability_report, "readme_fidelity=clarified", "COMPARABILITY_REPORT.md")

        if status["user_language"] != "en":
            raise AssertionError("status.json lost the expected user_language value")
        if status["status"] != "partial":
            raise AssertionError("status.json lost the expected status value")
        if status["documented_command_source"] != "code_block":
            raise AssertionError("status.json lost the expected documented_command_source value")
        if status["documented_command_section"] != "Usage":
            raise AssertionError("status.json lost the expected documented_command_section value")
        if status["patch_branch"] != "repro/2026-03-30-demo":
            raise AssertionError("status.json lost the expected patch_branch value")
        if status["highest_patch_risk"] != "low":
            raise AssertionError("status.json lost the expected highest_patch_risk value")
        if status["evidence_level"] != "mixed":
            raise AssertionError("status.json lost the expected evidence_level value")
        if status["observed_metrics"] != {"miou": 79.4}:
            raise AssertionError("status.json lost non-training observed metrics")
        if status["best_metric"] != {"name": "miou", "value": 79.4}:
            raise AssertionError("status.json lost the non-training best metric")
        if status["result_match"]["status"] != "not_evaluated":
            raise AssertionError("status.json lost the result-match evaluation state")
        if status["next_safe_action"] != "Review the blocker and confirm the next documented verification step.":
            raise AssertionError("status.json lost the expected next_safe_action value")
        if len(status["human_decisions_required"]) != 1:
            raise AssertionError("status.json lost the expected human_decisions_required value")
        if len(status["artifact_provenance"]) != 2:
            raise AssertionError("status.json lost the expected artifact_provenance value")
        if status["verified_commit_count"] != 1:
            raise AssertionError("status.json lost the expected verified_commit_count value")
        if status["outputs"]["scientific_changelog"] != "repro_outputs/SCIENTIFIC_CHANGELOG.md":
            raise AssertionError("status.json lost the scientific changelog output path")
        if status["outputs"]["comparability_report"] != "repro_outputs/COMPARABILITY_REPORT.md":
            raise AssertionError("status.json lost the comparability report output path")

        print("ok: True")
        print("checks: 31")
        print("failures: 0")
        return 0
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    raise SystemExit(main())
