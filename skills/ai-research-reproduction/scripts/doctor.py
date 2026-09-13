#!/usr/bin/env python3
"""Read-only installation/environment checks. No installs, model calls or repo execution."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys


def inspect(skill: Path, repo: Path | None = None, modules: tuple[str, ...] = ()) -> dict:
    checks = []

    def check(name, ok, en, zh):
        checks.append({"check": name, "ok": bool(ok), "next_action": None if ok else {"en": en, "zh": zh}})

    check("python", sys.version_info >= (3, 11), "Launch this script with Python 3.11+.",
          "请使用 Python 3.11+ 启动本脚本。")
    check("git", shutil.which("git") is not None, "Install Git and make it available on PATH.",
          "请安装 Git，并确保 PATH 中可以找到它。")
    check("entrypoint", (skill / "SKILL.md").is_file() and (skill / "scripts/orchestrate_repro.py").is_file(),
          "Reinstall the complete ai-research-reproduction skill directory.", "请重新安装完整的复现主技能目录。")
    try:
        manifest = json.loads((skill / "_bundled/MANIFEST.json").read_text(encoding="utf-8"))
        entries = manifest["files"]
        valid = bool(entries)
        for item in entries:
            target = (skill / item["target"]).resolve()
            if not target.is_relative_to(skill.resolve()):
                raise ValueError("out-of-scope bundle entry")
            data = target.read_bytes().replace(b"\r\n", b"\n")
            valid = valid and hashlib.sha256(data).hexdigest() == item["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    check("bundle", valid, "Reinstall the skill; developers can run sync_reproduction_bundle.py.",
          "请重新安装技能；开发者可运行 sync_reproduction_bundle.py 同步运行时。")
    if repo is not None:
        check("repository", repo.is_dir(), "Select an existing target repository directory.", "请选择已存在的目标仓库目录。")
        check("readme", repo.is_dir() and any(p.is_file() and p.name.lower().startswith("readme") for p in repo.iterdir()),
              "Select the README directory, or inspect the repository's documentation first.",
              "请选择 README 所在目录，或先检查仓库文档。")
    for module in modules:
        # Top-level discovery avoids importing parent packages or executing repo code.
        if not module.isidentifier():
            raise ValueError("require-module accepts top-level Python module names only")
        found = importlib.util.find_spec(module) is not None
        check("module:" + module, found, "Use the intended environment and install only reviewed target dependencies.",
              "请使用预期环境，并仅安装经过确认的目标依赖。")
    return {"ok": all(item["ok"] for item in checks), "python": sys.executable,
            "python_version": sys.version.split()[0], "checks": checks,
            "scope": "read_only_local_preflight_not_task_or_model_acceptance"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--require-module", action="append", default=[])
    args = parser.parse_args()
    try:
        result = inspect(Path(__file__).resolve().parents[1], args.repo, tuple(args.require_module))
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
