#!/usr/bin/env python3
"""Regression checks for reviewed README-command selection and stable errors."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "skills/ai-research-reproduction/scripts/orchestrate_repro.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def init_repo(root: Path, readme: str, files: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    (root / "README.md").write_text(readme, encoding="utf-8")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "init")
    git(root, "config", "user.email", "rigorpilot@example.com")
    git(root, "config", "user.name", "RigorPilot Test")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    return root


def invoke(repo: Path, *extra: str, check: bool = False) -> tuple[dict, subprocess.CompletedProcess[str]]:
    process = subprocess.run(
        [sys.executable, str(ORCHESTRATOR), "--repo", str(repo), "--agent-output", *extra],
        cwd=repo.parent,
        env=dict(os.environ, PYTHONIOENCODING="utf-8", RIGORPILOT_LESSONS="0"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
        timeout=30,
    )
    return json.loads(process.stdout), process


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-command-selection-"))
    checks = 0
    try:
        multi = init_repo(
            temp_root / "multi",
            "# Demo\n\n## Evaluation\n\n```bash\npython eval_a.py\npython eval_b.py\n```\n",
            {"eval_a.py": "print('metric=1')\n", "eval_b.py": "print('metric=2')\n"},
        )
        plan, _ = invoke(multi, "--plan-only", "--timeout", "30")
        candidates = plan["command_candidates"]
        if [item["id"] for item in candidates] != ["cmd-01", "cmd-02"]:
            raise AssertionError(f"candidate ids are not stable/extraction ordered: {candidates}")
        if plan["selected_command_id"] != "cmd-01" or not plan["selection_fingerprint"]:
            raise AssertionError("plan did not expose selected command id/fingerprint")
        if plan["reviewed_run_args"] != [
            "--run-selected", "--command-id", "cmd-01", "--plan-fingerprint", plan["selection_fingerprint"],
            "--timeout", "30",
        ]:
            raise AssertionError("plan did not return copyable reviewed execution args")
        checks += 1

        contract = plan.get("proposed_run_contract", {})
        if contract.get("target_command_timeout_seconds") != 30 or contract.get("timeout_scope") != "target_command_only":
            raise AssertionError("plan lost target-command timeout scope")
        if contract.get("target_timeout_flag") != "--timeout":
            raise AssertionError("plan lost the reviewed non-training timeout flag")
        if contract.get("orchestrator_must_reach_terminal_state") is not True:
            raise AssertionError("plan no longer requires orchestrator terminal-state finalization")
        if contract.get("external_timeout_wrapper_allowed") is not False:
            raise AssertionError("plan no longer forbids a racing external timeout wrapper")
        if "equal or shorter timeout" not in contract.get("outer_timeout_guidance", ""):
            raise AssertionError("plan no longer warns against a racing outer timeout")
        checks += 1

        training_repo = init_repo(
            temp_root / "training-plan",
            "# Training fixture\n\n## Training\n\n```bash\npython train.py\n```\n",
            {"train.py": "print('train-start')\n"},
        )
        training_plan, _ = invoke(training_repo, "--plan-only", "--train-timeout", "45")
        if training_plan.get("selected_goal") != "training":
            raise AssertionError("training plan did not classify the documented training target")
        if training_plan.get("reviewed_run_args", [])[-2:] != ["--train-timeout", "45"]:
            raise AssertionError("training reviewed args did not bind --train-timeout")
        training_contract = training_plan.get("proposed_run_contract", {})
        if training_contract.get("target_timeout_flag") != "--train-timeout" or training_contract.get("target_command_timeout_seconds") != 45:
            raise AssertionError("training plan lost its reviewed timeout contract")
        checks += 1

        reviewed, reviewed_process = invoke(
            multi,
            "--run-selected",
            "--command-id", "cmd-02",
            "--plan-fingerprint", plan["selection_fingerprint"],
            "--no-gpu-monitor",
        )
        if reviewed_process.returncode != 0 or reviewed.get("status") != "success":
            raise AssertionError(f"reviewed command execution failed: {reviewed}")
        if reviewed.get("selected_command_id") != "cmd-02" or reviewed.get("documented_command") != "python eval_b.py":
            raise AssertionError("explicit reviewed command id did not select the requested README command")
        persisted = json.loads((multi / "repro_outputs/status.json").read_text(encoding="utf-8"))
        if persisted.get("selection_source") != "reviewed_command_id" or persisted.get("documented_command_id") != "cmd-02":
            raise AssertionError("status.json lost reviewed command provenance")
        checks += 1

        no_token, no_token_process = invoke(multi, "--run-selected", "--command-id", "cmd-01")
        if no_token_process.returncode == 0 or no_token.get("error", {}).get("code") != "review_token_required":
            raise AssertionError("explicit command id executed without the reviewed plan fingerprint")
        checks += 1

        stale_plan, _ = invoke(multi, "--plan-only")
        (multi / "README.md").write_text(
            "# Demo\n\n## Evaluation\n\n```bash\npython eval_a.py\npython eval_b.py\npython eval_c.py\n```\n",
            encoding="utf-8",
        )
        (multi / "eval_c.py").write_text("print('metric=3')\n", encoding="utf-8")
        stale, stale_process = invoke(
            multi,
            "--run-selected",
            "--command-id", "cmd-01",
            "--plan-fingerprint", stale_plan["selection_fingerprint"],
        )
        if stale_process.returncode == 0 or stale.get("error", {}).get("code") != "plan_changed":
            raise AssertionError("changed README command set did not invalidate the reviewed plan")
        if (multi / "repro_outputs/_runtime").exists() and any((multi / "repro_outputs/_runtime").iterdir()):
            # A previous reviewed run exists; stale execution must not add another runtime attempt.
            runtime_count = len(list((multi / "repro_outputs/_runtime").iterdir()))
            if runtime_count != 1:
                raise AssertionError("stale reviewed plan launched target execution")
        checks += 1

        setup_only = init_repo(
            temp_root / "setup-only",
            "# Setup only\n\n## Installation\n\n```bash\npip install -r requirements.txt\nwget https://example.invalid/model.bin\n```\n",
            {"requirements.txt": "definitely-not-a-real-package-12345\n"},
        )
        setup_plan, _ = invoke(setup_only, "--plan-only")
        if setup_plan["command_candidates"] or setup_plan["documented_command"] is not None:
            raise AssertionError("setup/download commands leaked into reproduction candidates")
        setup_run, _ = invoke(setup_only, "--run-selected")
        if setup_run.get("error", {}).get("code") != "no_documented_command":
            raise AssertionError("setup-only repository did not fail closed as no documented run target")
        if (setup_only / "repro_outputs/_runtime").exists():
            raise AssertionError("setup-only repository unexpectedly launched pip/download execution")
        checks += 1

        misleading_install = init_repo(
            temp_root / "misleading-install",
            "# Misleading heading\n\n## Usage\n\n```bash\nmake install\npython evaluate.py\n```\n",
            {"Makefile": "install:\n\t@echo should-not-run\n", "evaluate.py": "print('score=1')\n"},
        )
        misleading_plan, _ = invoke(misleading_install, "--plan-only")
        commands = [item["command"] for item in misleading_plan["command_candidates"]]
        if commands != ["python evaluate.py"] or misleading_plan.get("documented_command") != "python evaluate.py":
            raise AssertionError(f"install syntax leaked through a misleading Usage heading: {commands}")
        checks += 1

        shell_repo = init_repo(
            temp_root / "shell",
            "# Shell\n\n## Evaluation\n\n```bash\npython producer.py | python consumer.py\n```\n",
            {"producer.py": "print('score=1')\n", "consumer.py": "import sys; print(sys.stdin.read().strip())\n"},
        )
        shell_plan, _ = invoke(shell_repo, "--plan-only")
        candidate = shell_plan["command_candidates"][0]
        if candidate["feasible"] is not False or candidate["requires_native_shell"] is not True:
            raise AssertionError("shell syntax was not surfaced as an explicit review requirement")
        shell_blocked, _ = invoke(
            shell_repo,
            "--run-selected", "--command-id", candidate["id"],
            "--plan-fingerprint", shell_plan["selection_fingerprint"],
        )
        if shell_blocked.get("error", {}).get("code") != "shell_review_required":
            raise AssertionError("direct-mode shell syntax did not fail with shell_review_required")
        if shell_blocked.get("status") != "blocked" or shell_blocked.get("runtime_status") is not None:
            raise AssertionError("shell preflight rejection must be blocked without target execution")
        if "--shell-mode native" not in shell_blocked.get("next_safe_action", "") and "--shell-mode native" not in shell_blocked.get("next_action", ""):
            raise AssertionError("shell preflight did not provide reviewed native-shell guidance")
        checks += 1

        placeholder_repo = init_repo(
            temp_root / "placeholder",
            "# Placeholder\n\n## Evaluation\n\n```bash\npython evaluate.py --data <DATA_PATH>\n```\n",
            {"evaluate.py": "print('never')\n"},
        )
        placeholder_plan, _ = invoke(placeholder_repo, "--plan-only")
        placeholder_candidate = placeholder_plan["command_candidates"][0]
        if placeholder_candidate.get("requires_native_shell") is not False or "placeholder" not in placeholder_candidate.get("feasibility_reason", ""):
            raise AssertionError("angle-bracket placeholder was misclassified as shell syntax")
        placeholder_result, _ = invoke(
            placeholder_repo,
            "--run-selected", "--command-id", placeholder_candidate["id"],
            "--plan-fingerprint", placeholder_plan["selection_fingerprint"],
        )
        if placeholder_result.get("error", {}).get("code") != "placeholder_required":
            raise AssertionError("placeholder command did not expose placeholder_required")
        if placeholder_result.get("status") != "blocked" or placeholder_result.get("runtime_status") is not None:
            raise AssertionError("placeholder preflight rejection must be blocked without target execution")
        if "<...>" not in placeholder_result.get("next_safe_action", ""):
            raise AssertionError("placeholder preflight did not explain safe re-planning")
        checks += 1

        missing_dep = init_repo(
            temp_root / "missing-dep",
            "# Missing dependency\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n",
            {"evaluate.py": "import rigorpilot_missing_dependency_81273\n"},
        )
        dep_result, _ = invoke(missing_dep, "--run-selected", "--no-gpu-monitor")
        if dep_result.get("error", {}).get("code") != "missing_dependency":
            raise AssertionError(f"missing dependency error was not classified: {dep_result.get('error')}")
        checks += 1

        missing_asset = init_repo(
            temp_root / "missing-asset",
            "# Missing asset\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n",
            {"evaluate.py": "from pathlib import Path\nPath('data/missing.json').read_text()\n"},
        )
        asset_result, _ = invoke(missing_asset, "--run-selected", "--no-gpu-monitor")
        if asset_result.get("error", {}).get("code") != "missing_asset":
            raise AssertionError(f"missing asset error was not classified: {asset_result.get('error')}")
        checks += 1

        missing_executable = init_repo(
            temp_root / "missing-executable",
            "# Missing executable\n\n## Evaluation\n\n```bash\npython_rigorpilot_missing_81273 evaluate.py\n```\n",
            {"evaluate.py": "print('never')\n"},
        )
        executable_result, _ = invoke(missing_executable, "--run-selected")
        if executable_result.get("error", {}).get("code") != "command_not_found":
            raise AssertionError(f"missing executable error was not classified: {executable_result.get('error')}")
        checks += 1

        failed_repo = init_repo(
            temp_root / "failed-command",
            "# Failure\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n",
            {"evaluate.py": "raise RuntimeError('boom')\n"},
        )
        failed_result, _ = invoke(failed_repo, "--run-selected")
        if failed_result.get("error", {}).get("code") != "command_failed":
            raise AssertionError(f"generic failed command was not classified: {failed_result.get('error')}")
        checks += 1

        timeout_repo = init_repo(
            temp_root / "timeout",
            "# Timeout\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n",
            {"evaluate.py": "import time\ntime.sleep(5)\n"},
        )
        timeout_result, _ = invoke(timeout_repo, "--run-selected", "--timeout", "1")
        if timeout_result.get("error", {}).get("code") != "timeout":
            raise AssertionError(f"timed-out command was not classified: {timeout_result.get('error')}")
        if "reviewed command" not in timeout_result.get("next_safe_action", "") or "--timeout" not in timeout_result.get("next_safe_action", ""):
            raise AssertionError("timeout guidance did not preserve the reviewed command and user-bounded timeout contract")
        checks += 1

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
