#!/usr/bin/env python3
"""Verify restart reconciliation and explicit retry lineage."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import atomic_write_json, reconcile_run, request_cancel, retry_run, run_persistent_command


def command_for(code: str, *args: str) -> str:
    argv = [sys.executable, "-c", code, *args]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def write_stale_run(run_dir: Path, pid: int | None) -> None:
    run_dir.mkdir(parents=True)
    atomic_write_json(
        run_dir / "state.json",
        {
            "schema_version": "1.0",
            "run_id": run_dir.name,
            "status": "running",
            "pid": pid,
            "last_heartbeat": "2000-01-01T00:00:00Z",
            "attempt": 1,
        },
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"schema_version": "1.0", "sequence": 1, "timestamp": "2000-01-01T00:00:00Z", "type": "started", "data": {}}) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    checks = 0
    with tempfile.TemporaryDirectory(prefix="rigorpilot-recovery-test-") as temporary:
        root = Path(temporary)
        runtime_root = root / "runtime"

        dead = runtime_root / "dead-run"
        write_stale_run(dead, 2_147_483_000)
        recovery = reconcile_run(dead, stale_after_seconds=0)
        state = json.loads((dead / "state.json").read_text(encoding="utf-8"))
        if recovery["status"] != "interrupted" or state["status"] != "interrupted":
            raise AssertionError("dead stale run was not reconciled to interrupted")
        if "recovered_interrupted" not in (dead / "events.jsonl").read_text(encoding="utf-8"):
            raise AssertionError("interrupted recovery was not appended to the event stream")
        checks += 2

        live = runtime_root / "live-run"
        write_stale_run(live, os.getpid())
        recovery = reconcile_run(live, stale_after_seconds=0)
        if recovery["status"] != "orphaned":
            raise AssertionError("live process with stale heartbeat was not protected as orphaned")
        cancel = request_cancel(runtime_root, "live-run")
        if cancel["cancel_requested"] or (live / "CANCEL").exists():
            raise AssertionError("runtime control implied an orphaned process would consume a cancel file")
        checks += 2

        marker = root / "ready.txt"
        code = "import sys; from pathlib import Path; raise SystemExit(0 if Path(sys.argv[1]).exists() else 7)"
        first = run_persistent_command(
            repo=root,
            command=command_for(code, str(marker)),
            timeout=10,
            runtime_root=runtime_root,
            run_id="attempt-one",
        )
        if first["runtime_status"] != "failed":
            raise AssertionError("retry fixture did not produce a failed first attempt")
        marker.touch()
        second = retry_run(runtime_root=runtime_root, run_id="attempt-one")
        second_spec = json.loads(Path(second["runtime_dir"]).joinpath("spec.json").read_text(encoding="utf-8"))
        if second["runtime_status"] != "success" or second["runtime_retry_of"] != "attempt-one":
            raise AssertionError("explicit retry did not produce a successful linked attempt")
        if second_spec["attempt"] != 2 or second_spec["retry_of"] != "attempt-one":
            raise AssertionError("retry lineage was not persisted in spec.json")
        if not Path(second["resources_log_path"]).is_file():
            raise AssertionError("retried run lost resource evidence")
        checks += 4

        control = subprocess.run(
            [sys.executable, str(SHARED_SCRIPTS / "runtime_runner.py"), "--runtime-root", str(runtime_root), "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        rows = json.loads(control.stdout)
        if control.returncode != 0 or not any(row.get("attempt") == 2 for row in rows):
            raise AssertionError("runtime control CLI did not list retry attempts")
        checks += 1

    print("ok: True")
    print(f"checks: {checks}")
    print("failures: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
