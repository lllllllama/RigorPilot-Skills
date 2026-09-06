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

from runtime_runner import resolve_direct_argv, run_persistent_command


def command_for(code: str, *args: str) -> str:
    argv = [sys.executable, "-c", code, *args]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def wait_for(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not path.exists():
        raise AssertionError(f"timed out waiting for {path}")


def check_executable_lookup(root: Path, runtime_root: Path) -> int:
    environment = dict(os.environ)
    environment["PATH"] = str(Path(sys.executable).parent)
    argv = [Path(sys.executable).name, "-c", "import sys; print('path-lookup-ok')"]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    result = run_persistent_command(repo=root, command=command, timeout=10,
                                    runtime_root=runtime_root, child_env=environment)
    if result["runtime_status"] != "success" or "path-lookup-ok" not in result["stdout"]:
        raise AssertionError(f"bare executable did not use the child PATH: {result}")
    run_dir = Path(result["runtime_dir"])
    spec = json.loads((run_dir / "spec.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    actual = next(event["data"]["argv"] for event in events if event["type"] == "started")
    if spec["command"] != command or spec["requested_argv"] != argv or spec["argv"] != actual:
        raise AssertionError("runtime did not preserve original command and actual executed argv")
    if not Path(actual[0]).is_absolute():
        raise AssertionError("bare executable lookup was left to platform-specific process search")

    for label, env in (("empty", {**environment, "PATH": ""}), ("absent", {})):
        blocked = run_persistent_command(repo=root, command=command, timeout=10,
                                         runtime_root=runtime_root, child_env=env)
        if blocked["runtime_status"] != "blocked" or "PATH" not in str(blocked.get("launch_error")):
            raise AssertionError(f"{label} child PATH fell back to controller Python")
    missing = run_persistent_command(repo=root, command="rigorpilot-nonexistent-executable", timeout=10,
                                     runtime_root=runtime_root, child_env=environment)
    if missing["runtime_status"] != "blocked":
        raise AssertionError("missing executable did not produce a durable blocked result")
    explicit = run_persistent_command(repo=root, command=command_for("import sys; print('explicit-path-ok')"), timeout=10,
                                      runtime_root=runtime_root, child_env={**environment, "PATH": ""})
    if explicit["runtime_status"] != "success":
        raise AssertionError("empty PATH changed explicit executable path semantics")
    interpreter = Path(sys.executable)
    relative_argv = [str(Path(interpreter.parent.name) / interpreter.name),
                     "-c", "import sys; print('relative-path-ok')"]
    relative_command = subprocess.list2cmdline(relative_argv) if os.name == "nt" else shlex.join(relative_argv)
    relative_run = run_persistent_command(repo=interpreter.parent.parent, command=relative_command,
                                          timeout=10, runtime_root=runtime_root,
                                          child_env={**environment, "PATH": ""})
    if relative_run["runtime_status"] != "success" or "relative-path-ok" not in relative_run["stdout"]:
        raise AssertionError("explicit relative executable was not anchored to execution cwd")

    # These are lookup-only fixture files: they are never executed.
    tools_dir = root / "relative-tools"
    tools_dir.mkdir()
    name = "lookup-fixture.EXE" if os.name == "nt" else "lookup-fixture"
    fixture = tools_dir / name
    fixture.write_text("fixture", encoding="utf-8")
    fixture.chmod(0o755)
    resolved = resolve_direct_argv([name], root, {"PATH": "relative-tools"})
    if resolved != [str(fixture)]:
        raise AssertionError("relative PATH entry was not anchored to execution cwd")
    for explicit_name in (str(fixture), "./relative-tools/" + name):
        if resolve_direct_argv([explicit_name], root, {}) != [str(fixture)]:
            raise AssertionError("explicit executable path did not preserve its execution-cwd meaning")
    try:
        resolve_direct_argv([name], tools_dir, {"PATH": str(root)})
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("lookup implicitly searched the execution cwd outside PATH")
    if os.name == "nt":
        if resolve_direct_argv(["lookup-fixture"], root, {"Path": "relative-tools", "PATHEXT": ".EXE"}) != [str(fixture)]:
            raise AssertionError("Windows lookup did not use the child's PATH/PATHEXT")
        try:
            resolve_direct_argv(["lookup-fixture"], root, {"PATH": "relative-tools", "PATHEXT": ".CMD"})
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("Windows lookup leaked the parent's PATHEXT")
    return 10


def main() -> int:
    checks = 0
    with tempfile.TemporaryDirectory(prefix="rigorpilot-runtime-test-") as temporary:
        root = Path(temporary)
        runtime_root = root / "runtime"
        checks += check_executable_lookup(root, runtime_root)

        success = run_persistent_command(
            repo=root,
            command=command_for("import sys; sys.stdout.reconfigure(encoding='utf-8'); print('α' * 5000); print('stderr-ok', file=sys.stderr)"),
            timeout=10,
            runtime_root=runtime_root,
            run_id="success-run",
            capture_limit=128,
        )
        run_dir = runtime_root / "success-run"
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        if success["runtime_status"] != "success" or state["status"] != "success":
            raise AssertionError(f"successful process did not reach a durable success state: {success}")
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
        release = root / "release-child.txt"
        child_code = (
            "import sys,time\nfrom pathlib import Path\n"
            "while not Path(sys.argv[2]).exists(): time.sleep(0.02)\n"
            "Path(sys.argv[1]).write_text('orphan', encoding='utf-8')"
        )
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}, sys.argv[1], sys.argv[2]]); "
            "time.sleep(5)"
        )
        timed = run_persistent_command(
            repo=root,
            command=command_for(parent_code, str(marker), str(release)),
            timeout=0.35,
            runtime_root=runtime_root,
            run_id="timeout-run",
        )
        if not timed["timed_out"] or timed["runtime_status"] != "timed_out":
            raise AssertionError("timeout was not persisted as a terminal state")
        # Only a child surviving completed termination can see this trigger.
        # A fixed pre-termination sleep incorrectly failed on slow taskkill hosts.
        release.write_text("runtime returned", encoding="utf-8")
        time.sleep(0.5)
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
