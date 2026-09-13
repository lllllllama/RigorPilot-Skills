"""One bounded real-client acceptance experiment; not a general model backend."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from check_codex_quota import read_quota
CODEX = "C:/Users/17745/.vscode/extensions/openai.chatgpt-26.908.31748-win32-x64/bin/windows-x86_64/codex.exe"
PYTHON = "D:/Anaconda3/python.exe"
SKILL_COMMIT = "3f4ff415bc678fc83db673288d33b1a8fb5458aa"
TARGET_COMMIT = "7bc720e951fe422b8f8814aa5aa1b64121d26b4c"
NODE_VERSION = "22.20.0"
SKILLS_VERSION = "1.5.26"
MAX_BYTES = 256 * 1024**2


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate():
    size = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file() and not p.is_symlink())
    if size > MAX_BYTES or shutil.disk_usage(ROOT).free < 1024**3:
        raise ValueError("disk gate exceeded; evidence retained")
    return size


def environment():
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in
           ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL")) and
           (not k.startswith("CODEX_") or k == "CODEX_HOME")}
    for key in list(env):
        if key.upper() in ("NODE_TLS_REJECT_UNAUTHORIZED", "NPM_CONFIG_STRICT_SSL", "GIT_SSL_NO_VERIFY"):
            del env[key]
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", RIGORPILOT_LESSONS="0",
               CUDA_VISIBLE_DEVICES="-1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTEST_ADDOPTS="-p no:cacheprovider", DO_NOT_TRACK="1", CI="1",
               DISABLE_TELEMETRY="1", NODE_TLS_REJECT_UNAUTHORIZED="1", npm_config_strict_ssl="true",
               GIT_SSL_NO_VERIFY="false", npm_config_cache=str(ROOT / "npm-cache-verified"))
    paths = [str(ROOT / f"node-v{NODE_VERSION}-win-x64"), str(Path(PYTHON).parent),
             "C:/Users/17745/AppData/Local/Programs/PowerShell/7",
             "C:/Users/17745/AppData/Local/Programs/ripgrep/ripgrep-15.2.0-x86_64-pc-windows-msvc"]
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    return env


def capture(label, argv, cwd, timeout=90):
    directory = ROOT / "setup" / label
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with (directory / "stdout.log").open("wb") as out, (directory / "stderr.log").open("wb") as err:
        result = subprocess.run(argv, cwd=cwd, env=environment(), stdout=out, stderr=err,
                                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    write(directory / "RECEIPT.json", {"argv": argv, "cwd": str(cwd), "returncode": result.returncode,
          "seconds": round(time.monotonic() - started, 3)})
    gate()
    if result.returncode:
        raise ValueError(f"{label} failed; logs retained")


def prepare():
    gate()
    archive = ROOT / f"node-v{NODE_VERSION}-win-x64.zip"
    base = f"https://nodejs.org/dist/v{NODE_VERSION}/"
    checksums = urllib.request.urlopen(base + "SHASUMS256.txt", timeout=30).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == archive.name)
    with urllib.request.urlopen(base + archive.name, timeout=45) as response, archive.open("xb") as out:
        total = 0
        while block := response.read(1024**2):
            total += len(block)
            if total > 40 * 1024**2:
                raise ValueError("Node archive too large")
            out.write(block)
    if digest(archive) != expected:
        raise ValueError("Node archive checksum mismatch")
    with zipfile.ZipFile(archive) as zipped:
        if sum(info.file_size for info in zipped.infolist()) > 120 * 1024**2:
            raise ValueError("Node extracted size exceeds budget")
        for info in zipped.infolist():
            if not (ROOT / info.filename).resolve().is_relative_to(ROOT):
                raise ValueError("Unsafe archive path")
        zipped.extractall(ROOT)
    write(ROOT / "NODE.json", {"version": NODE_VERSION, "source": base + archive.name,
          "sha256": expected, "bytes": archive.stat().st_size, "installation": "temporary_portable_no_global_change"})
    for arm in ("B", "A"):
        repo = ROOT / arm / "repo"
        repo.mkdir(parents=True, exist_ok=False)
        capture(arm + "-git-init", ["git", "init", "--quiet", str(repo)], ROOT)
        capture(arm + "-git-line-endings", ["git", "config", "core.autocrlf", "false"], repo)
        capture(arm + "-git-remote", ["git", "remote", "add", "origin", "https://github.com/karpathy/micrograd.git"], repo)
        capture(arm + "-git-fetch", ["git", "fetch", "--quiet", "--depth", "1", "origin", TARGET_COMMIT], repo)
        capture(arm + "-git-checkout", ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], repo)
        originals = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
        write(ROOT / arm / "BASELINE.json", {"commit": TARGET_COMMIT, "originals": {
              name: digest(repo / name) for name in originals if name}})
    node = ROOT / f"node-v{NODE_VERSION}-win-x64/node.exe"
    npm = ROOT / f"node-v{NODE_VERSION}-win-x64/node_modules/npm/bin/npx-cli.js"
    capture("public-npx-install", [str(node), str(npm), "--yes", f"skills@{SKILLS_VERSION}", "add",
            f"https://github.com/lllllllama/RigorPilot-Skills/tree/{SKILL_COMMIT}",
            "--skill", "ai-research-reproduction", "--agent", "codex", "--copy", "--yes"], ROOT / "B/repo", 120)
    installed = ROOT / "B/repo/.agents/skills/ai-research-reproduction"
    if not (installed / "SKILL.md").is_file():
        raise ValueError("Installed skill not at expected project discovery path")
    files = {}
    for path in installed.rglob("*"):
        if path.is_symlink():
            raise ValueError("Installed skill contains symlink")
        if path.is_file():
            relative = path.relative_to(installed).as_posix()
            source = subprocess.check_output(["git", "show", f"{SKILL_COMMIT}:skills/ai-research-reproduction/{relative}"], cwd=PROJECT)
            if source.replace(b"\r\n", b"\n") != path.read_bytes().replace(b"\r\n", b"\n"):
                raise ValueError("Remote installation differs from pinned skill")
            files[relative] = digest(path)
    write(ROOT / "INSTALL.json", {"ok": True, "skill_commit": SKILL_COMMIT, "installer": f"skills@{SKILLS_VERSION}",
          "source": "public_github_commit", "installed_path": str(installed), "files": files,
          "comparison": "LF-normalized content against Git commit; exact installed hashes retained"})
    capture("installed-doctor", [PYTHON, str(installed / "scripts/doctor.py"), "--repo", str(ROOT / "B/repo"),
            "--require-module", "torch", "--require-module", "pytest"], ROOT)
    print(json.dumps({"prepared": True, "bytes": gate(), "installed_files": len(files)}), flush=True)


def prepare_secure():
    """Retain the inherited-TLS-disabled attempt; install afresh with verification."""
    repo = ROOT / "B/repo"
    if repo.exists():
        raise ValueError("Move and preserve the earlier setup before preparing secure B")
    repo.mkdir(parents=True)
    for name, argv in (
        ("init", ["git", "init", "--quiet"]),
        ("line-endings", ["git", "config", "core.autocrlf", "false"]),
        ("remote", ["git", "remote", "add", "origin", "https://github.com/karpathy/micrograd.git"]),
        ("fetch", ["git", "fetch", "--quiet", "--depth", "1", "origin", TARGET_COMMIT]),
        ("checkout", ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"]),
    ):
        capture("B-secure-git-" + name, argv, repo)
    originals = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    write(ROOT / "B/BASELINE.json", {"commit": TARGET_COMMIT, "originals": {name: digest(repo / name) for name in originals if name}})
    node = ROOT / f"node-v{NODE_VERSION}-win-x64/node.exe"
    npm = ROOT / f"node-v{NODE_VERSION}-win-x64/node_modules/npm/bin/npx-cli.js"
    capture("public-npx-install-verified", [str(node), str(npm), "--yes", f"skills@{SKILLS_VERSION}", "add",
            f"https://github.com/lllllllama/RigorPilot-Skills/tree/{SKILL_COMMIT}",
            "--skill", "ai-research-reproduction", "--agent", "codex", "--copy", "--yes"], repo, 120)
    installed = repo / ".agents/skills/ai-research-reproduction"
    files = {}
    for path in installed.rglob("*"):
        if path.is_file():
            relative = path.relative_to(installed).as_posix()
            source = subprocess.check_output(["git", "show", f"{SKILL_COMMIT}:skills/ai-research-reproduction/{relative}"], cwd=PROJECT)
            if source.replace(b"\r\n", b"\n") != path.read_bytes().replace(b"\r\n", b"\n"):
                raise ValueError("Remote skill differs from pinned source")
            files[relative] = digest(path)
    if len(files) != 46:
        raise ValueError("Unexpected installed skill file set")
    write(ROOT / "INSTALL-secure.json", {"ok": True, "skill_commit": SKILL_COMMIT, "installer": f"skills@{SKILLS_VERSION}",
          "source": "public_github_commit", "installed_path": str(installed), "files": files,
          "node_tls_reject_unauthorized": "1", "npm_strict_ssl": "true", "git_ssl_no_verify": "false"})
    capture("installed-doctor-verified", [PYTHON, str(installed / "scripts/doctor.py"), "--repo", str(repo),
            "--require-module", "torch", "--require-module", "pytest"], ROOT)
    print(json.dumps({"prepared_secure": True, "bytes": gate(), "installed_files": len(files)}), flush=True)


def run(arm):
    destination = ROOT / arm / "client"
    if destination.exists():
        raise ValueError("A client attempt already exists; no automatic retry")
    quota = read_quota(CODEX)
    if quota["minimum_remaining_percent"] < 70:
        raise ValueError("Refusing new trial below 70% reported quota; 60% is not a hard reservation")
    if arm == "A":
        verdict = json.loads((ROOT / "B/INDEPENDENT.json").read_text(encoding="utf-8"))
        if not verdict["ok"]:
            raise ValueError("B must independently pass before spending on A")
    destination.mkdir(parents=True)
    shutil.copyfile(Path(__file__), destination / "COLLECTOR.py")
    write(destination / "QUOTA_BEFORE.json", quota)
    common = (
        "复现当前仓库已有的自动求导梯度正确性测试。请阅读原始 README 和必要源码，"
        "自行选择并实际执行现有的最小测试，报告实际完成的范围、失败和局限，"
        "将实际命令与完整输出保存在 repro_outputs/。不要修改原始 README、源码、测试或科学含义。"
        "仅使用现有 Python 环境和 CPU；不要下载数据/模型、安装依赖、联网研究或启动训练。"
        "不要访问工作区外的项目、凭据或历史记忆。不要启动其他 Agent。"
        "单个命令最多 30 秒，整项任务最多 240 秒，最多 16 次工具执行；遇到阻塞如实报告并停止。"
        "当前 PATH 中的 Python 已配置好，允许正常生成测试/证据产物。"
    )
    prompt = common + ("使用已安装的 ai-research-reproduction 技能完成此任务，并生成与原始 README 同目录的批注副本。" if arm == "B" else "")
    (destination / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    disabled = []
    for directory in (Path("C:/Users/17745/.codex/skills"), Path("C:/Users/17745/.agents/skills")):
        for path in directory.rglob("SKILL.md"):
            disabled.append('{path=' + json.dumps(path.parent.as_posix()) + ',enabled=false}')
    configs = ["model_reasoning_effort=high", 'forced_login_method="chatgpt"', 'approval_policy="never"',
               "project_doc_max_bytes=0", "memories.use_memories=false", "memories.generate_memories=false",
               'web_search="disabled"', 'windows.sandbox="unelevated"',
               "sandbox_workspace_write.network_access=false", "tool_output_token_limit=3000",
               "features.rollout_budget.enabled=true", "features.rollout_budget.limit_tokens=150000",
               "features.rollout_budget.reminder_at_remaining_tokens=[30000,10000]",
               "skills.config=[" + ",".join(disabled) + "]"]
    argv = [CODEX, "exec", "--ignore-user-config", "--strict-config", "--ephemeral", "--json",
            "--sandbox", "workspace-write", "--model", "gpt-6-astra", "--cd", str(ROOT / arm / "repo")]
    for name in ("plugins", "remote_plugin", "multi_agent", "shell_snapshot", "skill_mcp_dependency_install", "skill_search"):
        argv += ["--disable", name]
    for value in configs:
        argv += ["-c", value]
    argv += ["-"]
    write(destination / "START.json", {"at": datetime.now(timezone.utc).isoformat(), "arm": arm,
          "argv": argv, "model": "gpt-6-astra", "reasoning_effort": "high", "prompt_sha256": digest(destination / "PROMPT.txt"),
          "operator_sha256": digest(Path(__file__)), "limits": {"seconds": 240, "tool_starts": 16, "requested_rollout_tokens": 150000,
          "minimum_reported_before_start": 70, "stop_at_reported_remaining": 65},
          "scope": "explicit_named_skill_first_use_not_automatic_discovery_or_prompt_only_ablation"})
    started = time.monotonic()
    with (destination / "TRACE.jsonl").open("wb") as out, (destination / "stderr.log").open("wb") as err:
        process = subprocess.Popen(argv, cwd=ROOT / arm / "repo", env=environment(), stdin=subprocess.PIPE,
                                   stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        reason = None
        next_quota = started + 30
        observations = []
        while process.poll() is None:
            time.sleep(1)
            elapsed = time.monotonic() - started
            trace = (destination / "TRACE.jsonl").read_text(encoding="utf-8", errors="replace")
            tool_starts = sum(1 for line in trace.splitlines() if '"type":"item.started"' in line and
                              any(word in line for word in ('"command_execution"', '"tool_call"')))
            if elapsed > 240:
                reason = "wall_timeout"
            elif tool_starts > 16:
                reason = "tool_limit"
            elif len(trace.encode("utf-8")) > 4 * 1024**2:
                reason = "trace_limit"
            if time.monotonic() >= next_quota:
                try:
                    measured = read_quota(CODEX, timeout=10)
                    observations.append({"seconds": round(elapsed, 1), **measured})
                    if measured["minimum_remaining_percent"] <= 65:
                        reason = "quota_buffer_stop"
                except Exception:
                    reason = "quota_unknown_stop"
                next_quota = time.monotonic() + 30
            if reason:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
                process.wait(timeout=15)
                break
        returncode = process.wait(timeout=10)
    write(destination / "END.json", {"returncode": returncode, "stop_reason": reason,
          "seconds": round(time.monotonic() - started, 3), "quota_observations": observations,
          "trace_sha256": digest(destination / "TRACE.jsonl"), "extra_model_requests_unknown_until_trace_review": True})
    try:
        write(destination / "QUOTA_AFTER.json", read_quota(CODEX))
    except Exception:
        write(destination / "QUOTA_AFTER.json", {"ok": False})
    print(json.dumps({"arm": arm, "returncode": returncode, "stop_reason": reason, "bytes": gate()}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "prepare-secure", "run"))
    parser.add_argument("--arm", choices=("A", "B"), default="B")
    args = parser.parse_args()
    {"prepare": prepare, "prepare-secure": prepare_secure, "run": lambda: run(args.arm)}[args.action]()
