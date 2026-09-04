#!/usr/bin/env python3
"""Test the external benchmark runner against a local pinned Git repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "benchmarks" / "run_external_reproduction.py"
    suite_runner = repo_root / "benchmarks" / "run_external_suite.py"
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-external-test-"))
    checks = 0
    try:
        source = temp_root / "source"
        source.mkdir()
        git(source, "init")
        git(source, "config", "user.email", "benchmark@example.invalid")
        git(source, "config", "user.name", "Benchmark Test")
        (source / "README.md").write_text(
            "# Pinned canary\n\n![result](assets/result.png)\n\n## Evaluation\n\n```bash\npython verify.py\n```\n",
            encoding="utf-8",
        )
        (source / "assets").mkdir()
        (source / "assets" / "result.png").write_bytes(b"tracked-readme-image")
        (source / "verify.py").write_text(
            "import os\n"
            "assert 'RIGORPILOT_TEST_API_KEY' not in os.environ\n"
            "print('accuracy=0.91')\n",
            encoding="utf-8",
        )
        git(source, "add", "README.md", "verify.py", "assets/result.png")
        git(source, "commit", "-m", "test: pinned benchmark source")
        commit = git(source, "rev-parse", "HEAD")
        manifest = temp_root / "cases.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "cases": {
                        "local-canary": {
                            "status": "ready",
                            "repository": str(source),
                            "commit": commit,
                            "target_subdir": ".",
                            "tier": "test",
                            "network_required": False,
                            "environment": {
                                "system_site_packages": False,
                                "dependency_mode": "fresh-empty-venv",
                                "dependency_probes": [],
                                "cache_policy": "isolated-local-test"
                            },
                            "setup_steps": [],
                            "known_adaptations": [],
                            "orchestrator": {
                                "expected_command": "python verify.py",
                                "expected_goal": "evaluation",
                                "expected_status": "success",
                                "expected_stdout_contains": "accuracy=0.91",
                                "timeout_seconds": 30,
                                "include_analysis_pass": True,
                                "expected_metrics": ["accuracy=0.91"]
                            }
                        }
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        output = temp_root / "report.json"
        child_env = dict(os.environ)
        child_env["RIGORPILOT_TEST_API_KEY"] = "must-not-reach-external-code"
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "--case",
                "local-canary",
                "--manifest",
                str(manifest),
                "--work-root",
                str(temp_root / "runs"),
                "--output",
                str(output),
                "--showcase-root",
                str(temp_root / "showcases"),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_env,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"external benchmark runner failed:\n{result.stdout}\n{result.stderr}")
        report = json.loads(output.read_text(encoding="utf-8"))
        if report["status"] != "passed" or not all(report["dimensions"].values()):
            raise AssertionError(f"external benchmark dimensions failed: {report['dimensions']}")
        checks += 1
        if report["source"]["actual_commit"] != commit or not report["source"]["fresh_checkout"]:
            raise AssertionError("external benchmark lost pinned fresh-checkout provenance")
        checks += 1
        showcase_repo = temp_root / "showcases" / "local-canary" / "repo"
        showcase_readme = showcase_repo / "RIGORPILOT_README.md"
        if (showcase_repo / "README.md").read_bytes() != (source / "README.md").read_bytes():
            raise AssertionError("showcase did not retain the original repository README")
        if (showcase_repo / "assets" / "result.png").read_bytes() != b"tracked-readme-image":
            raise AssertionError("showcase deleted or altered a README-related repository file")
        showcase_text = showcase_readme.read_text(encoding="utf-8")
        if showcase_text.count("![result](assets/result.png)") != 1:
            raise AssertionError("showcase README omitted, duplicated, or rewrote original image markup")
        if "](repro_outputs/SUMMARY.md)" not in showcase_text:
            raise AssertionError("source-adjacent showcase README did not rebase inserted evidence links")
        showcase_manifest = json.loads((showcase_repo.parent / "SHOWCASE.json").read_text(encoding="utf-8"))
        if showcase_manifest != report.get("showcase") or showcase_manifest.get("tracked_files_retained") != 3:
            raise AssertionError("showcase manifest and benchmark report disagree")
        restored = temp_root / "showcase-restored.md"
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "skills" / "ai-research-reproduction" / "scripts" / "annotate_readme.py"),
                "strip",
                "--input",
                str(showcase_readme),
                "--output",
                str(restored),
                "--against",
                str(showcase_repo / "README.md"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        checks += 1
        if len(report.get("identity", {}).get("harness_sha256", "")) != 64 or len(report["identity"].get("case_sha256", "")) != 64:
            raise AssertionError("external benchmark did not fingerprint harness and case identities")
        checks += 1
        if not report["selection"]["command_match"] or not report["selection"]["goal_match"]:
            raise AssertionError("external benchmark did not measure README selection")
        checks += 1
        if report["execution"]["result_match"]["status"] != "matched":
            raise AssertionError("external benchmark lost explicit result matching")
        checks += 1
        if not report["evidence"]["complete"] or not report["target_repo_changes"]["tracked_source_unchanged"]:
            raise AssertionError("external benchmark evidence or source-integrity check failed")
        checks += 1
        fidelity = report["evidence"].get("readme_fidelity") or {}
        if not fidelity.get("round_trip_verified"):
            raise AssertionError(f"annotated README did not round-trip to the original bytes: {fidelity}")
        if not fidelity.get("one_annotation_per_heading"):
            raise AssertionError(f"annotated README did not insert exactly one block per heading: {fidelity}")
        if fidelity.get("original_sha256") != fidelity.get("stripped_sha256"):
            raise AssertionError("annotated README fidelity hashes differ")
        checks += 1
        if report["scope"]["network_required"] or not report["intervention_accounting"]["autonomous_after_manifest"]:
            raise AssertionError("external benchmark lost network/intervention accounting")
        checks += 1
        if report["environment"]["secret_environment_variables_stripped"] < 1:
            raise AssertionError("external benchmark did not record stripped secret environment variables")
        checks += 1
        if report["scope"]["workspace_retained"] or report["limits"]["peak_workspace_bytes"] <= 0:
            raise AssertionError("external benchmark did not record bounded disposable workspace usage")
        workspace = repo_root / report["scope"]["workspace"]
        if workspace.exists():
            raise AssertionError("external benchmark retained its workspace without --keep-workspace")
        archive = report["evidence"].get("archive") or {}
        archived_names = {item["name"] for item in archive.get("files", [])}
        if archived_names != {
            "ANNOTATED_README.md",
            "COMMANDS.md",
            "COMPARABILITY_REPORT.md",
            "LOG.md",
            "SCIENTIFIC_CHANGELOG.md",
            "SUMMARY.md",
            "status.json",
        }:
            raise AssertionError(f"unexpected compact evidence archive: {sorted(archived_names)}")
        checks += 1
        phase_names = [phase["name"] for phase in report["phases"]]
        if phase_names != [
            "init-repository",
            "fetch-pinned-commit",
            "checkout-pinned-commit",
            "create-venv",
            "rigorpilot-orchestrator",
        ]:
            raise AssertionError(f"unexpected durable phase sequence: {phase_names}")
        checks += 1

        suite_output = temp_root / "suite.json"
        suite_history = temp_root / "suite.jsonl"
        suite_result = subprocess.run(
            [
                sys.executable,
                str(suite_runner),
                "--cases",
                "local-canary",
                "--manifest",
                str(manifest),
                "--output",
                str(suite_output),
                "--history",
                str(suite_history),
                "--max-total-minutes",
                "1",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if suite_result.returncode != 0:
            raise AssertionError(f"external suite runner failed:\n{suite_result.stdout}\n{suite_result.stderr}")
        suite = json.loads(suite_output.read_text(encoding="utf-8"))
        history_rows = [json.loads(line) for line in suite_history.read_text(encoding="utf-8").splitlines()]
        if suite["status"] != "passed" or suite["passed"] != 1 or suite["failed"] != 0:
            raise AssertionError("external suite did not aggregate its explicit case correctly")
        if len(history_rows) != 1 or history_rows[0]["case"] != "local-canary":
            raise AssertionError("external suite did not append a compact historical row")
        checks += 2

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
