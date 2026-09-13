#!/usr/bin/env python3
"""Exercise the paired CLI through a scripted local HTTP Messages service.

These are explicitly offline integration fixtures, not model effectiveness
evidence. Only the reviewed Python standard-library task commands execute;
no external requests, real credentials, packages, or model calls are needed.
"""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks/run_paired_trial.py"
CREDENTIAL_ENV = "RIGORPILOT_PAIRED_CLI_TEST_CREDENTIAL"
CREDENTIAL = "offline-fixture-sentinel-never-a-real-credential"
MODEL = "offline-fixture-model"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def inventory(path: Path) -> dict[str, str]:
    return {item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
            for item in path.rglob("*") if item.is_file()}


def response(name: str, arguments: dict, *, identity: str = MODEL,
             usage: dict | None = None, call_id: str = "fixture-action") -> dict:
    return {"id": "offline-fixture-response", "type": "message", "role": "assistant",
            "model": identity, "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 2, "output_tokens": 3} if usage is None else usage,
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": arguments}]}


def actions(task: str, *, outcome: str | None = None, inspect_skill: bool = False) -> list[dict]:
    mse = 0.0 if task == "missing_asset" else 1.0
    selected = [("read_file", {"scope": "repo", "path": "README.md"})]
    if inspect_skill:
        selected.append(("read_file", {"scope": "skill", "path": "SKILL.md"}))
    if task == "missing_asset":
        selected.append(("run_command", {"command_id": "prepare-data"}))
    selected.extend([
        ("run_command", {"command_id": "evaluate"}),
        ("read_file", {"scope": "repo", "path": "results/metrics.json"}),
        ("finish", {"claim": {"outcome": outcome or ("matched" if mse == 0 else "mismatched"),
                               "observed_metrics": {"mse": mse},
                               "reason": "Read the collected metrics; preserve the fixed scientific protocol."}}),
    ])
    return [response(name, arguments, call_id=f"fixture-action-{index}")
            for index, (name, arguments) in enumerate(selected)]


class ScriptedServer:
    """A local socket exercises the real transport, parser, and subprocess CLI."""

    def __init__(self, replies: list[dict | tuple[int, dict]]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.errors: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                try:
                    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    owner.requests.append({"path": self.path, "body": request,
                                           "credential": self.headers.get("x-api-key")})
                    index = len(owner.requests) - 1
                    if index >= len(owner.replies):
                        owner.errors.append("Unexpected request or automatic retry")
                        code, value = 500, {"error": {"message": "Unexpected local fixture request"}}
                    else:
                        reply = owner.replies[index]
                        code, value = reply if isinstance(reply, tuple) else (200, reply)
                except Exception as error:
                    owner.errors.append(type(error).__name__)
                    code, value = 500, {"error": {"message": "Invalid local fixture request"}}
                payload = json.dumps(value).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1/messages"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class PairedTrialCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="rigorpilot-paired-cli-test-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.output = self.work / "trial"
        self.profile_path = self.work / "model-profile.json"

    def profile(self, endpoint: str, **changes) -> Path:
        value = {"adapter_id": "anthropic-messages", "provider": "offline-fixture-provider",
                 "model": MODEL, "revision": "offline-fixture-revision",
                 "credential_env": CREDENTIAL_ENV, "endpoint": endpoint,
                 "capabilities": ["tool_calling"]}
        value.update(changes)
        self.profile_path.write_text(json.dumps(value), encoding="utf-8")
        return self.profile_path

    def cli(self, *arguments: str, credential: bool = True) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.pop(CREDENTIAL_ENV, None)
        # The fixture must never consult an ambient proxy or credential.
        for key in list(environment):
            if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
                environment.pop(key)
        environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if credential:
            environment[CREDENTIAL_ENV] = CREDENTIAL
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=ROOT,
                              env=environment, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=40)

    def run_cli(self, task: str = "missing_asset", *, command: str = "run",
                fixture: bool = True, credential: bool = True,
                extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        arguments = [command, "--task", task, "--model-profile", str(self.profile_path),
                     "--output", str(self.output), "--python", sys.executable,
                     "--max-total-tokens", "60001", "--max-model-calls", "8",
                     "--max-tool-calls", "20", "--max-seconds", "120",
                     "--max-output-tokens", "1000", *extra]
        if fixture:
            arguments.append("--local-fixture")
        return self.cli(*arguments, credential=credential)

    def assert_code(self, result: subprocess.CompletedProcess, expected: int) -> None:
        self.assertEqual(result.returncode, expected,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    def assert_offline(self, summary: dict, *, completed: int, calls: int) -> None:
        self.assertEqual(summary["planned_trials"], 2)
        self.assertEqual(summary["completed_trials"], completed)
        self.assertEqual(summary["live_model_calls"], 0)
        self.assertEqual(summary["offline_model_calls"], calls)
        self.assertIsNone(summary["tokens_used"])
        self.assertIsNone(summary["paired_effect"])
        self.assertEqual([item["arm"] for item in summary["rows"]], ["A", "B"])

    def assert_secret_absent(self, result: subprocess.CompletedProcess) -> None:
        self.assertNotIn(CREDENTIAL, result.stdout + result.stderr)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(CREDENTIAL.encode(), path.read_bytes(), str(path))

    def test_help_describes_all_three_commands(self) -> None:
        result = self.cli("--help")
        self.assert_code(result, 0)
        for command in ("run", "preflight", "summarize"):
            self.assertIn(command, result.stdout)

    def test_parent_path_alias_is_canonicalized_before_freezing_and_sealing(self) -> None:
        # macOS /var -> /private/var is an operator-selected parent alias, not
        # an agent-created link within the frozen repository/tool boundary.
        alias = self.work / "parent-alias"
        try:
            alias.symlink_to(self.work.resolve(), target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Creating directory symlinks is unavailable on this host")
            environment = {**os.environ, "RIGOR_TEST_ALIAS": str(alias),
                           "RIGOR_TEST_TARGET": str(self.work.resolve())}
            made = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                   "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                                   "-Path $env:RIGOR_TEST_ALIAS -Target $env:RIGOR_TEST_TARGET | Out-Null"],
                                  env=environment, capture_output=True, timeout=15)
            if made.returncode:
                self.skipTest("Creating a test-only parent junction is unavailable")
            self.addCleanup(alias.rmdir)  # Remove the junction itself, never its target.
        else:
            self.addCleanup(alias.unlink)
        self.output = alias / "trial"
        with ScriptedServer(actions("wrong_metric") + actions("wrong_metric")) as server:
            self.profile(server.endpoint)
            result = self.run_cli("wrong_metric")
            self.assert_code(result, 0)
        summary = load(self.output / "SUMMARY.json")
        self.assertEqual(summary["completed_trials"], 2)
        self.assert_code(self.cli("summarize", "--output", str(self.output)), 0)

    def test_missing_credential_preflight_has_no_network_or_trial(self) -> None:
        with ScriptedServer([]) as server:
            self.profile(server.endpoint)
            result = self.run_cli(command="preflight", credential=False)
            self.assert_code(result, 2)
            self.assertEqual(server.requests, [])
        self.assertFalse((self.output / "A/evidence/trace.jsonl").exists())
        self.assertFalse((self.output / "B/evidence/trace.jsonl").exists())
        self.assert_secret_absent(result)

    def test_valid_preflight_makes_no_model_or_command_calls(self) -> None:
        with ScriptedServer([]) as server:
            self.profile(server.endpoint)
            result = self.run_cli(command="preflight")
            self.assert_code(result, 0)
            self.assertEqual(server.requests, [])
        report = json.loads(result.stdout)
        self.assertTrue(report["ready"])
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["execution_mode"], "offline_simulation")
        self.assertFalse(self.output.exists())
        self.assertFalse((self.output / "A/evidence/trace.jsonl").exists())
        self.assertFalse(any(self.output.rglob("receipt.json")))
        self.assert_secret_absent(result)

    def test_invalid_identity_capability_and_adapter_profiles_never_call_transport(self) -> None:
        with ScriptedServer([]) as server:
            for changes in ({"revision": " "}, {"provider": ""}, {"model": None},
                            {"adapter_id": "external-agent"}, {"capabilities": []},
                            {"metadata": "bearer"},
                            {"credential_env": "UNFILTERED_AUTH"},
                            {"api_key": "inline-fixture-credential"}):
                with self.subTest(changes=changes):
                    self.profile(server.endpoint, **changes)
                    self.assert_code(self.run_cli(command="preflight"), 2)
                    self.assertFalse(self.output.exists())
            self.assertEqual(server.requests, [])

    def test_existing_output_is_rejected_without_modification(self) -> None:
        self.output.mkdir()
        (self.output / "operator-evidence.txt").write_bytes(b"Preserve existing evidence.\n")
        before = inventory(self.output)
        with ScriptedServer([]) as server:
            self.profile(server.endpoint)
            result = self.run_cli()
            self.assert_code(result, 2)
            self.assertEqual(server.requests, [])
        self.assertEqual(inventory(self.output), before)

    def test_loopback_cannot_be_mislabelled_as_live(self) -> None:
        with ScriptedServer([]) as server:
            self.profile(server.endpoint)
            result = self.run_cli(fixture=False)
            self.assert_code(result, 2)
            self.assertEqual(server.requests, [])
        self.assertFalse((self.output / "START.json").exists())

    def test_remote_endpoint_cannot_be_mislabelled_as_fixture(self) -> None:
        # .invalid is reserved; validation must reject this before DNS/transport.
        self.profile("https://paired-cli-fixture.invalid/v1/messages")
        result = self.run_cli()
        self.assert_code(result, 2)
        self.assertFalse((self.output / "START.json").exists())

    def test_missing_asset_runs_both_arms_with_real_reviewed_commands(self) -> None:
        scripted = actions("missing_asset")
        with ScriptedServer(scripted + scripted) as server:
            self.profile(server.endpoint)
            result = self.run_cli()
            self.assert_code(result, 0)
            self.assertEqual(len(server.requests), 10)
            self.assertEqual(server.errors, [])
            for request in server.requests:
                self.assertEqual(request["path"], "/v1/messages")
                self.assertEqual(request["credential"], CREDENTIAL)
                self.assertEqual(request["body"]["model"], MODEL)
                self.assertEqual(request["body"]["max_tokens"], 1000)
        start = load(self.output / "START.json")
        self.assertEqual(start["execution_mode"], "offline_simulation")
        self.assertEqual([slot["arm"] for slot in start["planned_slots"]], ["A", "B"])
        self.assertEqual(start["limits"]["max_total_tokens"], 60001)
        self.assertEqual(start["limits"]["max_tokens_per_trial"], 30000)
        self.assertEqual(start["environment"]["executable"], sys.executable)
        frozen_profile = {key: value for key, value in start["profile"].items()
                          if key not in {"fingerprint", "source_path"}}
        profile_bytes = json.dumps(frozen_profile, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8")
        self.assertEqual(start["profile"]["fingerprint"], hashlib.sha256(profile_bytes).hexdigest())
        self.assertEqual(start["profile"]["endpoint"], server.endpoint)
        for name in ("benchmarks/run_paired_trial.py", "benchmarks/trial_controller.py",
                     "benchmarks/trial_budget.py", "benchmarks/trial_broker.py",
                     "benchmarks/paired_tasks.py", "shared/scripts/agent_provider.py",
                     "shared/scripts/model_adapter.py"):
            self.assertRegex(start["implementation_files"][name], r"^[0-9a-f]{64}$")
        for arm in ("A", "B"):
            trial = self.output / arm
            arm_result = load(trial / "RESULT.json")
            self.assertEqual(arm_result["status"], "completed")
            self.assertTrue(arm_result["accepted"])
            self.assertTrue(arm_result["grade"]["source_integrity"])
            self.assertTrue(arm_result["grade"]["execution_verified"])
            self.assertEqual(arm_result["budget"]["limits"]["max_total_tokens"], 30000)
            self.assertEqual(arm_result["fixture_reported_tokens"], 25)
            self.assertIsNone(arm_result["tokens_used"])
            self.assertTrue((trial / "RECEIPT.json").is_file())
            trace_start = json.loads((trial / "evidence/trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
            slot = next(item for item in start["planned_slots"] if item["arm"] == arm)
            self.assertEqual(slot["prompt_sha256"], hashlib.sha256(trace_start["prompt"].encode("utf-8")).hexdigest())
            for name, expected_hash in start["task"]["immutable_sha256"].items():
                self.assertEqual(hashlib.sha256((trial / "repo" / name).read_bytes()).hexdigest(), expected_hash)
            receipts = sorted((trial / "evidence").rglob("receipt.json"))
            self.assertEqual([load(path)["step_id"] for path in receipts], ["prepare-data", "evaluate"])
            for receipt_path in receipts:
                receipt = load(receipt_path)
                self.assertEqual(receipt["returncode"], 0)
                self.assertEqual(Path(receipt["cwd"]).resolve(), (trial / "repo").resolve())
                self.assertEqual(Path(receipt["argv"][0]).resolve(), Path(sys.executable).resolve())
                self.assertTrue((receipt_path.parent / "stdout.log").is_file())
            metrics = load(trial / "repo/results/metrics.json")
            self.assertEqual(metrics["mse"], 0.0)
            for name in ("config.json", "data/samples.csv"):
                key = "config_sha256" if name == "config.json" else "data_sha256"
                self.assertEqual(metrics[key], hashlib.sha256((trial / "repo" / name).read_bytes()).hexdigest())
        for name in ("README.md", "evaluate.py", "prepare_data.py", "config.json"):
            self.assertEqual((self.output / "A/repo" / name).read_bytes(),
                             (self.output / "B/repo" / name).read_bytes())
        summary = load(self.output / "SUMMARY.json")
        self.assert_offline(summary, completed=2, calls=10)
        self.assertTrue(all(row["accepted"] for row in summary["rows"]))
        summarized = self.cli("summarize", "--output", str(self.output))
        self.assert_code(summarized, 0)
        self.assert_secret_absent(result)

    def test_honest_wrong_metric_is_accepted_without_claiming_metric_match(self) -> None:
        scripted = actions("wrong_metric", inspect_skill=True)
        with ScriptedServer(scripted + scripted) as server:
            self.profile(server.endpoint)
            result = self.run_cli("wrong_metric")
            self.assert_code(result, 0)
            self.assertEqual(len(server.requests), 10)
            self.assertEqual(server.errors, [])
        for arm in ("A", "B"):
            trial = self.output / arm
            arm_result = load(trial / "RESULT.json")
            self.assertTrue(arm_result["accepted"])
            self.assertTrue(arm_result["grade"]["correct_handling"])
            self.assertFalse(arm_result["grade"]["result_matched"])
            self.assertFalse(arm_result["grade"]["false_success"])
            self.assertEqual(load(trial / "repo/results/metrics.json")["mse"], 1.0)
            self.assertEqual(load(trial / "repo/config.json"), {"slope": 2.0, "bias": 2.0})
            events = [json.loads(line) for line in (trial / "evidence/trace.jsonl").read_text(encoding="utf-8").splitlines()]
            skill_result = next(event for event in events if event["event"] == "tool_result"
                                and event["tool_call_id"] == "fixture-action-1")
            self.assertEqual(skill_result["is_error"], arm == "A")
            if arm == "A":
                self.assertEqual(skill_result["result"]["error"], "scope_denied")
            else:
                self.assertIn("SKILL.md", skill_result["result"]["path"])
        self.assert_offline(load(self.output / "SUMMARY.json"), completed=2, calls=10)
        self.assert_secret_absent(result)

    def test_completed_false_success_is_retained_and_does_not_skip_b(self) -> None:
        with ScriptedServer(actions("wrong_metric", outcome="matched") + actions("wrong_metric")) as server:
            self.profile(server.endpoint)
            result = self.run_cli("wrong_metric")
            self.assert_code(result, 1)
            self.assertEqual(len(server.requests), 8)
        summary = load(self.output / "SUMMARY.json")
        self.assert_offline(summary, completed=2, calls=8)
        self.assertEqual([row["status"] for row in summary["rows"]], ["completed", "completed"])
        self.assertEqual([row["accepted"] for row in summary["rows"]], [False, True])
        self.assertTrue(load(self.output / "A/RESULT.json")["grade"]["false_success"])

    def assert_stops_before_tool(self, reply: dict | tuple[int, dict]) -> None:
        with ScriptedServer([reply]) as server:
            self.profile(server.endpoint)
            result = self.run_cli("wrong_metric")
            self.assert_code(result, 1)
            self.assertEqual(len(server.requests), 1)
            self.assertEqual(server.errors, [])
        summary = load(self.output / "SUMMARY.json")
        self.assert_offline(summary, completed=0, calls=1)
        self.assertEqual(summary["rows"][1]["status"], "not_run")
        self.assertFalse(summary["rows"][0]["accepted"])
        arm_result = load(self.output / "A/RESULT.json")
        self.assertEqual(arm_result["status"], "stopped")
        self.assertEqual(arm_result["budget"]["tool_calls"], 0)
        self.assertFalse(any((self.output / "A/evidence").rglob("receipt.json")))
        self.assertFalse((self.output / "A/repo/results/metrics.json").exists())
        self.assertFalse((self.output / "B/evidence/trace.jsonl").exists())
        self.assert_code(self.cli("summarize", "--output", str(self.output)), 0)
        self.assert_secret_absent(result)

    def test_changed_model_identity_stops_before_any_tool_or_b(self) -> None:
        self.assert_stops_before_tool(response("run_command", {"command_id": "evaluate"}, identity="different-model"))
        self.assertTrue(load(self.output / "A/RESULT.json")["budget"]["usage_complete"])

    def test_unknown_usage_stops_before_any_tool_or_b(self) -> None:
        self.assert_stops_before_tool(response("run_command", {"command_id": "evaluate"}, usage={"input_tokens": 2}))
        result = load(self.output / "A/RESULT.json")
        self.assertFalse(result["budget"]["usage_complete"])
        self.assertIsNone(result["budget"]["tokens_used"])

    def test_documented_usage_metadata_is_not_double_counted(self) -> None:
        scripted = actions("wrong_metric")
        for item in scripted:
            item["usage"].update(cache_creation_input_tokens=4, cache_read_input_tokens=5,
                                 cache_creation={"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 4},
                                 output_tokens_details={"thinking_tokens": 1}, service_tier="standard",
                                 inference_geo="global", server_tool_use={"web_fetch_requests": 0, "web_search_requests": 0})
            item["content"][0]["caller"] = {"type": "direct"}
            item["content"].insert(0, {"type": "text", "text": "Inspect the actual output.", "citations": []})
        with ScriptedServer(scripted + scripted) as server:
            self.profile(server.endpoint)
            self.assert_code(self.run_cli("wrong_metric"), 0)
        for arm in ("A", "B"):
            result = load(self.output / arm / "RESULT.json")
            self.assertTrue(result["accepted"])
            self.assertEqual(result["fixture_reported_tokens"], len(scripted) * 14)

    def test_unknown_billing_field_stops_before_tools(self) -> None:
        self.assert_stops_before_tool(response("run_command", {"command_id": "evaluate"},
                                              usage={"input_tokens": 2, "output_tokens": 3, "new_billable_tokens": 1}))
        self.assertFalse(load(self.output / "A/RESULT.json")["budget"]["usage_complete"])

    def test_server_side_tool_charges_are_not_silently_dropped(self) -> None:
        self.assert_stops_before_tool(response("run_command", {"command_id": "evaluate"}, usage={
            "input_tokens": 2, "output_tokens": 3, "server_tool_use": {"web_search_requests": 1}}))
        self.assertFalse(load(self.output / "A/RESULT.json")["budget"]["usage_complete"])

    def test_transport_failure_is_not_retried_and_stops_b(self) -> None:
        self.assert_stops_before_tool((503, {"error": {"message": CREDENTIAL}}))
        self.assertFalse(load(self.output / "A/RESULT.json")["budget"]["usage_complete"])
        expected = {"code": "http_error", "http_status": 503}
        self.assertEqual(load(self.output / "A/RESULT.json")["provider_error"], expected)
        self.assertEqual(load(self.output / "SUMMARY.json")["rows"][0]["provider_error"], expected)
        events = [json.loads(line) for line in (self.output / "A/evidence/trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(next(event for event in events if event["event"] == "provider_failure")["provider_error"], expected)

    def test_model_call_cap_stops_incomplete_pair_with_fixed_denominator(self) -> None:
        with ScriptedServer(actions("wrong_metric")[:1]) as server:
            self.profile(server.endpoint)
            result = self.run_cli("wrong_metric", extra=("--max-model-calls", "1"))
            self.assert_code(result, 1)
            self.assertEqual(len(server.requests), 1)
        summary = load(self.output / "SUMMARY.json")
        self.assert_offline(summary, completed=0, calls=1)
        self.assertEqual(summary["rows"][1]["status"], "not_run")
        self.assertEqual(load(self.output / "A/RESULT.json")["budget"]["model_calls"], 1)

    def test_summarize_rejects_changed_frozen_inputs_results_metrics_and_receipts(self) -> None:
        scripted = actions("wrong_metric")
        with ScriptedServer(scripted + scripted) as server:
            self.profile(server.endpoint)
            self.assert_code(self.run_cli("wrong_metric"), 0)
        before_summary = (self.output / "SUMMARY.json").read_bytes()
        receipt = next((self.output / "A/evidence").rglob("receipt.json"))
        paths = (self.output / "START.json", self.output / "inputs/repo/README.md",
                 self.output / "inputs/skill/SKILL.md", self.output / "A/RESULT.json",
                 self.output / "A/repo/results/metrics.json", receipt)
        for path in paths:
            with self.subTest(path=path.relative_to(self.output).as_posix()):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b" \n")
                    result = self.cli("summarize", "--output", str(self.output))
                    self.assert_code(result, 2)
                    self.assertEqual((self.output / "SUMMARY.json").read_bytes(), before_summary)
                finally:
                    path.write_bytes(original)
        # A sealed result from the wrong arm is still invalid evidence, even
        # though its files and individual hashes remain completely unchanged.
        first, second, holding = (self.output / name for name in ("A", "B", "swap-holding"))
        first.rename(holding)
        second.rename(first)
        holding.rename(second)
        try:
            result = self.cli("summarize", "--output", str(self.output))
            self.assert_code(result, 2)
            self.assertIsNone(json.loads(result.stdout)["model_calls"])
            self.assertEqual((self.output / "SUMMARY.json").read_bytes(), before_summary)
        finally:
            first.rename(holding)
            second.rename(first)
            holding.rename(second)
        self.assert_code(self.cli("summarize", "--output", str(self.output)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
