#!/usr/bin/env python3
"""Prepare a conservative asset manifest for reproduction work."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List


COMMON_ASSET_DIRS = ["datasets", "data", "checkpoints", "weights", "cache", ".cache"]
KEYWORDS = ("checkpoint", "weight", "dataset", "cache", "model", "download")
URL_RE = re.compile(r"https?://\S+")
PATH_RE = re.compile(r"[\w./-]+\.(?:ckpt|pth|pt|bin|safetensors|zip|tar|gz|json|yaml)")


def first_existing(root: Path, names: List[str]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def collect_text_hints(repo: Path) -> List[Dict[str, str]]:
    hints: List[Dict[str, str]] = []
    readme = first_existing(repo, ["README.md", "README"])
    if readme:
        text = readme.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            lowered = line.lower()
            if not any(keyword in lowered for keyword in KEYWORDS):
                continue
            urls = URL_RE.findall(line)
            paths = PATH_RE.findall(line)
            if not urls and not paths:
                continue
            hints.append(
                {
                    "source": str(readme.resolve()),
                    "line": line.strip(),
                    "urls": ", ".join(urls) if urls else "",
                    "paths": ", ".join(paths) if paths else "",
                }
            )

    for directory in ["configs", "config"]:
        config_root = repo / directory
        if not config_root.exists():
            continue
        for path in config_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".yaml", ".yml", ".json", ".toml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if not any(keyword in text.lower() for keyword in KEYWORDS):
                continue
            matches = PATH_RE.findall(text)
            urls = URL_RE.findall(text)
            if not matches and not urls:
                continue
            hints.append(
                {
                    "source": str(path.resolve()),
                    "line": "config hint",
                    "urls": ", ".join(urls[:3]) if urls else "",
                    "paths": ", ".join(matches[:5]) if matches else "",
                }
            )
    return hints


def prepare_assets(repo: Path, assets_root: Path) -> Dict[str, object]:
    assets_root.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict[str, str]] = []

    for name in COMMON_ASSET_DIRS:
        repo_candidate = repo / name
        manifest.append(
            {
                "asset_group": name,
                "source_hint": str(repo_candidate.resolve()) if repo_candidate.exists() else "not found in repo",
                "target_path": str((assets_root / name).resolve()),
                "status": "present" if repo_candidate.exists() else "missing",
            }
        )

    return {
        "repo_path": str(repo.resolve()),
        "assets_root": str(assets_root.resolve()),
        "manifest": manifest,
        "text_hints": collect_text_hints(repo),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a conservative asset manifest.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--assets-root", default="artifacts/assets", help="Directory where prepared assets should live.")
    parser.add_argument(
        "--output-json",
        default="artifacts/assets/asset_manifest.json",
        help="Path to write the manifest JSON.",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    assets_root = Path(args.assets_root).resolve()
    output_json = Path(args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)

    data = prepare_assets(repo, assets_root)
    output_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
