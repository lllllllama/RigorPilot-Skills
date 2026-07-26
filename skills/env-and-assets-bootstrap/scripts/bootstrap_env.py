#!/usr/bin/env python3
"""Bootstrap a conservative research environment on Windows, macOS, or Linux."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from plan_setup import ENV_FILES, find_first, parse_env_name, venv_activation_commands


CONDA_ENV_FILES = {"environment.yml", "environment.yaml", "conda.yml"}


def format_command(command: Iterable[str]) -> str:
    return " ".join(str(part) for part in command)


def run_command(command: List[str], *, cwd: Path, dry_run: bool) -> None:
    print(f"+ {format_command(command)}")
    if dry_run:
        return
    subprocess.run(command, cwd=cwd, check=True)


def choose_manager(preferred: str) -> Optional[str]:
    if preferred != "auto":
        if shutil.which(preferred):
            return preferred
        raise FileNotFoundError(f"Requested manager `{preferred}` was not found on PATH.")

    for candidate in ["conda", "mamba"]:
        if shutil.which(candidate):
            return candidate
    return None


def venv_python(env_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def print_activation_instructions(env_name: Optional[str], using_conda: bool) -> None:
    if using_conda:
        target = env_name or "<env-name>"
        print(f"Activate with: conda activate {target}")
        return

    print("Activate the virtualenv with one of:")
    for item in venv_activation_commands():
        platforms = ", ".join(item.get("platforms", []))
        print(f"  [{platforms}] {item['command']}")


def install_with_manager(manager: str, env_name: str, repo_path: Path, rel_env_file: Optional[str], *, dry_run: bool) -> None:
    if rel_env_file == "requirements.txt":
        run_command(
            [manager, "run", "-n", env_name, "python", "-m", "pip", "install", "-r", rel_env_file],
            cwd=repo_path,
            dry_run=dry_run,
        )
    elif rel_env_file in {"pyproject.toml", "setup.py"}:
        run_command(
            [manager, "run", "-n", env_name, "python", "-m", "pip", "install", "-e", "."],
            cwd=repo_path,
            dry_run=dry_run,
        )


def install_with_venv(env_python: Path, repo_path: Path, rel_env_file: Optional[str], *, dry_run: bool) -> None:
    if rel_env_file == "requirements.txt":
        run_command(
            [str(env_python), "-m", "pip", "install", "-r", rel_env_file],
            cwd=repo_path,
            dry_run=dry_run,
        )
    elif rel_env_file in {"pyproject.toml", "setup.py"}:
        run_command(
            [str(env_python), "-m", "pip", "install", "-e", "."],
            cwd=repo_path,
            dry_run=dry_run,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a conservative AI research environment.")
    parser.add_argument("repo", nargs="?", default=".", help="Target repository path.")
    parser.add_argument("env_name", nargs="?", default="repro-env", help="Fallback environment name.")
    parser.add_argument("--python-version", default="3.10", help="Python version to use for conda or mamba environments.")
    parser.add_argument(
        "--manager",
        choices=["auto", "conda", "mamba"],
        default="auto",
        help="Conda-compatible manager to use when available.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    args = parser.parse_args()

    repo_path = Path(args.repo).resolve()
    env_file = find_first(repo_path, ENV_FILES)
    rel_env_file = env_file.relative_to(repo_path).as_posix() if env_file else None
    declared_env_name = parse_env_name(env_file) if env_file else None
    resolved_env_name = declared_env_name or args.env_name
    manager = choose_manager(args.manager)

    print(f"Target repo: {repo_path}")
    print(f"Detected environment file: {rel_env_file or 'none'}")

    if env_file and env_file.name in CONDA_ENV_FILES:
        if manager is None:
            raise SystemExit("A conda-compatible manager is required for environment.yml-based setup. Install conda or mamba first.")

        create_command = [manager, "env", "create", "-f", rel_env_file]
        if not declared_env_name:
            create_command.extend(["-n", resolved_env_name])
        run_command(create_command, cwd=repo_path, dry_run=args.dry_run)
        print_activation_instructions(declared_env_name or resolved_env_name, using_conda=True)
        return 0

    if manager is not None:
        run_command(
            [manager, "create", "-y", "-n", resolved_env_name, f"python={args.python_version}"],
            cwd=repo_path,
            dry_run=args.dry_run,
        )
        install_with_manager(manager, resolved_env_name, repo_path, rel_env_file, dry_run=args.dry_run)
        print_activation_instructions(resolved_env_name, using_conda=True)
        return 0

    env_dir = repo_path / ".venv"
    run_command([sys.executable, "-m", "venv", str(env_dir)], cwd=repo_path, dry_run=args.dry_run)
    install_with_venv(venv_python(env_dir), repo_path, rel_env_file, dry_run=args.dry_run)
    print_activation_instructions(None, using_conda=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
