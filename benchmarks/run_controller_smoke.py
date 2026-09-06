#!/usr/bin/env python3
"""Offline controller checks: scripted transport, real reviewed local processes.

No live model CLI, credentials, network requests or dependency installs. This
is deterministic engineering evidence, not a paired-model benchmark.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

from paired_eval import write_new
from paired_tasks import prepare_task
from trial_broker import TrialBroker
from trial_budget import BudgetLedger
from trial_controller import run_trial

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = {"provider": "scripted-fixture", "model": "no-model-simulation", "revision": "fixture-v1"}
# Synthetic accounting limits test admission; they are not a proposed model spend.
LIMITS = {"max_total_tokens": 100000, "max_model_calls": 8, "max_tool_calls": 12, "max_seconds": 45}


def action(name: str, **arguments) -> tuple:
    return name, arguments


def claim(outcome: str, **metrics) -> dict:
    return {"outcome": outcome, "observed_metrics": metrics,
            "reason": "Explicitly scripted controller acceptance; not a model decision."}


class ScriptedTransport:
    def __init__(self, actions: list[tuple], unknown_usage: bool = False):
        self.actions, self.unknown_usage, self.calls = actions, unknown_usage, 0

    def complete(self, messages, system, tools, max_tokens, timeout):
        name, arguments = self.actions[self.calls]
        self.calls += 1
        return {"model": IDENTITY["model"], "content": [{"type": "tool_use", "id": f"fixture-{self.calls}",
                "name": name, "input": copy.deepcopy(arguments)}],
                "usage": None if self.unknown_usage else {"input_tokens": 20, "output_tokens": 10}}


def smoke(output: Path) -> dict:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a fresh output directory; old evidence is never replaced")
    output.mkdir(parents=True)
    scenarios = {
        "missing_asset": {"task": "missing_asset", "actions": [
            action("read_file", scope="repo", path="README.md"),
            action("run_command", command_id="evaluate"),
            action("run_command", command_id="prepare-data"),
            action("run_command", command_id="evaluate"),
            action("read_file", scope="repo", path="results/metrics.json"),
            action("finish", claim=claim("matched", mse=0.0))]},
        "wrong_metric": {"task": "wrong_metric", "actions": [
            action("read_file", scope="repo", path="README.md"),
            action("run_command", command_id="evaluate"),
            action("read_file", scope="repo", path="results/metrics.json"),
            action("finish", claim=claim("mismatched", mse=1.0))]},
        "unknown_usage": {"task": "wrong_metric", "unknown_usage": True,
                          "actions": [action("run_command", command_id="evaluate")]},
        "path_denied": {"task": "wrong_metric", "actions": [
            action("read_file", scope="repo", path="../evidence/budget.jsonl"),
            action("finish", claim=claim("blocked"))]},
    }
    implementation = {f"benchmarks/{name}": hashlib.sha256((ROOT / "benchmarks" / name).read_bytes()).hexdigest()
                      for name in ("trial_controller.py", "trial_broker.py", "trial_budget.py", "paired_tasks.py",
                                   "paired_eval.py", "run_controller_smoke.py")}
    write_new(output / "START.json", {"mode": "offline_simulation", "scenarios": list(scenarios),
                                     "created_at": datetime.now(timezone.utc).isoformat(),
                                     "implementation_sha256": implementation, "identity": IDENTITY, "limits": LIMITS})
    rows = []
    for scenario, specification in scenarios.items():
        base = output / scenario
        task = prepare_task(specification["task"], base / "repo", ROOT)
        write_new(base / "TASK.json", task)
        broker = TrialBroker(base / "repo", base / "evidence", task, sys.executable)
        ledger = BudgetLedger(base / "evidence/budget.jsonl", LIMITS)
        transport = ScriptedTransport(specification["actions"], specification.get("unknown_usage", False))
        prompt = task["goal_en"] + "\nReviewed command identifiers: " + ", ".join(item["id"] for item in task["commands"])
        result = run_trial(broker=broker, provider=transport, ledger=ledger, identity=IDENTITY,
                           prompt=prompt, trace_path=base / "evidence/trace.jsonl", max_output_tokens=100,
                           execution_mode="offline_simulation")
        executions = broker.executions
        if scenario == "missing_asset":
            passed = (result["accepted"] and len(executions) == 3 and executions[0]["returncode"] != 0
                      and [record["returncode"] for record in executions[1:]] == [0, 0])
        elif scenario == "wrong_metric":
            passed = result["accepted"] and result["grade"]["result_matched"] is False
        elif scenario == "unknown_usage":
            passed = (result["status"] == "stopped" and not executions and transport.calls == 1
                      and result["budget"]["tokens_used"] is None and bool(result["budget"]["pending"]))
        else:
            events = [json.loads(line) for line in (base / "evidence/trace.jsonl").read_text(encoding="utf-8").splitlines()]
            passed = (not result["accepted"] and not executions and result["grade"]["incorrect_blocking"]
                      and any(event.get("is_error") and event.get("result", {}).get("error") == "unsafe_path" for event in events))
        write_new(base / "RESULT.json", result)
        rows.append({"scenario": scenario, "expected_boundary_observed": bool(passed),
                     "command_attempts": len(executions), "failed_commands": sum(record["returncode"] != 0 for record in executions),
                     "result": f"{scenario}/RESULT.json", "trace": f"{scenario}/evidence/trace.jsonl"})
    report = {"mode": "offline_controller_acceptance", "rows": rows, "checks_passed": sum(row["expected_boundary_observed"] for row in rows),
              "live_model_calls": 0, "tokens_used": None, "cost": None, "paired_effect": None,
              "scope": "Scripted transport and usage, real standard-library commands; not measured agent decisions or a model A/B result.",
              "boundaries": ["No live adapter/CLI, campaign-wide spending control, OS sandbox or provider cancellation guarantee.",
                             "Original task source bytes remain unchanged; failed commands and unknown reservations are retained.",
                             "The six earlier paired model slots remain unrun; this is a separate controller check."]}
    write_new(output / "REPORT.json", report)
    size = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    if size > 1024**2:
        raise ValueError("Controller smoke exceeds 1 MiB; evidence retained for inspection")
    return {"report": str(output / "REPORT.json"), "checks_passed": report["checks_passed"], "checks": len(rows),
            "bytes": size, "live_model_calls": 0, "mode": report["mode"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "repro_outputs" / ("controller-check-" + uuid.uuid4().hex[:10]))
    args = parser.parse_args()
    try:
        result = smoke(args.output)
        print(json.dumps(result, indent=2))
        return int(result["checks_passed"] != result["checks"])
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error), "live_model_calls": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
