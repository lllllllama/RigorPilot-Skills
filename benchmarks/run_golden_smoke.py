#!/usr/bin/env python3
"""Run a deterministic, API-free smoke benchmark against the reproduction harness."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


OUTPUT_FILES = {
    "SUMMARY.md",
    "COMMANDS.md",
    "LOG.md",
    "SCIENTIFIC_CHANGELOG.md",
    "COMPARABILITY_REPORT.md",
    "status.json",
    "ANNOTATED_README.md",
}
RUNTIME_FILES = {"spec.json", "state.json", "events.jsonl", "resources.jsonl", "stdout.log", "stderr.log"}


def write_case(repo: Path, command: str, files: Dict[str, str]) -> None:
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(
        "# RigorPilot Golden Smoke Case\n\n"
        "## Evaluation\n\n"
        "```bash\n"
        f"{command}\n"
        "```\n",
        encoding="utf-8",
    )
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def git_commit(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def git_dirty(repo_root: Path) -> bool | None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def run_case(
    orchestrator: Path,
    root: Path,
    name: str,
    command: str,
    files: Dict[str, str],
    expected_status: str,
    expected_match: str,
    extra_args: List[str] | None = None,
    expected_model: str | None = None,
) -> Dict[str, Any]:
    case_repo = root / name / "repo"
    output_dir = root / name / "repro_outputs"
    write_case(case_repo, command, files)
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            str(orchestrator),
            "--repo",
            str(case_repo),
            "--output-dir",
            str(output_dir),
            "--run-selected",
            *(extra_args or []),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    payload: Dict[str, Any] = {}
    parse_error = None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        parse_error = str(exc)

    present_outputs = sorted(path.name for path in output_dir.glob("*") if path.is_file()) if output_dir.exists() else []
    missing_outputs = sorted(OUTPUT_FILES - set(present_outputs))
    actual_status = payload.get("status")
    actual_match = (payload.get("result_match") or {}).get("status")
    annotated = (output_dir / "ANNOTATED_README.md").read_text(encoding="utf-8") if (output_dir / "ANNOTATED_README.md").exists() else ""
    false_result_match = expected_match != "matched" and "tier: result-match" in annotated
    runtime_dir = Path(payload["runtime_dir"]) if payload.get("runtime_dir") else None
    runtime_files = {path.name for path in runtime_dir.iterdir() if path.is_file()} if runtime_dir and runtime_dir.is_dir() else set()
    runtime_evidence_complete = RUNTIME_FILES.issubset(runtime_files)
    actual_model = (payload.get("model_adapter") or {}).get("model")
    passed = (
        result.returncode == 0
        and parse_error is None
        and actual_status == expected_status
        and actual_match == expected_match
        and not missing_outputs
        and not false_result_match
        and runtime_evidence_complete
        and (expected_model is None or actual_model == expected_model)
    )
    return {
        "name": name,
        "passed": passed,
        "duration_seconds": duration,
        "expected": {"status": expected_status, "result_match": expected_match},
        "actual": {"status": actual_status, "result_match": actual_match},
        "observed_metrics": payload.get("observed_metrics", {}),
        "missing_outputs": missing_outputs,
        "false_result_match": false_result_match,
        "runtime_status": payload.get("runtime_status"),
        "runtime_evidence_complete": runtime_evidence_complete,
        "model_adapter_recorded": actual_model,
        "process_returncode": result.returncode,
        "parse_error": parse_error,
        "stderr_excerpt": (result.stderr or "").strip()[-500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RigorPilot's deterministic golden smoke benchmark.")
    parser.add_argument(
        "--output",
        default="benchmark_outputs/golden_smoke.json",
        help="Path for the machine-readable benchmark report.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    orchestrator = repo_root / "skills" / "ai-research-reproduction" / "scripts" / "orchestrate_repro.py"
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-golden-smoke-"))
    started = time.monotonic()
    try:
        model_profile = temp_root / "model-profile.json"
        model_profile.write_text(
            json.dumps(
                {
                    "adapter_id": "golden-host",
                    "provider": "host",
                    "model": "golden-test-model",
                    "capabilities": ["structured_output"],
                }
            ),
            encoding="utf-8",
        )
        cases = [
            run_case(
                orchestrator,
                temp_root,
                "metric_match",
                "python evaluate.py",
                {"evaluate.py": "print('accuracy=0.875')\n"},
                "success",
                "matched",
                ["--expected-metric", "accuracy=0.88", "--metric-absolute-tolerance", "0.01"],
            ),
            run_case(
                orchestrator,
                temp_root,
                "metric_mismatch",
                "python evaluate.py",
                {"evaluate.py": "print('accuracy=0.875')\n"},
                "success",
                "mismatched",
                ["--expected-metric", "accuracy=0.90", "--metric-absolute-tolerance", "0.01"],
            ),
            run_case(
                orchestrator,
                temp_root,
                "missing_executable",
                "rigorpilot-command-that-does-not-exist --evaluate",
                {},
                "blocked",
                "not_evaluated",
            ),
            run_case(
                orchestrator,
                temp_root,
                "model_adapter_snapshot",
                "python evaluate.py",
                {"evaluate.py": "print('accuracy=0.875')\n"},
                "success",
                "not_evaluated",
                [
                    "--model-profile-json",
                    str(model_profile),
                    "--require-model-capability",
                    "structured_output",
                ],
                expected_model="golden-test-model",
            ),
            run_case(
                orchestrator,
                temp_root,
                "shell_requires_opt_in",
                "python evaluate.py | python consume.py",
                {
                    "evaluate.py": "print('accuracy=0.875')\n",
                    "consume.py": "import sys\nprint(sys.stdin.read())\n",
                },
                "blocked",
                "not_evaluated",
            ),
        ]
        elapsed = round(time.monotonic() - started, 3)
        report = {
            "schema_version": "1.0",
            "benchmark": "rigorpilot-golden-smoke",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_commit": git_commit(repo_root),
            "working_tree_dirty": git_dirty(repo_root),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "api_calls": 0,
            "gpu_required": False,
            "duration_seconds": elapsed,
            "summary": {
                "cases_total": len(cases),
                "cases_passed": sum(1 for case in cases if case["passed"]),
                "false_result_matches": sum(1 for case in cases if case["false_result_match"]),
                "complete_evidence_bundles": sum(1 for case in cases if not case["missing_outputs"]),
                "complete_runtime_bundles": sum(1 for case in cases if case["runtime_evidence_complete"]),
            },
            "cases": cases,
        }
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["summary"]["cases_passed"] == len(cases) else 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
