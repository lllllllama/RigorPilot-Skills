#!/usr/bin/env python3
"""Controller regressions use only scripted transports, never real model calls.

These tests exercise accounting and fail-closed tool dispatch. They do not
measure model ability, infer subscription usage, or establish OS isolation.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

from trial_budget import BudgetLedger

IDENTITY = {
    "provider": "scripted-unit-fixture",
    "model": "scripted-unit-model",
    "revision": "frozen-unit-revision",
}


def response(*blocks: dict, usage: object = None, model: str = IDENTITY["model"]) -> dict:
    """A transport fixture, not a real provider response or usage observation."""
    return {
        "model": model,
        "content": list(blocks),
        "usage": {"input_tokens": 4, "output_tokens": 3} if usage is None else usage,
    }


def tool(name: str = "run_command", *, identifier: str = "tool-unit-1", **arguments) -> dict:
    return {"type": "tool_use", "id": identifier, "name": name, "input": arguments}


class ScriptedProvider:
    def __init__(self, *responses: object, before_response=None):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.before_response = before_response

    def complete(self, messages, system, tools, max_tokens, timeout):
        self.calls.append(copy.deepcopy({
            "messages": messages, "system": system, "tools": tools,
            "max_tokens": max_tokens, "timeout": timeout,
        }))
        if self.before_response is not None:
            self.before_response()
        if not self.responses:
            raise AssertionError("Controller made an unexpected extra fixture call")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)


class FakeBroker:
    def __init__(self, *, grade=None, failures=None):
        self.finished = False
        self.grade = None
        self.calls: list[tuple[str, dict]] = []
        self.run_count = 0
        self.result_grade = {"correct_handling": True} if grade is None else grade
        self.failures = {} if failures is None else failures

    def dispatch(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name in self.failures:
            raise self.failures.pop(name)
        if name == "run_command":
            self.run_count += 1
            return {"returncode": 0, "stdout": "fixture-only output"}
        if name == "finish":
            self.finished = True
            self.grade = copy.deepcopy(self.result_grade)
            return self.grade
        return {"content": "fixture-only repository content"}


class TrialControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rigorpilot-controller-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.clock_value = 1000.0

    def ledger(self, **changes):
        limits = {
            "max_total_tokens": 100000,
            "max_model_calls": 4,
            "max_tool_calls": 6,
            "max_seconds": 30,
        }
        limits.update(changes)
        return BudgetLedger(self.work / "budget.jsonl", limits, clock=lambda: self.clock_value)

    def trial(self, provider, *, broker=None, ledger=None, **changes):
        from trial_controller import run_trial

        arguments = {
            "broker": FakeBroker() if broker is None else broker,
            "provider": provider,
            "ledger": self.ledger() if ledger is None else ledger,
            "identity": dict(IDENTITY),
            "prompt": "Read the repository README, run its documented evaluation, and report its real outcome.",
            "trace_path": self.work / "trace.jsonl",
            "max_output_tokens": 128,
            "execution_mode": "offline_simulation",
        }
        arguments.update(changes)
        return run_trial(**arguments)

    def trace(self):
        return [json.loads(line) for line in (self.work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_identity_requires_exact_public_nonempty_fields_before_provider(self):
        variants = [None, {}, [], {**IDENTITY, "model": ""}, {**IDENTITY, "revision": " "},
                    {**IDENTITY, "provider": 1}, {**IDENTITY, "api_key": "fixture-must-not-be-used"}]
        for index, identity in enumerate(variants):
            with self.subTest(identity=identity):
                provider, broker = ScriptedProvider(), FakeBroker()
                ledger = BudgetLedger(self.work / f"invalid-identity-{index}.jsonl", {
                    "max_total_tokens": 100000, "max_model_calls": 4,
                    "max_tool_calls": 6, "max_seconds": 30,
                })
                with self.assertRaises(ValueError):
                    self.trial(provider, broker=broker, ledger=ledger, identity=identity)
                self.assertEqual(provider.calls, [])
                self.assertEqual(broker.calls, [])
                self.assertEqual(ledger.snapshot()["model_calls"], 0)

    def test_invalid_output_cap_never_reaches_provider(self):
        for index, value in enumerate((0, -1, True, 1.5, "128", None)):
            with self.subTest(cap=value):
                provider = ScriptedProvider()
                ledger = BudgetLedger(self.work / f"invalid-cap-{index}.jsonl", {
                    "max_total_tokens": 100000, "max_model_calls": 4,
                    "max_tool_calls": 6, "max_seconds": 30,
                })
                with self.assertRaises(ValueError):
                    self.trial(provider, ledger=ledger, max_output_tokens=value)
                self.assertEqual(provider.calls, [])
                self.assertEqual(ledger.snapshot()["model_calls"], 0)

    def test_tiny_reservation_budget_prevents_all_model_and_tool_calls(self):
        provider, broker, ledger = ScriptedProvider(), FakeBroker(), self.ledger(max_total_tokens=1)
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(provider.calls, [])
        self.assertEqual(broker.calls, [])
        self.assertEqual(ledger.snapshot()["model_calls"], 0)
        self.assertEqual(ledger.snapshot()["tokens_used"], 0)
        self.assertEqual(ledger.snapshot()["status"], "stopped")

    def test_provider_exception_is_unknown_and_is_not_retried(self):
        provider = ScriptedProvider(RuntimeError("fixture transport outcome unknown"))
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(ledger.snapshot()["model_calls"], 1)
        self.assertIsNone(ledger.snapshot()["tokens_used"])
        self.assertFalse(ledger.snapshot()["usage_complete"])

    def test_missing_usage_retains_unknown_outcome_without_dispatch(self):
        item = response(tool())
        del item["usage"]
        provider, broker, ledger = ScriptedProvider(item), FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertIsNone(ledger.snapshot()["tokens_used"])

    def test_excess_reported_usage_stops_before_any_side_effect(self):
        provider = ScriptedProvider(response(tool(), usage={"input_tokens": 100001, "output_tokens": 1}))
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(ledger.snapshot()["tokens_used"], 100002)
        self.assertFalse(ledger.snapshot()["budget_compliant"])

    def test_late_response_keeps_actual_usage_but_never_dispatches(self):
        def advance():
            self.clock_value += 31.0

        provider = ScriptedProvider(response(tool()), before_response=advance)
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(ledger.snapshot()["tokens_used"], 7)
        self.assertEqual(ledger.snapshot()["status"], "stopped")

    def test_model_identity_drift_is_charged_and_never_dispatches(self):
        provider = ScriptedProvider(response(tool(), model="unexpected-model"))
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(ledger.snapshot()["tokens_used"], 7)

    def test_duplicate_tool_ids_in_one_response_prevent_whole_batch(self):
        provider = ScriptedProvider(response(tool(), tool("finish")))
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(ledger.snapshot()["tokens_used"], 7)

    def test_duplicate_tool_id_across_rounds_is_not_replayed(self):
        provider = ScriptedProvider(response(tool()), response(tool()))
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(broker.run_count, 1)
        self.assertEqual(ledger.snapshot()["tokens_used"], 14)

    def test_malformed_trailing_block_prevents_first_valid_tool(self):
        provider = ScriptedProvider(response(tool(), {"type": "tool_use", "id": "bad", "name": "finish", "input": []}))
        broker, ledger = FakeBroker(), self.ledger()
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])

    def test_model_call_cap_blocks_next_round_after_valid_tool(self):
        provider = ScriptedProvider(response(tool()))
        broker, ledger = FakeBroker(), self.ledger(max_model_calls=1)
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.run_count, 1)
        self.assertEqual(ledger.snapshot()["model_calls"], 1)

    def test_tool_call_cap_prevents_second_side_effect(self):
        provider = ScriptedProvider(response(tool(identifier="one"), tool(identifier="two")))
        broker, ledger = FakeBroker(), self.ledger(max_tool_calls=1)
        self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.run_count, 1)
        self.assertEqual(ledger.snapshot()["tool_calls"], 1)

    def test_existing_trace_is_not_overwritten_or_resumed(self):
        trace = self.work / "trace.jsonl"
        original = b'{"fixture":"existing evidence"}\n'
        trace.write_bytes(original)
        provider, broker, ledger = ScriptedProvider(), FakeBroker(), self.ledger()
        with self.assertRaises((ValueError, FileExistsError)):
            self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(provider.calls, [])
        self.assertEqual(broker.calls, [])
        self.assertEqual(trace.read_bytes(), original)

    def test_scripted_completion_is_not_reported_as_live_usage(self):
        provider = ScriptedProvider(response(tool("finish", claim={
            "outcome": "matched", "observed_metrics": {}, "reason": "fixture only",
        })))
        broker, ledger = FakeBroker(), self.ledger()
        result = self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["execution_mode"], "offline_simulation")
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["live_model_calls"], 0)
        self.assertEqual(result["simulated_model_calls"], 1)
        self.assertEqual(result["fixture_reported_tokens"], 7)
        self.assertIsNone(result["tokens_used"])
        self.assertIsNone(result["cost"])
        events = self.trace()
        names = [item["event"] for item in events]
        self.assertLess(names.index("request_reserved"), names.index("model_response"))
        self.assertLess(names.index("model_response"), names.index("tool_start"))
        self.assertEqual(events[-1]["event"], "trial_end")
        self.assertTrue(result["trace_complete"])
        self.assertEqual(events[-1]["result"], result)

    def test_model_finish_does_not_override_independent_grade(self):
        provider = ScriptedProvider(response(tool("finish", claim={
            "outcome": "matched", "observed_metrics": {}, "reason": "model says success",
        })))
        grade = {"correct_handling": False, "false_success": True}
        result = self.trial(provider, broker=FakeBroker(grade=grade))
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["grade"], grade)

    def test_plain_text_success_claim_does_not_complete_task(self):
        provider, broker = ScriptedProvider(response({"type": "text", "text": "Everything passed!"})), FakeBroker()
        result = self.trial(provider, broker=broker)
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(result["accepted"])
        self.assertEqual(broker.calls, [])
        self.assertEqual(len(provider.calls), 1)

    def test_recoverable_broker_error_returns_tool_result_before_next_call(self):
        from trial_broker import BrokerError

        provider = ScriptedProvider(
            response(tool("read_file", identifier="bad-path", scope="repo", path="../private")),
            response(tool("finish", identifier="finished", claim={
                "outcome": "blocked", "observed_metrics": {}, "reason": "fixture only",
            })),
        )
        broker = FakeBroker(failures={"read_file": BrokerError("path_not_allowed", "do-not-persist-private-path")})
        result = self.trial(provider, broker=broker)
        self.assertEqual(len(provider.calls), 2)
        returned = provider.calls[1]["messages"][-1]
        self.assertEqual(returned["role"], "user")
        self.assertEqual(returned["content"][0]["type"], "tool_result")
        self.assertEqual(returned["content"][0]["tool_use_id"], "bad-path")
        self.assertTrue(returned["content"][0]["is_error"])
        self.assertEqual(json.loads(returned["content"][0]["content"]), {"error": "path_not_allowed"})
        self.assertNotIn("do-not-persist-private-path", (self.work / "trace.jsonl").read_text(encoding="utf-8"))
        self.assertTrue(result["accepted"])

    def test_provider_does_not_receive_controller_paths_or_secrets(self):
        provider = ScriptedProvider(response(tool("finish")))
        self.trial(provider)
        self.assertEqual(len(provider.calls), 1)
        request = provider.calls[0]
        self.assertEqual(request["max_tokens"], 128)
        self.assertGreater(request["timeout"], 0)
        self.assertLessEqual(request["timeout"], 30)
        self.assertEqual({item["name"] for item in request["tools"]},
                         {"list_files", "read_file", "run_command", "finish"})
        payload = json.dumps(request)
        self.assertNotIn(str(self.work), payload)
        self.assertNotIn(self.work.as_posix(), payload)
        self.assertNotIn("RigorPilot", request["system"])
        self.assertNotIn("api_key", payload)

    def test_provider_exception_text_is_not_persisted(self):
        private = "fixture-private-token-and-absolute-path"
        result = self.trial(ScriptedProvider(RuntimeError(private)))
        self.assertEqual(result["reason"], "provider_exception:RuntimeError")
        self.assertNotIn(private, (self.work / "trace.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn(private, (self.work / "budget.jsonl").read_text(encoding="utf-8"))

    def test_provider_argument_mutation_does_not_mutate_controller_tools(self):
        from trial_controller import TOOLS

        original = copy.deepcopy(TOOLS)

        class MutatingProvider(ScriptedProvider):
            def complete(self, messages, system, tools, max_tokens, timeout):
                result = super().complete(messages, system, tools, max_tokens, timeout)
                messages.append({"role": "system", "content": "fixture mutation"})
                tools.clear()
                return result

        provider = MutatingProvider(response(tool()), response(tool("finish", identifier="finished")))
        self.trial(provider)
        self.assertEqual(TOOLS, original)
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn("fixture mutation", json.dumps(provider.calls[1]["messages"]))
        self.assertEqual(provider.calls[1]["tools"], original)

    def test_cache_token_counts_are_included_in_fixture_accounting(self):
        usage = {"input_tokens": 4, "output_tokens": 3,
                 "cache_read_input_tokens": 5, "cache_creation_input_tokens": 6}
        result = self.trial(ScriptedProvider(response(tool("finish"), usage=usage)))
        self.assertEqual(result["fixture_reported_tokens"], 18)
        self.assertEqual(result["budget"]["known_tokens"], 18)
        self.assertIsNone(result["tokens_used"])

    def test_finished_broker_cannot_start_a_new_model_trial(self):
        broker = FakeBroker()
        broker.finished = True
        provider = ScriptedProvider()
        with self.assertRaises(ValueError):
            self.trial(provider, broker=broker)
        self.assertEqual(provider.calls, [])

    def test_used_ledger_cannot_silently_resume_or_replay(self):
        ledger = self.ledger()
        ledger.reserve("earlier-request", 1, 1)
        ledger.settle("earlier-request", {"input_tokens": 1, "output_tokens": 1})
        provider = ScriptedProvider()
        with self.assertRaises(ValueError):
            self.trial(provider, ledger=ledger)
        self.assertEqual(provider.calls, [])

    def test_invalid_prompt_and_mode_fail_before_provider(self):
        variants = [{"prompt": value} for value in ("", " ", None, "x" * (256 * 1024 + 1))]
        variants += [{"execution_mode": value} for value in ("", None, "live", "automatic", [], {})]
        for index, changes in enumerate(variants):
            with self.subTest(case=index):
                provider = ScriptedProvider()
                ledger = BudgetLedger(self.work / f"invalid-input-{index}.jsonl", {
                    "max_total_tokens": 100000, "max_model_calls": 4,
                    "max_tool_calls": 6, "max_seconds": 30,
                })
                with self.assertRaises(ValueError):
                    self.trial(provider, ledger=ledger, **changes)
                self.assertEqual(provider.calls, [])

    def test_malformed_usage_never_dispatches_or_reports_known_zero(self):
        variants = [[], {}, {"input_tokens": 1}, {"input_tokens": True, "output_tokens": 1},
                    {"input_tokens": -1, "output_tokens": 1},
                    {"input_tokens": 1, "output_tokens": 1, "cost": 0},
                    {"input_tokens": 1, "output_tokens": float("nan")}]
        for index, usage in enumerate(variants):
            with self.subTest(case=index):
                ledger = BudgetLedger(self.work / f"bad-usage-{index}.jsonl", {
                    "max_total_tokens": 100000, "max_model_calls": 4,
                    "max_tool_calls": 6, "max_seconds": 30,
                })
                provider, broker = ScriptedProvider(response(tool(), usage=usage)), FakeBroker()
                result = self.trial(provider, broker=broker, ledger=ledger,
                                    trace_path=self.work / f"bad-usage-trace-{index}.jsonl")
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(broker.calls, [])
                self.assertFalse(result["accepted"])
                self.assertFalse(result["budget"]["usage_complete"])
                self.assertIsNone(result["fixture_reported_tokens"])

    def test_malformed_content_is_charged_but_never_dispatches(self):
        variants = [None, [], {}, [1], [{"type": "text", "text": 1}],
                    [{"type": "tool_use", "id": "", "name": "run_command", "input": {}}],
                    [{"type": "tool_use", "id": "bad", "name": None, "input": {}}],
                    [{"type": "text", "text": "fixture", "extra": "unsupported"}],
                    [tool("finish", identifier="first"), tool(identifier="after-finish")]]
        for index, content in enumerate(variants):
            with self.subTest(case=index):
                ledger = BudgetLedger(self.work / f"bad-content-{index}.jsonl", {
                    "max_total_tokens": 100000, "max_model_calls": 4,
                    "max_tool_calls": 6, "max_seconds": 30,
                })
                item = response()
                item["content"] = content
                provider, broker = ScriptedProvider(item), FakeBroker()
                result = self.trial(provider, broker=broker, ledger=ledger,
                                    trace_path=self.work / f"bad-content-trace-{index}.jsonl")
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(broker.calls, [])
                self.assertFalse(result["accepted"])
                self.assertEqual(result["fixture_reported_tokens"], 7)

    def test_usage_is_durable_before_broker_observes_first_dispatch(self):
        ledger = self.ledger()
        testcase = self

        class CheckingBroker(FakeBroker):
            def dispatch(self, name, arguments):
                snapshot = ledger.snapshot()
                testcase.assertEqual(snapshot["known_tokens"], 7)
                testcase.assertEqual(snapshot["pending"], {})
                testcase.assertEqual(snapshot["tool_calls"], 1)
                events = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]
                testcase.assertEqual(events[-2]["type"], "settled")
                testcase.assertEqual(events[-1]["type"], "tool")
                return super().dispatch(name, arguments)

        result = self.trial(ScriptedProvider(response(tool("finish"))), broker=CheckingBroker(), ledger=ledger)
        self.assertTrue(result["accepted"])

    def test_unexpected_broker_exception_is_not_retried(self):
        provider = ScriptedProvider(response(tool()))
        broker = FakeBroker(failures={"run_command": RuntimeError("fixture-private-error")})
        result = self.trial(provider, broker=broker)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(broker.calls), 1)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "controller_error:RuntimeError")
        self.assertNotIn("fixture-private-error", (self.work / "trace.jsonl").read_text(encoding="utf-8"))

    def test_transport_reservation_is_durable_before_dispatch(self):
        ledger = self.ledger()
        testcase = self

        def inspect_reservation():
            snapshot = ledger.snapshot()
            testcase.assertEqual(snapshot["model_calls"], 1)
            testcase.assertEqual(len(snapshot["pending"]), 1)
            testcase.assertFalse(snapshot["usage_complete"])
            events = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]
            testcase.assertEqual(events[-1]["type"], "reserved")

        provider = ScriptedProvider(response(tool("finish")), before_response=inspect_reservation)
        result = self.trial(provider, ledger=ledger)
        self.assertTrue(result["accepted"])

    def test_trace_failure_before_transport_prevents_dispatch(self):
        from trial_controller import Trace

        provider, broker = ScriptedProvider(), FakeBroker()
        with mock.patch.object(Trace, "record", side_effect=OSError("fixture disk-full failure")):
            result = self.trial(provider, broker=broker)
        self.assertEqual(provider.calls, [])
        self.assertEqual(broker.calls, [])
        self.assertFalse(result["trace_complete"])
        self.assertFalse(result["accepted"])

    def test_output_usage_over_request_cap_stops_below_total_budget(self):
        provider = ScriptedProvider(response(tool(), usage={"input_tokens": 4, "output_tokens": 129}))
        broker = FakeBroker()
        result = self.trial(provider, broker=broker, max_output_tokens=128)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(result["fixture_reported_tokens"], 133)
        self.assertLess(133, result["budget"]["limits"]["max_total_tokens"])
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(result["accepted"])

    def test_input_usage_over_reservation_stops_below_total_budget(self):
        provider = ScriptedProvider(response(tool(), usage={"input_tokens": 90000, "output_tokens": 1}))
        broker = FakeBroker()
        result = self.trial(provider, broker=broker)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(result["fixture_reported_tokens"], 90001)
        self.assertLess(90001, result["budget"]["limits"]["max_total_tokens"])
        self.assertFalse(result["accepted"])

    def test_time_expires_while_recording_reservation_before_provider(self):
        from trial_controller import Trace

        original = Trace.record

        def delayed_record(trace, event, **fields):
            original(trace, event, **fields)
            if event == "request_reserved":
                self.clock_value += 31.0

        provider, broker, ledger = ScriptedProvider(response(tool())), FakeBroker(), self.ledger()
        with mock.patch.object(Trace, "record", new=delayed_record):
            result = self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(provider.calls, [])
        self.assertEqual(broker.calls, [])
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["dispatch_reservations"], 1)
        self.assertFalse(result["accepted"])

    def test_time_expires_while_recording_tool_start_before_dispatch(self):
        from trial_controller import Trace

        original = Trace.record

        def delayed_record(trace, event, **fields):
            original(trace, event, **fields)
            if event == "tool_start":
                self.clock_value += 31.0

        provider, broker, ledger = ScriptedProvider(response(tool())), FakeBroker(), self.ledger()
        with mock.patch.object(Trace, "record", new=delayed_record):
            result = self.trial(provider, broker=broker, ledger=ledger)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(broker.calls, [])
        self.assertEqual(result["fixture_reported_tokens"], 7)
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(result["accepted"])

    def test_request_trace_failure_retains_reservation_without_counting_invocation(self):
        from trial_controller import Trace

        original = Trace.record

        def fail_request_trace(trace, event, **fields):
            if event == "request_reserved":
                raise OSError("fixture cannot persist request trace")
            return original(trace, event, **fields)

        provider, broker = ScriptedProvider(), FakeBroker()
        with mock.patch.object(Trace, "record", new=fail_request_trace):
            result = self.trial(provider, broker=broker)
        self.assertEqual(provider.calls, [])
        self.assertEqual(broker.calls, [])
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["simulated_model_calls"], 0)
        self.assertEqual(result["dispatch_reservations"], 1)
        self.assertFalse(result["accepted"])

    def test_smoke_cli_runs_real_stdlib_commands_with_scripted_transport(self):
        # This is a real subprocess smoke with deliberately scripted model
        # decisions/usage, not evidence of a live agent or an A/B improvement.
        output = self.work / "offline-smoke"
        command = [sys.executable, str(ROOT / "benchmarks/run_controller_smoke.py"), "--output", str(output)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", timeout=25)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["checks_passed"], 4)
        self.assertEqual(summary["checks"], 4)
        self.assertEqual(summary["live_model_calls"], 0)
        self.assertLessEqual(summary["bytes"], 1024**2)
        report = json.loads((output / "REPORT.json").read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "offline_controller_acceptance")
        self.assertEqual(report["live_model_calls"], 0)
        for field in ("tokens_used", "cost", "paired_effect"):
            self.assertIsNone(report[field])
        rows = {item["scenario"]: item for item in report["rows"]}
        self.assertTrue(all(item["expected_boundary_observed"] for item in rows.values()))
        self.assertEqual(rows["missing_asset"]["command_attempts"], 3)
        self.assertEqual(rows["missing_asset"]["failed_commands"], 1)
        self.assertEqual(rows["wrong_metric"]["command_attempts"], 1)
        self.assertEqual(rows["unknown_usage"]["command_attempts"], 0)
        self.assertEqual(rows["path_denied"]["command_attempts"], 0)

        missing = output / "missing_asset"
        receipts = sorted((missing / "evidence/commands").rglob("receipt.json"))
        self.assertEqual(len(receipts), 3)
        first = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertNotEqual(first["returncode"], 0)
        self.assertIn("FileNotFoundError", first["stderr"])
        self.assertEqual((receipts[0].parent / "stderr.log").read_bytes().decode("utf-8"), first["stderr"])
        self.assertEqual([json.loads(path.read_text(encoding="utf-8"))["returncode"] for path in receipts[1:]], [0, 0])
        for row in rows.values():
            result = json.loads((output / row["result"]).read_text(encoding="utf-8"))
            self.assertEqual(result["execution_mode"], "offline_simulation")
            self.assertEqual(result["live_model_calls"], 0)
            self.assertIsNone(result["tokens_used"])
            self.assertIsNone(result["cost"])
        wrong = json.loads((output / rows["wrong_metric"]["result"]).read_text(encoding="utf-8"))
        self.assertTrue(wrong["accepted"])
        self.assertFalse(wrong["grade"]["result_matched"])
        unknown = json.loads((output / rows["unknown_usage"]["result"]).read_text(encoding="utf-8"))
        self.assertEqual(unknown["status"], "stopped")
        self.assertEqual(unknown["simulated_model_calls"], 1)
        self.assertIsNone(unknown["fixture_reported_tokens"])
        self.assertTrue(unknown["budget"]["pending"])
        self.assertEqual(list((output / "unknown_usage/evidence/commands").iterdir()), [])

        before = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in output.rglob("*") if path.is_file()}
        repeated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                  encoding="utf-8", timeout=10)
        self.assertEqual(repeated.returncode, 2)
        self.assertFalse(json.loads(repeated.stdout)["ok"])
        after = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in output.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_smoke_cli_help_needs_no_transport_or_credentials(self):
        completed = subprocess.run([sys.executable, str(ROOT / "benchmarks/run_controller_smoke.py"), "--help"],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("--output", completed.stdout)
        self.assertIn("Offline controller checks", completed.stdout)

    def test_finish_result_trace_failure_stays_incomplete_after_writable_end(self):
        from trial_controller import Trace

        original = Trace.record
        injected = []

        def fail_finish_result_once(trace, event, **fields):
            if event == "tool_result" and fields["tool_call_id"] == "finish-fixture" and not injected:
                injected.append(event)
                raise OSError("fixture transient finish-result persistence failure")
            return original(trace, event, **fields)

        provider = ScriptedProvider(response(tool("finish", identifier="finish-fixture")))
        broker = FakeBroker()
        with mock.patch.object(Trace, "record", new=fail_finish_result_once):
            result = self.trial(provider, broker=broker)
        self.assertEqual(injected, ["tool_result"])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(broker.calls), 1)
        self.assertTrue(broker.finished)
        self.assertTrue(result["grade"]["correct_handling"])
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["trace_complete"])
        events = self.trace()
        self.assertEqual(events[-1]["event"], "trial_end")
        self.assertEqual(events[-1]["result"], result)
        self.assertFalse(any(item["event"] == "tool_result" for item in events))

    def test_final_trace_failure_retains_grade_without_accepted_completion(self):
        from trial_controller import Trace

        original = Trace.record
        injected = []

        def fail_trial_end(trace, event, **fields):
            if event == "trial_end":
                injected.append(event)
                raise OSError("fixture final evidence persistence failure")
            return original(trace, event, **fields)

        provider = ScriptedProvider(response(tool("finish", identifier="finish-fixture")))
        broker = FakeBroker()
        with mock.patch.object(Trace, "record", new=fail_trial_end):
            result = self.trial(provider, broker=broker)
        self.assertEqual(injected, ["trial_end"])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(broker.calls), 1)
        self.assertTrue(broker.finished)
        self.assertTrue(result["grade"]["correct_handling"])
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["trace_complete"])
        self.assertEqual(result["fixture_reported_tokens"], 7)
        self.assertTrue(any(item["event"] == "tool_result" for item in self.trace()))
        self.assertFalse(any(item["event"] == "trial_end" for item in self.trace()))


if __name__ == "__main__":
    unittest.main()
