#!/usr/bin/env python3
"""Create a conservative environment setup plan for a research repository."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


ENV_FILES = [
    "environment.yml",
    "environment.yaml",
    "conda.yml",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
]
ALL_PLATFORMS = ["windows", "macos", "linux"]


def find_first(repo: Path, candidates: List[str]) -> Optional[Path]:
    for name in candidates:
        path = repo / name
        if path.exists():
            return path
    return None


def parse_env_name(path: Path) -> Optional[str]:
    if path.suffix not in {".yml", ".yaml"}:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*name:\s*([A-Za-z0-9._-]+)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def command_entry(label: str, command: str, platforms: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "label": label,
        "command": command,
        "platforms": list(platforms or ALL_PLATFORMS),
    }


def venv_activation_commands() -> List[Dict[str, Any]]:
    return [
        command_entry("adapted", ".\\.venv\\Scripts\\Activate.ps1", ["windows"]),
        command_entry("adapted", "source .venv/bin/activate", ["macos", "linux"]),
    ]


def append_venv_flow(setup_commands: List[Dict[str, Any]], install_command: Optional[str] = None) -> None:
    setup_commands.append(command_entry("adapted", "python -m venv .venv"))
    setup_commands.extend(venv_activation_commands())
    if install_command:
        setup_commands.append(command_entry("documented", install_command))


def build_setup_commands(repo: Path) -> Dict[str, object]:
    setup_commands: List[Dict[str, Any]] = []
    notes: List[str] = []
    unresolved: List[str] = []

    env_file = find_first(repo, ENV_FILES)
    env_name = parse_env_name(env_file) if env_file else None

    if env_file is None:
        unresolved.append("No top-level environment specification file was found.")
        setup_commands.append(command_entry("inferred", "python -m venv .venv"))
        setup_commands.extend(
            [
                command_entry("inferred", ".\\.venv\\Scripts\\Activate.ps1", ["windows"]),
                command_entry("inferred", "source .venv/bin/activate", ["macos", "linux"]),
            ]
        )
        notes.append("Defaulted to a virtualenv fallback because no environment file was detected.")
        return {
            "environment_file": None,
            "environment_name": None,
            "setup_commands": setup_commands,
            "setup_notes": notes,
            "unresolved_setup_risks": unresolved,
        }

    rel_env_file = env_file.relative_to(repo).as_posix()
    notes.append(f"Detected environment file `{rel_env_file}`.")
    if env_name:
        notes.append(f"Detected conda environment name `{env_name}`.")

    if env_file.name in {"environment.yml", "environment.yaml", "conda.yml"}:
        setup_commands.append(command_entry("documented", f"conda env create -f {rel_env_file}"))
        setup_commands.append(command_entry("adapted", f"conda activate {env_name}" if env_name else "conda activate <env-name>"))
        if not env_name:
            unresolved.append("The conda environment name was not declared and still needs confirmation.")
    elif env_file.name == "requirements.txt":
        append_venv_flow(setup_commands, f"python -m pip install -r {rel_env_file}")
        notes.append("Fell back to a virtualenv plus requirements installation plan.")
    elif env_file.name == "pyproject.toml":
        append_venv_flow(setup_commands, "python -m pip install -e .")
        notes.append("Detected a pyproject-based installation flow.")
    elif env_file.name == "setup.py":
        append_venv_flow(setup_commands, "python -m pip install -e .")
        notes.append("Detected a setup.py-based editable install flow.")

    return {
        "environment_file": rel_env_file,
        "environment_name": env_name,
        "setup_commands": setup_commands,
        "setup_notes": notes,
        "unresolved_setup_risks": unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a conservative environment setup plan.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    payload = build_setup_commands(repo)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
