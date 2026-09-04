#!/usr/bin/env python3
"""Build or verify the self-contained runtime shipped with the main skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


BUNDLE_FILES = {
    "shared/scripts/command_utils.py": "_bundled/shared/scripts/command_utils.py",
    "shared/scripts/model_adapter.py": "_bundled/shared/scripts/model_adapter.py",
    "shared/scripts/resource_monitor.py": "_bundled/shared/scripts/resource_monitor.py",
    "shared/scripts/runtime_runner.py": "_bundled/shared/scripts/runtime_runner.py",
    "shared/scripts/task_queue.py": "_bundled/shared/scripts/task_queue.py",
    "shared/scripts/lessons_store.py": "_bundled/shared/scripts/lessons_store.py",
    "shared/scripts/write_run_bundle.py": "_bundled/shared/scripts/write_run_bundle.py",
    "skills/repo-intake-and-plan/scripts/scan_repo.py": "_bundled/skills/repo-intake-and-plan/scripts/scan_repo.py",
    "skills/repo-intake-and-plan/scripts/extract_commands.py": "_bundled/skills/repo-intake-and-plan/scripts/extract_commands.py",
    "skills/env-and-assets-bootstrap/scripts/plan_setup.py": "_bundled/skills/env-and-assets-bootstrap/scripts/plan_setup.py",
    "skills/env-and-assets-bootstrap/scripts/prepare_assets.py": "_bundled/skills/env-and-assets-bootstrap/scripts/prepare_assets.py",
    "skills/minimal-run-and-audit/scripts/write_outputs.py": "_bundled/skills/minimal-run-and-audit/scripts/write_outputs.py",
    "skills/run-train/scripts/run_training.py": "_bundled/skills/run-train/scripts/run_training.py",
    "skills/run-train/scripts/write_outputs.py": "_bundled/skills/run-train/scripts/write_outputs.py",
    "skills/analyze-project/scripts/analyze_project.py": "_bundled/skills/analyze-project/scripts/analyze_project.py",
    "references/agent-operating-principles.md": "references/agent-operating-principles.md",
    "references/research-rigor-principles.md": "references/research-rigor-principles.md",
    "references/deep-learning-experiment-principles.md": "references/deep-learning-experiment-principles.md",
    "references/continuous-learning-policy.md": "references/continuous-learning-policy.md",
}


def normalized_bytes(path: Path) -> bytes:
    """Keep bundle identity stable across Git LF/CRLF checkout policies."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def digest(path: Path) -> str:
    return hashlib.sha256(normalized_bytes(path)).hexdigest()


def expected_manifest(repo_root: Path) -> dict:
    files = []
    for source_rel, target_rel in sorted(BUNDLE_FILES.items()):
        source = repo_root / source_rel
        if not source.is_file():
            raise FileNotFoundError(f"Bundle source does not exist: {source}")
        files.append(
            {
                "source": source_rel,
                "target": target_rel,
                "sha256": digest(source),
            }
        )
    return {"schema_version": "1.0", "files": files}


def sync(repo_root: Path, check: bool) -> list[str]:
    skill_root = repo_root / "skills" / "ai-research-reproduction"
    manifest = expected_manifest(repo_root)
    failures: list[str] = []

    for item in manifest["files"]:
        source = repo_root / item["source"]
        target = skill_root / item["target"]
        if check:
            if not target.is_file():
                failures.append(f"missing bundled file: {item['target']}")
            elif normalized_bytes(target) != normalized_bytes(source):
                failures.append(f"stale bundled file: {item['target']}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest_path = skill_root / "_bundled" / "MANIFEST.json"
    rendered = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if check:
        if not manifest_path.is_file():
            failures.append("missing bundled file: _bundled/MANIFEST.json")
        elif manifest_path.read_text(encoding="utf-8") != rendered:
            failures.append("stale bundled file: _bundled/MANIFEST.json")
        allowed = {
            item["target"] for item in manifest["files"] if item["target"].startswith("_bundled/")
        }
        allowed.add("_bundled/MANIFEST.json")
        for path in (skill_root / "_bundled").rglob("*"):
            if path.is_file():
                relative = path.relative_to(skill_root).as_posix()
                if relative not in allowed:
                    failures.append(f"unexpected bundled file: {relative}")
    else:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the main skill's self-contained runtime bundle.")
    parser.add_argument("--check", action="store_true", help="Fail instead of writing when bundled files are missing or stale.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    failures = sync(repo_root, args.check)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("bundle_status: current" if args.check else "bundle_status: synchronized")
    print(f"files: {len(BUNDLE_FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
