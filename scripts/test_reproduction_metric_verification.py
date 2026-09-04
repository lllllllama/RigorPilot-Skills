#!/usr/bin/env python3
"""End-to-end checks for explicit reproduction metric verification."""

from __future__ import annotations

import json
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


def run_orchestrator(orchestrator: Path, repo: Path, output_dir: Path, extra: list[str]) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(orchestrator),
            "--repo",
            str(repo),
            "--output-dir",
            str(output_dir),
            "--run-selected",
            *extra,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


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
