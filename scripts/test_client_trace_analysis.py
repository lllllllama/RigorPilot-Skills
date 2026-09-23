#!/usr/bin/env python3
"""Check command-call deduplication and retained trace accounting."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from analyze_client_trace import count_commands, derive


def command(kind: str, item_id: str) -> dict:
    return {"type": kind, "item": {"type": "command_execution", "id": item_id}}


def main() -> int:
    events = [
        {"type": "thread.started", "thread_id": "session-1"}, {"type": "turn.started"},
        command("item.started", "same"), command("item.started", "same"), command("item.completed", "same"),
        command("item.started", "incomplete"), {"type": "turn.started"},
        command("item.started", "same"), command("item.completed", "same"),
        command("item.started", "retry-new-id"), command("item.completed", "retry-new-id"),
    ]
    counts = count_commands(events)
    assert counts["command_event_count"] == 8, counts
    assert counts["unique_command_count"] == 4, counts
    assert counts["command_started_count"] == 4 and counts["command_completed_count"] == 3, counts
    assert counts["incomplete_command_ids"][0]["item_id"] == "incomplete"
    retained = derive(ROOT / "benchmark_outputs/real_client/20260922/AUTO/client/TRACE.jsonl", ROOT / "benchmark_outputs/real_client/20260922/AUTO/REPORT.json")
    assert retained["counts"]["command_event_count"] == 10
    assert retained["counts"]["unique_command_count"] == 5
    assert retained["counts"]["command_started_count"] == retained["counts"]["command_completed_count"] == 5
    assert retained["counts"]["incomplete_command_ids"] == []
    assert retained["provider_usage_raw"]["input_tokens"] == 141255
    print("ok: trace calls are deduplicated and retained usage is unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
