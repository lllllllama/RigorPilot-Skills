#!/usr/bin/env python3
"""Scan a repository for README-first reproduction signals."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


KEY_FILES = [
    "README.md",
    "README",
    "requirements.txt",
    "environment.yml",
    "environment.yaml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Dockerfile",
]

SIGNAL_DIRS = [
    "configs",
    "config",
    "scripts",
    "tools",
    "examples",
    "notebooks",
    "checkpoints",
]


def first_existing(root: Path, names: List[str]) -> Optional[Path]:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def scan_repo(root: Path) -> Dict[str, object]:
    if not root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {root}")

    top_level = sorted(item.name for item in root.iterdir())
    detected_files = [name for name in KEY_FILES if (root / name).exists()]
    detected_dirs = [name for name in SIGNAL_DIRS if (root / name).exists()]
    readme = first_existing(root, ["README.md", "README"])

    warnings: List[str] = []
    if readme is None:
        warnings.append("No README file was found at the repository root.")
    if not detected_files:
        warnings.append("No common environment or packaging files were detected.")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_path": str(root.resolve()),
        "readme_path": str(readme.resolve()) if readme else None,
        "detected_files": detected_files,
        "detected_dirs": detected_dirs,
        "structure": {
            "top_level": top_level,
            "top_level_file_count": sum(1 for item in root.iterdir() if item.is_file()),
            "top_level_dir_count": sum(1 for item in root.iterdir() if item.is_dir()),
        },
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a repository for key reproduction signals.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human summary.")
    args = parser.parse_args()

    data = scan_repo(Path(args.repo))
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Repository: {data['repo_path']}")
        print(f"README: {data['readme_path'] or 'not found'}")
        print("Detected files:", ", ".join(data["detected_files"]) or "none")
        print("Detected dirs:", ", ".join(data["detected_dirs"]) or "none")
        if data["warnings"]:
            print("Warnings:")
            for item in data["warnings"]:
                print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
