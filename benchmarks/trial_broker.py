#!/usr/bin/env python3
"""Neutral read/execute broker for the three reviewed pilot tasks.

This is a tool-access boundary, NOT an OS sandbox. The operator owns the task
manifest, interpreter, evidence and working directory. Models cannot supply
shell commands, execution receipts or grader files through this interface.
The optional skill namespace is read-only; bundled helpers are not executable.
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat

from paired_eval import execute_step, write_new
from paired_tasks import TASK_IDS, grade_task


MAX_READ_BYTES = 64 * 1024
MAX_TREE_BYTES = 32 * 1024 * 1024
_OUTPUTS = {"data/samples.csv", "results/metrics.json", "results/predictions.json"}
_COMMANDS = {
    "micrograd": {"gradient-tests": ["python", "-m", "pytest", "--junitxml", "{attempt}/pytest.xml"]},
    "missing_asset": {"prepare-data": ["python", "prepare_data.py"], "evaluate": ["python", "evaluate.py"]},
    "wrong_metric": {"evaluate": ["python", "evaluate.py"]},
}


class BrokerError(ValueError):
    """Rejected tool request or changed operator-owned execution boundary."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _linked(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    # Path.is_junction is absent in Python 3.11, which CI also supports.
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _unlinked(path: Path) -> None:
    for component in (path, *path.parents):
        if _linked(component):
            raise BrokerError("unsafe_path", "Linked path components are not allowed")


