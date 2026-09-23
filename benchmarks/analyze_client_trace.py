#!/usr/bin/env python3
"""Derive command-call counts from an immutable real-client JSONL trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ANALYZER_VERSION = "1.0"


def count_commands(events: list[dict]) -> dict:
    session = "unknown-session"
    turn = 0
    command_events = 0
    calls: dict[tuple[str, str, str], set[str]] = {}
    for event in events:
        kind = event.get("type")
        if kind == "thread.started":
            session = str(event.get("thread_id") or session)
        elif kind == "turn.started":
            turn += 1
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution" or kind not in {"item.started", "item.completed", "item.failed"}:
            continue
        command_events += 1
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("command_execution event is missing item.id")
        key = (session, str(event.get("turn_id") or turn), item_id)
        calls.setdefault(key, set()).add(kind)
    return {
        "command_event_count": command_events,
        "unique_command_count": len(calls),
        "command_started_count": sum("item.started" in states for states in calls.values()),
        "command_completed_count": sum("item.completed" in states for states in calls.values()),
        "command_failed_count": sum("item.failed" in states for states in calls.values()),
        "incomplete_command_ids": [
            {"client_session": session, "turn": turn, "item_id": item_id}
            for (session, turn, item_id), states in calls.items()
            if "item.completed" not in states and "item.failed" not in states
        ],
    }


def derive(trace: Path, source_report: Path | None = None) -> dict:
    raw = trace.read_bytes()
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("trace lines must be JSON objects")
    report = json.loads(source_report.read_text(encoding="utf-8")) if source_report else {}
    if not isinstance(report, dict):
        raise ValueError("source report must be a JSON object")
    return {
        "schema_version": "1.0",
        "analyzer_version": ANALYZER_VERSION,
        "source_trace": trace.as_posix(),
        "source_trace_sha256": hashlib.sha256(raw).hexdigest(),
        "source_report": source_report.as_posix() if source_report else None,
        "tested_skill_commit": report.get("skill_commit"),
        "task_fixture_version": report.get("upstream_commit"),
        "client_version": report.get("client_version"),
        "date": report.get("date"),
        "verification_type": report.get("scope"),
        "provider_usage_raw": report.get("model_usage"),
        "model_cost_raw": report.get("model_cost"),
        "counts": count_commands(events),
        "interpretation": "Calls are distinct by client session, turn, and item ID. The original trace and reports are unchanged; event count is not an execution count.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = derive(args.trace, args.source_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
