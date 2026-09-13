#!/usr/bin/env python3
"""Run one bounded A/B pair through the existing transport, broker and grader.

This is a new constrained skill-guidance protocol, NOT the earlier full-package
pilot. Loopback fixtures are explicitly offline and never measure model ability.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared/scripts"))
from agent_provider import AnthropicProvider
from model_adapter import normalize_model_profile, profile_fingerprint
from paired_eval import disk_gate, encoded, inventory, load, python_environment, sha
from paired_tasks import TASK_IDS, prepare_task
from trial_broker import TrialBroker, _linked, _snapshot
from trial_budget import BudgetLedger
from trial_controller import run_trial

PROTOCOL = "constrained-skill-guidance-pair-v1"
SOURCES = ["benchmarks/" + name for name in (
    "run_paired_trial.py", "trial_controller.py", "trial_broker.py", "trial_budget.py",
    "paired_eval.py", "paired_tasks.py")] + [
    "shared/scripts/agent_provider.py", "shared/scripts/model_adapter.py"]


class ConfigurationError(ValueError):
    """Safe, actionable local configuration diagnostic; never provider text."""


class TrialMessagesProvider(AnthropicProvider):
    """Normalize documented metadata, never unknown billing/usage fields.

    https://platform.claude.com/docs/en/api/messages/create
    Cache/thinking breakdowns are already included in top-level token totals.
    """

    @staticmethod
    def usage(raw: object) -> object:
        token_keys = {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"}
        metadata = {"cache_creation", "output_tokens_details", "server_tool_use", "service_tier", "inference_geo"}
        if not isinstance(raw, dict) or set(raw) - token_keys - metadata:
            return raw  # Unknown fields remain visible to the fail-closed ledger.
        tokens = {key: value for key, value in raw.items() if key in token_keys}
        if not BudgetLedger._valid_usage(tokens):
            return raw
        for field in ("service_tier", "inference_geo"):
            if raw.get(field) is not None and (not isinstance(raw[field], str) or len(raw[field]) > 128):
                return raw
        for field, keys, total in (
            ("cache_creation", {"ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"}, tokens.get("cache_creation_input_tokens", 0)),
            ("output_tokens_details", {"thinking_tokens"}, tokens["output_tokens"]),
            ("server_tool_use", {"web_fetch_requests", "web_search_requests"}, 0),
        ):
            detail = raw.get(field)
            if detail is not None and (not isinstance(detail, dict) or set(detail) - keys
                                      or any(type(value) is not int or value < 0 for value in detail.values())
                                      or sum(detail.values()) > total):
                return raw
        return tokens

    def complete(self, *args, **kwargs) -> dict:
        result = super().complete(*args, **kwargs)
        result["usage"] = self.usage(result.get("usage"))
        for block in result["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("citations") in (None, []):
                block.pop("citations", None)
            if block.get("type") == "tool_use" and block.get("caller") == {"type": "direct"}:
                block.pop("caller")
        return result


def durable_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())


def configure(args) -> dict:
    raw = load(args.model_profile)
    allowed = {"adapter_id", "provider", "model", "revision", "credential_env",
               "endpoint", "capabilities", "parameters", "metadata"}
    if set(raw) - allowed:
        raise ConfigurationError("unsupported model-profile fields")
    if "metadata" in raw and not isinstance(raw["metadata"], dict):
        raise ConfigurationError("metadata must be an object, not an authentication-scheme string")
    for field in ("provider", "model", "revision"):
        if not isinstance(raw.get(field), str) or not raw[field].strip() or len(raw[field]) > 256:
            raise ConfigurationError("explicit bounded provider/model/revision strings are required")
    profile = normalize_model_profile(raw)
    # execute_step strips these names from reviewed child-process environments.
    # Do not accept a custom credential name that would bypass that filter.
    credential_env = profile["credential_env"] or "ANTHROPIC_API_KEY"
    if not any(word in credential_env.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL")):
        raise ConfigurationError("credential_env must include TOKEN, SECRET, PASSWORD, API_KEY or CREDENTIAL for child-process filtering")
    if profile["adapter_id"] != "anthropic-messages" or "tool_calling" not in profile["capabilities"]:
        raise ConfigurationError("this entrypoint requires anthropic-messages and tool_calling")
    if (set(profile["metadata"]) - {"auth_scheme"}
            or profile["metadata"].get("auth_scheme", "x-api-key") not in ("bearer", "x-api-key")):
        raise ConfigurationError("only metadata.auth_scheme bearer or x-api-key is supported")
    endpoint = profile["endpoint"] or os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    url = urlsplit(endpoint)
    local = url.hostname in ("localhost", "127.0.0.1")
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.scheme not in ("https", "http") or (url.scheme == "http" and not local)):
        raise ConfigurationError("endpoint requires HTTPS without credentials/query/fragment (HTTP loopback fixtures only)")
    if local != args.local_fixture:
        raise ConfigurationError("loopback requires --local-fixture; that flag cannot target a remote endpoint")
    profile["endpoint"] = endpoint
    profile["fingerprint"] = profile_fingerprint(profile)
    AnthropicProvider(profile)  # Validate parameters without performing HTTP.
    if not os.getenv(credential_env):
        raise ConfigurationError("configured credential environment variable is missing; no request sent")
    limits = {name: getattr(args, name) for name in (
        "max_total_tokens", "max_model_calls", "max_tool_calls", "max_seconds", "max_output_tokens")}
    if any(type(value) is not int or value <= 0 for value in limits.values()):
        raise ConfigurationError("all budgets must be positive integers")
    limits["max_tokens_per_trial"] = limits["max_total_tokens"] // 2
    if limits["max_output_tokens"] >= limits["max_tokens_per_trial"]:
        raise ConfigurationError("the per-arm budget must leave room for input and output tokens")
    output = args.output.absolute()
    if output.exists() or _linked(output):
        raise ConfigurationError("choose a fresh output directory; existing evidence is never replaced")
    environment = python_environment(args.python)
    if args.task == "micrograd" and not all(environment["packages"].get(key) for key in ("torch", "pytest")):
        raise ConfigurationError("micrograd needs existing torch and pytest; no automatic installation")
    return {"profile": profile, "environment": environment, "limits": limits,
            "execution_mode": "offline_simulation" if args.local_fixture else "live_transport"}


def prompt_for(task: dict, arm: str) -> str:
    prompt = task["goal_en"] + "\nRead README.md. Reviewed command identifiers: " + ", ".join(
        step["id"] for step in task["commands"])
    prompt += "\nUse finish to submit the outcome, observed_metrics and reason. Do not create a claim file yourself."
    if arm == "B":
        prompt += ("\nRead SKILL.md through the skill namespace and use its applicable guidance. "
                   "Skill files are read-only; bundled helper execution is unavailable in this trial. "
                   "The same reviewed command tools and finish contract apply to both arms.")
    return prompt


def seal(base: Path, start_sha256: str, arm: str) -> None:
    files, _ = _snapshot(base)
    durable_new(base / "RECEIPT.json", {"files": files, "start_sha256": start_sha256, "arm": arm})


def summarize(output: Path) -> dict:
    output = output.resolve()
    start = load(output / "START.json")
    if sha((output / "START.json").read_bytes()) != load(output / "FREEZE.json")["start_sha256"]:
        raise ValueError("START identity changed; evidence cannot be summarized as the frozen pair")
    if start.get("protocol_id") != PROTOCOL or [row["arm"] for row in start["planned_slots"]] != ["A", "B"]:
        raise ValueError("unsupported or incomplete frozen pair")
    if (_snapshot(output / "inputs/repo")[0] != start["task"]["immutable_sha256"]
            or _snapshot(output / "inputs/skill")[0] != start["skill_files"]):
        raise ValueError("frozen repository or skill inputs changed; summary refused")
    offline = start["execution_mode"] == "offline_simulation"
    rows, results = [], []
    incomplete = False
    for slot in start["planned_slots"]:
        arm = slot["arm"]
        base = output / arm
        if not (base / "RECEIPT.json").exists():
            uncertain = (base / "evidence").exists() or (base / "RESULT.json").exists()
            incomplete = incomplete or uncertain
            rows.append({"arm": arm, "status": "incomplete" if uncertain else "not_run", "accepted": False})
            continue
        receipt = load(base / "RECEIPT.json")
        if receipt.get("start_sha256") != sha((output / "START.json").read_bytes()) or receipt.get("arm") != arm:
            raise ValueError("trial belongs to a different frozen pair or arm")
        actual, _ = _snapshot(base)
        del actual["RECEIPT.json"]
        if actual != receipt.get("files"):
            raise ValueError("trial files changed after collection; summary refused")
        result = load(base / "RESULT.json")
        if result["execution_mode"] != start["execution_mode"]:
            raise ValueError("trial execution mode differs from the frozen pair")
        results.append(result)
        rows.append({"arm": arm, "status": result["status"], "accepted": result["accepted"],
                     "provider_error": result.get("provider_error"),
                     "grade": result["grade"], "elapsed_seconds": result["elapsed_seconds"],
                     "result": f"{arm}/RESULT.json", "trace": f"{arm}/evidence/trace.jsonl"})
    complete_pair = len(results) == 2 and all(result["status"] == "completed" for result in results)
    usage_complete = not incomplete and all(result["budget"]["usage_complete"] for result in results)
    known_calls = sum(result["model_calls"] for result in results)
    return {"protocol_id": PROTOCOL, "comparison": "constrained_skill_guidance_not_full_package",
            "execution_mode": start["execution_mode"], "planned_trials": 2,
            "completed_trials": sum(row["status"] == "completed" for row in rows),
            "accepted_trials": sum(row["accepted"] for row in rows), "rows": rows,
            "live_model_calls": 0 if offline else (None if incomplete else known_calls),
            "offline_model_calls": (None if incomplete else known_calls) if offline else 0,
            "tokens_used": sum(result["budget"]["known_tokens"] for result in results) if not offline and usage_complete else None,
            "known_reported_tokens": sum(result["budget"]["known_tokens"] for result in results),
            "usage_complete": usage_complete,
            "paired_effect": int(rows[1]["accepted"]) - int(rows[0]["accepted"]) if not offline and complete_pair else None,
            "cost": None, "limitations": [
                "One fixed A-then-B development pair is not a statistical estimate of general agent benefit.",
                "B reads the skill; it cannot execute bundled helpers. Earlier full-package pilot slots are unchanged.",
                "Equal per-arm token allocations gate requests; unknown usage stops the pair, without refunds or retries.",
                "Reported tokens are not subscription balance or a guaranteed provider billing cap.",
                "Trusted local commands, no OS sandbox; hash receipts detect accidental changes, not coordinated forgery.",
                "Local-fixture responses and usage are scripted, never evidence of real model effectiveness."]}


def run_pair(args, configuration: dict) -> dict:
    # Canonicalize the operator-selected parent once (e.g. macOS /var). The
    # preflight rejects an existing/linked selected output; links *inside*
    # frozen scopes are still rejected by the broker and publication seal.
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    disk_gate(output)
    profile, limits = configuration["profile"], configuration["limits"]
    skill_source = ROOT / "skills/ai-research-reproduction"
    skill_files = inventory(skill_source)
    task = prepare_task(args.task, output / "inputs/repo", ROOT)
    shutil.copytree(skill_source, output / "inputs/skill", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if inventory(output / "inputs/skill") != skill_files:
        raise ValueError("skill changed while freezing inputs")
    slots = [{"arm": arm, "prompt_sha256": sha(prompt_for(task, arm).encode("utf-8"))} for arm in ("A", "B")]
    start = {"protocol_id": PROTOCOL, "created_at": datetime.now(timezone.utc).isoformat(),
             "task": task, "planned_slots": slots, "profile": profile, **{key: configuration[key] for key in (
                 "environment", "limits", "execution_mode")},
             "skill_files": skill_files, "implementation_files": {name: sha((ROOT / name).read_bytes()) for name in SOURCES}}
    durable_new(output / "START.json", start)
    durable_new(output / "FREEZE.json", {"start_sha256": sha((output / "START.json").read_bytes())})
    for slot in slots:
        disk_gate(output)
        arm, base = slot["arm"], output / slot["arm"]
        if {name: sha((ROOT / name).read_bytes()) for name in SOURCES} != start["implementation_files"]:
            raise ValueError("executor changed during the pair; evidence retained")
        if python_environment(args.python) != start["environment"]:
            raise ValueError("Python environment changed during the pair")
        shutil.copytree(output / "inputs/repo", base / "repo")
        skill = output / "inputs/skill" if arm == "B" else None
        if inventory(output / "inputs/skill") != skill_files:
            raise ValueError("frozen skill changed during the pair")
        broker = TrialBroker(base / "repo", base / "evidence", task,
                             configuration["environment"]["requested_executable"], skill_root=skill)
        ledger_limits = {key: limits[key] for key in ("max_model_calls", "max_tool_calls", "max_seconds")}
        ledger_limits["max_total_tokens"] = limits["max_tokens_per_trial"]
        ledger = BudgetLedger(base / "evidence/budget.jsonl", ledger_limits)
        result = run_trial(broker=broker, provider=TrialMessagesProvider(profile), ledger=ledger,
                           identity={key: profile[key] for key in ("provider", "model", "revision")},
                           prompt=prompt_for(task, arm), trace_path=base / "evidence/trace.jsonl",
                           max_output_tokens=limits["max_output_tokens"], execution_mode=configuration["execution_mode"])
        durable_new(base / "RESULT.json", result)
        seal(base, sha((output / "START.json").read_bytes()), arm)
        if (result["status"] != "completed" or not result["trace_complete"]
                or not result["budget"]["usage_complete"] or not result["budget"]["budget_compliant"]):
            break
    report = summarize(output)
    durable_new(output / "SUMMARY.json", report)
    disk_gate(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run"):
        command = sub.add_parser(name)
        command.add_argument("--task", choices=TASK_IDS, required=True)
        command.add_argument("--model-profile", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--python", default=sys.executable)
        command.add_argument("--local-fixture", action="store_true", help="Loopback scripted protocol test only; never model evidence")
        for flag, default in (("max-total-tokens", 60000), ("max-model-calls", 8), ("max-tool-calls", 20),
                              ("max-seconds", 120), ("max-output-tokens", 1000)):
            command.add_argument("--" + flag, type=int, default=default)
    sub.add_parser("summarize").add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "summarize":
            result = summarize(args.output)
        else:
            configuration = configure(args)
            result = ({"ready": True, "phase": "preflight_only", "model_calls": 0,
                       "execution_mode": configuration["execution_mode"], "limits": configuration["limits"],
                       "note": "Configuration and local environment only; endpoint reachability is not tested."}
                      if args.command == "preflight" else run_pair(args, configuration))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return int(args.command == "run" and result["accepted_trials"] != 2)
    except Exception as error:
        # Do not echo arbitrary provider/profile exception text or claim zero
        # requests after an interrupted run. START and pending ledgers survive.
        print(json.dumps({"ok": False, "error_type": type(error).__name__,
                          "message": str(error) if isinstance(error, ConfigurationError) else
                          "Check profile, limits and fresh output; existing evidence was retained.",
                          "model_calls": 0 if args.command == "preflight" else None}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
