#!/usr/bin/env python3
"""Offline verification: simulated decisions, actual execution and process restart."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/ai-research-reproduction/scripts"))
sys.path.insert(0, str(ROOT / "benchmarks"))
from run_agent import run
from model_adapter import normalize_model_profile
from annotate_readme import strip_annotated_bytes
from run_external_reproduction import rebase_inserted_evidence_links

FIXTURE = ROOT / "examples/harness-lab"
SOURCE_FILES = ("README.md", "prepare.py", "evaluate.py")


def call(name: str, reason: str, **args) -> dict:
    return {"type": "tool_use", "id": "simulation-" + name, "name": name,
            "input": {"reason": reason, **args}}


class SimulatedDecisions:
    """A fixed script, NOT an LLM. Only command execution and verification are real."""
    def complete(self, messages, system, tools, max_tokens, timeout):
        steps = [
            [call("read_file", "模拟决策：先读取原始说明。", path="README.md"),
             call("update_plan", "模拟决策：明确最小任务和验收条件。", steps=["评估", "根据失败准备资产", "恢复并验证"])],
            [call("run_command", "模拟决策：有意触发一次缺失资产错误。", command_id="evaluate")],
            [call("update_plan", "模拟决策：根据预期的缺失资产错误，先准备再重试。", steps=["已观察缺失资产", "准备资产", "暂停后恢复评估"]),
             call("run_command", "模拟决策：只调用 README 中已审核的准备命令。", command_id="prepare")],
            [call("run_command", "模拟决策：新进程恢复后只重试失败的评估。", command_id="evaluate")],
            [call("finish", "模拟决策：提交独立验证，而非凭声明判定成功。", summary="模拟决策结束；以进程和源码验收为准。")],
        ]
        index = sum(message.get("role") == "assistant" for message in messages)
        if index >= len(steps):
            raise ValueError("Offline simulation exhausted; unexpected controller trajectory")
        return {"model": "simulation-no-model", "content": steps[index],
                "usage": {"input_tokens": 0, "output_tokens": 0}}


def lab_task() -> dict:
    return {"goal": "离线验证示例：执行已审核命令，记录缺失资产错误，跨进程恢复并独立验证；不代表真实模型能力。",
        "language": "zh", "commands": {
            "prepare": {"argv": ["python", "prepare.py"], "documented_command": "python prepare.py",
                        "expected_stdout": "prepared: ready.json", "timeout_seconds": 10},
            "evaluate": {"argv": ["python", "evaluate.py"], "documented_command": "python evaluate.py",
                         "expected_stdout": "verified: sum=6", "timeout_seconds": 10}},
        "required_commands": ["evaluate"],
        "budget": {"max_model_calls": 5, "max_tool_calls": 7, "max_total_tokens": 70000,
                   "max_output_tokens": 200, "max_seconds": 30, "max_output_bytes": 500000}}


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def independent_verification_passed(state: dict, required_commands: list[str]) -> bool:
    verification = state.get("verification", {})
    command_checks = verification.get("commands", {})
    return (state.get("status") == "success" and verification.get("source_unchanged") is True
            and bool(required_commands) and isinstance(command_checks, dict)
            and all(command_checks.get(name) is True for name in required_commands))


def remove_temporary_git_pointer(repo: Path, metadata: Path) -> None:
    """Remove only this lab's regular .git pointer, comparing filesystem identity."""
    pointer = repo / ".git"
    try:
        pointer_stat = pointer.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(pointer_stat.st_mode):
        raise RuntimeError(f"Preserved unexpected .git entry (not a regular pointer file): {pointer}")
    try:
        lines = pointer.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) != 1 or not lines[0].startswith("gitdir: "):
            raise ValueError("unrecognized gitdir pointer format")
        target_text = lines[0][len("gitdir: "):].strip()
        if not target_text:
            raise ValueError("empty gitdir target")
        target = Path(target_text)
        if not target.is_absolute():
            target = pointer.parent / target
        # Git may canonicalize /var to /private/var or Windows short paths to
        # long paths. Relative gitdir paths are relative to the pointer's parent.
        actual, expected = target.resolve(strict=True), metadata.resolve(strict=True)
        if not actual.is_dir() or not expected.is_dir() or not actual.samefile(expected):
            raise ValueError("gitdir does not identify this run's temporary metadata")
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"Preserved unexpected .git pointer at {pointer}: {exc}") from exc
    pointer.unlink()


def worker(output: Path, resume: bool) -> int:
    task = json.loads((output / "TASK.json").read_text(encoding="utf-8"))
    profile = normalize_model_profile({"adapter_id": "offline-verification-simulation", "provider": "simulation",
        "model": "simulation-no-model", "endpoint": "simulation://offline", "capabilities": ["tool_calling"],
        "metadata": {"simulation": True, "live_model_evidence": False}})
    state = run(task, output / "repo", output / "repo/repro_outputs", profile, SimulatedDecisions(),
                resume=resume, pause_after_tools=None if resume else 5)
    write_json(output / ("RESUME_SESSION.json" if resume else "PAUSE_SESSION.json"),
               {"pid": os.getpid(), "phase": "resume" if resume else "pause", "status": state["status"]})
    return int(state["status"] != ("success" if resume else "paused"))


