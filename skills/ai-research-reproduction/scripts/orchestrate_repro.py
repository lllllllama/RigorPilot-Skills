#!/usr/bin/env python3
"""Minimal orchestration for README-first reproduction scaffolding."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from annotate_readme import strip_annotated_bytes, write_annotated_readme


SKILL_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHARED_SCRIPTS = Path(__file__).resolve().parents[3] / "shared" / "scripts"
BUNDLED_SHARED_SCRIPTS = SKILL_ROOT / "_bundled" / "shared" / "scripts"
SHARED_SCRIPTS = (
    SOURCE_SHARED_SCRIPTS
    if (SOURCE_SHARED_SCRIPTS / "command_utils.py").is_file()
    else BUNDLED_SHARED_SCRIPTS
)
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import run_persistent_command
from model_adapter import ModelAdapterError, load_model_profile, missing_capabilities
from command_utils import contains_shell_syntax


def load_lessons_store():
    """Load the shared lesson store; return None when unavailable (optional feature)."""
    import importlib.util

    module_path = SHARED_SCRIPTS / "lessons_store.py"
    if not module_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("lessons_store", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def maybe_record_lesson(repo_path: Path, context: Dict[str, Any]) -> Optional[str]:
    """Record failure blockers and later resolutions per the continuous-learning policy."""
    store = load_lessons_store()
    if store is None or not store.lessons_enabled():
        return None
    fingerprint = store.repo_fingerprint(repo_path)
    status = context.get("status")
    try:
        if status in {"partial", "blocked"}:
            path = store.record_lesson(
                kind="failure-fix",
                skill="ai-research-reproduction",
                summary=f"[{status}] {context.get('main_blocker', 'unrecorded blocker')}",
                detail=str(context.get("documented_command") or ""),
                fingerprint=fingerprint,
            )
            return str(path) if path else None
        if status == "success":
            prior_failures = [
                item
                for item in store.load_lessons()
                if item.get("fingerprint") == fingerprint and str(item.get("summary", "")).startswith("[")
            ]
            if prior_failures:
                path = store.record_lesson(
                    kind="failure-fix",
                    skill="ai-research-reproduction",
                    summary=f"[resolved] {context.get('documented_command')} now succeeds",
                    detail=f"previous blocker: {prior_failures[-1].get('summary', '')}",
                    fingerprint=fingerprint,
                )
                return str(path) if path else None
    except Exception:
        return None
    return None


def locale(user_language: str) -> str:
    return "zh" if user_language.lower().startswith("zh") else "en"


def text(user_language: str, en: str, zh: str) -> str:
    return zh if locale(user_language) == "zh" else en


def run_json(script: Path, args: List[str]) -> Dict[str, Any]:
    command = [sys.executable, str(script), *args]
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_env,
    )
    return json.loads(result.stdout)


def write_bundle(script: Path, output_dir: Path, context: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        context_path = Path(handle.name)
        handle.write(json.dumps(context, indent=2, ensure_ascii=False))

    try:
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--context-json",
                str(context_path),
                "--output-dir",
                str(output_dir),
            ],
            check=True,
        )
    finally:
        if context_path.exists():
            context_path.unlink()


SOURCE_SIDE_EFFECT_SUFFIXES = {
    ".c", ".cc", ".cfg", ".cmd", ".cpp", ".cu", ".cuh", ".h", ".hpp",
    ".ini", ".ipynb", ".js", ".json", ".mjs", ".ps1", ".py", ".pyi",
    ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml",
}
SOURCE_SIDE_EFFECT_NAMES = {"dockerfile", "makefile"}
CACHE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox"}
GENERATED_OUTPUT_PARTS = {
    "artifacts", "checkpoints", "logs", "outputs", "predictions", "results",
    "runs", "tensorboard", "wandb",
}


def _snapshot_digest(tracked_files: Dict[str, str], untracked_source_files: Dict[str, str]) -> str:
    payload = {
        "tracked_files": tracked_files,
        "untracked_source_files": untracked_source_files,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _ignored_untracked_roots(repo_path: Path, ignore_paths: Optional[List[Path]]) -> List[str]:
    roots: List[str] = []
    for raw in ignore_paths or []:
        try:
            relative = Path(raw).resolve().relative_to(repo_path.resolve()).as_posix().rstrip("/")
        except (OSError, ValueError):
            continue
        if relative and relative != "." and relative not in roots:
            roots.append(relative)
    return sorted(roots)


def _is_ignored_untracked(relative: str, ignored_roots: List[str]) -> bool:
    parts = Path(relative).parts
    lowered_parts = {part.lower() for part in parts}
    if any(part in CACHE_PARTS for part in parts) or lowered_parts.intersection(GENERATED_OUTPUT_PARTS):
        return True
    normalized = relative.replace("\\", "/").rstrip("/")
    return any(normalized == root or normalized.startswith(root + "/") for root in ignored_roots)


def _is_source_side_effect(relative: str) -> bool:
    path = Path(relative)
    return path.suffix.lower() in SOURCE_SIDE_EFFECT_SUFFIXES or path.name.lower() in SOURCE_SIDE_EFFECT_NAMES


def tracked_source_snapshot(
    repo_path: Path,
    ignore_untracked_paths: Optional[List[Path]] = None,
) -> Dict[str, Any]:
    """Hash tracked files plus untracked source/config files.

    Generated evidence roots may be excluded from the untracked-source scan.
    Tracked files are never excluded.
    """
    try:
        tracked_result = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
        untracked_result = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files", "--others", "--exclude-standard", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        return {
            "status": "unavailable",
            "reason": f"git unavailable: {exc}",
            "files": {},
            "untracked_source_files": {},
        }
    if tracked_result.returncode != 0 or untracked_result.returncode != 0:
        return {
            "status": "unavailable",
            "reason": "target is not a readable Git worktree",
            "files": {},
            "untracked_source_files": {},
        }

    files: Dict[str, str] = {}
    for raw in tracked_result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw)
        path = repo_path / relative
        try:
            if path.is_symlink():
                files[relative] = "symlink:" + os.readlink(path)
            elif path.is_file():
                files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                files[relative] = "missing"
        except OSError as exc:
            files[relative] = f"unreadable:{type(exc).__name__}"

    ignored_roots = _ignored_untracked_roots(repo_path, ignore_untracked_paths)
    untracked_source_files: Dict[str, str] = {}
    for raw in untracked_result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = os.fsdecode(raw).replace("\\", "/")
        if _is_ignored_untracked(relative, ignored_roots) or not _is_source_side_effect(relative):
            continue
        path = repo_path / relative
        try:
            if path.is_symlink():
                untracked_source_files[relative] = "symlink:" + os.readlink(path)
            elif path.is_file():
                untracked_source_files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                untracked_source_files[relative] = "missing"
        except OSError as exc:
            untracked_source_files[relative] = f"unreadable:{type(exc).__name__}"

    return {
        "status": "captured",
        "files": files,
        "untracked_source_files": untracked_source_files,
        "ignored_untracked_roots": ignored_roots,
        "snapshot_sha256": _snapshot_digest(files, untracked_source_files),
    }


def compare_source_snapshots(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    if before.get("status") != "captured" or after.get("status") != "captured":
        return {
            "status": "unavailable",
            "unchanged": None,
            "changed_files": [],
            "reason": before.get("reason") or after.get("reason") or "source snapshot unavailable",
        }
    before_files = before.get("files", {})
    after_files = after.get("files", {})
    before_untracked = before.get("untracked_source_files", {})
    after_untracked = after.get("untracked_source_files", {})
    changed_tracked = sorted(
        path for path in set(before_files) | set(after_files)
        if before_files.get(path) != after_files.get(path)
    )
    added_untracked = sorted(path for path in after_untracked if path not in before_untracked)
    modified_untracked = sorted(
        path for path in set(before_untracked) & set(after_untracked)
        if before_untracked.get(path) != after_untracked.get(path)
    )
    removed_untracked = sorted(path for path in before_untracked if path not in after_untracked)
    changed_untracked = sorted(set(added_untracked + modified_untracked + removed_untracked))
    changed = sorted(set(changed_tracked + changed_untracked))
    return {
        "status": "verified",
        "unchanged": not changed,
        "tracked_file_count": len(before_files),
        "untracked_source_file_count_before": len(before_untracked),
        "untracked_source_file_count_after": len(after_untracked),
        "before_sha256": before.get("snapshot_sha256") or _snapshot_digest(before_files, before_untracked),
        "after_sha256": after.get("snapshot_sha256") or _snapshot_digest(after_files, after_untracked),
        "changed_files": changed,
        "changed_tracked_files": changed_tracked,
        "changed_untracked_source_files": changed_untracked,
        "unexpected_added_source_files": added_untracked,
        "modified_untracked_source_files": modified_untracked,
        "removed_untracked_source_files": removed_untracked,
        "ignored_untracked_roots": after.get("ignored_untracked_roots", before.get("ignored_untracked_roots", [])),
    }


def _evidence_record(path: Path, repo_path: Path, output_dir: Path) -> Dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(output_dir.resolve()).as_posix()
        scope = "output"
        rendered_path = relative
    except ValueError:
        try:
            relative = resolved.relative_to(repo_path.resolve()).as_posix()
            scope = "repo"
            rendered_path = relative
        except ValueError:
            scope = "absolute"
            rendered_path = str(resolved)
    return {
        "scope": scope,
        "path": rendered_path,
        "size_bytes": resolved.stat().st_size,
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def write_evidence_manifest(
    repo_path: Path,
    output_dir: Path,
    context: Dict[str, Any],
    invocation_path: Path,
) -> Path:
    candidates: Dict[str, Optional[Path]] = {
        "summary": output_dir / "SUMMARY.md",
        "status": output_dir / "status.json",
        "commands": output_dir / "COMMANDS.md",
        "log": output_dir / "LOG.md",
        "scientific_changelog": output_dir / "SCIENTIFIC_CHANGELOG.md",
        "comparability_report": output_dir / "COMPARABILITY_REPORT.md",
        "patches": output_dir / "PATCHES.md",
        "annotated_readme": output_dir / "ANNOTATED_README.md",
        "invocation": invocation_path,
        "runtime_state": Path(context["runtime_state_path"]) if context.get("runtime_state_path") else None,
        "runtime_events": Path(context["runtime_events_path"]) if context.get("runtime_events_path") else None,
        "runtime_stdout": Path(context["stdout_log_path"]) if context.get("stdout_log_path") else None,
        "runtime_stderr": Path(context["stderr_log_path"]) if context.get("stderr_log_path") else None,
        "runtime_resources": Path(context["resources_log_path"]) if context.get("resources_log_path") else None,
    }
    source_readme = next((repo_path / name for name in ("README.md", "README") if (repo_path / name).is_file()), None)
    if source_readme is not None:
        candidates["source_readme"] = source_readme

    records: Dict[str, Any] = {}
    for label, path in candidates.items():
        if path is not None and path.is_file():
            records[label] = _evidence_record(path, repo_path, output_dir)

    manifest_path = output_dir / "evidence_manifest.json"
    manifest = {
        "schema_version": "1.0",
        "target_repo": str(repo_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "files": records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def _resolve_manifest_record(record: Dict[str, Any], repo_path: Path, output_dir: Path) -> Optional[Path]:
    scope = str(record.get("scope") or "")
    raw_path = str(record.get("path") or "")
    if not raw_path:
        return None
    if scope == "output":
        base = output_dir.resolve()
        resolved = (base / raw_path).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            return None
        return resolved
    if scope == "repo":
        base = repo_path.resolve()
        resolved = (base / raw_path).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            return None
        return resolved
    if scope == "absolute":
        return Path(raw_path).resolve()
    return None


def verify_evidence_manifest(repo_path: Path, output_dir: Path) -> Dict[str, Any]:
    manifest_path = output_dir / "evidence_manifest.json"
    if not manifest_path.is_file():
        return {"valid": False, "manifest_path": str(manifest_path), "files": {}, "error": "manifest missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "manifest_path": str(manifest_path), "files": {}, "error": str(exc)}

    results: Dict[str, bool] = {}
    for label, record in (manifest.get("files") or {}).items():
        if not isinstance(record, dict):
            results[str(label)] = False
            continue
        path = _resolve_manifest_record(record, repo_path, output_dir)
        if path is None or not path.is_file():
            results[str(label)] = False
            continue
        try:
            results[str(label)] = (
                path.stat().st_size == int(record.get("size_bytes", -1))
                and hashlib.sha256(path.read_bytes()).hexdigest() == record.get("sha256")
            )
        except (OSError, TypeError, ValueError):
            results[str(label)] = False
    valid = bool(results) and all(results.values())
    return {
        "valid": valid,
        "manifest_path": str(manifest_path),
        "files": results,
    }


def plan_payload(
    chosen: Dict[str, Any],
    setup_plan: Dict[str, Any],
    shell_mode: str,
    nontraining_timeout_seconds: int,
    training_timeout_seconds: int,
) -> Dict[str, Any]:
    selected_id = chosen.get("documented_command_id")
    fingerprint = chosen.get("selection_fingerprint")
    training_target = chosen.get("selected_goal") == "training"
    timeout_flag = "--train-timeout" if training_target else "--timeout"
    target_timeout_seconds = training_timeout_seconds if training_target else nontraining_timeout_seconds
    reviewed_run_args = []
    if selected_id and fingerprint:
        reviewed_run_args = [
            "--run-selected",
            "--command-id", selected_id,
            "--plan-fingerprint", fingerprint,
            timeout_flag, str(target_timeout_seconds),
        ]
    return {
        "schema_version": "1.0",
        "mode": "plan_only",
        "selected_goal": chosen["selected_goal"],
        "selected_command_id": selected_id,
        "documented_command": chosen.get("documented_command") or None,
        "documented_command_source": chosen.get("command_source", "none"),
        "documented_command_section": chosen.get("documented_command_section"),
        "requires_substitution": bool(chosen.get("requires_substitution")),
        "selection_source": chosen.get("selection_source"),
        "selection_fingerprint": fingerprint,
        "command_candidates": chosen.get("command_candidates", []),
        "reviewed_run_args": reviewed_run_args,
        "setup_advisory_count": len(setup_plan.get("unresolved_setup_risks", [])),
        "plan_side_effects": {
            "executes_target_command": False,
            "installs_dependencies": False,
            "downloads_assets": False,
            "modifies_target_source": False,
            "writes_evidence": False,
        },
        "proposed_run_contract": {
            "shell_mode": shell_mode,
            "target_command_timeout_seconds": target_timeout_seconds,
            "target_timeout_flag": timeout_flag,
            "timeout_scope": "target_command_only",
            "orchestrator_must_reach_terminal_state": True,
            "external_timeout_wrapper_allowed": False,
            "outer_timeout_guidance": (
                "Do not wrap the orchestrator in an equal or shorter timeout. "
                f"If the host requires an outer watchdog, keep it comfortably longer than {timeout_flag} "
                "so child-process cleanup and terminal evidence can finish."
            ),
            "installs_dependencies": False,
            "downloads_assets": False,
            "orchestrator_modifies_target_source": False,
            "target_command_side_effects": "repository-defined; review the selected command",
            "writes_evidence": True,
        },
    }


def selection_error_payload(error: CommandSelectionError) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "selection_error",
        "status": "blocked",
        "error": {
            "code": error.code,
            "summary": str(error),
            "requires_human": True,
            "safe_next_actions": ["Run --plan-only again and choose a command from the current candidate set."],
        },
        "selection_fingerprint": error.fingerprint,
        "command_candidates": error.candidates,
    }


def compact_agent_payload(
    context: Dict[str, Any],
    output_dir: Path,
    invocation_path: Path,
    source_integrity: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": context.get("status"),
        "selected_goal": context.get("selected_goal"),
        "selected_command_id": context.get("documented_command_id"),
        "documented_command": context.get("documented_command"),
        "selection_fingerprint": context.get("selection_fingerprint"),
        "error": context.get("error"),
        "runtime_status": context.get("runtime_status"),
        "result_match": context.get("result_match", {}).get("status", "not_evaluated"),
        "main_blocker": context.get("main_blocker"),
        "next_safe_action": context.get("next_safe_action"),
        "evidence": {
            "summary": str(output_dir / "SUMMARY.md"),
            "status": str(output_dir / "status.json"),
            "stdout": context.get("stdout_log_path"),
            "stderr": context.get("stderr_log_path"),
            "annotated_readme": context.get("annotated_readme"),
            "invocation": str(invocation_path),
            "manifest": str(output_dir / "evidence_manifest.json"),
        },
        "source_integrity": source_integrity,
        "source_adjacent_readme": context.get("source_adjacent_readme"),
    }


def incomplete_runtime_without_status(output_dir: Path) -> Optional[Dict[str, Any]]:
    runtime_root = output_dir / "_runtime"
    if not runtime_root.is_dir():
        return None
    candidates: List[Dict[str, Any]] = []
    for state_path in runtime_root.glob("*/state.json"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict) or state.get("status") not in {"created", "running"}:
            continue
        candidates.append(
            {
                "run_id": state.get("run_id") or state_path.parent.name,
                "status": state.get("status"),
                "state_path": str(state_path.resolve()),
                "started_at": state.get("started_at"),
                "last_heartbeat": state.get("last_heartbeat"),
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("last_heartbeat") or item.get("started_at") or ""))
    return candidates[-1]


def verify_existing_output(repo_path: Path, output_dir: Path) -> Dict[str, Any]:
    checks: Dict[str, bool] = {}
    status_path = output_dir / "status.json"
    if not status_path.is_file():
        incomplete_runtime = incomplete_runtime_without_status(output_dir)
        if incomplete_runtime is not None:
            return {
                "schema_version": "1.0",
                "mode": "verify_only",
                "evidence_valid": False,
                "checks": {"status_file": False, "runtime_terminal": False},
                "runtime": incomplete_runtime,
                "error": {
                    "code": "runtime_incomplete_without_status",
                    "summary": (
                        "Missing status.json while a retained runtime state is still nonterminal; "
                        "the orchestrator may still be running or may have been interrupted before "
                        "child-process cleanup and terminal evidence finalization. Do not replay the command automatically."
                    ),
                },
            }
        return {"schema_version": "1.0", "mode": "verify_only", "evidence_valid": False,
                "checks": {"status_file": False},
                "error": {"code": "evidence_missing", "summary": f"Missing {status_path}"}}
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"schema_version": "1.0", "mode": "verify_only", "evidence_valid": False,
                "checks": {"status_file": False},
                "error": {"code": "evidence_invalid", "summary": str(exc)}}

    checks["status_file"] = True
    try:
        checks["target_repo"] = Path(status.get("target_repo", "")).resolve() == repo_path.resolve()
    except (OSError, TypeError):
        checks["target_repo"] = False

    runtime = status.get("runtime")
    if runtime:
        state_path = Path(str(runtime.get("state_path") or ""))
        stdout_path = Path(str(runtime.get("stdout_log_path") or ""))
        stderr_path = Path(str(runtime.get("stderr_log_path") or ""))
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            checks["runtime"] = (
                stdout_path.is_file()
                and stderr_path.is_file()
                and state.get("status") == runtime.get("status")
                and state.get("run_id") == runtime.get("run_id")
            )
        except (OSError, json.JSONDecodeError):
            checks["runtime"] = False
    else:
        checks["runtime"] = True

    annotated = output_dir / "ANNOTATED_README.md"
    source_readme = next((repo_path / name for name in ("README.md", "README") if (repo_path / name).is_file()), None)
    if annotated.is_file() and source_readme is not None:
        try:
            checks["readme_round_trip"] = strip_annotated_bytes(annotated.read_bytes()) == source_readme.read_bytes()
        except (OSError, ValueError):
            checks["readme_round_trip"] = False
    else:
        checks["readme_round_trip"] = source_readme is None and not annotated.exists()

    invocation_path = output_dir / "invocation.json"
    source_integrity: Dict[str, Any] = {"status": "not_recorded", "unchanged": None, "changed_files": []}
    if invocation_path.is_file():
        try:
            source_integrity = json.loads(invocation_path.read_text(encoding="utf-8")).get(
                "source_integrity", source_integrity
            )
            checks["invocation"] = True
        except (OSError, json.JSONDecodeError):
            checks["invocation"] = False
    else:
        checks["invocation"] = False

    if source_integrity.get("status") == "verified" and source_integrity.get("after_sha256"):
        ignore_paths = [
            repo_path / relative
            for relative in source_integrity.get("ignored_untracked_roots", [])
            if isinstance(relative, str) and relative
        ]
        current_snapshot = tracked_source_snapshot(repo_path, ignore_paths)
        checks["source_current"] = (
            current_snapshot.get("status") == "captured"
            and current_snapshot.get("snapshot_sha256") == source_integrity.get("after_sha256")
        )
    else:
        checks["source_current"] = source_integrity.get("status") in {"not_requested", "not_recorded"}

    manifest_verification = verify_evidence_manifest(repo_path, output_dir)
    checks["evidence_manifest"] = bool(manifest_verification.get("valid"))

    failed_checks = [name for name, ok in checks.items() if not ok]
    if not failed_checks:
        verification_error = None
    elif "target_repo" in failed_checks:
        verification_error = {"code": "target_repo_mismatch", "summary": "Evidence belongs to a different target repository."}
    elif "source_current" in failed_checks:
        verification_error = {"code": "source_changed_after_run", "summary": "Current source no longer matches the post-run source snapshot."}
    elif "evidence_manifest" in failed_checks:
        verification_error = {"code": "evidence_tampered", "summary": "Retained evidence no longer matches its local manifest."}
    else:
        verification_error = {"code": "evidence_invalid", "summary": "One or more evidence consistency checks failed."}

    return {
        "schema_version": "1.0",
        "mode": "verify_only",
        "evidence_valid": all(checks.values()),
        "task_status": status.get("status"),
        "runtime_status": runtime.get("status") if runtime else None,
        "result_match": status.get("result_match", {}).get("status", "not_evaluated"),
        "checks": checks,
        "source_integrity": source_integrity,
        "evidence_manifest": manifest_verification,
        "status_path": str(status_path),
        "error": verification_error,
    }


def _bounded_log_text(run_data: Dict[str, Any], limit: int = 131072) -> str:
    parts = [str(item) for item in run_data.get("execution_log", [])]
    for key in ("stderr_log_path", "stdout_log_path"):
        raw_path = run_data.get(key)
        if not raw_path:
            continue
        try:
            data = Path(str(raw_path)).read_bytes()
        except OSError:
            continue
        parts.append(data[-limit:].decode("utf-8", errors="replace"))
    return "\n".join(parts)[-limit:]


def classify_execution_error(
    *,
    run_selected: bool,
    chosen: Dict[str, Any],
    run_data: Dict[str, Any],
    source_integrity: Dict[str, Any],
) -> Optional[str]:
    if not run_selected:
        return None
    if source_integrity.get("unchanged") is False:
        return "source_modified"
    if (
        run_data.get("runtime_status") == "success"
        and run_data.get("result_match", {}).get("status") == "mismatched"
    ):
        return "metric_mismatch"
    if chosen.get("requires_substitution"):
        return "placeholder_required"
    if not chosen.get("documented_command"):
        return "no_documented_command"
    if not chosen.get("command_feasible", True):
        reason = str(chosen.get("command_feasibility_reason") or "").lower()
        if "shell" in reason:
            return "shell_review_required"
        if "download" in reason:
            return "large_download_review_required"
        if "directory is absent" in reason:
            return "missing_asset"
        return "prerequisite_unavailable"
    if run_data.get("status") == "success":
        return None

    evidence = _bounded_log_text(run_data)
    lowered = evidence.lower()
    blocker = str(run_data.get("main_blocker") or "").lower()
    if "shell syntax" in lowered or "shell syntax" in blocker:
        return "shell_review_required"
    if "modulenotfounderror" in lowered or "no module named" in lowered:
        return "missing_dependency"
    if "filenotfounderror" in lowered or "no such file or directory" in lowered:
        return "missing_asset"
    if run_data.get("runtime_status") == "timed_out" or "timed out" in blocker:
        return "timeout"
    if run_data.get("cancelled") or run_data.get("runtime_status") == "cancelled":
        return "cancelled"
    if "executable not found" in blocker or "failed before launch" in lowered:
        return "command_not_found"
    return "command_failed"


def build_error_record(context: Dict[str, Any], error_code: Optional[str]) -> Optional[Dict[str, Any]]:
    if not error_code:
        return None
    return {
        "code": error_code,
        "summary": context.get("main_blocker"),
        "requires_human": bool(context.get("human_decisions_required")),
        "safe_next_actions": [context.get("next_safe_action")] if context.get("next_safe_action") else [],
    }


def build_asset_commands(asset_data: Dict[str, Any], user_language: str = "en") -> List[Dict[str, str]]:
    """Report observations, not mandatory preparation invented from directory names."""
    commands: List[Dict[str, str]] = []
    for item in asset_data.get("manifest", []):
        group = item.get("asset_group", "asset")
        if item.get("status") == "present":
            commands.append({"label": "inferred", "execution_status": "not_run", "command": text(
                user_language,
                f"# Observed {group} path: {item.get('source_hint')}; contents and applicability are unverified.",
                f"# 已发现 {group} 路径：{item.get('source_hint')}；内容及是否适用于当前目标尚未验证。",
            )})

    for hint in asset_data.get("text_hints", []):
        descriptor = hint.get("paths") or hint.get("urls") or hint.get("line", "")
        source = Path(hint.get("source", "README.md")).name
        commands.append({"label": "documented", "execution_status": "not_run", "command": text(
            user_language,
            f"# Asset hint from {source}: {descriptor}; confirm relevance to the selected command before preparation.",
            f"# 来自 {source} 的资源线索：{descriptor}；准备前先确认是否与选定命令相关。",
        )})
    return commands


def derive_dataset_hint(asset_data: Dict[str, Any]) -> str:
    for hint in asset_data.get("text_hints", []):
        if "dataset" in hint.get("line", "").lower():
            return hint.get("paths") or hint.get("urls") or "README-documented dataset"
    for item in asset_data.get("manifest", []):
        if item.get("asset_group") in {"datasets", "data"} and item.get("status") == "present":
            return item.get("source_hint", "repo-local dataset")
    return "unknown"


def derive_checkpoint_hint(asset_data: Dict[str, Any]) -> str:
    for hint in asset_data.get("text_hints", []):
        line = hint.get("line", "").lower()
        if "checkpoint" in line or "weight" in line or "model" in line:
            return hint.get("paths") or hint.get("urls") or "README-documented checkpoint"
    for item in asset_data.get("manifest", []):
        if item.get("asset_group") in {"checkpoints", "weights"} and item.get("status") == "present":
            return item.get("source_hint", "repo-local checkpoint")
    return "none"


def extract_config_path(command: str) -> str | None:
    tokens = shlex.split(command, posix=True)
    for index, token in enumerate(tokens):
        if token in {"--config", "--cfg"} and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--config="):
            return token.split("=", 1)[1]
        if token.startswith("--cfg="):
            return token.split("=", 1)[1]
    return None


def estimate_training_duration(repo_path: Path, command: str, max_train_steps: int) -> str:
    if max_train_steps > 0:
        if max_train_steps <= 200:
            return f"roughly minutes to under 1 hour for about {max_train_steps} steps, depending on dataset size and GPU throughput"
        if max_train_steps <= 5000:
            return f"roughly hours for about {max_train_steps} steps, depending on dataset size and GPU throughput"
        return f"likely many hours to multi-day for about {max_train_steps} steps, depending on dataset size and GPU throughput"

    config_rel = extract_config_path(command)
    if config_rel:
        config_path = (repo_path / config_rel).resolve()
        if config_path.exists() and config_path.suffix.lower() in {".yaml", ".yml", ".json", ".toml", ".py"}:
            text_content = config_path.read_text(encoding="utf-8", errors="replace")
            step_match = None
            for key in ["max_steps", "total_steps", "train_steps", "num_steps"]:
                step_match = re.search(rf"{key}\s*[:=]\s*(\d+)", text_content, flags=re.IGNORECASE)
                if step_match:
                    steps = int(step_match.group(1))
                    if steps <= 200:
                        return f"roughly minutes to under 1 hour from config-bound {steps} steps, depending on GPU throughput"
                    if steps <= 5000:
                        return f"roughly hours from config-bound {steps} steps, depending on GPU throughput"
                    return f"likely many hours to multi-day from config-bound {steps} steps, depending on dataset size and GPU throughput"

            epoch_match = None
            for key in ["epochs", "max_epochs", "num_epochs", "train_epochs"]:
                epoch_match = re.search(rf"{key}\s*[:=]\s*(\d+)", text_content, flags=re.IGNORECASE)
                if epoch_match:
                    epochs = int(epoch_match.group(1))
                    if epochs <= 3:
                        return f"roughly minutes to under 1 hour for about {epochs} epochs, depending on dataset size and GPU throughput"
                    if epochs <= 20:
                        return f"roughly hours for about {epochs} epochs, depending on dataset size and GPU throughput"
                    return f"likely many hours to multi-day for about {epochs} epochs, depending on dataset size and GPU throughput"

    return "unknown; likely hours to multi-day on the full dataset until a bounded schedule is confirmed"


OUT_DIR_RE = re.compile(r"--out[_-]?dir[= ]([\w./-]+)")
TARGET_COMMAND_KINDS = {"run", "smoke"}
CATEGORY_PRIORITY = {"inference": 0, "evaluation": 1, "training": 2, "other": 3}
NON_TARGET_COMMAND_PREFIXES = (
    "pip install ", "pip3 install ", "python -m pip install ", "python3 -m pip install ",
    "uv pip install ", "poetry install ", "conda install ", "conda create ", "conda env create ",
    "conda activate ", "git clone ", "wget ", "curl ", "aria2c ", "make install ",
    "npm install ", "npm ci ", "yarn install ", "pnpm install ", "apt install ", "apt-get install ",
    "dnf install ", "yum install ", "brew install ", "choco install ", "winget install ",
)


def is_non_target_command(command: str) -> bool:
    lowered = command.strip().lower()
    return any(lowered == prefix.rstrip() or lowered.startswith(prefix) for prefix in NON_TARGET_COMMAND_PREFIXES)


def command_score(command: Dict[str, Any], produced_out_dirs: frozenset = frozenset()) -> int:
    text_value = str(command.get("command", "")).lower()
    kind = command.get("kind", "run")
    score = {"run": 40, "smoke": 30, "asset": 10, "setup": 0}.get(kind, 0)

    if any(token in text_value for token in ["python ", "python3 ", "./", "whisper "]):
        score += 8
    if any(token in text_value for token in ["txt2img", "img2img", "amg.py", "transcribe", "infer", "eval"]):
        score += 8
    # Self-contained commands (pretrained init, downloadable weights) beat
    # commands that consume another documented command's training output.
    if re.search(r"--init_from=|--pretrained|https?://", text_value):
        score += 6
    out_match = OUT_DIR_RE.search(text_value)
    if out_match and out_match.group(1) in produced_out_dirs and command.get("category") != "training":
        score -= 8
    if "<" in text_value and ">" in text_value:
        score -= 10
    if text_value.startswith(("pip install", "conda install", "conda env create", "conda activate", "git clone", "cd ")):
        score -= 12
    if command.get("category") == "training":
        if "--device=cpu" in text_value:
            score += 6
        if re.search(r"--(?:max_iters|max-steps|max_steps|epochs?)[= ]\d+|--dry-run\b", text_value):
            score += 6
        if text_value.startswith(("torchrun ", "deepspeed ")) or "--nproc_per_node" in text_value:
            score -= 12
    return score


LARGE_REMOTE_MODEL_RE = re.compile(
    r"--init_from=(?:gpt2-(?:medium|large|xl)|[^\s]*(?:large|xl))\b",
    re.IGNORECASE,
)


def command_feasibility(
    command: Dict[str, Any],
    repo_path: Optional[Path],
    shell_mode: str = "direct",
) -> tuple[bool, str]:
    text_value = str(command.get("command", ""))
    if command.get("needs_substitution"):
        return False, "documented placeholder values require substitution before execution"
    if shell_mode == "direct" and contains_shell_syntax(text_value):
        return False, "command requires native shell syntax; review it before using --shell-mode native"
    if command.get("category") != "inference":
        return True, "no static prerequisite blocker detected"
    out_match = OUT_DIR_RE.search(text_value)
    if out_match and repo_path is not None and not (repo_path / out_match.group(1)).exists():
        return False, f"required local output directory is absent: {out_match.group(1)}"
    if LARGE_REMOTE_MODEL_RE.search(text_value):
        return False, "command implies a large remote pretrained-model download"
    return True, "no static prerequisite blocker detected"


def _candidate_fingerprint(candidates: List[Dict[str, Any]]) -> str:
    stable = [
        {
            "id": item["id"],
            "command": item["command"],
            "category": item["category"],
            "kind": item["kind"],
            "section": item.get("section"),
            "source": item.get("source"),
            "source_file": item.get("source_file"),
            "needs_substitution": item.get("needs_substitution", False),
        }
        for item in candidates
    ]
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_command_candidates(
    commands: List[Dict[str, Any]],
    repo_path: Optional[Path] = None,
    shell_mode: str = "direct",
) -> List[Dict[str, Any]]:
    produced_out_dirs = frozenset(
        match.group(1)
        for item in commands
        if item.get("category") == "training"
        for match in [OUT_DIR_RE.search(str(item.get("command", "")).lower())]
        if match
    )
    candidates: List[Dict[str, Any]] = []
    for item in commands:
        if item.get("kind", "run") not in TARGET_COMMAND_KINDS or is_non_target_command(str(item.get("command", ""))):
            continue
        feasible, feasibility_reason = command_feasibility(item, repo_path, shell_mode)
        candidates.append(
            {
                "id": f"cmd-{len(candidates) + 1:02d}",
                "command": item.get("command", ""),
                "category": item.get("category", "other"),
                "kind": item.get("kind", "run"),
                "section": item.get("section"),
                "source": item.get("source", "readme"),
                "source_file": item.get("source_file"),
                "score": command_score(item, produced_out_dirs),
                "needs_substitution": bool(item.get("needs_substitution")),
                "requires_native_shell": bool(
                    not item.get("needs_substitution")
                    and contains_shell_syntax(str(item.get("command", "")))
                ),
                "feasible": feasible,
                "feasibility_reason": feasibility_reason,
                "auto_selectable": bool(not item.get("needs_substitution") and feasible),
            }
        )
    ranked = sorted(
        candidates,
        key=lambda item: (
            CATEGORY_PRIORITY.get(str(item.get("category")), 99),
            -int(item.get("score", 0)),
            item["id"],
        ),
    )
    for rank, item in enumerate(ranked, start=1):
        item["selection_rank"] = rank
    return candidates


class CommandSelectionError(ValueError):
    def __init__(self, code: str, message: str, candidates: List[Dict[str, Any]], fingerprint: str):
        super().__init__(message)
        self.code = code
        self.candidates = candidates
        self.fingerprint = fingerprint


def choose_goal(
    commands: List[Dict[str, Any]],
    repo_path: Optional[Path] = None,
    shell_mode: str = "direct",
    command_id: str = "",
    plan_fingerprint: str = "",
) -> Dict[str, Any]:
    candidates = build_command_candidates(commands, repo_path, shell_mode)
    fingerprint = _candidate_fingerprint(candidates)
    if plan_fingerprint and plan_fingerprint != fingerprint:
        raise CommandSelectionError(
            "plan_changed",
            "The documented command set changed after review; run --plan-only again before execution.",
            candidates,
            fingerprint,
        )

    selected: Optional[Dict[str, Any]] = None
    selection_source = "policy"
    if command_id:
        selected = next((item for item in candidates if item["id"] == command_id), None)
        if selected is None:
            raise CommandSelectionError(
                "unknown_command_id",
                f"Unknown command id `{command_id}`; select one of the current plan candidates.",
                candidates,
                fingerprint,
            )
        selection_source = "reviewed_command_id"
    else:
        ranked = sorted(
            (item for item in candidates if item["auto_selectable"]),
            key=lambda item: (
                CATEGORY_PRIORITY.get(str(item.get("category")), 99),
                -int(item.get("score", 0)),
                item["id"],
            ),
        )
        if ranked:
            selected = ranked[0]
        elif candidates:
            selected = sorted(
                candidates,
                key=lambda item: (
                    CATEGORY_PRIORITY.get(str(item.get("category")), 99),
                    -int(item.get("score", 0)),
                    item["id"],
                ),
            )[0]
            selection_source = "policy_blocked_candidate"
        else:
            selected = None

    if selected is not None:
        return {
            "selected_goal": selected["category"],
            "goal_priority": selected["category"],
            "documented_command": selected["command"],
            "documented_command_id": selected["id"],
            "command_source": selected.get("source", "readme"),
            "documented_command_kind": selected.get("kind", "run"),
            "documented_command_section": selected.get("section"),
            "documented_command_source_file": selected.get("source_file"),
            "requires_substitution": bool(selected.get("needs_substitution")),
            "command_feasible": bool(selected.get("feasible")),
            "command_feasibility_reason": selected.get("feasibility_reason"),
            "selection_source": selection_source,
            "selection_fingerprint": fingerprint,
            "command_candidates": candidates,
            "goal_candidates": sorted(candidates, key=lambda item: item["selection_rank"])[:3],
        }

    return {
        "selected_goal": "repo-intake-only",
        "goal_priority": "other",
        "documented_command": "",
        "documented_command_id": None,
        "command_source": "none",
        "documented_command_kind": "none",
        "documented_command_section": None,
        "documented_command_source_file": None,
        "requires_substitution": False,
        "command_feasible": False,
        "command_feasibility_reason": "no auto-selectable README-backed run/smoke command",
        "selection_source": selection_source,
        "selection_fingerprint": fingerprint,
        "command_candidates": candidates,
        "goal_candidates": sorted(candidates, key=lambda item: item["selection_rank"])[:3],
    }


DOC_LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)\)")
DOC_PRIORITY_TOKENS = ("get_started", "getting_started", "install", "quick", "usage", "user_guide", "docs/")


def delegate_to_docs(readme_path: str, extract_script: Path, command_data: Dict[str, Any]) -> Dict[str, Any]:
    """When the README itself yields no runnable command, follow its local doc links.

    Real repos (e.g. mmsegmentation) keep all commands in docs/get_started
    files; without this the run degrades to repo-intake-only.
    """
    if any(item.get("kind") in {"run", "smoke"} for item in command_data.get("commands", [])):
        return command_data
    readme_file = Path(readme_path)
    readme_text = readme_file.read_text(encoding="utf-8-sig", errors="replace")
    links: List[tuple] = []
    for match in DOC_LINK_RE.finditer(readme_text):
        rel = match.group(1)
        if rel.startswith(("http://", "https://")):
            continue
        target = (readme_file.parent / rel).resolve()
        if target.exists() and target.suffix.lower() == ".md":
            links.append((rel, target))
    links.sort(key=lambda item: (0 if any(token in item[0].lower() for token in DOC_PRIORITY_TOKENS) else 1, len(item[0])))
    for rel, target in links[:3]:
        doc_data = run_json(extract_script, ["--readme", str(target), "--json"])
        doc_commands = doc_data.get("commands", [])
        for item in doc_commands:
            item["source_file"] = rel
        command_data["commands"].extend(doc_commands)
        if any(item.get("kind") in {"run", "smoke"} for item in doc_commands):
            command_data.setdefault("warnings", []).append(
                f"README had no runnable commands; delegated extraction to linked doc `{rel}`."
            )
            break
    return command_data


def plan_skill_chain(selected_goal: str, include_analysis_pass: bool, include_paper_gap: bool) -> List[str]:
    chain = [
        "repo-intake-and-plan",
        "env-and-assets-bootstrap",
    ]
    if include_analysis_pass:
        chain.append("analyze-project")
    chain.append("run-train" if selected_goal == "training" else "minimal-run-and-audit")
    if include_paper_gap:
        chain.append("paper-context-resolver")
    return chain


METRIC_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_.-]{1,31})\s*[:=]\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)
METRIC_NOISE_TOKENS = {"loss", "lr", "time", "mem", "epoch", "step", "iter", "iteration"}


def parse_observed_metrics(output_text: str) -> Dict[str, Any]:
    observed: Dict[str, float] = {}
    for match in METRIC_RE.finditer(output_text):
        observed[match.group(1)] = float(match.group(2))
    priority = [name for name in observed if not any(token in name.lower() for token in METRIC_NOISE_TOKENS)]
    chosen = priority[-1] if priority else (list(observed)[-1] if observed else None)
    return {
        "observed_metrics": observed,
        "best_metric": {"name": chosen, "value": observed[chosen]} if chosen else None,
    }


def parse_expected_metrics(values: List[str]) -> Dict[str, float]:
    expected: Dict[str, float] = {}
    for raw in values:
        name, separator, value_text = raw.partition("=")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"Expected metric must use NAME=VALUE syntax: {raw!r}")
        try:
            value = float(value_text.strip())
        except ValueError as exc:
            raise ValueError(f"Expected metric value is not numeric: {raw!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Expected metric value must be finite: {raw!r}")
        expected[name] = value
    return expected


def compare_expected_metrics(
    observed: Dict[str, Any],
    expected: Dict[str, float],
    absolute_tolerance: float,
) -> Dict[str, Any]:
    if not expected:
        return {
            "status": "not_evaluated",
            "reason": "No explicit expected metrics were supplied.",
            "absolute_tolerance": absolute_tolerance,
            "comparisons": [],
        }

    observed_by_key = {str(name).lower(): (str(name), value) for name, value in observed.items()}
    comparisons: List[Dict[str, Any]] = []
    for expected_name, expected_value in expected.items():
        matched_observed = observed_by_key.get(expected_name.lower())
        if matched_observed is None:
            comparisons.append(
                {
                    "metric": expected_name,
                    "expected": expected_value,
                    "observed": None,
                    "absolute_error": None,
                    "within_tolerance": False,
                    "reason": "metric_not_observed",
                }
            )
            continue
        observed_name, raw_observed_value = matched_observed
        try:
            observed_value = float(raw_observed_value)
        except (TypeError, ValueError):
            comparisons.append(
                {
                    "metric": expected_name,
                    "observed_name": observed_name,
                    "expected": expected_value,
                    "observed": raw_observed_value,
                    "absolute_error": None,
                    "within_tolerance": False,
                    "reason": "observed_value_not_numeric",
                }
            )
            continue
        absolute_error = abs(observed_value - expected_value)
        comparisons.append(
            {
                "metric": expected_name,
                "observed_name": observed_name,
                "expected": expected_value,
                "observed": observed_value,
                "absolute_error": absolute_error,
                "within_tolerance": absolute_error <= absolute_tolerance,
            }
        )

    matched = bool(comparisons) and all(item["within_tolerance"] for item in comparisons)
    return {
        "status": "matched" if matched else "mismatched",
        "reason": "All expected metrics are within tolerance." if matched else "At least one expected metric is missing or outside tolerance.",
        "absolute_tolerance": absolute_tolerance,
        "comparisons": comparisons,
    }


def maybe_run_command(
    repo_path: Path,
    command: str,
    timeout: int,
    user_language: str,
    shell_mode: str = "direct",
    runtime_root: Optional[Path] = None,
    model_adapter: Optional[Dict[str, Any]] = None,
    monitor_gpu: bool = False,
) -> Dict[str, Any]:
    if not command:
        return {
            "status": "not_run",
            "documented_command_status": "not_run",
            "execution_log": [],
            "main_blocker": text(
                user_language,
                "No documented command was extracted from README.",
                "README 中未提取到已文档化命令。",
            ),
        }

    selected_runtime_root = (runtime_root or (repo_path / "repro_outputs" / "_runtime")).resolve()
    result = run_persistent_command(
        repo=repo_path,
        command=command,
        timeout=timeout,
        runtime_root=selected_runtime_root,
        shell_mode=shell_mode,
        model_adapter=model_adapter,
        monitor_gpu=monitor_gpu,
    )
    if result.get("launch_error"):
        exc = result["launch_error"]
        return {
            "status": "blocked",
            "documented_command_status": "blocked",
            "execution_log": [f"Command failed before launch: {exc}"],
            "main_blocker": text(
                user_language,
                f"Executable not found for documented command: {exc}",
                f"文档命令缺少可执行程序：{exc}",
            ),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
        }
    if result.get("cancelled"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "execution_log": ["Command cancelled through the runtime control file."],
            "main_blocker": text(
                user_language,
                "The selected documented command was cancelled.",
                "选定的文档命令已取消。",
            ),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
        }
    if result.get("timed_out"):
        return {
            "status": "partial",
            "documented_command_status": "partial",
            "execution_log": [
                item for item in [
                    f"STDOUT:\n{result.get('stdout', '').strip()}" if result.get("stdout", "").strip() else "",
                    f"STDERR:\n{result.get('stderr', '').strip()}" if result.get("stderr", "").strip() else "",
                    f"Command timed out after {timeout} seconds.",
                ] if item
            ],
            "main_blocker": text(
                user_language,
                f"Selected documented command did not finish within {timeout} seconds.",
                f"选定的文档命令未在 {timeout} 秒内完成。",
            ),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
        }

    combined: List[str] = []
    if result.get("stdout", "").strip():
        combined.append("STDOUT:\n" + result["stdout"].strip())
    if result.get("stderr", "").strip():
        combined.append("STDERR:\n" + result["stderr"].strip())

    metric_data = parse_observed_metrics("\n".join([result.get("stdout", ""), result.get("stderr", "")]))

    if result.get("returncode") == 0:
        return {
            "status": "success",
            "documented_command_status": "success",
            "execution_log": combined,
            "main_blocker": text(user_language, "None.", "无。"),
            "execution_mode": shell_mode,
            **runtime_metadata(result),
            **metric_data,
        }

    return {
        "status": "partial",
        "documented_command_status": "partial",
        "execution_log": combined,
        **metric_data,
        "execution_mode": shell_mode,
        **runtime_metadata(result),
        "main_blocker": text(
            user_language,
            f"Selected documented command exited with code {result.get('returncode')}.",
            f"选定的文档命令以退出码 {result.get('returncode')} 结束。",
        ),
    }


def runtime_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "runtime_run_id",
        "runtime_dir",
        "runtime_status",
        "runtime_state_path",
        "runtime_events_path",
        "stdout_log_path",
        "stderr_log_path",
        "stdout_truncated",
        "stderr_truncated",
        "cancelled",
        "duration_seconds",
        "runtime_attempt",
        "runtime_retry_of",
        "resources_log_path",
        "resource_summary",
        "model_adapter",
    ]
    return {key: result.get(key) for key in keys}


def maybe_run_training(
    *,
    repo_path: Path,
    command: str,
    train_script: Path,
    lane: str,
    user_language: str,
    full_training_authorized: bool,
    train_timeout: int,
    dataset_hint: str,
    checkpoint_hint: str,
    resume_from: str,
    max_train_steps: int,
    shell_mode: str,
    runtime_root: Path,
    model_profile_json: str,
    required_model_capabilities: List[str],
    gpu_monitor_enabled: bool,
) -> Dict[str, Any]:
    if not command:
        return {
            "status": "not_run",
            "documented_command_status": "not_run",
            "execution_log": [],
            "main_blocker": text(
                user_language,
                "No documented training command was extracted from README.",
                "README 中未提取到已文档化训练命令。",
            ),
            "lane": lane,
            "run_mode": "startup_verification" if lane == "trusted" else "full_kickoff",
            "resume_from": resume_from or None,
            "dataset": dataset_hint,
            "checkpoint_source": checkpoint_hint,
            "max_steps": max_train_steps,
            "completed_steps": 0,
            "best_metric": None,
            "best_checkpoint": None,
            "stop_reason": "not_run",
            "last_epoch": None,
            "last_step": None,
            "observed_metrics": {},
            "checkpoint_candidates": [],
            "monitoring_scope": "not_run",
            "execution_mode": shell_mode,
        }

    if resume_from:
        run_mode = "resume"
    elif lane == "trusted" and not full_training_authorized:
        run_mode = "startup_verification"
    else:
        run_mode = "full_kickoff"

    training_args = [
            "--repo",
            str(repo_path),
            "--command",
            command,
            "--timeout",
            str(train_timeout),
            "--lane",
            lane,
            "--run-mode",
            run_mode,
            "--dataset",
            dataset_hint,
            "--checkpoint-source",
            checkpoint_hint,
            "--resume-from",
            resume_from,
            "--max-steps",
            str(max_train_steps),
            "--shell-mode",
            shell_mode,
            "--runtime-root",
            str(runtime_root),
        ]
    if model_profile_json:
        training_args.extend(["--model-profile-json", model_profile_json])
    for capability in required_model_capabilities:
        training_args.extend(["--require-model-capability", capability])
    if not gpu_monitor_enabled:
        training_args.append("--no-gpu-monitor")
    return run_json(train_script, training_args)


def build_context(
    *,
    chosen: Dict[str, Any],
    repo_path: Path,
    scan_data: Dict[str, Any],
    command_data: Dict[str, Any],
    setup_plan: Dict[str, Any],
    asset_data: Dict[str, Any],
    run_data: Dict[str, Any],
    user_language: str,
    run_selected: bool,
    include_analysis_pass: bool,
    include_paper_gap: bool,
    lane: str,
    full_training_authorized: bool,
    stage_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    skill_chain = plan_skill_chain(chosen["selected_goal"], include_analysis_pass, include_paper_gap)
    execution_skill = "run-train" if chosen["selected_goal"] == "training" else "minimal-run-and-audit"
    status = run_data["status"] if run_selected else "not_run"
    metric_acceptance_failed = (
        run_selected
        and run_data.get("runtime_status") == "success"
        and run_data.get("result_match", {}).get("status") == "mismatched"
    )
    documented_status = (
        run_data["documented_command_status"]
        if run_selected
        else ("not_run" if not chosen["documented_command"] else "documented")
    )

    structure = scan_data.get("structure", {})
    # Intake plans are not execution evidence, even when their provenance is documented.
    setup_commands = [dict(item, execution_status="not_run") for item in setup_plan.get("setup_commands", [])]
    asset_commands = build_asset_commands(asset_data, user_language)
    setup_advisories = list(setup_plan.get("unresolved_setup_risks", []))
    dataset_hint = run_data.get("dataset") or derive_dataset_hint(asset_data)
    checkpoint_hint = run_data.get("checkpoint_source") or derive_checkpoint_hint(asset_data)
    training_duration_hint = (
        estimate_training_duration(repo_path, chosen["documented_command"], int(run_data.get("max_steps") or 0))
        if chosen["selected_goal"] == "training" and chosen["documented_command"]
        else None
    )

    notes: List[str] = []
    notes.extend(scan_data.get("warnings", []))
    notes.extend(command_data.get("warnings", []))
    notes.extend(setup_plan.get("setup_notes", []))
    notes.extend(run_data.get("execution_log", []))

    assumptions = [
        "README remains the primary source of truth.",
        "Environment creation should prefer isolated setup before any semantic code changes.",
        "Model architecture should remain unchanged unless the researcher explicitly requests otherwise.",
    ]
    if chosen["selected_goal"] == "training" and lane == "trusted" and not full_training_authorized:
        assumptions.append("Only startup verification is allowed before the researcher explicitly authorizes a fuller training reproduction run.")

    unverified_inferences = [
        "Asset and dataset hints remain conservative until the repo or README confirms the exact path layout."
    ]
    protocol_deviations: List[str] = []
    human_decisions_required: List[str] = []

    if not chosen["documented_command"]:
        result_summary = text(
            user_language,
            "No documented runnable command was extracted. Repo intake was completed.",
            "未提取到可运行的文档命令，已完成仓库 intake。",
        )
    elif chosen["selected_goal"] != "training":
        result_summary = text(
            user_language,
            f"Selected goal `{chosen['selected_goal']}` from README evidence.",
            f"已根据 README 证据选择目标 `{chosen['selected_goal']}`。",
        )
    else:
        result_summary = text(
            user_language,
            "Selected the documented training command after no smaller inference or evaluation target was available.",
            "在没有更小的推理或评测目标时，已选择文档中的训练命令。",
        )

    if run_selected:
        if status == "success":
            result_summary = text(user_language, "Selected documented command finished successfully.", "选定的文档命令已成功完成。")
        elif metric_acceptance_failed:
            result_summary = text(
                user_language,
                "The documented command completed, but explicit metric acceptance failed; this is not a successful reproduction result.",
                "文档命令已完成，但显式指标验收未通过；本次结果不能视为复现成功。",
            )
        elif status == "partial":
            result_summary = (
                text(
                    user_language,
                    "Selected training command produced early training evidence within the current monitoring window.",
                    "选定的训练命令已在当前监控窗口内产生早期训练证据。",
                )
                if chosen["selected_goal"] == "training"
                else text(
                    user_language,
                    "Selected documented command started but did not complete cleanly.",
                    "选定的文档命令已启动，但未完整成功结束。",
                )
            )
        elif status == "blocked":
            result_summary = (
                text(user_language, "Selected training command could not be launched.", "选定的训练命令无法启动。")
                if chosen["selected_goal"] == "training"
                else text(user_language, "Selected documented command could not be launched.", "选定的文档命令无法启动。")
            )

    section = chosen.get("documented_command_section")
    command_notes = [
        text(
            user_language,
            f"README path: {scan_data.get('readme_path') or 'not found'}",
            f"README 路径：{scan_data.get('readme_path') or 'not found'}",
        ),
        text(
            user_language,
            f"Detected top-level entries: {', '.join(structure.get('top_level', [])) or 'none'}",
            f"检测到的顶层条目：{', '.join(structure.get('top_level', [])) or 'none'}",
        ),
    ]
    if setup_plan.get("environment_file"):
        command_notes.append(f"Environment plan source: {setup_plan['environment_file']}")
    command_notes.extend(setup_plan.get("setup_notes", []))
    if chosen["documented_command"]:
        source_note = text(
            user_language,
            f"Main run label: documented from README ({chosen.get('command_source', 'readme')})",
            f"主运行标签：来自 README 的 documented（{chosen.get('command_source', 'readme')}）",
        )
        if section:
            source_note += text(user_language, f", section `{section}`", f"，章节 `{section}`")
        command_notes.append(source_note)
        if chosen.get("documented_command_id"):
            command_notes.append(
                text(
                    user_language,
                    f"Reviewed command id: `{chosen['documented_command_id']}`; selection source: `{chosen.get('selection_source', 'policy')}`.",
                    f"已审阅命令 ID：`{chosen['documented_command_id']}`；选择来源：`{chosen.get('selection_source', 'policy')}`。",
                )
            )
    command_notes.append(f"Planned skill chain: {', '.join(skill_chain)}")

    # Setup discovery gaps are advisory until a selected action actually needs them.
    # Preserve every gap separately; an observed execution failure still requires review below.
    if chosen.get("requires_substitution"):
        human_decisions_required.append(text(user_language,
            "Substitute the placeholder values (<...>) in the selected documented command before execution.",
            "执行前请将选定文档命令中的占位符（<...>）替换为真实值。"))
    if not chosen["documented_command"]:
        human_decisions_required.append(text(user_language,
            "Select or confirm a documented runnable command before treating this as a reproduction run.",
            "先选择或确认可运行的文档命令，才能将本次操作视为复现执行。"))
    if chosen["selected_goal"] == "training" and lane == "trusted" and not full_training_authorized:
        human_decisions_required.append(text(user_language,
            "Review the startup verification evidence and confirm whether to continue with a fuller training reproduction run.",
            "检查启动验证证据，并确认是否继续更完整的训练复现。"))
    if metric_acceptance_failed:
        human_decisions_required.append(text(user_language,
            "Review missing or out-of-tolerance metrics against the recorded expectations and experiment protocol before accepting the result or changing the command.",
            "接受结果或调整命令前，请按已记录的期望值和实验协议检查缺失或超出容差的指标。"))
    elif run_selected and status in {"partial", "blocked"}:
        human_decisions_required.append(text(user_language,
            "Review the blocker before adapting commands, dependencies, or protocol-sensitive settings.",
            "调整命令、依赖或影响实验协议的设置前，请先检查阻塞原因。"))
    if include_paper_gap:
        human_decisions_required.append(text(user_language,
            "Provide a narrow paper question and an authoritative paper source before running paper-context-resolver.",
            "运行 paper-context-resolver 前，请提供具体的论文问题与权威论文来源。"))

    if metric_acceptance_failed:
        next_action = text(
            user_language,
            "Inspect `status.json.result_match` and the raw logs, then check metric names, data, preprocessing, checkpoints, and evaluation conditions. Do not widen tolerances or change expected values merely to obtain a pass.",
            "检查 `status.json.result_match` 和原始日志，再核对指标名称、数据、预处理、权重与评测条件。不要仅为通过验收而放宽容差或更改期望值。",
        )
        next_safe_action = text(
            user_language,
            "Preserve the failed acceptance evidence and review the mismatch before any retry or protocol change; command completion alone does not satisfy the expected result.",
            "保留验收失败证据，在重试或修改实验协议前检查不匹配原因；命令完成本身不代表已达到期望结果。",
        )
    elif (
        run_selected
        and chosen["selected_goal"] != "training"
        and run_data.get("runtime_status") == "timed_out"
    ):
        next_action = text(
            user_language,
            "Inspect the retained stdout/stderr to confirm whether the same documented command was still making progress. If the user's stated command-time budget allows it, rerun the same reviewed command with a larger `--timeout` within that bound; do not change dependencies, inputs, or the command merely to avoid the timeout.",
            "检查保留的 stdout/stderr，确认同一文档命令在超时时是否仍有进展。若用户给定的单命令时间预算允许，可在该上限内用更大的 `--timeout` 重跑同一已审核命令；不要仅为避开超时而修改依赖、输入或命令。",
        )
        next_safe_action = text(
            user_language,
            "Keep the reviewed command and protocol unchanged. Only increase `--timeout` up to the user's existing bound after confirming the timeout was the blocker; otherwise preserve the partial evidence and stop.",
            "保持已审核命令和实验协议不变。确认阻塞项确实只是超时后，才可在用户既有上限内增大 `--timeout`；否则保留 partial 证据并停止。",
        )
    elif run_selected and status == "blocked" and chosen.get("requires_substitution"):
        next_action = text(
            user_language,
            "Resolve the README placeholder values from documented repository context, then run --plan-only again before executing the updated concrete command.",
            "先从仓库文档中确定 README 占位符的真实值，再重新运行 --plan-only，确认具体命令后执行。",
        )
        next_safe_action = text(
            user_language,
            "Do not execute literal <...> placeholders or guess protocol-sensitive values; preserve the reviewed plan and replan after the concrete values are known.",
            "不要直接执行字面量 <...> 占位符，也不要猜测影响实验协议的值；确定真实值后重新生成并审核计划。",
        )
    elif run_selected and status == "blocked" and not chosen.get("command_feasible", True):
        feasibility_reason = str(chosen.get("command_feasibility_reason") or "")
        lowered_reason = feasibility_reason.lower()
        if "native shell" in lowered_reason or "shell syntax" in lowered_reason:
            next_action = text(
                user_language,
                f"Review the exact shell operators in `{chosen['documented_command']}`. If they are intended and authorized, rerun the same reviewed candidate with `--run-selected --command-id {chosen.get('documented_command_id')} --plan-fingerprint {chosen.get('selection_fingerprint')} --shell-mode native`.",
                f"检查 `{chosen['documented_command']}` 中的 shell 运算符；若确认文档确实要求且已授权，请使用同一已审核候选并加 `--run-selected --command-id {chosen.get('documented_command_id')} --plan-fingerprint {chosen.get('selection_fingerprint')} --shell-mode native` 重新执行。",
            )
            next_safe_action = text(
                user_language,
                "Keep direct mode as the default. Only after reviewing the exact documented command, rerun that reviewed candidate with `--shell-mode native`; do not broaden shell authorization globally.",
                "默认继续使用 direct 模式；仅在检查过该文档命令后，才对同一已审核候选加 `--shell-mode native` 重跑，不要扩大为全局 shell 授权。",
            )
        elif "download" in lowered_reason:
            next_action = text(
                user_language,
                "Review the documented model/asset download size and source, obtain explicit authorization for the download, then replan before execution.",
                "检查文档中的模型/资源下载来源与规模，取得明确下载授权后再重新计划并执行。",
            )
            next_safe_action = text(
                user_language,
                "Do not bypass the large-download gate by changing the command or silently fetching a different checkpoint.",
                "不要通过修改命令绕过大下载门槛，也不要静默改为下载其他 checkpoint。",
            )
        elif "directory is absent" in lowered_reason:
            next_action = text(
                user_language,
                "Satisfy the README-documented local prerequisite that produces the required output directory, then run --plan-only again.",
                "先按 README 满足会生成所需本地输出目录的前置步骤，然后重新运行 --plan-only。",
            )
            next_safe_action = text(
                user_language,
                "Do not invent a replacement checkpoint/output directory; preserve the documented producer-consumer relationship.",
                "不要自行编造替代 checkpoint/输出目录；保持文档中的生产者-消费者关系。",
            )
        else:
            next_action = text(
                user_language,
                f"Review the documented prerequisite before retrying: {feasibility_reason}",
                f"重试前先检查文档前置条件：{feasibility_reason}",
            )
            next_safe_action = text(
                user_language,
                "Keep the reviewed command unchanged until its documented prerequisite is satisfied, then replan.",
                "在满足文档前置条件前保持已审核命令不变，满足后重新计划。",
            )
    elif chosen["selected_goal"] == "training":
        if lane == "trusted" and not full_training_authorized:
            next_action = text(
                user_language,
                f"Review `train_outputs/status.json`, then decide whether to authorize a fuller training reproduction run. Planned command: `{chosen['documented_command']}`. Estimated duration: {training_duration_hint}.",
                f"先检查 `train_outputs/status.json`，再决定是否授权更完整的训练复现。计划继续执行的命令是：`{chosen['documented_command']}`。保守预估时长：{training_duration_hint}。",
            )
            next_safe_action = "Keep the repo unchanged, review startup evidence, and only continue with fuller training after explicit researcher approval."
        elif lane == "explore":
            next_action = text(
                user_language,
                "Review the recorded training evidence and continue isolated exploratory training if the variant still looks promising.",
                "先检查已记录的训练证据，如该变体仍有希望，再继续隔离的探索训练。",
            )
            next_safe_action = "Keep exploratory changes isolated and compare the recorded early metrics before widening the search."
        else:
            next_action = text(
                user_language,
                "Review the current training record and continue monitoring or resume from the latest checkpoint if needed.",
                "先检查当前训练记录，如有需要，再继续监控或从最新 checkpoint 恢复。",
            )
            next_safe_action = "Preserve the documented training semantics and continue from recorded checkpoints only if the current run remains faithful."
    else:
        next_action = (
            text(user_language, "Prepare environment and assets, then retry the documented command.", "先准备环境与资源，再重试该文档命令。")
            if status in {"partial", "blocked", "not_run"}
            else text(user_language,
                "Check the recorded evidence against the requested target, deliver the bounded result, and stop. Further experiments require a new request; this result alone does not establish paper-level reproduction.",
                "按本次请求核对已记录的证据，交付限定范围内的结果，然后停止。后续实验需要新的请求；本次结果本身不代表论文级复现。")
        )
        next_safe_action = (
            "Review setup assumptions and confirm the next documented command before making any semantic changes."
            if status in {"partial", "blocked", "not_run"}
            else text(user_language,
                "Verify the existing evidence and return the result to the user, then stop without launching additional commands or optional stages unless requested.",
                "核验现有证据并向用户交付结果，然后停止；未经请求，不启动额外命令或可选阶段。")
        )

    run_execution_status = run_data.get("runtime_status") or "not_run"
    run_commands = ([{
        "label": "documented", "command": chosen["documented_command"],
        "execution_status": run_execution_status,
        "execution_evidence": run_data.get("runtime_state_path"),
    }] if chosen["documented_command"] else [])
    verification_commands = (
        [{"label": "inferred", "command": "python - <<'PY'\nimport pathlib\nprint(pathlib.Path('train_outputs/status.json').exists())\nPY"}]
        if chosen["selected_goal"] == "training"
        else []
    )
    if chosen["selected_goal"] != "training":
        comparison_status = run_data.get("result_match", {}).get("status", "not_evaluated")
        command_notes.append(text(
            user_language,
            f"No separate verification command was executed. Built-in metric comparison: `{comparison_status}`; inspect `status.json.result_match` for expected values and tolerance.",
            f"未执行单独的验证命令。内置指标比较状态为 `{comparison_status}`；期望值与容差见 `status.json.result_match`。",
        ))
    for item in verification_commands:
        item["execution_status"] = "not_run"
    command_reporting = {
        "setup": "not_run", "assets": "not_run",
        "main_run": run_execution_status, "verification": "not_run",
    }

    evidence = [
        text(
            user_language,
            f"Detected files: {', '.join(scan_data.get('detected_files', [])) or 'none'}",
            f"检测到的文件：{', '.join(scan_data.get('detected_files', [])) or 'none'}",
        ),
        text(
            user_language,
            f"Command categories: {json.dumps(command_data.get('counts', {}), ensure_ascii=False)}",
            f"命令分类：{json.dumps(command_data.get('counts', {}), ensure_ascii=False)}",
        ),
        text(
            user_language,
            f"Selected command kind: {chosen.get('documented_command_kind', 'none')}",
            f"已选命令类型：{chosen.get('documented_command_kind', 'none')}",
        ),
    ]
    if setup_plan.get("environment_file"):
        evidence.append(f"Environment file: {setup_plan['environment_file']}")
    if asset_data.get("text_hints"):
        evidence.append(f"Asset hints detected: {len(asset_data['text_hints'])}")

    timeline = [
        text(user_language, "Scanned repository structure and key metadata files.", "已扫描仓库结构和关键元数据文件。"),
        text(user_language, "Extracted README code blocks and shell-like commands.", "已提取 README 中的代码块和 shell 风格命令。"),
        text(user_language, f"Selected `{chosen['selected_goal']}` as the smallest trustworthy target.", f"已将 `{chosen['selected_goal']}` 选为最小可信目标。"),
        text(user_language, "Prepared conservative setup and asset assumptions.", "已准备保守的环境与资源假设。"),
        text(user_language, "Execution step was skipped." if not run_selected else "Attempted the selected documented command.", "执行步骤已跳过。" if not run_selected else "已尝试选定的文档命令。"),
    ]
    if chosen["selected_goal"] == "training":
        timeline.append(text(user_language, f"Training lane `{lane}` selected with run mode `{run_data.get('run_mode', 'startup_verification')}`.", f"已选择训练 lane `{lane}`，运行模式为 `{run_data.get('run_mode', 'startup_verification')}`。"))
        if training_duration_hint:
            timeline.append(text(user_language, f"Estimated fuller training duration: {training_duration_hint}.", f"保守估计完整训练时长：{training_duration_hint}。"))

    artifact_provenance = [
        {"artifact": "readme", "source": scan_data.get("readme_path") or "not found", "kind": "repo_file"},
        {"artifact": "documented_command", "source": chosen.get("command_source", "none"), "kind": "readme_extraction"},
        {"artifact": "environment_plan", "source": setup_plan.get("environment_file") or "inferred", "kind": "setup_plan"},
        {"artifact": "asset_manifest", "source": "artifacts/assets/asset_manifest.json", "kind": "generated"},
        {"artifact": "output_dir", "source": "repro_outputs/", "kind": "generated"},
    ]
    if chosen["selected_goal"] == "training":
        artifact_provenance.append({"artifact": "train_outputs", "source": "train_outputs/", "kind": "generated"})

    return {
        "schema_version": "1.0",
        "generated_at": scan_data.get("generated_at"),
        "user_language": user_language,
        "target_repo": str(repo_path.resolve()),
        "readme_first": True,
        "lane": lane,
        "selected_goal": chosen["selected_goal"],
        "goal_priority": chosen["goal_priority"],
        "execution_skill": execution_skill,
        "planned_skill_chain": skill_chain,
        "stage_results": stage_results,
        "status": status,
        "documented_command_status": documented_status,
        "documented_command": chosen["documented_command"] or "None extracted",
        "documented_command_id": chosen.get("documented_command_id"),
        "documented_command_kind": chosen.get("documented_command_kind", "none"),
        "documented_command_source": chosen.get("command_source", "none"),
        "documented_command_section": chosen.get("documented_command_section"),
        "documented_command_source_file": chosen.get("documented_command_source_file"),
        "requires_substitution": bool(chosen.get("requires_substitution")),
        "command_feasible": bool(chosen.get("command_feasible")),
        "command_feasibility_reason": chosen.get("command_feasibility_reason"),
        "selection_source": chosen.get("selection_source"),
        "selection_fingerprint": chosen.get("selection_fingerprint"),
        "command_candidates": chosen.get("command_candidates", []),
        "goal_candidates": chosen.get("goal_candidates", []),
        "evidence_level": "direct" if chosen["documented_command"] else "mixed",
        "result_summary": result_summary,
        "main_blocker": run_data.get("main_blocker", text(user_language, "No blocker recorded.", "未记录阻塞项。")),
        "next_action": next_action,
        "next_safe_action": next_safe_action,
        "setup_commands": setup_commands,
        "asset_commands": asset_commands,
        "run_commands": run_commands,
        "verification_commands": verification_commands,
        "command_notes": command_notes,
        "command_reporting": command_reporting,
        "setup_advisories": setup_advisories,
        "timeline": timeline,
        "assumptions": assumptions,
        "unverified_inferences": unverified_inferences,
        "evidence": evidence,
        "blockers": [run_data.get("main_blocker", text(user_language, "None.", "无。"))],
        "protocol_deviations": protocol_deviations,
        "human_decisions_required": human_decisions_required,
        "artifact_provenance": artifact_provenance,
        "notes": notes,
        "patches_applied": False,
        "patch_branch": "",
        "readme_fidelity": "preserved",
        "highest_patch_risk": "low",
        "verified_commits": [],
        "validation_summary": "",
        "patch_notes": [],
        "full_training_authorized": full_training_authorized,
        "requires_full_training_confirmation": chosen["selected_goal"] == "training" and lane == "trusted" and not full_training_authorized,
        "run_mode": run_data.get("run_mode", "startup_verification" if chosen["selected_goal"] == "training" else None),
        "resume_from": run_data.get("resume_from"),
        "dataset": dataset_hint,
        "checkpoint_source": checkpoint_hint,
        "full_training_command": chosen["documented_command"] if chosen["selected_goal"] == "training" else None,
        "training_duration_hint": training_duration_hint,
        "max_steps": run_data.get("max_steps"),
        "completed_steps": run_data.get("completed_steps"),
        "best_metric": run_data.get("best_metric"),
        "best_checkpoint": run_data.get("best_checkpoint"),
        "stop_reason": run_data.get("stop_reason"),
        "last_epoch": run_data.get("last_epoch"),
        "last_step": run_data.get("last_step"),
        "observed_metrics": run_data.get("observed_metrics", {}),
        "result_match": run_data.get("result_match", {"status": "not_evaluated"}),
        "checkpoint_candidates": run_data.get("checkpoint_candidates", []),
        "monitoring_scope": run_data.get("monitoring_scope"),
        "execution_mode": run_data.get("execution_mode", "direct"),
        "runtime_run_id": run_data.get("runtime_run_id"),
        "runtime_dir": run_data.get("runtime_dir"),
        "runtime_status": run_data.get("runtime_status"),
        "runtime_state_path": run_data.get("runtime_state_path"),
        "runtime_events_path": run_data.get("runtime_events_path"),
        "stdout_log_path": run_data.get("stdout_log_path"),
        "stderr_log_path": run_data.get("stderr_log_path"),
        "stdout_truncated": run_data.get("stdout_truncated", False),
        "stderr_truncated": run_data.get("stderr_truncated", False),
        "cancelled": run_data.get("cancelled", False),
        "duration_seconds": run_data.get("duration_seconds"),
        "runtime_attempt": run_data.get("runtime_attempt"),
        "runtime_retry_of": run_data.get("runtime_retry_of"),
        "resources_log_path": run_data.get("resources_log_path"),
        "resource_summary": run_data.get("resource_summary", {}),
        "model_adapter": run_data.get("model_adapter"),
    }


def main() -> int:
    started_monotonic = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run a minimal README-first reproduction orchestration.")
    parser.add_argument("--repo", required=True, help="Path to the target repository.")
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory to write standardized outputs into (default: <repo>/repro_outputs).",
    )
    parser.add_argument("--source-adjacent-readme", action="store_true", help="Also write an owned RIGORPILOT_README.md beside the original README, preserving relative media paths.")
    parser.add_argument("--train-output-dir", default="", help="Optional override for the supplemental training output directory.")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Optional runtime state root (default: <output-dir>/_runtime).",
    )
    parser.add_argument("--model-profile-json", default="", help="Optional provider-neutral model identity/capability profile.")
    parser.add_argument(
        "--require-model-capability",
        action="append",
        default=[],
        help="Required model capability; repeat as needed.",
    )
    parser.add_argument("--monitor-gpu", action="store_true", help="Sample NVIDIA telemetry for non-training commands too.")
    parser.add_argument("--no-gpu-monitor", action="store_true", help="Disable NVIDIA telemetry for training commands.")
    parser.add_argument("--user-language", default="en", help="Language tag for human-readable reports.")
    parser.add_argument("--run-selected", action="store_true", help="Execute the selected documented command.")
    parser.add_argument(
        "--command-id",
        default="",
        help="Select a README-backed command id returned by --plan-only; never accepts arbitrary shell text.",
    )
    parser.add_argument(
        "--plan-fingerprint",
        default="",
        help="Bind --command-id to the exact candidate set returned by the reviewed plan.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Inspect README/setup signals and print the selected command plus side-effect contract without writing evidence or executing target code.",
    )
    parser.add_argument(
        "--verify-output",
        action="store_true",
        help="Verify an existing evidence bundle and print a compact result without executing target code.",
    )
    parser.add_argument(
        "--agent-output",
        action="store_true",
        help="Print a compact agent-facing result; the durable evidence bundle remains unchanged.",
    )
    parser.add_argument("--include-analysis-pass", action="store_true", help="Run analyze-project and record its outputs in the stage ledger.")
    parser.add_argument(
        "--include-paper-gap",
        action="store_true",
        help="Request paper-context-resolver; records a blocked stage until a narrow question and source are supplied.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help=(
            "Target-command timeout in seconds for non-training documented commands. "
            "Do not wrap the whole orchestrator in an equal or shorter external timeout; "
            "cleanup and terminal evidence finalization occur after the target deadline."
        ),
    )
    parser.add_argument(
        "--train-timeout",
        type=int,
        default=120,
        help=(
            "Target training monitoring timeout in seconds. Pass the intended bound during --plan-only "
            "so reviewed_run_args binds it; do not wrap the whole orchestrator in an equal or shorter external timeout."
        ),
    )
    parser.add_argument("--lane", choices=["trusted", "explore"], default="trusted", help="Execution lane policy.")
    parser.add_argument("--full-training-authorized", action="store_true", help="Allow the orchestrator to proceed beyond startup verification for training.")
    parser.add_argument("--resume-from", default="", help="Optional checkpoint path to pass through to run-train.")
    parser.add_argument("--max-train-steps", type=int, default=0, help="Optional expected max train steps for reporting.")
    parser.add_argument(
        "--expected-metric",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Explicit expected metric for result matching. Repeat for multiple metrics.",
    )
    parser.add_argument(
        "--metric-absolute-tolerance",
        type=float,
        default=0.0,
        help="Maximum absolute error allowed for every --expected-metric value.",
    )
    parser.add_argument(
        "--shell-mode",
        choices=["direct", "native"],
        default="direct",
        help="Use direct argv execution by default; native shell execution requires explicit opt-in after review.",
    )
    args = parser.parse_args()

    if args.plan_only and args.run_selected:
        parser.error("--plan-only cannot be combined with --run-selected")
    if args.verify_output and (args.plan_only or args.run_selected):
        parser.error("--verify-output cannot be combined with --plan-only or --run-selected")
    if args.plan_fingerprint and not args.command_id:
        parser.error("--plan-fingerprint requires --command-id")

    if args.timeout <= 0 or args.train_timeout <= 0:
        parser.error("--timeout and --train-timeout must be greater than zero")
    if args.metric_absolute_tolerance < 0 or not math.isfinite(args.metric_absolute_tolerance):
        parser.error("--metric-absolute-tolerance must be a finite non-negative number")
    try:
        expected_metrics = parse_expected_metrics(args.expected_metric)
    except ValueError as exc:
        parser.error(str(exc))

    repo_path = Path(args.repo).resolve()
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else (repo_path / "repro_outputs").resolve()
    )
    if args.verify_output:
        verification = verify_existing_output(repo_path, output_dir)
        print(json.dumps(verification, indent=2, ensure_ascii=False))
        return 0 if verification.get("evidence_valid") else 1

    source_skills_dir = Path(__file__).resolve().parents[2]
    bundled_skills_dir = SKILL_ROOT / "_bundled" / "skills"
    base_dir = (
        source_skills_dir
        if (source_skills_dir / "repo-intake-and-plan" / "scripts" / "scan_repo.py").is_file()
        else bundled_skills_dir
    )
    scan_script = base_dir / "repo-intake-and-plan" / "scripts" / "scan_repo.py"
    extract_script = base_dir / "repo-intake-and-plan" / "scripts" / "extract_commands.py"
    setup_script = base_dir / "env-and-assets-bootstrap" / "scripts" / "plan_setup.py"
    asset_script = base_dir / "env-and-assets-bootstrap" / "scripts" / "prepare_assets.py"
    repro_write_script = base_dir / "minimal-run-and-audit" / "scripts" / "write_outputs.py"
    train_write_script = base_dir / "run-train" / "scripts" / "write_outputs.py"
    train_execute_script = base_dir / "run-train" / "scripts" / "run_training.py"
    analyze_script = base_dir / "analyze-project" / "scripts" / "analyze_project.py"

    scan_data = run_json(scan_script, ["--repo", str(repo_path), "--json"])
    readme_path = scan_data.get("readme_path")
    command_data: Dict[str, Any] = {"commands": [], "counts": {}, "warnings": []}
    if readme_path:
        command_data = run_json(extract_script, ["--readme", readme_path, "--json"])
        command_data = delegate_to_docs(readme_path, extract_script, command_data)

    train_output_dir = Path(args.train_output_dir).resolve() if args.train_output_dir else output_dir.parent / "train_outputs"
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else output_dir / "_runtime"
    try:
        model_adapter = load_model_profile(Path(args.model_profile_json) if args.model_profile_json else None)
        missing_model_capabilities = missing_capabilities(model_adapter, args.require_model_capability)
    except ModelAdapterError as exc:
        parser.error(str(exc))
    if missing_model_capabilities:
        parser.error(f"model profile is missing required capabilities: {', '.join(missing_model_capabilities)}")
    setup_plan = run_json(setup_script, ["--repo", str(repo_path), "--json"])
    if args.command_id and args.run_selected and not args.plan_fingerprint:
        candidates = build_command_candidates(command_data.get("commands", []), repo_path, args.shell_mode)
        error = CommandSelectionError(
            "review_token_required",
            "Executing an explicit command id requires the selection fingerprint returned by --plan-only.",
            candidates,
            _candidate_fingerprint(candidates),
        )
        print(json.dumps(selection_error_payload(error), indent=2, ensure_ascii=False))
        return 2
    try:
        chosen = choose_goal(
            command_data.get("commands", []),
            repo_path,
            args.shell_mode,
            args.command_id,
            args.plan_fingerprint,
        )
    except CommandSelectionError as exc:
        print(json.dumps(selection_error_payload(exc), indent=2, ensure_ascii=False))
        return 2
    if args.plan_only:
        print(
            json.dumps(
                plan_payload(chosen, setup_plan, args.shell_mode, args.timeout, args.train_timeout),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    assets_root = output_dir.parent / "artifacts" / "assets"
    asset_manifest_path = assets_root / "asset_manifest.json"
    asset_data = run_json(
        asset_script,
        [
            "--repo",
            str(repo_path),
            "--assets-root",
            str(assets_root),
            "--output-json",
            str(asset_manifest_path),
        ],
    )

    stage_results: List[Dict[str, Any]] = [
        {
            "stage": "repo-intake-and-plan",
            "status": "success",
            "detail": "Repository metadata and README commands were inspected.",
        },
        {
            "stage": "env-and-assets-bootstrap",
            "status": "success",
            "detail": "Setup plan and asset manifest were generated without installing dependencies.",
            "outputs": [str(asset_manifest_path)],
        },
    ]
    if args.include_analysis_pass:
        analysis_output_dir = output_dir.parent / "analysis_outputs"
        try:
            run_json(
                analyze_script,
                ["--repo", str(repo_path), "--output-dir", str(analysis_output_dir)],
            )
            stage_results.append(
                {
                    "stage": "analyze-project",
                    "status": "success",
                    "detail": "Read-only project analysis completed.",
                    "outputs": [str(analysis_output_dir / "status.json")],
                }
            )
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            stage_results.append(
                {
                    "stage": "analyze-project",
                    "status": "blocked",
                    "detail": f"Read-only project analysis failed: {type(exc).__name__}: {exc}",
                }
            )

    source_snapshot_ignores = [output_dir, train_output_dir, runtime_root, assets_root]
    source_before = (
        tracked_source_snapshot(repo_path, source_snapshot_ignores)
        if args.run_selected else
        {"status": "not_requested", "files": {}, "untracked_source_files": {}}
    )
    dataset_hint = derive_dataset_hint(asset_data)
    checkpoint_hint = derive_checkpoint_hint(asset_data)
    run_data: Dict[str, Any] = {
        "status": "not_run",
        "documented_command_status": "not_run",
        "execution_log": [],
        "main_blocker": text(args.user_language, "Execution was not requested.", "未请求执行。"),
        "lane": args.lane,
        "run_mode": "startup_verification" if chosen["selected_goal"] == "training" and args.lane == "trusted" and not args.full_training_authorized else ("full_kickoff" if chosen["selected_goal"] == "training" else None),
        "resume_from": args.resume_from or None,
        "dataset": dataset_hint,
        "checkpoint_source": checkpoint_hint,
        "max_steps": args.max_train_steps,
        "completed_steps": 0,
        "best_metric": None,
        "best_checkpoint": None,
        "stop_reason": "not_run" if chosen["selected_goal"] == "training" else None,
        "last_epoch": None,
        "last_step": None,
        "observed_metrics": {},
        "result_match": {"status": "not_evaluated", "reason": "Execution was not requested.", "comparisons": []},
        "checkpoint_candidates": [],
        "monitoring_scope": "not_run",
        "execution_mode": args.shell_mode,
        "model_adapter": model_adapter,
    }
    if args.run_selected and chosen.get("requires_substitution"):
        run_data["status"] = "blocked"
        run_data["documented_command_status"] = "blocked"
        run_data["main_blocker"] = text(
            args.user_language,
            "Documented command contains placeholder values (<...>); substitute them before execution.",
            "文档命令包含占位符（<...>），需要先替换为真实值再执行。",
        )
    elif args.run_selected and chosen.get("documented_command") and not chosen.get("command_feasible", True):
        run_data["status"] = "blocked"
        run_data["documented_command_status"] = "blocked"
        run_data["main_blocker"] = text(
            args.user_language,
            f"Selected documented command is not safe to run under the current plan: {chosen.get('command_feasibility_reason')}",
            f"当前计划下不应直接执行选定的文档命令：{chosen.get('command_feasibility_reason')}",
        )
    elif args.run_selected:
        if chosen["selected_goal"] == "training":
            run_data = maybe_run_training(
                repo_path=repo_path,
                command=chosen["documented_command"],
                train_script=train_execute_script,
                lane=args.lane,
                user_language=args.user_language,
                full_training_authorized=args.full_training_authorized,
                train_timeout=args.train_timeout,
                dataset_hint=dataset_hint,
                checkpoint_hint=checkpoint_hint,
                resume_from=args.resume_from,
                max_train_steps=args.max_train_steps,
                shell_mode=args.shell_mode,
                runtime_root=runtime_root,
                model_profile_json=args.model_profile_json,
                required_model_capabilities=args.require_model_capability,
                gpu_monitor_enabled=not args.no_gpu_monitor,
            )
        else:
            run_data = maybe_run_command(
                repo_path,
                chosen["documented_command"],
                args.timeout,
                args.user_language,
                args.shell_mode,
                runtime_root,
                model_adapter,
                args.monitor_gpu,
            )

    run_data["result_match"] = compare_expected_metrics(
        run_data.get("observed_metrics", {}),
        expected_metrics,
        args.metric_absolute_tolerance,
    )
    if (
        args.run_selected
        and run_data.get("runtime_status") == "success"
        and run_data.get("status") in {"success", "partial"}
        and run_data["result_match"]["status"] == "mismatched"
    ):
        # Keep command/runtime success as process evidence, but never let exit 0
        # override an explicitly failed result criterion in the overall outcome.
        run_data["status"] = "partial"
        run_data["main_blocker"] = text(
            args.user_language,
            "Explicit metric acceptance failed: at least one expected metric is missing or outside the configured absolute tolerance. Inspect `status.json.result_match` for per-metric evidence.",
            "显式指标验收未通过：至少一个期望指标缺失或超出设定的绝对容差。逐项证据见 `status.json.result_match`。",
        )

    source_integrity = (
        compare_source_snapshots(
            source_before,
            tracked_source_snapshot(repo_path, source_snapshot_ignores),
        )
        if args.run_selected else
        {"status": "not_requested", "unchanged": None, "changed_files": []}
    )
    if args.run_selected and source_integrity.get("unchanged") is False:
        if run_data.get("status") == "success":
            run_data["status"] = "partial"
        run_data["main_blocker"] = text(
            args.user_language,
            "The selected command changed tracked source or introduced unexpected untracked source/config files; preserve the evidence and review those changes before accepting the run.",
            "选定命令修改了已跟踪源码，或引入了意外的未跟踪源码/配置文件；请保留证据并审查这些变更后再接受本次运行。",
        )

    execution_stage = "run-train" if chosen["selected_goal"] == "training" else "minimal-run-and-audit"
    stage_results.append(
        {
            "stage": execution_stage,
            "status": run_data["status"] if args.run_selected else "not_requested",
            "detail": (
                "Selected documented command was attempted."
                if args.run_selected
                else "Execution was not requested; no command was run."
            ),
        }
    )
    if args.include_paper_gap:
        stage_results.append(
            {
                "stage": "paper-context-resolver",
                "status": "blocked",
                "detail": "A narrow paper question and authoritative paper source were not supplied.",
            }
        )

    context = build_context(
        chosen=chosen,
        repo_path=repo_path,
        scan_data=scan_data,
        command_data=command_data,
        setup_plan=setup_plan,
        asset_data=asset_data,
        run_data=run_data,
        user_language=args.user_language,
        run_selected=args.run_selected,
        include_analysis_pass=args.include_analysis_pass,
        include_paper_gap=args.include_paper_gap,
        lane=args.lane,
        full_training_authorized=args.full_training_authorized,
        stage_results=stage_results,
    )
    context["source_integrity"] = source_integrity
    if args.run_selected and source_integrity.get("unchanged") is False:
        context["human_decisions_required"].append(text(
            args.user_language,
            "Review the tracked changes and unexpected untracked source/config files before any reproduction claim.",
            "在做出任何复现结论前，请审查已跟踪文件变更以及意外新增的未跟踪源码/配置文件。",
        ))
        context["protocol_deviations"].append(
            "Target command changed source/config files: " + ", ".join(source_integrity.get("changed_files", []))
        )
    error_code = classify_execution_error(
        run_selected=args.run_selected,
        chosen=chosen,
        run_data=run_data,
        source_integrity=source_integrity,
    )
    context["error"] = build_error_record(context, error_code)

    context["annotated_readme"] = None
    context["readme_section_coverage"] = {}
    context["source_adjacent_readme"] = {"status": "not_requested", "path": None}
    if readme_path and Path(readme_path).exists():
        annotated_path, coverage = write_annotated_readme(
            readme_path=Path(readme_path),
            context={
                **context,
                "readme_commands": command_data.get("commands", []),
                "execution_log": run_data.get("execution_log", []),
                "local_dataset_present": any(
                    item.get("asset_group") in {"datasets", "data"} and item.get("status") == "present"
                    for item in asset_data.get("manifest", [])
                ),
            },
            output_path=output_dir / "ANNOTATED_README.md",
            source_adjacent=args.source_adjacent_readme,
            train_output_dir=train_output_dir,
        )
        context["annotated_readme"] = str(annotated_path)
        context["readme_section_coverage"] = coverage
        context["source_adjacent_readme"] = coverage["source_adjacent_readme"]
    elif args.source_adjacent_readme:
        context["source_adjacent_readme"] = {"status": "blocked", "path": None, "reason": "No source README was found; standard evidence retained."}

    invocation_path = output_dir / "invocation.json"
    evidence_manifest_path = output_dir / "evidence_manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    context["invocation_path"] = str(invocation_path)
    context["evidence_manifest_path"] = str(evidence_manifest_path)

    write_bundle(repro_write_script, output_dir, context)
    if context["selected_goal"] == "training":
        write_bundle(train_write_script, train_output_dir, context)

    context["lesson_recorded"] = maybe_record_lesson(repo_path, context) if args.run_selected else None

    invocation = {
        "schema_version": "1.0",
        "argv": [sys.executable, *sys.argv],
        "cwd": os.getcwd(),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "run_selected": bool(args.run_selected),
        "selected_goal": context.get("selected_goal"),
        "selected_command_id": context.get("documented_command_id"),
        "documented_command": context.get("documented_command"),
        "selection_source": context.get("selection_source"),
        "selection_fingerprint": context.get("selection_fingerprint"),
        "error": context.get("error"),
        "source_integrity": source_integrity,
    }
    invocation_path.write_text(json.dumps(invocation, indent=2, ensure_ascii=False), encoding="utf-8")
    write_evidence_manifest(repo_path, output_dir, context, invocation_path)

    payload = compact_agent_payload(context, output_dir, invocation_path, source_integrity) if args.agent_output else context
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
