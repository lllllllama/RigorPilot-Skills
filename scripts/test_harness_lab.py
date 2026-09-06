#!/usr/bin/env python3
"""Offline lab checks are engineering tests, not model-quality evidence."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from run_harness_lab import (FIXTURE, ROOT, SOURCE_FILES, independent_verification_passed,
                             remove_temporary_git_pointer)


def test_git_pointer_identity(base: Path) -> None:
    repo, metadata, unexpected = base / "repo", base / "metadata", base / "unexpected"
    repo.mkdir(parents=True)
    (metadata / "child").mkdir(parents=True)
    unexpected.mkdir()
    pointer = repo / ".git"
    for spelling in [str(metadata), "../metadata", "../metadata/child/..", str(metadata / "child" / "..")]:
        pointer.write_text(f"gitdir: {spelling}\n", encoding="utf-8")
        remove_temporary_git_pointer(repo, metadata)
        assert not pointer.exists() and metadata.is_dir(), spelling
    for contents in [f"gitdir: {unexpected}\n", "gitdir: ../does-not-exist\n", "not a gitdir pointer\n"]:
        pointer.write_text(contents, encoding="utf-8")
        try:
            remove_temporary_git_pointer(repo, metadata)
        except RuntimeError as exc:
            assert "Preserved unexpected .git pointer" in str(exc)
        else:
            raise AssertionError("Unexpected Git pointer was not rejected")
        assert pointer.read_text(encoding="utf-8") == contents
        assert unexpected.is_dir() and metadata.is_dir()
    pointer.unlink()
    pointer.mkdir()
    try:
        remove_temporary_git_pointer(repo, metadata)
    except RuntimeError as exc:
        assert "not a regular pointer file" in str(exc)
    else:
        raise AssertionError("Unexpected .git directory was not rejected")
    assert pointer.is_dir()
    pointer.rmdir()
    # Symlink creation may require privileges on Windows; when available,
    # metadata aliases must work, while a symlink used as .git is never deleted.
    alias = base / "metadata-alias"
    try:
        alias.symlink_to(metadata, target_is_directory=True)
    except OSError:
        return
    pointer.write_text(f"gitdir: {alias}\n", encoding="utf-8")
    remove_temporary_git_pointer(repo, metadata)
    assert not pointer.exists() and alias.is_dir()
    target_pointer = base / "target-pointer"
    target_pointer.write_text(f"gitdir: {metadata}\n", encoding="utf-8")
    pointer.symlink_to(target_pointer)
    try:
        remove_temporary_git_pointer(repo, metadata)
    except RuntimeError as exc:
        assert "not a regular pointer file" in str(exc)
    else:
        raise AssertionError("Symlink .git was not rejected")
    assert pointer.is_symlink() and target_pointer.is_file()


def main() -> int:
    # Schema 1.1 nests command checks. A nonempty dict must not hide False or a
    # missing required command behind Python truthiness or an optimistic status.
    for command_checks, expected in [({"evaluate": True}, True), ({"evaluate": False}, False),
                                     ({"prepare": True}, False), ({}, False), ({"evaluate": 1}, False)]:
        state = {"status": "success", "verification": {"source_unchanged": True, "commands": command_checks}}
        assert independent_verification_passed(state, ["evaluate"]) is expected
    assert not independent_verification_passed({"status": "success", "verification": {
        "source_unchanged": False, "commands": {"evaluate": True}}}, ["evaluate"])
    with tempfile.TemporaryDirectory(prefix="rigorpilot-lab-test-") as temporary:
        test_git_pointer_identity(Path(temporary) / "pointer-fixtures")
        output = Path(temporary) / "evidence"
        command = [sys.executable, str(ROOT / "scripts/run_harness_lab.py"), "--output", str(output)]
        environment = {**os.environ, "GIT_DIR": str(Path(temporary) / "must-not-create.git"),
                       "GIT_INDEX_FILE": str(Path(temporary) / "must-not-create.index")}
        result = subprocess.run(command, capture_output=True, timeout=60, env=environment)
        assert result.returncode == 0, (result.stdout, result.stderr)
        report_bytes = (output / "REPORT.json").read_bytes()
        report = json.loads(report_bytes)
        assert report["status"] == "success" and all(report["checks"].values()), report
        assert report["simulation"] and report["api_calls"] == report["model_tokens"] == report["network_requests"] == 0
        assert report["real_command_attempts"] == 3 and report["controller_sessions"] == 2
        repo = output / "repo"
        assert not (repo / ".git").exists(), "Temporary Git metadata reference leaked"
        assert not Path(environment["GIT_DIR"]).exists() and not Path(environment["GIT_INDEX_FILE"]).exists()
        assert len(list((repo / "repro_outputs/_runtime").iterdir())) == 3
        assert sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) < 1024 * 1024
        for name in SOURCE_FILES:
            assert (repo / name).read_bytes() == (FIXTURE / name).read_bytes()
        events = [json.loads(line) for line in (repo / "repro_outputs/trajectory.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [event["type"] for event in events].count("paused") == 1
        assert [event["type"] for event in events].count("resumed") == 1
        for phase, status in [("PAUSE", "paused"), ("RESUME", "success")]:
            session = json.loads((output / (phase + "_SESSION.json")).read_text(encoding="utf-8"))
            assert session["status"] == status and session["pid"] > 0
        repeated = subprocess.run(command, capture_output=True, timeout=10)
        assert repeated.returncode != 0 and (output / "REPORT.json").read_bytes() == report_bytes
        empty_output = Path(temporary) / "existing-empty"
        empty_output.mkdir()
        refused = subprocess.run(command[:-1] + [str(empty_output)], capture_output=True, timeout=10)
        assert refused.returncode != 0 and list(empty_output.iterdir()) == []
    print("ok: True; offline simulation, real failure/recovery, source fidelity, small output and overwrite refusal verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
