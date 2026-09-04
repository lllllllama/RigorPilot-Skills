#!/usr/bin/env python3
"""Exercise persistent runtime state, logs, timeout, and cancellation."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import run_persistent_command


def command_for(code: str, *args: str) -> str:
    argv = [sys.executable, "-c", code, *args]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def wait_for(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not path.exists():
        raise AssertionError(f"timed out waiting for {path}")


def main() -> int:
    checks = 0
    with tempfile.TemporaryDirectory(prefix="rigorpilot-runtime-test-") as temporary:
        root = Path(temporary)
        runtime_root = root / "runtime"

        success = run_persistent_command(
            repo=root,
            command=command_for("import sys; print('α' * 5000); print('stderr-ok', file=sys.stderr)"),
            timeout=10,
            runtime_root=runtime_root,
            run_id="success-run",
            capture_limit=128,
        )
        run_dir = runtime_root / "success-run"
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        if success["runtime_status"] != "success" or state["status"] != "success":
            raise AssertionError("successful process did not reach a durable success state")
        checks += 1
        if not success["stdout_truncated"] or len(success["stdout"]) > 128:
            raise AssertionError("bounded stdout tail was not enforced")
        if len((run_dir / "stdout.log").read_text(encoding="utf-8")) <= 5000:
            raise AssertionError("full stdout was not streamed to disk")
        if "stderr-ok" not in (run_dir / "stderr.log").read_text(encoding="utf-8"):
            raise AssertionError("stderr was not streamed to disk")
        checks += 3
        resources = [json.loads(line) for line in (run_dir / "resources.jsonl").read_text(encoding="utf-8").splitlines()]
        if not resources or resources[0]["process"]["scope"] != "root_process":
            raise AssertionError("runtime did not persist scoped resource telemetry")
        if success["resource_summary"]["samples"] < 1:
            raise AssertionError("runtime result did not expose a resource summary")
        checks += 2
        event_types = {event["type"] for event in events}
        if not {"created", "started", "stream_chunk", "stream_closed", "completed"}.issubset(event_types):
            raise AssertionError(f"runtime event stream is incomplete: {event_types}")
        checks += 1

        marker = root / "orphan-marker.txt"
        child_code = "import sys,time; from pathlib import Path; time.sleep(1); Path(sys.argv[1]).write_text('orphan', encoding='utf-8')"
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}, sys.argv[1]]); "
            "time.sleep(5)"
        )
        timed = run_persistent_command(
            repo=root,
            command=command_for(parent_code, str(marker)),
            timeout=0.35,
            runtime_root=runtime_root,
            run_id="timeout-run",
        )
        if not timed["timed_out"] or timed["runtime_status"] != "timed_out":
            raise AssertionError("timeout was not persisted as a terminal state")
        time.sleep(1.1)
        if marker.exists():
            raise AssertionError("timeout left a child process running")
        checks += 2

        cancelled_result: dict = {}

        def execute_cancelled() -> None:
            cancelled_result.update(
                run_persistent_command(
                    repo=root,
                    command=command_for("import time; time.sleep(5)"),
                    timeout=10,
                    runtime_root=runtime_root,
                    run_id="cancel-run",
                )
            )

        worker = threading.Thread(target=execute_cancelled)
        worker.start()
        cancel_dir = runtime_root / "cancel-run"
        wait_for(cancel_dir / "state.json")
        (cancel_dir / "CANCEL").touch()
        worker.join(timeout=10)
        if worker.is_alive():
            raise AssertionError("cancelled runtime did not stop")
        if not cancelled_result.get("cancelled") or cancelled_result.get("runtime_status") != "cancelled":
            raise AssertionError("cancellation was not persisted as a terminal state")
        checks += 2

    print("ok: True")
    print(f"checks: {checks}")
    print("failures: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
