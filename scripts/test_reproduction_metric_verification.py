#!/usr/bin/env python3
"""End-to-end checks for explicit reproduction metric verification."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def write_repo(root: Path) -> None:
    (root / "README.md").write_text(
        "# Metric Demo\n\n"
        "## Evaluation\n\n"
        "```bash\n"
        "python evaluate.py\n"
        "```\n",
        encoding="utf-8",
    )
    (root / "evaluate.py").write_text("print('accuracy=0.875')\n", encoding="utf-8")


def run_orchestrator(orchestrator: Path, repo: Path, output_dir: Path, extra: list[str], *, execute: bool = True) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(orchestrator),
            "--repo",
            str(repo),
            "--output-dir",
            str(output_dir),
            *(["--run-selected"] if execute else []),
            "--no-gpu-monitor",
            *extra,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0"),
    )
    return json.loads(result.stdout)


def assert_failed_acceptance(payload: dict, output: Path) -> None:
    persisted = json.loads((output / "status.json").read_text(encoding="utf-8"))
    if payload["status"] != "partial" or persisted["status"] != "partial":
        raise AssertionError("Failed expected metrics must not retain overall success")
    if payload["runtime_status"] != "success" or payload["documented_command_status"] != "success":
        raise AssertionError("Metric failure must not overwrite the successful process evidence")
    if persisted["runtime"]["status"] != "success":
        raise AssertionError("Durable runtime evidence lost process success")
    if not payload["human_decisions_required"] or "status.json.result_match" not in payload["next_action"]:
        raise AssertionError("Failed acceptance lacks an actionable review checkpoint")
    if payload["main_blocker"] in {"None.", "无。"}:
        raise AssertionError("Failed acceptance was not recorded as a blocker")
    readme = (output / "ANNOTATED_README.md").read_text(encoding="utf-8")
    if "🟡 `partial`" not in readme or "🟢 `success`" in readme or "tier: result-match" in readme:
        raise AssertionError("Overall README banner falsely promotes failed acceptance")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    orchestrator = repo_root / "skills" / "ai-research-reproduction" / "scripts" / "orchestrate_repro.py"
    temp_root = Path(tempfile.mkdtemp(prefix="codex-repro-metric-verification-", dir=repo_root))
    checks = 0
    try:
        sample_repo = temp_root / "sample_repo"
        sample_repo.mkdir()
        write_repo(sample_repo)

        verified_output = temp_root / "verified_outputs"
        verified = run_orchestrator(
            orchestrator,
            sample_repo,
            verified_output,
            ["--expected-metric", "accuracy=0.88", "--metric-absolute-tolerance", "0.01"],
        )
        verified_status = json.loads((verified_output / "status.json").read_text(encoding="utf-8"))
        verified_readme = (verified_output / "ANNOTATED_README.md").read_text(encoding="utf-8")
        if verified["result_match"]["status"] != "matched":
            raise AssertionError("explicit expected metric was not matched within tolerance")
        if verified["status"] != "success" or verified["human_decisions_required"]:
            raise AssertionError("A matched completed evaluation acquired a false blocker")
        checks += 1
        if verified_status["observed_metrics"] != {"accuracy": 0.875}:
            raise AssertionError("repro status did not persist observed metrics")
        checks += 1
        if verified_status["best_metric"] != {"name": "accuracy", "value": 0.875}:
            raise AssertionError("repro status did not persist the best metric")
        checks += 1
        if "tier: result-match" not in verified_readme:
            raise AssertionError("verified metric match did not earn result-match evidence")
        checks += 1

        unverified_output = temp_root / "unverified_outputs"
        unverified = run_orchestrator(orchestrator, sample_repo, unverified_output, [])
        unverified_readme = (unverified_output / "ANNOTATED_README.md").read_text(encoding="utf-8")
        if unverified["result_match"]["status"] != "not_evaluated":
            raise AssertionError("run without expected metrics should remain not_evaluated")
        if unverified["status"] != "success":
            raise AssertionError("No-expectation execution-success compatibility changed")
        checks += 1
        if "tier: result-match" in unverified_readme:
            raise AssertionError("observed metric without an expectation earned false result-match evidence")
        checks += 1

        mismatched_output = temp_root / "mismatched_outputs"
        mismatched = run_orchestrator(
            orchestrator,
            sample_repo,
            mismatched_output,
            ["--expected-metric", "accuracy=0.90", "--metric-absolute-tolerance", "0.01"],
        )
        mismatched_readme = (mismatched_output / "ANNOTATED_README.md").read_text(encoding="utf-8")
        if mismatched["result_match"]["status"] != "mismatched":
            raise AssertionError("out-of-tolerance metric was not marked mismatched")
        assert_failed_acceptance(mismatched, mismatched_output)
        if "Do not widen tolerances" not in mismatched["next_action"] or "failed acceptance evidence" not in mismatched["next_safe_action"]:
            raise AssertionError("Mismatch guidance did not preserve the acceptance contract")
        checks += 1

        missing_output = temp_root / "missing_metric_outputs"
        missing = run_orchestrator(
            orchestrator, sample_repo, missing_output,
            ["--expected-metric", "loss=0.1", "--user-language", "zh"],
        )
        assert_failed_acceptance(missing, missing_output)
        comparison = missing["result_match"]["comparisons"][0]
        if missing["result_match"]["status"] != "mismatched" or comparison["reason"] != "metric_not_observed":
            raise AssertionError("A missing expected metric was not rejected by the existing comparison contract")
        if "验收未通过" not in missing["result_summary"] or "保留验收失败证据" not in missing["next_safe_action"]:
            raise AssertionError("Chinese acceptance-failure guidance was lost")
        checks += 1

        planned = run_orchestrator(
            orchestrator, sample_repo, temp_root / "planned_outputs",
            ["--expected-metric", "loss=0.1"], execute=False,
        )
        if planned["status"] != "not_run" or planned["runtime_status"] is not None:
            raise AssertionError("An unexecuted plan was incorrectly promoted to an executed metric failure")
        checks += 1

        (sample_repo / "evaluate.py").write_text("raise RuntimeError('intentional process failure')\n", encoding="utf-8")
        failed = run_orchestrator(
            orchestrator, sample_repo, temp_root / "failed_process_outputs", ["--expected-metric", "loss=0.1"],
        )
        if failed["status"] != "partial" or failed["runtime_status"] != "failed" or "exited with code" not in failed["main_blocker"]:
            raise AssertionError("Missing metrics masked the actual failed-process blocker")
        checks += 1
        evaluation_tail = mismatched_readme.split("## Evaluation", 1)[1]
        if "[!WARNING]" not in evaluation_tail or "tier: result-match" in evaluation_tail:
            raise AssertionError("mismatched result was not downgraded to warning execution evidence")
        checks += 1

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    raise SystemExit(main())
