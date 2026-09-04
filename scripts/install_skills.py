#!/usr/bin/env python3
"""Install this repository's skill folders into a client-neutral or client-specific skills directory."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Mapping


SHARED_REFERENCE_FILES = [
    "agent-operating-principles.md",
    "research-rigor-principles.md",
    "deep-learning-experiment-principles.md",
    "explore-variant-spec.md",
    "research-pitfall-checklist.md",
    "research-thinking-loop.md",
    "continuous-learning-policy.md",
]

# Runtime modules loaded by installed skills via parents[3]/shared/scripts;
# they must be installed next to the skills.
SHARED_SCRIPT_FILES = [
    "command_utils.py",
    "model_adapter.py",
    "resource_monitor.py",
    "runtime_runner.py",
    "task_queue.py",
    "write_run_bundle.py",
    "write_explore_bundle.py",
    "lessons_store.py",
]


def default_target(client: str, env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    env_map = os.environ if env is None else env
    home_path = (home or Path.home()).expanduser()

    if client == "agents":
        agents_home = env_map.get("AGENTS_HOME")
        base = Path(agents_home).expanduser() if agents_home else home_path / ".agents"
        return (base / "skills").resolve()

    if client == "codex":
        codex_home = env_map.get("CODEX_HOME")
        base = Path(codex_home).expanduser() if codex_home else home_path / ".codex"
        return (base / "skills").resolve()

    if client == "claude":
        claude_home = env_map.get("CLAUDE_HOME")
        base = Path(claude_home).expanduser() if claude_home else home_path / ".claude"
        return (base / "skills").resolve()

    raise ValueError(f"Unsupported client: {client}")


def discover_skills(skills_root: Path) -> List[Path]:
    return sorted(
        path for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    )


def safe_remove(path: Path, root: Path) -> None:
    # Validate containment on the entry itself, without following a symlink:
    # resolving first would reject (or worse, rmtree) the symlink's target
    # instead of the entry inside the target root.
    if path.parent.resolve() != root.resolve():
        raise ValueError(f"Refusing to remove path outside target root: {path}")
    if path.is_symlink():
        path.unlink()
        return
    if path.exists():
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)


def copy_skill(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        dirs_exist_ok=False,
    )


def install_shared_references(repo_root: Path, target_root: Path, force: bool) -> List[Path]:
    source_root = repo_root / "references"
    target_reference_root = target_root.parent / "references"
    installed: List[Path] = []

    for filename in SHARED_REFERENCE_FILES:
        source_path = source_root / filename
        target_path = target_reference_root / filename
        if not source_path.exists():
            raise FileNotFoundError(f"Shared reference does not exist: {source_path}")
        if target_path.exists():
            if target_path.read_bytes() == source_path.read_bytes():
                installed.append(target_path)
                continue
            if not force:
                raise FileExistsError(
                    f"Shared reference already exists with different content: {target_path}. "
                    "Re-run with --force to replace it."
                )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        installed.append(target_path)

    return installed


def install_shared_scripts(repo_root: Path, target_root: Path, force: bool) -> List[Path]:
    source_root = repo_root / "shared" / "scripts"
    target_script_root = target_root.parent / "shared" / "scripts"
    installed: List[Path] = []

    for filename in SHARED_SCRIPT_FILES:
        source_path = source_root / filename
        target_path = target_script_root / filename
        if not source_path.exists():
            raise FileNotFoundError(f"Shared script does not exist: {source_path}")
        if target_path.exists():
            if target_path.read_bytes() == source_path.read_bytes():
                installed.append(target_path)
                continue
            if not force:
                raise FileExistsError(
                    f"Shared script already exists with different content: {target_path}. "
                    "Re-run with --force to replace it."
                )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        installed.append(target_path)

    return installed


def install_skills(
    repo_root: Path,
    target_root: Path,
    mode: str,
    force: bool,
) -> List[Path]:
    skills_root = repo_root / "skills"
    skill_dirs = discover_skills(skills_root)
    target_root.mkdir(parents=True, exist_ok=True)
    install_shared_references(repo_root, target_root, force)
    install_shared_scripts(repo_root, target_root, force)

    installed: List[Path] = []
    for skill_dir in skill_dirs:
        target_path = target_root / skill_dir.name
        if target_path.exists() or target_path.is_symlink():
            if not force:
                raise FileExistsError(
                    f"Target already exists: {target_path}. Re-run with --force to replace it."
                )
            safe_remove(target_path, target_root)

        if mode == "copy":
            copy_skill(skill_dir, target_path)
        else:
            try:
                target_path.symlink_to(skill_dir.resolve(), target_is_directory=True)
            except OSError as exc:
                # Windows commonly denies symlink creation unless Developer Mode
                # or elevated privileges are enabled. A portable copy is safer
                # than failing an otherwise valid local installation.
                if os.name != "nt" or getattr(exc, "winerror", None) != 1314:
                    raise
                copy_skill(skill_dir, target_path)

        installed.append(target_path)

    return installed


def format_paths(paths: Iterable[Path]) -> str:
    return "\n".join(f"- {path}" for path in paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install all skill folders into a neutral, Codex, or Claude Code skills directory.")
    parser.add_argument(
        "--client",
        choices=["agents", "codex", "claude"],
        default="agents",
        help="Which skill directory convention to target. Defaults to the neutral Agent Skills directory for cross-client compatibility.",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Override the skills directory. Defaults to AGENTS_HOME/skills or ~/.agents/skills for neutral installs, CODEX_HOME/skills or ~/.codex/skills for Codex, and CLAUDE_HOME/skills or ~/.claude/skills for Claude Code.",
    )
    parser.add_argument(
        "--mode",
        choices=["copy", "symlink"],
        default="copy",
        help="Installation mode. Use symlink for local development, copy for portable installs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing target skill folders.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    target_root = (
        Path(args.target).expanduser().resolve()
        if args.target
        else default_target(args.client)
    )
    installed = install_skills(repo_root, target_root, args.mode, args.force)

    print(f"Installed {len(installed)} skills to {target_root} for {args.client}")
    if args.mode == "symlink":
        copied = [path for path in installed if not path.is_symlink()]
        if copied:
            print(
                f"Warning: symlink permission was unavailable; installed {len(copied)} skill(s) as copies instead.",
                file=sys.stderr,
            )
    print(format_paths(installed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
