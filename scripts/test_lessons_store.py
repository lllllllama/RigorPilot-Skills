#!/usr/bin/env python3
"""Regression checks for the continuous-learning lesson store."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def load_module(repo_root: Path):
    module_path = repo_root / "shared" / "scripts" / "lessons_store.py"
    spec = importlib.util.spec_from_file_location("lessons_store", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    temp_root = Path(tempfile.mkdtemp(prefix="codex-lessons-store-", dir=repo_root))
    checks = 0
    old_home = os.environ.get("RIGORPILOT_HOME")
    old_toggle = os.environ.get("RIGORPILOT_LESSONS")
    try:
        os.environ["RIGORPILOT_HOME"] = str(temp_root / "rigorpilot-home")
        os.environ.pop("RIGORPILOT_LESSONS", None)
        store = load_module(repo_root)

        path = store.record_lesson(
            kind="failure-fix",
            skill="ai-research-reproduction",
            summary="[partial] checkpoint missing",
            detail="python eval.py",
            fingerprint="demo@abc123",
        )
        if path is None or not path.exists():
            raise AssertionError("lesson store did not persist a valid lesson")
        checks += 1

        store.record_lesson(kind="failure-fix", skill="ai-research-reproduction", summary="[partial] checkpoint missing")
        if len(store.load_lessons()) != 1:
            raise AssertionError("duplicate lesson was not deduplicated")
        checks += 1

        secret = store.record_lesson(kind="preference", skill="x", summary="api_key=sk-12345 leaked")
        if secret is not None or len(store.load_lessons()) != 1:
            raise AssertionError("secret-looking lesson was not refused")
        checks += 1

        store.record_lesson(kind="preference", skill="core", summary="Prefer zh reports")
        overlay = store.summarize()
        text = overlay.read_text(encoding="utf-8")
        if "Prefer zh reports" not in text or "checkpoint missing" not in text:
            raise AssertionError("overlay summary lost recorded lessons")
        if "repository wins" not in text:
            raise AssertionError("overlay lost the core-wins disclaimer")
        checks += 2

        os.environ["RIGORPILOT_LESSONS"] = "0"
        disabled = store.record_lesson(kind="preference", skill="core", summary="should not persist")
        if disabled is not None or len(store.load_lessons()) != 2:
            raise AssertionError("RIGORPILOT_LESSONS=0 did not disable recording")
        checks += 1
        os.environ.pop("RIGORPILOT_LESSONS", None)

        if not store.touch_lesson("Prefer zh reports"):
            raise AssertionError("touch did not find the lesson by summary")
        touched = [i for i in store.load_lessons() if i.get("summary") == "Prefer zh reports"][0]
        if touched.get("use_count") != 1 or not touched.get("last_used"):
            raise AssertionError("touch did not bump use_count/last_used")
        checks += 1

        import time as _time
        removed = store.prune(now=int(_time.time()) + 400 * 86400)
        if removed < 1:
            raise AssertionError("prune did not drop stale lessons after the window")
        checks += 1

        cli = subprocess.run(
            [
                sys.executable,
                str(repo_root / "shared" / "scripts" / "lessons_store.py"),
                "record",
                "--kind",
                "user-correction",
                "--skill",
                "ai-research-explore",
                "--summary",
                "Researcher prefers mIoU over aAcc as headline metric",
            ],
            capture_output=True,
            text=True,
            check=True,
            env=os.environ.copy(),
        )
        payload = json.loads(cli.stdout)
        if not payload.get("recorded"):
            raise AssertionError("CLI record path failed")
        checks += 1

        print("ok: True")
        print(f"checks: {checks}")
        print("failures: 0")
        return 0
    finally:
        if old_home is None:
            os.environ.pop("RIGORPILOT_HOME", None)
        else:
            os.environ["RIGORPILOT_HOME"] = old_home
        if old_toggle is None:
            os.environ.pop("RIGORPILOT_LESSONS", None)
        else:
            os.environ["RIGORPILOT_LESSONS"] = old_toggle
        if temp_root.exists():
            shutil.rmtree(temp_root)


if __name__ == "__main__":
    raise SystemExit(main())
