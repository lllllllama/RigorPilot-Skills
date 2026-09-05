#!/usr/bin/env python3
"""One explicit real-model micrograd trial; keep its evidence and delete the checkout."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/ai-research-reproduction/scripts"))
from run_agent import run
from agent_provider import AnthropicProvider
from model_adapter import normalize_model_profile
from run_external_reproduction import preserve_showcase, safe_remove_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Explicit model ID available at your configured provider")
    parser.add_argument("--credential-env", default="ANTHROPIC_API_KEY")
    parser.add_argument("--auth-scheme", choices=["api-key", "bearer"], default="api-key")
    parser.add_argument("--output", required=True, help="Fresh evidence directory")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        parser.error("Choose a fresh output directory")
    profile = normalize_model_profile({"adapter_id": "anthropic-messages", "provider": "anthropic", "model": args.model,
        "credential_env": args.credential_env, "capabilities": ["tool_calling"], "metadata": {"auth_scheme": args.auth_scheme}})
    if not os.getenv(args.credential_env):
        parser.error("Credential environment variable is not configured")
    # Resolve endpoint identity for resume/provenance, but do not publish private gateway URLs.
    profile["metadata"]["endpoint_source"] = "ANTHROPIC_BASE_URL" if os.getenv("ANTHROPIC_BASE_URL") else "official"
    profile = normalize_model_profile(profile)
    case = json.loads((ROOT / "benchmarks/external_cases.json").read_text(encoding="utf-8"))["cases"]["micrograd"]
    temporary = Path(tempfile.mkdtemp(prefix="rigorpilot-live-agent-"))
    try:
        repo = temporary / "repo"
        repo.mkdir()
        for command in [["git", "init", str(repo)], ["git", "-C", str(repo), "-c", "core.autocrlf=false", "fetch", "--depth", "1", case["repository"], case["commit"]],
                        ["git", "-C", str(repo), "-c", "core.autocrlf=false", "checkout", "--detach", "FETCH_HEAD"]]:
            subprocess.run(command, check=True, capture_output=True, timeout=60)
        task = {"goal": "Read micrograd's README and relevant test code. Plan and run the documented gradient tests, then request independent verification. Do not install dependencies or claim paper scores.",
            "commands": {"gradient-tests": {"argv": ["python", "-m", "pytest"], "source": "README.md", "documented_command": "python -m pytest",
                "timeout_seconds": 30, "expected_stdout": "2 passed"}}, "required_commands": ["gradient-tests"],
            "budget": {"max_model_calls": 6, "max_tool_calls": 12, "max_total_tokens": 45000, "max_output_tokens": 1000, "max_seconds": 180}}
        evidence = temporary / "repro_outputs"
        state = run(task, repo, evidence, profile, AnthropicProvider(profile))
        output.mkdir(parents=True)
        snapshot = preserve_showcase(repo=repo, case_root=temporary, evidence_dir=evidence, source_readme=repo / "README.md",
            showcase_root=output, case_name="micrograd", repository_url=case["repository"], commit=case["commit"])
        report = {"status": state["status"], "model_profile": profile, "usage": state["usage"], "usage_complete": state["usage_complete"], "model_calls": state["model_calls"],
            "tool_calls": state["tool_calls"], "verification": state["verification"], "elapsed_seconds": state["elapsed_seconds"],
            "blocker": state.get("blocker"), "snapshot": snapshot, "task": task,
            "scope": "Single real-model execution trial with reviewed command set; not a model-quality benchmark or clean dependency install."}
        (output / "REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: report[k] for k in ["status", "model_calls", "tool_calls", "usage", "verification", "blocker"]}, indent=2))
        return int(state["status"] != "success")
    finally:
        safe_remove_workspace(temporary, temporary.parent)


if __name__ == "__main__":
    raise SystemExit(main())
