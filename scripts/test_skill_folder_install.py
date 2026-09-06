#!/usr/bin/env python3
"""Exercise a skills-directory-only install without repository-level helpers.

This models the directory layout of skills installers; it does not invoke npx
or claim that a live third-party installer/network transaction was tested.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def invoke(script: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [sys.executable, str(script), *args], cwd=cwd,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "RIGORPILOT_LESSONS": "0"},
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(f"installed {script.name} failed:\n{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="rigorpilot-folder-install-") as temporary:
        # Resolve platform aliases (/var vs /private/var, Windows short paths)
        # before comparing this boundary with resolved installed references.
        workspace = Path(temporary).resolve()
        installed = workspace / "agent-home" / "skills"
        shutil.copytree(root / "skills", installed,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        referenced_guides: set[Path] = set()
        for contract in installed.glob("*/SKILL.md"):
            content = contract.read_text(encoding="utf-8")
            if "../../references/" in content:
                raise AssertionError(f"{contract.parent.name} still requires checkout-level references")
            for relative in re.findall(r"`(\.\./ai-research-reproduction/references/[^`]+\.md)`", content):
                guide = (contract.parent / relative).resolve()
                if not guide.is_relative_to(installed) or not guide.is_file():
                    raise AssertionError(f"installed {contract.parent.name} cannot resolve {relative}")
                source = root / "references" / guide.name
                if guide.read_bytes() != source.read_bytes():
                    raise AssertionError(f"installed shared guide differs from canonical source: {guide.name}")
                referenced_guides.add(guide)
        if not referenced_guides:
            raise AssertionError("no shared guide references were exercised")
        # The shared operating guide loads these sibling policies by filename;
        # the variant guide resolves the advanced contract by installed skill.
        guides = installed / "ai-research-reproduction/references"
        for name in ("research-rigor-principles.md", "deep-learning-experiment-principles.md"):
            if not (guides / name).is_file():
                raise AssertionError(f"shared operating guide lost its sibling dependency: {name}")
        if not (installed / "ai-research-explore/references/research-campaign-spec.md").is_file():
            raise AssertionError("variant guide lost its installed campaign reference")
        public_scripts = sorted(installed.glob("*/scripts/*.py"))
        if not public_scripts:
            raise AssertionError("no public CLI entrypoints were discovered")
        for script in public_scripts:
            invoke(script, ["--help"], workspace)
        invoke(installed / "ai-research-reproduction/_bundled/shared/scripts/lessons_store.py",
               ["summarize", "--help"], workspace)

        # A legacy external shared directory must not shadow a complete bundle.
        stale_shared = installed.parent / "shared" / "scripts"
        stale_shared.mkdir(parents=True)
        shutil.copy2(root / "shared/scripts/model_adapter.py", stale_shared / "model_adapter.py")
        invoke(installed / "ai-research-reproduction/scripts/run_agent.py", ["--help"], workspace)

        # Execute a real, API-free fixture through the installed leaf runtime,
        # then render its evidence through the installed writer fallback.
        target = workspace / "target"
        target.mkdir()
        (target / "evaluate.py").write_text("print('accuracy=0.91')\n", encoding="utf-8")
        argv = [sys.executable, "evaluate.py"]
        command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        executed = invoke(installed / "minimal-run-and-audit/scripts/run_command.py", [
            "--repo", str(target), "--command", command, "--timeout", "10",
        ], workspace)
        payload = json.loads(executed.stdout)
        if payload.get("runtime_status") != "success" or payload.get("observed_metrics", {}).get("accuracy") != 0.91:
            raise AssertionError(f"installed leaf lost execution evidence: {payload}")
        if "accuracy=0.91" not in Path(payload["stdout_log_path"]).read_text(encoding="utf-8"):
            raise AssertionError("installed leaf did not retain the actual process stdout")
        context = workspace / "context.json"
        context.write_text(json.dumps({**payload, "target_repo": str(target),
                                       "documented_command": command,
                                       "selected_goal": "evaluation",
                                       "goal_priority": "evaluation",
                                       "readme_first": False,
                                       "user_language": "en",
                                       "result_summary": "Local fixture completed with accuracy=0.91.",
                                       "next_action": "Inspect the retained fixture evidence."}), encoding="utf-8")
        output = workspace / "repro_outputs"
        invoke(installed / "minimal-run-and-audit/scripts/write_outputs.py", [
            "--context-json", str(context), "--output-dir", str(output),
        ], workspace)
        persisted = json.loads((output / "status.json").read_text(encoding="utf-8"))
        if persisted.get("runtime", {}).get("status") != "success":
            raise AssertionError("installed writer did not preserve verified runtime status")
        print("ok: True")
        print(f"public_cli_checks: {len(public_scripts)}")
        print(f"shared_guide_checks: {len(referenced_guides)}")
        print("checks: stale shared fallback, real execution, persisted evidence")
        print("failures: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
