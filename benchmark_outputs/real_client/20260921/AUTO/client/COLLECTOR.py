"""One bounded Codex real-client canary for the current RigorPilot skill."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "benchmark_outputs/real_client/20260921"
PRIVATE = PROJECT / "tmp/real_client_private/20260921"
CODEX = Path(r"C:\Users\17745\.vscode\extensions\openai.chatgpt-26.908.40401-win32-x64\bin\windows-x86_64\codex.exe")
PYTHON = Path(r"D:\Anaconda3\python.exe")
SKILL_COMMIT = "9a86470a42468d89729fb08a6064c7deb2af228d"
TARGET_COMMIT = "7bc720e951fe422b8f8814aa5aa1b64121d26b4c"
MODEL = "gpt-6-astra"
MAX_SECONDS = 240
MAX_TOOL_STARTS = 16
START_QUOTA_FLOOR = 70
STOP_QUOTA_FLOOR = 65
QUOTA_GATE_OVERRIDE_BY_USER = True
MAX_PUBLIC_BYTES = 8 * 1024**2

sys.path.insert(0, str(PROJECT / "scripts"))
from check_codex_quota import read_quota  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(token in key.upper() for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL"))
        and (not key.startswith("CODEX_") or key == "CODEX_HOME")
    }
    for key in ("NODE_TLS_REJECT_UNAUTHORIZED", "NPM_CONFIG_STRICT_SSL", "GIT_SSL_NO_VERIFY"):
        env.pop(key, None)
    env.update(
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        RIGORPILOT_LESSONS="0",
        CUDA_VISIBLE_DEVICES="-1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTEST_ADDOPTS="-p no:cacheprovider",
        DO_NOT_TRACK="1",
        CI="1",
        DISABLE_TELEMETRY="1",
        NODE_TLS_REJECT_UNAUTHORIZED="1",
        npm_config_strict_ssl="true",
        GIT_SSL_NO_VERIFY="false",
    )
    prepend = [
        str(PYTHON.parent),
        r"C:\Users\17745\AppData\Local\Programs\PowerShell\7",
        r"C:\Users\17745\AppData\Local\Programs\ripgrep\ripgrep-15.2.0-x86_64-pc-windows-msvc",
    ]
    env["PATH"] = os.pathsep.join(prepend + [env.get("PATH", "")])
    return env


def ensure_fresh() -> None:
    if ROOT.exists():
        raise SystemExit(f"refusing to overwrite existing experiment: {ROOT}")
    ROOT.mkdir(parents=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)


def git(*args: str, cwd: Path = PROJECT, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=safe_env(), check=True,
        capture_output=True, timeout=timeout,
    )


def prepare() -> None:
    ensure_fresh()
    repo = ROOT / "B/repo"
    repo.mkdir(parents=True)
    git("init", "--quiet", cwd=repo)
    git("config", "core.autocrlf", "false", cwd=repo)
    git("remote", "add", "origin", "https://github.com/karpathy/micrograd.git", cwd=repo)
    git("fetch", "--quiet", "--depth", "1", "origin", TARGET_COMMIT, cwd=repo, timeout=120)
    git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=repo)
    actual_commit = git("rev-parse", "HEAD", cwd=repo).stdout.decode().strip()
    if actual_commit.lower() != TARGET_COMMIT.lower():
        raise RuntimeError("micrograd commit mismatch")
    tracked = [item for item in git("ls-files", "-z", cwd=repo).stdout.decode().split("\0") if item]
    write_json(ROOT / "B/BASELINE.json", {
        "commit": TARGET_COMMIT,
        "originals": {name: sha(repo / name) for name in tracked},
    })

    installed = repo / ".agents/skills/ai-research-reproduction"
    names = git("ls-tree", "-r", "--name-only", SKILL_COMMIT, "skills/ai-research-reproduction", cwd=PROJECT).stdout.decode().splitlines()
    if not names:
        raise RuntimeError("current skill commit has no tracked skill files")
    hashes: dict[str, str] = {}
    for source_name in names:
        relative = Path(source_name).relative_to("skills/ai-research-reproduction")
        destination = installed / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = subprocess.check_output(["git", "show", f"{SKILL_COMMIT}:{source_name}"], cwd=PROJECT)
        destination.write_bytes(payload)
        hashes[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
    write_json(ROOT / "INSTALL.json", {
        "ok": True,
        "skill_commit": SKILL_COMMIT,
        "source": "local_git_commit_copy",
        "installed_path": str(installed),
        "files": hashes,
        "scope": "project-local skill copy for real-client behavior; not remote installer acceptance",
    })

    doctor = subprocess.run(
        [str(PYTHON), str(installed / "scripts/doctor.py"), "--repo", str(repo),
         "--require-module", "torch", "--require-module", "pytest"],
        cwd=PROJECT, env=safe_env(), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    (ROOT / "B/doctor.stdout.log").write_text(doctor.stdout, encoding="utf-8")
    (ROOT / "B/doctor.stderr.log").write_text(doctor.stderr, encoding="utf-8")
    if doctor.returncode != 0:
        raise RuntimeError("installed doctor failed")

    shutil.copyfile(Path(__file__), ROOT / "COLLECTOR.py")
    write_json(ROOT / "PREPARE.json", {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "skill_commit": SKILL_COMMIT,
        "target_commit": TARGET_COMMIT,
        "installed_files": len(hashes),
        "python": str(PYTHON),
        "codex": str(CODEX),
        "model": MODEL,
        "reasoning_effort": "high",
        "limits": {"seconds": MAX_SECONDS, "tool_starts": MAX_TOOL_STARTS,
                   "quota_start_floor": START_QUOTA_FLOOR, "quota_stop_floor": STOP_QUOTA_FLOOR},
        "quota_gate_override_by_user": QUOTA_GATE_OVERRIDE_BY_USER,
    })
    print(json.dumps({"prepared": True, "tracked": len(tracked), "installed_files": len(hashes)}))


def prompt_text() -> str:
    return (
        "复现当前仓库已有的自动求导梯度正确性测试。请阅读原始 README 和必要源码，"
        "自行选择并实际执行现有的最小测试，报告实际完成的范围、失败和局限，"
        "将实际命令与完整输出保存在 repro_outputs/。不要修改原始 README、源码、测试或科学含义。"
        "仅使用现有 Python 环境和 CPU；不要下载数据/模型、安装依赖、联网研究或启动训练。"
        "不要访问工作区外的项目、凭据或历史记忆。不要启动其他 Agent。"
        "单个命令最多 30 秒，整项任务最多 240 秒，最多 16 次工具执行；遇到阻塞如实报告并停止。"
        "当前 PATH 中的 Python 已配置好，允许正常生成测试/证据产物。"
        "使用已安装的 ai-research-reproduction 技能完成此任务，并生成与原始 README 同目录的批注副本。"
        "优先使用技能的 plan -> reviewed command-id/fingerprint -> run -> verify 快速路径；任务和证据验收完成后立即向用户交付结果并结束，不要继续做额外实验。"
    )


def auto_prompt_text() -> str:
    return (
        "复现当前仓库已有的自动求导梯度正确性测试。请阅读原始 README 和必要源码，"
        "自行选择并实际执行现有的最小测试，报告实际完成的范围、失败和局限，"
        "将实际命令与完整输出保存在 repro_outputs/，并生成与原始 README 同目录的批注副本。"
        "不要修改原始 README、源码、测试或科学含义。"
        "仅使用现有 Python 环境和 CPU；不要下载数据/模型、安装依赖、联网研究或启动训练。"
        "不要访问工作区外的项目、凭据或历史记忆。不要启动其他 Agent。"
        "单个命令最多 30 秒，整项任务最多 240 秒，最多 16 次工具执行；遇到阻塞如实报告并停止。"
        "当前 PATH 中的 Python 已配置好，允许正常生成测试/证据产物。"
        "任务和证据验收完成后立即向用户交付结果并结束，不要继续做额外实验。"
    )


def prepare_auto() -> None:
    repo = ROOT / "AUTO/repo"
    if repo.exists():
        raise RuntimeError("AUTO repo already exists")
    repo.mkdir(parents=True)
    git("init", "--quiet", cwd=repo)
    git("config", "core.autocrlf", "false", cwd=repo)
    git("remote", "add", "origin", "https://github.com/karpathy/micrograd.git", cwd=repo)
    git("fetch", "--quiet", "--depth", "1", "origin", TARGET_COMMIT, cwd=repo, timeout=120)
    git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=repo)
    actual_commit = git("rev-parse", "HEAD", cwd=repo).stdout.decode().strip()
    if actual_commit.lower() != TARGET_COMMIT.lower():
        raise RuntimeError("AUTO micrograd commit mismatch")
    tracked = [item for item in git("ls-files", "-z", cwd=repo).stdout.decode().split("\0") if item]
    write_json(ROOT / "AUTO/BASELINE.json", {
        "commit": TARGET_COMMIT,
        "originals": {name: sha(repo / name) for name in tracked},
    })
    installed = repo / ".agents/skills/ai-research-reproduction"
    names = git("ls-tree", "-r", "--name-only", SKILL_COMMIT, "skills/ai-research-reproduction", cwd=PROJECT).stdout.decode().splitlines()
    hashes: dict[str, str] = {}
    for source_name in names:
        relative = Path(source_name).relative_to("skills/ai-research-reproduction")
        destination = installed / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = subprocess.check_output(["git", "show", f"{SKILL_COMMIT}:{source_name}"], cwd=PROJECT)
        destination.write_bytes(payload)
        hashes[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
    write_json(ROOT / "AUTO/INSTALL.json", {
        "ok": True,
        "skill_commit": SKILL_COMMIT,
        "source": "local_git_commit_copy",
        "installed_path": str(installed),
        "files": hashes,
        "scope": "project-local skill available for natural-language auto-selection test",
    })
    doctor = subprocess.run(
        [str(PYTHON), str(installed / "scripts/doctor.py"), "--repo", str(repo),
         "--require-module", "torch", "--require-module", "pytest"],
        cwd=PROJECT, env=safe_env(), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    (ROOT / "AUTO/doctor.stdout.log").write_text(doctor.stdout, encoding="utf-8")
    (ROOT / "AUTO/doctor.stderr.log").write_text(doctor.stderr, encoding="utf-8")
    if doctor.returncode != 0:
        raise RuntimeError("AUTO installed doctor failed")
    write_json(ROOT / "AUTO/PREPARE.json", {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "skill_commit": SKILL_COMMIT,
        "target_commit": TARGET_COMMIT,
        "installed_files": len(hashes),
        "prompt_mentions_skill_name": False,
        "model": MODEL,
        "reasoning_effort": "high",
        "limits": {"seconds": MAX_SECONDS, "tool_starts": MAX_TOOL_STARTS,
                   "quota_start_floor": START_QUOTA_FLOOR, "quota_stop_floor": STOP_QUOTA_FLOOR},
    })
    print(json.dumps({"prepared_auto": True, "tracked": len(tracked), "installed_files": len(hashes)}))


def run_auto() -> None:
    repo = ROOT / "AUTO/repo"
    if not repo.is_dir() or not (ROOT / "AUTO/PREPARE.json").is_file():
        raise RuntimeError("run prepare-auto first")
    client = ROOT / "AUTO/client"
    if client.exists():
        raise RuntimeError("AUTO client attempt already exists; no automatic retry")
    client.mkdir(parents=True)
    quota_before = read_quota(str(CODEX), timeout=20)
    if not QUOTA_GATE_OVERRIDE_BY_USER and quota_before["minimum_remaining_percent"] < START_QUOTA_FLOOR:
        raise RuntimeError("quota below configured start floor; AUTO model turn not started")
    write_json(PRIVATE / "AUTO_QUOTA_BEFORE.json", quota_before)
    prompt = auto_prompt_text()
    if "ai-research-reproduction" in prompt or "skill" in prompt.lower():
        raise RuntimeError("AUTO prompt unexpectedly names or hints the skill")
    (client / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    shutil.copyfile(Path(__file__), client / "COLLECTOR.py")
    disabled = disabled_global_skills()
    configs = [
        "model_reasoning_effort=high",
        'forced_login_method="chatgpt"',
        'approval_policy="never"',
        "project_doc_max_bytes=0",
        "memories.use_memories=false",
        "memories.generate_memories=false",
        'web_search="disabled"',
        'windows.sandbox="unelevated"',
        "sandbox_workspace_write.network_access=false",
        "tool_output_token_limit=3000",
        "features.rollout_budget.enabled=true",
        "features.rollout_budget.limit_tokens=150000",
        "features.rollout_budget.reminder_at_remaining_tokens=[30000,10000]",
        "skills.config=[" + ",".join(disabled) + "]",
    ]
    argv = [
        str(CODEX), "exec", "--ignore-user-config", "--strict-config", "--ephemeral", "--json",
        "--sandbox", "workspace-write", "--model", MODEL, "--cd", str(repo),
    ]
    for name in ("plugins", "remote_plugin", "multi_agent", "shell_snapshot", "skill_mcp_dependency_install", "skill_search"):
        argv += ["--disable", name]
    for value in configs:
        argv += ["-c", value]
    argv += ["-"]
    write_json(client / "START.json", {
        "at": datetime.now(timezone.utc).isoformat(),
        "argv": argv,
        "model": MODEL,
        "reasoning_effort": "high",
        "client_version": subprocess.check_output([str(CODEX), "--version"], text=True).strip(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "collector_sha256": sha(Path(__file__)),
        "prompt_mentions_skill_name": False,
        "limits": {"seconds": MAX_SECONDS, "tool_starts": MAX_TOOL_STARTS,
                   "requested_rollout_tokens": 150000,
                   "minimum_reported_before_start": START_QUOTA_FLOOR,
                   "stop_at_reported_remaining": STOP_QUOTA_FLOOR},
        "scope": "fresh_client_natural_language_auto_skill_selection_canary",
        "quota_before_threshold_satisfied": quota_before["minimum_remaining_percent"] >= START_QUOTA_FLOOR,
        "quota_gate_override_by_user": QUOTA_GATE_OVERRIDE_BY_USER,
        "quota_observation_only": QUOTA_GATE_OVERRIDE_BY_USER,
    })
    started = time.monotonic()
    observations: list[dict] = []
    stop_reason = None
    with (client / "TRACE.jsonl").open("wb") as out, (client / "stderr.log").open("wb") as err:
        process = subprocess.Popen(
            argv, cwd=repo, env=safe_env(), stdin=subprocess.PIPE,
            stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert process.stdin is not None
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        next_quota = started + 30
        while process.poll() is None:
            time.sleep(1)
            elapsed = time.monotonic() - started
            trace = (client / "TRACE.jsonl").read_text(encoding="utf-8", errors="replace")
            tool_starts = sum(1 for line in trace.splitlines() if '"type":"item.started"' in line and
                              any(token in line for token in ('"command_execution"', '"tool_call"')))
            if elapsed > MAX_SECONDS:
                stop_reason = "wall_timeout"
            elif tool_starts > MAX_TOOL_STARTS:
                stop_reason = "tool_limit"
            elif len(trace.encode("utf-8")) > 4 * 1024**2:
                stop_reason = "trace_limit"
            if time.monotonic() >= next_quota:
                try:
                    measured = read_quota(str(CODEX), timeout=10)
                    observations.append({"seconds": round(elapsed, 1), "ok": True,
                                         "minimum_remaining_percent": measured["minimum_remaining_percent"]})
                    if not QUOTA_GATE_OVERRIDE_BY_USER and measured["minimum_remaining_percent"] <= STOP_QUOTA_FLOOR:
                        stop_reason = "quota_buffer_stop"
                except Exception:
                    observations.append({"seconds": round(elapsed, 1), "ok": False})
                    if not QUOTA_GATE_OVERRIDE_BY_USER:
                        stop_reason = "quota_unknown_stop"
                next_quota = time.monotonic() + 30
            if stop_reason:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
                process.wait(timeout=15)
                break
        returncode = process.wait(timeout=10)
    trace_text = (client / "TRACE.jsonl").read_text(encoding="utf-8", errors="replace")
    rows = [json.loads(line) for line in trace_text.splitlines() if line.strip().startswith("{")]
    types = [row.get("type") for row in rows if isinstance(row, dict)]
    tool_starts = sum(1 for line in trace_text.splitlines() if '"type":"item.started"' in line and
                      any(token in line for token in ('"command_execution"', '"tool_call"')))
    lower_trace = trace_text.lower()
    auto_evidence = {
        "mentions_skill_slug": "ai-research-reproduction" in lower_trace,
        "mentions_orchestrator": "orchestrate_repro.py" in lower_trace,
        "mentions_project_skill_path": ".agents/skills/ai-research-reproduction" in lower_trace.replace("\\\\", "/").replace("\\", "/"),
    }
    try:
        quota_after = read_quota(str(CODEX), timeout=20)
        write_json(PRIVATE / "AUTO_QUOTA_AFTER.json", quota_after)
    except Exception:
        quota_after = None
    write_json(PRIVATE / "AUTO_QUOTA_OBSERVATIONS.json", {"observations": observations})
    write_json(client / "END.public.json", {
        "returncode": returncode,
        "stop_reason": stop_reason,
        "seconds": round(time.monotonic() - started, 3),
        "turn_completed": "turn.completed" in types,
        "turn_failed": "turn.failed" in types,
        "tool_starts": tool_starts,
        "trace_sha256": sha(client / "TRACE.jsonl"),
        "auto_loading_evidence": auto_evidence,
        "quota_checks_count": 1 + len(observations) + (1 if quota_after else 0),
        "quota_floor_breached": any(item.get("minimum_remaining_percent", 101) <= STOP_QUOTA_FLOOR for item in observations),
        "quota_gate_override_by_user": QUOTA_GATE_OVERRIDE_BY_USER,
        "quota_observation_only": QUOTA_GATE_OVERRIDE_BY_USER,
        "raw_quota_values_published": False,
    })
    print(json.dumps({"returncode": returncode, "stop_reason": stop_reason,
                      "turn_completed": "turn.completed" in types, "tool_starts": tool_starts,
                      "auto_loading_evidence": auto_evidence}))


def verify_auto() -> None:
    repo = ROOT / "AUTO/repo"
    client = ROOT / "AUTO/client"
    output = repo / "repro_outputs"
    installed = repo / ".agents/skills/ai-research-reproduction"
    end = json.loads((client / "END.public.json").read_text(encoding="utf-8"))
    grader = ROOT / "AUTO/EVIDENCE_CHECK.json"
    grade = subprocess.run(
        [str(PYTHON), str(PROJECT / "benchmarks/check_first_use.py"),
         "--baseline", str(ROOT / "AUTO/BASELINE.json"), "--repo", str(repo),
         "--output-dir", str(output), "--expected-stdout", "2 passed", "--report", str(grader)],
        cwd=PROJECT, env=safe_env(), capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    (ROOT / "AUTO/grader.stdout.log").write_text(grade.stdout, encoding="utf-8")
    (ROOT / "AUTO/grader.stderr.log").write_text(grade.stderr, encoding="utf-8")
    grader_payload = json.loads(grader.read_text(encoding="utf-8")) if grader.is_file() else {"ok": False}
    verify_process = subprocess.run(
        [str(PYTHON), str(installed / "scripts/orchestrate_repro.py"), "--repo", str(repo),
         "--verify-output", "--agent-output"],
        cwd=repo, env=safe_env(), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    verify_payload = json.loads(verify_process.stdout) if verify_process.stdout.strip().startswith("{") else {"evidence_valid": False}
    write_json(ROOT / "AUTO/VERIFY.json", verify_payload)
    (ROOT / "AUTO/verify.stderr.log").write_text(verify_process.stderr, encoding="utf-8")
    status_path = output / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    source_integrity = status.get("source_integrity") or {}
    auto_evidence = end.get("auto_loading_evidence") or {}
    auto_loaded = bool(auto_evidence.get("mentions_skill_slug") and auto_evidence.get("mentions_orchestrator"))
    checks = {
        "prompt_did_not_name_skill": json.loads((client / "START.json").read_text(encoding="utf-8"))["prompt_mentions_skill_name"] is False,
        "client_returncode_zero": end.get("returncode") == 0,
        "client_completed": end.get("turn_completed") is True and not end.get("stop_reason"),
        "auto_loading_trace_evidence": auto_loaded,
        "task_status_success": status.get("status") == "success",
        "runtime_success": (status.get("runtime") or {}).get("status") == "success",
        "source_integrity_unchanged": source_integrity.get("unchanged") is True,
        "independent_grader_passed": grade.returncode == 0 and grader_payload.get("ok") is True,
        "verify_output_passed": verify_process.returncode == 0 and verify_payload.get("evidence_valid") is True,
        "source_adjacent_readme_present": (repo / "RIGORPILOT_README.md").is_file(),
    }
    overall = all(checks.values())
    report = {
        "schema_version": "1.0",
        "scope": "fresh_client_natural_language_auto_skill_selection_canary",
        "date": "2026-09-21",
        "skill_commit": SKILL_COMMIT,
        "upstream_commit": TARGET_COMMIT,
        "model_requested": MODEL,
        "reasoning_effort": "high",
        "client_version": json.loads((client / "START.json").read_text(encoding="utf-8"))["client_version"],
        "checks": checks,
        "overall_pass": overall,
        "stop_reason": end.get("stop_reason"),
        "client_seconds": end.get("seconds"),
        "tool_starts": end.get("tool_starts"),
        "auto_loading_evidence": auto_evidence,
        "selection_source": status.get("selection_source"),
        "selected_command_id": status.get("documented_command_id"),
        "documented_command": status.get("documented_command"),
        "model_usage": None,
        "model_cost": None,
        "model_uplift": None,
        "limits": [
            "Prompt contains only the task/bounds and does not name the skill or its path.",
            "Project-local skill is installed; global skills and memory are disabled.",
            "Auto-loading requires trace evidence referencing the skill and reproduction orchestrator, not task success alone.",
            "One model attempt only; no automatic retry.",
            "User explicitly overrode the historical quota start/stop percentage gates for this one canary; quota readings are observation-only and not a billing guarantee.",
        ],
        "protocol_deviations": [
            "quota_start_floor and quota_stop_floor were observation-only for this run by explicit user authorization"
        ],
    }
    write_json(ROOT / "AUTO_REPORT.json", report)
    shutil.rmtree(repo / ".git", ignore_errors=True)
    shutil.rmtree(repo / ".agents", ignore_errors=True)
    shutil.rmtree(repo / ".pytest_cache", ignore_errors=True)
    size = sum(path.stat().st_size for path in ROOT.rglob("*") if path.is_file())
    if size > MAX_PUBLIC_BYTES:
        raise RuntimeError(f"public canary evidence exceeds {MAX_PUBLIC_BYTES} bytes: {size}")
    print(json.dumps({"overall_pass": overall, "checks": checks, "public_bytes": size}, ensure_ascii=False))
    raise SystemExit(0 if overall else 1)


def disabled_global_skills() -> list[str]:
    values: list[str] = []
    for directory in (Path(r"C:\Users\17745\.codex\skills"), Path(r"C:\Users\17745\.agents\skills")):
        if not directory.exists():
            continue
        for path in directory.rglob("SKILL.md"):
            values.append('{path=' + json.dumps(path.parent.as_posix()) + ',enabled=false}')
    return values


def run_once() -> None:
    repo = ROOT / "B/repo"
    if not repo.is_dir() or not (ROOT / "PREPARE.json").is_file():
        raise RuntimeError("run prepare first")
    client = ROOT / "B/client"
    if client.exists():
        raise RuntimeError("client attempt already exists; no automatic retry")
    client.mkdir(parents=True)

    quota_before = read_quota(str(CODEX), timeout=20)
    if quota_before["minimum_remaining_percent"] < START_QUOTA_FLOOR:
        raise RuntimeError("quota below configured start floor; no model turn started")
    write_json(PRIVATE / "QUOTA_BEFORE.json", quota_before)

    prompt = prompt_text()
    (client / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    disabled = disabled_global_skills()
    configs = [
        "model_reasoning_effort=high",
        'forced_login_method="chatgpt"',
        'approval_policy="never"',
        "project_doc_max_bytes=0",
        "memories.use_memories=false",
        "memories.generate_memories=false",
        'web_search="disabled"',
        'windows.sandbox="unelevated"',
        "sandbox_workspace_write.network_access=false",
        "tool_output_token_limit=3000",
        "features.rollout_budget.enabled=true",
        "features.rollout_budget.limit_tokens=150000",
        "features.rollout_budget.reminder_at_remaining_tokens=[30000,10000]",
        "skills.config=[" + ",".join(disabled) + "]",
    ]
    argv = [
        str(CODEX), "exec", "--ignore-user-config", "--strict-config", "--ephemeral", "--json",
        "--sandbox", "workspace-write", "--model", MODEL, "--cd", str(repo),
    ]
    for name in ("plugins", "remote_plugin", "multi_agent", "shell_snapshot", "skill_mcp_dependency_install", "skill_search"):
        argv += ["--disable", name]
    for value in configs:
        argv += ["-c", value]
    argv += ["-"]
    write_json(client / "START.json", {
        "at": datetime.now(timezone.utc).isoformat(),
        "argv": argv,
        "model": MODEL,
        "reasoning_effort": "high",
        "client_version": subprocess.check_output([str(CODEX), "--version"], text=True).strip(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "collector_sha256": sha(Path(__file__)),
        "limits": {"seconds": MAX_SECONDS, "tool_starts": MAX_TOOL_STARTS,
                   "requested_rollout_tokens": 150000,
                   "minimum_reported_before_start": START_QUOTA_FLOOR,
                   "stop_at_reported_remaining": STOP_QUOTA_FLOOR},
        "scope": "explicit_named_skill_real_client_canary_not_model_uplift_or_auto_discovery",
        "quota_before_threshold_satisfied": True,
    })

    started = time.monotonic()
    observations: list[dict] = []
    stop_reason = None
    with (client / "TRACE.jsonl").open("wb") as out, (client / "stderr.log").open("wb") as err:
        process = subprocess.Popen(
            argv, cwd=repo, env=safe_env(), stdin=subprocess.PIPE,
            stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert process.stdin is not None
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        next_quota = started + 30
        while process.poll() is None:
            time.sleep(1)
            elapsed = time.monotonic() - started
            trace = (client / "TRACE.jsonl").read_text(encoding="utf-8", errors="replace")
            tool_starts = sum(
                1 for line in trace.splitlines()
                if '"type":"item.started"' in line and any(token in line for token in ('"command_execution"', '"tool_call"'))
            )
            if elapsed > MAX_SECONDS:
                stop_reason = "wall_timeout"
            elif tool_starts > MAX_TOOL_STARTS:
                stop_reason = "tool_limit"
            elif len(trace.encode("utf-8")) > 4 * 1024**2:
                stop_reason = "trace_limit"
            if time.monotonic() >= next_quota:
                try:
                    measured = read_quota(str(CODEX), timeout=10)
                    observations.append({"seconds": round(elapsed, 1), "ok": True,
                                         "minimum_remaining_percent": measured["minimum_remaining_percent"]})
                    if measured["minimum_remaining_percent"] <= STOP_QUOTA_FLOOR:
                        stop_reason = "quota_buffer_stop"
                except Exception:
                    observations.append({"seconds": round(elapsed, 1), "ok": False})
                    stop_reason = "quota_unknown_stop"
                next_quota = time.monotonic() + 30
            if stop_reason:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
                process.wait(timeout=15)
                break
        returncode = process.wait(timeout=10)

    trace_text = (client / "TRACE.jsonl").read_text(encoding="utf-8", errors="replace")
    lines = [json.loads(line) for line in trace_text.splitlines() if line.strip().startswith("{")]
    types = [item.get("type") for item in lines if isinstance(item, dict)]
    tool_starts = sum(
        1 for line in trace_text.splitlines()
        if '"type":"item.started"' in line and any(token in line for token in ('"command_execution"', '"tool_call"'))
    )
    quota_after = None
    try:
        quota_after = read_quota(str(CODEX), timeout=20)
        write_json(PRIVATE / "QUOTA_AFTER.json", quota_after)
    except Exception:
        pass
    write_json(PRIVATE / "QUOTA_OBSERVATIONS.json", {"observations": observations})
    write_json(client / "END.public.json", {
        "returncode": returncode,
        "stop_reason": stop_reason,
        "seconds": round(time.monotonic() - started, 3),
        "turn_completed": "turn.completed" in types,
        "turn_failed": "turn.failed" in types,
        "tool_starts": tool_starts,
        "trace_sha256": sha(client / "TRACE.jsonl"),
        "quota_checks_count": 1 + len(observations) + (1 if quota_after else 0),
        "quota_floor_breached": any(item.get("minimum_remaining_percent", 101) <= STOP_QUOTA_FLOOR for item in observations),
        "raw_quota_values_published": False,
    })
    print(json.dumps({"returncode": returncode, "stop_reason": stop_reason,
                      "turn_completed": "turn.completed" in types, "tool_starts": tool_starts}))


def verify() -> None:
    repo = ROOT / "B/repo"
    client = ROOT / "B/client"
    output = repo / "repro_outputs"
    installed = repo / ".agents/skills/ai-research-reproduction"
    end = json.loads((client / "END.public.json").read_text(encoding="utf-8"))
    grader = ROOT / "B/EVIDENCE_CHECK.json"
    grade = subprocess.run(
        [str(PYTHON), str(PROJECT / "benchmarks/check_first_use.py"),
         "--baseline", str(ROOT / "B/BASELINE.json"), "--repo", str(repo),
         "--output-dir", str(output), "--expected-stdout", "2 passed", "--report", str(grader)],
        cwd=PROJECT, env=safe_env(), capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    (ROOT / "B/grader.stdout.log").write_text(grade.stdout, encoding="utf-8")
    (ROOT / "B/grader.stderr.log").write_text(grade.stderr, encoding="utf-8")
    grader_payload = json.loads(grader.read_text(encoding="utf-8")) if grader.is_file() else {"ok": False}

    verify_path = ROOT / "B/VERIFY.json"
    verify_process = subprocess.run(
        [str(PYTHON), str(installed / "scripts/orchestrate_repro.py"), "--repo", str(repo),
         "--verify-output", "--agent-output"],
        cwd=repo, env=safe_env(), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if verify_process.stdout.strip().startswith("{"):
        verify_payload = json.loads(verify_process.stdout)
    else:
        verify_payload = {"evidence_valid": False, "raw_stdout": verify_process.stdout[-2000:]}
    write_json(verify_path, verify_payload)
    (ROOT / "B/verify.stderr.log").write_text(verify_process.stderr, encoding="utf-8")

    status_path = output / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    source_integrity = status.get("source_integrity") or {}
    checks = {
        "client_returncode_zero": end.get("returncode") == 0,
        "client_completed": end.get("turn_completed") is True and not end.get("stop_reason"),
        "task_status_success": status.get("status") == "success",
        "runtime_success": (status.get("runtime") or {}).get("status") == "success",
        "source_integrity_unchanged": source_integrity.get("unchanged") is True,
        "independent_grader_passed": grade.returncode == 0 and grader_payload.get("ok") is True,
        "verify_output_passed": verify_process.returncode == 0 and verify_payload.get("evidence_valid") is True,
        "source_adjacent_readme_present": (repo / "RIGORPILOT_README.md").is_file(),
    }
    overall = all(checks.values())
    report = {
        "schema_version": "1.0",
        "scope": "one_real_client_fast_path_canary_not_model_uplift",
        "date": "2026-09-20",
        "skill_commit": SKILL_COMMIT,
        "upstream_commit": TARGET_COMMIT,
        "model_requested": MODEL,
        "reasoning_effort": "high",
        "client_version": json.loads((client / "START.json").read_text(encoding="utf-8"))["client_version"],
        "checks": checks,
        "overall_pass": overall,
        "stop_reason": end.get("stop_reason"),
        "client_seconds": end.get("seconds"),
        "tool_starts": end.get("tool_starts"),
        "task_error": status.get("error"),
        "selection_source": status.get("selection_source"),
        "selected_command_id": status.get("documented_command_id"),
        "documented_command": status.get("documented_command"),
        "result_match": (status.get("result_match") or {}).get("status"),
        "model_usage": None,
        "model_cost": None,
        "model_uplift": None,
        "baseline_A": "not_run_until_canary_passes",
        "quota": {"checked_without_publishing_values": True, "hard_budget_guarantee": False},
        "limits": [
            "Explicit named-skill invocation, not automatic skill discovery.",
            "Existing Python/PyTorch/pytest environment; no dependency cold start.",
            "Quota percentages are private and not published; they are not token accounting or a billing cap.",
            "One model attempt only; no automatic retry after provider/client failure or timeout.",
            "Command success alone does not satisfy this canary without normal client completion and independent evidence verification.",
        ],
    }
    write_json(ROOT / "REPORT.json", report)

    # Remove duplicate install and Git metadata from the publication snapshot only after all Git-backed checks finish.
    shutil.rmtree(repo / ".git", ignore_errors=True)
    shutil.rmtree(repo / ".agents", ignore_errors=True)
    shutil.rmtree(repo / ".pytest_cache", ignore_errors=True)
    size = sum(path.stat().st_size for path in ROOT.rglob("*") if path.is_file())
    if size > MAX_PUBLIC_BYTES:
        raise RuntimeError(f"public canary evidence exceeds {MAX_PUBLIC_BYTES} bytes: {size}")
    print(json.dumps({"overall_pass": overall, "checks": checks, "public_bytes": size}, ensure_ascii=False))
    raise SystemExit(0 if overall else 1)


if __name__ == "__main__":
    actions = {
        "prepare": prepare,
        "run": run_once,
        "verify": verify,
        "prepare-auto": prepare_auto,
        "run-auto": run_auto,
        "verify-auto": verify_auto,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit("usage: python tmp/run_real_client_canary_20260920.py " + "|".join(actions))
    actions[sys.argv[1]]()