def run_lab(output: Path) -> dict:
    output = output.resolve()
    # Exclusive creation protects even an existing empty directory from accidental reuse.
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    repo = output / "repo"
    repo.mkdir()
    for name in SOURCE_FILES:
        shutil.copyfile(FIXTURE / name, repo / name)
    task = lab_task()
    write_json(output / "TASK.json", task)
    # Do not inherit Git overrides that could redirect the temporary index or
    # invoke a user's fsmonitor/filter helpers during this offline exercise.
    lab_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    lab_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    # Separate temporary Git metadata prevents git ls-files from seeing a parent
    # checkout. Execution paths remain stable in the retained evidence directory.
    with tempfile.TemporaryDirectory(prefix="rigorpilot-lab-git-") as temporary:
        metadata = Path(temporary) / "metadata"
        commands = [["git", "init", "--template=", "--separate-git-dir", str(metadata), str(repo)],
                    ["git", "-C", str(repo), "-c", "core.autocrlf=false", "add", "--", *SOURCE_FILES]]
        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True, timeout=15, env=lab_env)
            for phase in ("pause", "resume"):
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--output", str(output), "--worker", phase],
                    capture_output=True, timeout=45, env=lab_env)
                (output / (phase + ".stdout.log")).write_bytes(completed.stdout)
                (output / (phase + ".stderr.log")).write_bytes(completed.stderr)
                if completed.returncode:
                    raise RuntimeError(f"Lab {phase} failed; inspect {output / (phase + '.stderr.log')}")
                if phase == "pause":
                    shutil.copyfile(repo / "repro_outputs/agent_state.json", output / "CHECKPOINT.json")
        finally:
            remove_temporary_git_pointer(repo, metadata)
    state = json.loads((repo / "repro_outputs/agent_state.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((output / "CHECKPOINT.json").read_text(encoding="utf-8"))
    annotated = rebase_inserted_evidence_links((repo / "repro_outputs/ANNOTATED_README.md").read_bytes(), "repro_outputs/", "train_outputs/")
    original = (repo / "README.md").read_bytes()
    checks = {
        "initial_evaluation_failed": checkpoint["results"]["evaluate"]["returncode"] != 0 and "missing asset" in checkpoint["results"]["evaluate"]["stderr"],
        "checkpoint_paused_after_preparation": checkpoint["status"] == "paused" and checkpoint["results"]["prepare"]["verified"],
        "three_real_command_attempts": [a["verified"] for a in state["attempts"]] == [False, True, True],
        "completed_attempts_preserved": state["attempts"][:2] == checkpoint["attempts"],
        "source_unchanged": all((repo / name).read_bytes() == (FIXTURE / name).read_bytes() for name in SOURCE_FILES),
        "readme_round_trip": strip_annotated_bytes(annotated) == original,
        "independent_verification": independent_verification_passed(state, task["required_commands"]),
    }
    (repo / "RIGORPILOT_README.md").write_bytes(annotated)
    report = {"schema_version": "1.0", "status": "success" if all(checks.values()) else "failed", "simulation": True,
        "scope": "Offline engineering lifecycle exercise; scripted model decisions, real subprocesses; NOT model-quality or research-reproduction evidence.",
        "network_requests": 0, "api_calls": 0, "model_tokens": 0, "simulated_model_turns": state["model_calls"],
        "real_command_attempts": len(state["attempts"]), "controller_sessions": 2, "checks": checks,
        "source_readme_sha256": hashlib.sha256(original).hexdigest(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "artifacts": {"readme": "repo/RIGORPILOT_README.md", "checkpoint": "CHECKPOINT.json", "state": "repo/repro_outputs/agent_state.json", "trajectory": "repo/repro_outputs/trajectory.jsonl"}}
    report["retained_bytes_before_report"] = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    write_json(output / "REPORT.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="repro_outputs/harness-lab", help="Fresh directory; existing directories are never overwritten")
    parser.add_argument("--worker", choices=["pause", "resume"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.worker:
            return worker(Path(args.output).resolve(), args.worker == "resume")
        report = run_lab(Path(args.output))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Offline lab stopped: {exc}\n")
    print(json.dumps({"status": report["status"], "simulation": True, "api_calls": 0,
                      "real_command_attempts": report["real_command_attempts"], "report": str(Path(args.output) / "REPORT.json")}, indent=2))
    return int(report["status"] != "success")


if __name__ == "__main__":
    raise SystemExit(main())
