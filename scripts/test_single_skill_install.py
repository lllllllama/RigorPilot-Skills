#!/usr/bin/env python3
"""Verify the main skill works after only its directory is installed."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote


def write_target_repo(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "README.md").write_text(
        "# 已安装 Skill Canary 🛠️\n\n"
        "![Curve](assets/curve.svg) · [Protocol](docs/protocol.md)\n\n"
        "## Evaluation\n\n"
        "```bash\npython evaluate.py\n```\n",
        encoding="utf-8",
    )
    (root / "evaluate.py").write_text("print('accuracy=0.91')\n", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets/curve.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="30">'
        '<path d="M0 25L40 10L80 5" fill="none" stroke="green"/></svg>\n', encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs/protocol.md").write_text("# Protocol\n\nExpected accuracy: 0.91.\n", encoding="utf-8")


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
        agent_help = subprocess.run([sys.executable, str(installed_skill / "scripts/run_agent.py"), "--help"],
                                    cwd=temp_root, capture_output=True, text=True)
        if agent_help.returncode != 0 or "--model-profile" not in agent_help.stdout:
            raise AssertionError(f"single-skill agent runner imports failed: {agent_help.stderr}")
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
        originals = {path.relative_to(target_repo): path.read_bytes()
                     for path in target_repo.rglob("*") if path.is_file()}
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
                "--source-adjacent-readme",
                "--include-analysis-pass",
                "--expected-metric",
                "accuracy=0.91",
                "--model-profile-json",
                str(model_profile),
                "--require-model-capability",
                "structured_output",
            ],
            cwd=temp_root,
            env={**os.environ, "RIGORPILOT_LESSONS": "0", "PYTHONIOENCODING": "utf-8"},
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
        if payload["verification_commands"] or not any("status.json.result_match" in note for note in payload["command_notes"]):
            raise AssertionError("installed skill invented a verification command instead of recording its built-in check")
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

        # Check the installed product's browsable output, not a benchmark-only
        # exporter. Keep the original image/document links in their source cwd.
        adjacent = target_repo / "RIGORPILOT_README.md"
        for emitted in (payload, status_payload):
            publication = emitted.get("source_adjacent_readme", {})
            if publication.get("status") != "written" or Path(publication.get("path", "")).resolve() != adjacent.resolve():
                raise AssertionError(f"installed output did not expose its browsable README: {publication}")
        for relative, original_bytes in originals.items():
            if (target_repo / relative).read_bytes() != original_bytes:
                raise AssertionError(f"installed run changed source/supporting file: {relative}")
        stripped = temp_root / "restored.md"
        strip_result = subprocess.run([
            sys.executable, str(installed_skill / "scripts/annotate_readme.py"), "strip",
            "--input", str(adjacent), "--output", str(stripped), "--against", str(target_repo / "README.md"),
        ], cwd=temp_root, capture_output=True, text=True, timeout=30)
        if strip_result.returncode != 0 or stripped.read_bytes() != originals[Path("README.md")]:
            raise AssertionError(f"installed source-adjacent README failed byte round trip: {strip_result.stderr}")
        markup = adjacent.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", markup):
            if "://" in link or link.startswith("#"):
                continue
            target = unquote(link.split("#", 1)[0])
            if not (adjacent.parent / target).exists():
                raise AssertionError(f"installed README has an unresolved local link: {link}")

        # A reviewed repeat updates only the owned generated copy and retains
        # the original README/media. It must not require deleting user files.
        repeated = subprocess.run([
            sys.executable, str(orchestrator), "--repo", str(target_repo), "--output-dir", str(output_dir),
            "--run-selected", "--expected-metric", "accuracy=0.91", "--source-adjacent-readme",
        ], cwd=temp_root, env={**os.environ, "RIGORPILOT_LESSONS": "0", "PYTHONIOENCODING": "utf-8"},
            capture_output=True, text=True, timeout=60)
        if repeated.returncode != 0 or json.loads(repeated.stdout).get("source_adjacent_readme", {}).get("status") != "written":
            raise AssertionError(f"installed source-adjacent refresh failed: {repeated.stdout}\n{repeated.stderr}")
        if any((target_repo / relative).read_bytes() != data for relative, data in originals.items()):
            raise AssertionError("repeated installed run changed original files")

        print("ok: True")
        print("checks: 18")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