def _relative(relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
            or "\0" in relative or Path(relative).is_absolute() or PureWindowsPath(relative).anchor
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise BrokerError("unsafe_path", "Expected a plain in-scope relative file path")
    return Path(relative)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _snapshot(root: Path) -> tuple[dict[str, str], set[str]]:
    """Walk without following links, including hidden files and empty folders."""
    _unlinked(root)
    if not root.is_dir():
        raise BrokerError("missing_scope", "A required scope directory is unavailable")
    files, directories, total = {}, set(), 0
    for parent, names, filenames in os.walk(root, followlinks=False):
        for name in [*names, *filenames]:
            path = Path(parent) / name
            if _linked(path):
                raise BrokerError("unsafe_path", "Linked entries are not permitted in a tool scope")
            relative = path.relative_to(root).as_posix()
            _relative(relative)
            if path.is_dir():
                directories.add(relative)
            elif path.is_file():
                total += path.stat().st_size
                if total > MAX_TREE_BYTES:
                    raise BrokerError("storage_limit", "Tool scope exceeds its 32 MiB inspection limit")
                files[relative] = _digest(path)
            else:
                raise BrokerError("unsafe_path", "Only regular files and directories are allowed")
    return files, directories


def _parents(files: set[str]) -> set[str]:
    return {parent.as_posix() for name in files for parent in Path(name).parents if str(parent) != "."}


class TrialBroker:
    """Single-owner broker. Task metadata is trusted operator input, not a tool argument."""

    boundary = {"mode": "broker_scoped", "execution": "reviewed_commands_only", "os_sandbox": False,
                "skill_access": "read_only", "environment": "same interpreter; not hard environment isolation"}

    def __init__(self, repo: Path, evidence: Path, task: dict, python: str, skill_root: Path | None = None):
        def operator_root(value: Path) -> Path:
            # Only the operator selects roots. Resolve OS parent aliases (for
            # example macOS /var -> /private/var) once, then freeze the physical
            # path. A linked selected root itself is still not accepted.
            selected = Path(value).absolute()
            if _linked(selected):
                raise BrokerError("unsafe_path", "Selected scope roots must not themselves be linked")
            return selected.resolve()

        self.repo, self.evidence = operator_root(repo), operator_root(evidence)
        self.skill_root = operator_root(skill_root) if skill_root is not None else None
        roots = [self.repo, self.evidence] + ([self.skill_root] if self.skill_root is not None else [])
        for root in roots:
            _unlinked(root)
        for index, first in enumerate(roots):
            for second in roots[index + 1:]:
                if first.resolve().is_relative_to(second.resolve()) or second.resolve().is_relative_to(first.resolve()):
                    raise BrokerError("overlapping_scopes", "Repository, skill and private evidence must be disjoint")
        self._task = copy.deepcopy(task)
        if not isinstance(self._task, dict) or self._task.get("task_id") not in TASK_IDS:
            raise BrokerError("invalid_task", "Only the three reviewed frozen tasks are supported")
        self._task_id = self._task["task_id"]
        try:
            commands = self._task["commands"]
            self._commands = {command["id"]: command for command in commands}
            if (len(self._commands) != len(commands)
                    or {key: value["argv"] for key, value in self._commands.items()} != _COMMANDS[self._task_id]):
                raise ValueError("unreviewed command")
            self._originals = dict(self._task["immutable_sha256"])
            if not self._originals:
                raise ValueError("empty baseline")
            for name in self._originals:
                _relative(name)
        except (KeyError, TypeError, ValueError) as error:
            raise BrokerError("invalid_task", "Invalid frozen sources or reviewed command set") from error
        actual, directories = _snapshot(self.repo)
        if actual != self._originals or directories != _parents(set(self._originals)):
            raise BrokerError("source_changed", "Initial repository must exactly match the frozen source tree")
        self._generated: dict[str, str] = {}
        self._allowed_outputs = set() if self._task_id == "micrograd" else _OUTPUTS - set(self._originals)
        self._allowed_directories = _parents(set(self._originals) | self._allowed_outputs)
        self._skill_files, self._skill_directories = _snapshot(self.skill_root) if self.skill_root else ({}, set())
        self._requested_python = python
        found = shutil.which(python)
        if found is None:
            raise BrokerError("interpreter_unavailable", "Selected existing Python executable is unavailable")
        self.python = str(Path(found).resolve())
        self._python_identity = self._interpreter_identity()
        self.evidence.mkdir(parents=True, exist_ok=True)
        self._command_root = self.evidence / "commands"
        if self._command_root.exists() or _linked(self._command_root):
            raise BrokerError("existing_evidence", "Command evidence requires a fresh directory")
        self._command_root.mkdir()
        self._records: list[tuple[Path, dict]] = []
        self._sequence = 0
        self.timeout_seconds = 45
        self.finished = False
        self.grade: dict | None = None

    @property
    def executions(self) -> list[dict]:
        """Read-only copies for the operator; tool callers cannot inject receipts."""
        return [copy.deepcopy(record) for _, record in self._records]

    def _interpreter_identity(self) -> tuple:
        found = shutil.which(self._requested_python)
        if found is None or str(Path(found).resolve()) != self.python:
            raise BrokerError("interpreter_changed", "Selected Python executable no longer resolves identically")
        info = Path(self.python).stat()
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def _check_repo(self, accept_generated: bool = False) -> dict[str, str]:
        actual, directories = _snapshot(self.repo)
        if any(actual.get(name) != digest for name, digest in self._originals.items()):
            raise BrokerError("source_changed", "Frozen repository sources changed or disappeared")
        generated = {name: digest for name, digest in actual.items() if name not in self._originals}
        if set(generated) - self._allowed_outputs or directories - self._allowed_directories:
            raise BrokerError("unexpected_file", "Repository contains an unauthorized file or directory")
        if not accept_generated and generated != self._generated:
            raise BrokerError("artifact_changed", "Generated files changed outside a collected command")
        return generated

    def _scope(self, scope: str) -> tuple[Path, dict[str, str]]:
        if scope == "repo":
            self._check_repo()
            return self.repo, {**self._originals, **self._generated}
        if scope == "skill" and self.skill_root is not None:
            current, directories = _snapshot(self.skill_root)
            if current != self._skill_files or directories != self._skill_directories:
                raise BrokerError("skill_changed", "Installed read-only skill namespace changed")
            return self.skill_root, self._skill_files
        raise BrokerError("scope_denied", "Only this trial's repository and optional installed skill are readable")

    @staticmethod
    def _arguments(args: dict, expected: set[str]) -> None:
        if not isinstance(args, dict) or set(args) != expected:
            raise BrokerError("invalid_arguments", "Tool arguments must match the exact documented fields")

    def dispatch(self, name: str, args: dict) -> dict:
        """Dispatch four exact-schema tools; rejected requests never launch a command."""
        if self.finished:
            raise BrokerError("trial_finished", "This trial has already submitted its final claim")
        try:
            if name == "list_files":
                self._arguments(args, {"scope"})
                _, files = self._scope(args["scope"])
                return {"scope": args["scope"], "files": sorted(files)}
            if name == "read_file":
                self._arguments(args, {"scope", "path"})
                relative = _relative(args["path"]).as_posix()
                root, files = self._scope(args["scope"])
                if relative not in files:
                    raise BrokerError("file_denied", "File is absent or outside the permitted namespace")
                path = root / relative
                if path.stat().st_size > MAX_READ_BYTES:
                    raise BrokerError("file_too_large", "Text reads are limited to 64 KiB")
                data = path.read_bytes()
                try:
                    content = data.decode("utf-8")
                except UnicodeError as error:
                    raise BrokerError("binary_file", "Binary media is preserved but cannot be read as text") from error
                if any(ord(char) < 32 and char not in "\r\n\t" for char in content):
                    raise BrokerError("binary_file", "Binary media is preserved but cannot be read as text")
                return {"scope": args["scope"], "path": relative, "content": content}
            if name == "run_command":
                self._arguments(args, {"command_id"})
                command_id = args["command_id"]
                if not isinstance(command_id, str) or command_id not in self._commands:
                    raise BrokerError("command_denied", "Only a frozen documented command identifier is accepted")
                if (type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds <= 45
                        or not math.isfinite(self.timeout_seconds)):
                    raise BrokerError("invalid_timeout", "Operator command timeout must be positive and at most 45 seconds")
                self._check_repo()
                if self._interpreter_identity() != self._python_identity:
                    raise BrokerError("interpreter_changed", "Selected Python executable identity changed")
                if self.skill_root:
                    self._scope("skill")
                _unlinked(self.evidence)
                _unlinked(self._command_root)
                self._sequence += 1
                attempt = self._command_root / f"{self._sequence:04d}"
                attempt.mkdir(exist_ok=False)
                try:
                    record = execute_step(self._commands[command_id], self.repo, attempt, self.python,
                                          timeout_seconds=self.timeout_seconds)
                except OSError as error:
                    write_new(attempt / "ERROR.json", {"command_id": command_id, "status": "collection_failed",
                                                       "error": str(error), "execution_verified": False})
                    raise
                self._records.append((attempt, copy.deepcopy(record)))
                self._generated = self._check_repo(accept_generated=True)
                result = {"command_id": command_id, **{key: record[key] for key in (
                    "returncode", "stdout", "stderr", "outcome", "elapsed_seconds")}}
                for key in ("stdout", "stderr"):
                    result[key + "_truncated"] = len(result[key].encode("utf-8")) > MAX_READ_BYTES
                    result[key] = result[key].encode("utf-8")[:MAX_READ_BYTES].decode("utf-8", errors="replace")
                return result
            if name == "finish":
                self._arguments(args, {"claim"})
                claim = args["claim"]
                if (not isinstance(claim, dict) or set(claim) != {"outcome", "observed_metrics", "reason"}
                        or claim.get("outcome") not in ("matched", "mismatched", "blocked")
                        or not isinstance(claim.get("reason"), str) or len(claim["reason"]) > 8192
                        or not isinstance(claim.get("observed_metrics"), dict)):
                    raise BrokerError("invalid_claim", "Expected neutral outcome, observed_metrics and short reason")
                if any(not isinstance(key, str) or type(value) not in (int, float) or not math.isfinite(value)
                       for key, value in claim["observed_metrics"].items()):
                    raise BrokerError("invalid_claim", "Observed metrics must be finite numeric values")
                self._check_repo()
                if self.skill_root:
                    self._scope("skill")
                latest = {record["step_id"]: index for index, (_, record) in enumerate(self._records)}
                selected = [self._records[index] for index in sorted(latest.values())]
                attempt = selected[-1][0] if selected else self.evidence
                grade = grade_task(self._task_id, self.repo, self._task,
                                   [copy.deepcopy(record) for _, record in selected], copy.deepcopy(claim), attempt)
                write_new(self.evidence / "CLAIM.json", claim)
                write_new(self.evidence / "GRADE.json", grade)
                self.grade, self.finished = copy.deepcopy(grade), True
                return {"finished": True, "grade": copy.deepcopy(grade)}
            raise BrokerError("unknown_tool", "Unknown broker tool")
        except BrokerError:
            raise
        except (OSError, TypeError, OverflowError) as error:
            raise BrokerError("broker_failure", str(error)) from error
