#!/usr/bin/env python3
"""Read Codex quota via the official app-server; never start a model turn.

Uses existing CLI authentication without reading/copying credentials. The
snapshot is not a billing cap, a reservation, or a prediction of the next turn.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


def quota_snapshot(result: dict) -> dict:
    buckets = result.get("rateLimitsByLimitId")
    bucket = buckets.get("codex") if isinstance(buckets, dict) else None
    if bucket is None:
        bucket = result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise ValueError("codex_quota_unavailable")
    windows = []
    for name in ("primary", "secondary"):
        window = bucket.get(name)
        if window is None:
            continue
        if not isinstance(window, dict):
            raise ValueError("invalid_quota_window")
        used = window.get("usedPercent")
        if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100:
            raise ValueError("invalid_quota_percentage")
        windows.append({"window": name, "used_percent": used, "remaining_percent": 100 - used})
    if not windows:
        raise ValueError("quota_windows_unavailable")
    return {"ok": True, "scope": "codex_reported_windows_snapshot", "windows": windows,
            "minimum_remaining_percent": min(item["remaining_percent"] for item in windows),
            "model_turns_started": 0, "hard_budget_guarantee": False}


def read_quota(executable: str, timeout: float = 20) -> dict:
    selected = shutil.which(executable)
    if not selected:
        raise ValueError("codex_executable_not_found")
    # Pass a native executable on Windows; do not silently introduce a shell.
    if os.name == "nt" and Path(selected).suffix.lower() != ".exe":
        raise ValueError("pass_native_codex_exe_with_--codex")
    process = subprocess.Popen([selected, "app-server", "--stdio"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    events = queue.Queue(maxsize=128)

    def receive():
        try:
            for line in process.stdout:
                if len(line) > 1_000_000:
                    break
                events.put_nowait(line)
        except (ValueError, OSError, queue.Full):
            pass
        finally:
            try:
                events.put_nowait(None)
            except queue.Full:
                pass

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def response(request_id):
        while time.monotonic() < deadline:
            line = events.get(timeout=max(0.01, deadline - time.monotonic()))
            if line is None:
                raise ValueError("app_server_closed")
            payload = json.loads(line)
            if not isinstance(payload, dict) or payload.get("id") != request_id:
                continue
            if "error" in payload or not isinstance(payload.get("result"), dict):
                raise ValueError("quota_request_failed")  # Never expose raw server errors.
            return payload["result"]
        raise TimeoutError("quota_timeout")

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {
            "name": "rigorpilot_quota_check", "version": "1.0"}}})
        response(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read", "params": {}})
        return quota_snapshot(response(2))
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        process.stdin.close()
        reader.join(timeout=1)
        process.stdout.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex", help="Native Codex executable; uses existing login")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
        parser.error("timeout must be positive and at most 60 seconds")
    try:
        result = read_quota(args.codex, args.timeout)
    except (ValueError, OSError, TimeoutError, queue.Empty, subprocess.SubprocessError):
        result = {"ok": False, "reason": "quota_unavailable_no_model_turn_started",
                  "model_turns_started": 0, "minimum_remaining_percent": None}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
