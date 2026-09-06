#!/usr/bin/env python3
"""Exercise real command runs without promoting setup guesses into requirements."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "skills/ai-research-reproduction/scripts/orchestrate_repro.py"


def run_case(root: Path, name: str, source: str, *, language: str = "en",
             execute: bool = True, asset_hint: bool = False, environment: str = "") -> tuple[dict, Path, Path]:
    case_root = root / name
    repo = case_root / "target"
    repo.mkdir(parents=True)
    original = b"# Example\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n"
    if asset_hint:
        original += b"\nDataset: data/required.json\n"
    (repo / "README.md").write_bytes(original)
    (repo / "evaluate.py").write_text(source, encoding="utf-8")
    if environment:
        (repo / "environment.yml").write_text(environment, encoding="utf-8")
    output = case_root / "repro_outputs"
    args = [sys.executable, str(ORCHESTRATOR), "--repo", str(repo), "--output-dir", str(output),
            "--user-language", language, "--timeout", "15", "--no-gpu-monitor"]
    if execute:
        args.append("--run-selected")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0")
    process = subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", env=env)
    payload = json.loads(process.stdout)
    assert (repo / "README.md").read_bytes() == original, "Reporting changed the original README"
    assert not (repo / ".venv").exists(), "Reporting unexpectedly executed a setup suggestion"
    persisted = json.loads((output / "status.json").read_text(encoding="utf-8"))
    for key in ("human_decisions_required", "setup_advisories", "command_reporting"):
        assert persisted[key] == payload[key], f"{key} disappeared from the durable status"
    assert all(item["execution_status"] == "not_run" for item in payload["setup_commands"])
    assert payload["command_reporting"]["setup"] == payload["command_reporting"]["assets"] == "not_run"
    return payload, output, repo


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rigorpilot-reporting-") as directory:
        root = Path(directory)
        for language in ("en", "zh"):
            payload, output, _ = run_case(root, "stdlib-" + language, "print('score=1.0')\n", language=language)
            assert payload["status"] == "success"
            assert payload["human_decisions_required"] == [], "Missing environment metadata became an artificial decision"
            assert payload["setup_advisories"], "Setup discovery gaps were silently discarded"
            assert payload["asset_commands"] == [], "Missing generic directories invented asset prerequisites"
            assert payload["command_reporting"]["main_run"] == "success"
            assert Path(payload["run_commands"][0]["execution_evidence"]).is_file()
            rendered = (output / "COMMANDS.md").read_text(encoding="utf-8")
            assert ("未执行" if language == "zh" else "not executed") in rendered
            assert rendered.startswith("# 命令记录" if language == "zh" else "# Commands")
            assert "execution_status: success" in rendered and "execution_status: not_run" in rendered
            manifest = json.loads((output.parent / "artifacts/assets/asset_manifest.json").read_text(encoding="utf-8"))
            assert manifest["manifest"] and all(item["status"] == "missing" for item in manifest["manifest"])

        payload, _, _ = run_case(root, "dry-run", "raise RuntimeError('must not execute')\n", execute=False)
        assert payload["command_reporting"]["main_run"] == "not_run"
        assert not payload["run_commands"][0]["execution_evidence"]
        assert payload["human_decisions_required"] == []

        payload, output, _ = run_case(root, "missing-dependency", "import rigorpilot_intentionally_missing_dependency_71830\n")
        assert payload["status"] != "success" and payload["human_decisions_required"]
        assert payload["command_reporting"]["main_run"] == "failed"
        assert payload["setup_advisories"], "Real failures must not hide setup discovery gaps"
        assert "ModuleNotFoundError" in Path(payload["stderr_log_path"]).read_text(encoding="utf-8")
        assert "ModuleNotFoundError" in (output / "status.json").read_text(encoding="utf-8")

        payload, _, repo = run_case(root, "missing-asset", "from pathlib import Path\nPath('data/required.json').read_text()\n", asset_hint=True)
        assert payload["status"] != "success" and payload["human_decisions_required"]
        assert "FileNotFoundError" in Path(payload["stderr_log_path"]).read_text(encoding="utf-8")
        assert any("data/required.json" in item["command"] for item in payload["asset_commands"]), "Documented asset hints were lost"
        assert not (repo / "data").exists(), "An observation must not create/download assets"

        payload, _, _ = run_case(root, "unresolved-conda-plan", "print('score=1.0')\n", execute=False,
                                 environment="dependencies:\n  - python=3.11\n")
        assert payload["setup_advisories"], "A conda plan requiring confirmation was dropped"
        assert any("<env-name>" in item["command"] for item in payload["setup_commands"])
        assert payload["human_decisions_required"] == [], "An unselected setup action became a required decision"

    print("ok: True")
    print("cases: 6")
    print("failures: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
