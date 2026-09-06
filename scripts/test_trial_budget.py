#!/usr/bin/env python3
"""Durable budget state-machine tests; no model calls or provider credentials."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from trial_budget import BudgetLedger, BudgetStop


class TrialBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rigorpilot-budget-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.jsonl"
        self.now = 1000.0
        self.limits = {"max_total_tokens": 100, "max_model_calls": 3, "max_tool_calls": 3, "max_seconds": 20}

    def ledger(self, **changes):
        return BudgetLedger(self.path, {**self.limits, **changes}, clock=lambda: self.now)

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_new_ledger_has_explicit_scope_and_zero_known_usage(self):
        state = self.ledger().snapshot()
        self.assertEqual(state["scope"], "single_trial")
        self.assertEqual(state["tokens_used"], 0)
        self.assertEqual(state["enforcement"], "reservation_plus_post_response_stop")
        self.assertEqual(self.rows()[0]["limits"], self.limits)

    def test_limits_require_exact_positive_integers(self):
        for invalid in (True, 0, -1, 1.0, "100", None, float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.ledger(max_total_tokens=invalid)
        with self.assertRaises(ValueError):
            self.ledger(extra=1)
        with self.assertRaises(ValueError):
            BudgetLedger(self.path, {}, clock=lambda: self.now)
        self.assertFalse(self.path.exists())

    def test_reservation_is_durable_before_return_and_not_known_usage(self):
        ledger = self.ledger()
        with mock.patch("trial_budget.os.fsync", wraps=__import__("os").fsync) as sync:
            ledger.reserve("r1", 20, 10)
            self.assertEqual(sync.call_count, 1)
        self.assertEqual(self.rows()[-1]["type"], "reserved")
        self.assertEqual(ledger.snapshot()["reserved_tokens"], 30)
        self.assertIsNone(ledger.snapshot()["tokens_used"])

    def test_settlement_releases_only_known_reservation(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        ledger.settle("r1", {"input_tokens": 15, "output_tokens": 5})
        self.assertEqual(ledger.snapshot()["tokens_used"], 20)
        self.assertEqual(ledger.snapshot()["reserved_tokens"], 0)
        ledger.reserve("r2", 60, 20)

    def test_cache_usage_counts_toward_actual_tokens(self):
        ledger = self.ledger()
        ledger.reserve("r1", 50, 10)
        ledger.settle("r1", {"input_tokens": 10, "output_tokens": 5,
                             "cache_creation_input_tokens": 20, "cache_read_input_tokens": 15})
        self.assertEqual(ledger.snapshot()["known_tokens"], 50)

    def test_invalid_usage_is_durable_unknown_and_keeps_reservation(self):
        for invalid in ({}, None, {"input_tokens": True, "output_tokens": 1},
                        {"input_tokens": -1, "output_tokens": 1},
                        {"input_tokens": 1.0, "output_tokens": 1},
                        {"input_tokens": float("nan"), "output_tokens": 1},
                        {"input_tokens": 1, "output_tokens": 1, "unaccounted_tokens": 4}):
            with self.subTest(invalid=invalid):
                path = Path(self.temp.name) / f"invalid-{len(list(Path(self.temp.name).iterdir()))}.jsonl"
                ledger = BudgetLedger(path, self.limits, clock=lambda: self.now)
                ledger.reserve("r1", 20, 10)
                with self.assertRaises(BudgetStop):
                    ledger.settle("r1", invalid)
                self.assertIsNone(ledger.snapshot()["tokens_used"])
                self.assertEqual(ledger.snapshot()["reserved_tokens"], 30)
                self.assertEqual(json.loads(path.read_text().splitlines()[-1])["type"], "unknown")

    def test_overshoot_retains_actual_usage_then_stops(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        with self.assertRaises(BudgetStop):
            ledger.settle("r1", {"input_tokens": 110, "output_tokens": 5})
        state = ledger.snapshot()
        self.assertEqual(state["known_tokens"], 115)
        self.assertEqual(state["tokens_used"], 115)
        self.assertFalse(state["budget_compliant"])
        self.assertEqual(self.ledger().snapshot()["known_tokens"], 115)
        with self.assertRaises(BudgetStop):
            ledger.tool_call()

    def test_pending_recovery_stops_and_preserves_every_byte(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        before = self.path.read_bytes()
        recovered = self.ledger()
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertEqual(recovered.snapshot()["status"], "stopped")
        self.assertEqual(recovered.snapshot()["reserved_tokens"], 30)
        with self.assertRaises(BudgetStop):
            recovered.reserve("r1", 20, 10)
        size = self.path.stat().st_size
        self.assertEqual(self.ledger().snapshot()["status"], "stopped")
        self.assertEqual(self.path.stat().st_size, size)

    def test_completed_recovery_retains_usage_and_call_counts(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        ledger.settle("r1", {"input_tokens": 5, "output_tokens": 1})
        ledger.tool_call()
        recovered = self.ledger()
        self.assertEqual(recovered.snapshot()["known_tokens"], 6)
        self.assertEqual(recovered.snapshot()["model_calls"], 1)
        self.assertEqual(recovered.snapshot()["tool_calls"], 1)
        recovered.check()

    def test_recovery_rejects_changed_limits_without_writes(self):
        self.ledger()
        before = self.path.read_bytes()
        with self.assertRaises(BudgetStop):
            self.ledger(max_total_tokens=101)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unknown_transport_outcome_is_not_retried(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        with self.assertRaises(BudgetStop):
            ledger.mark_unknown("transport timeout; request outcome unknown")
        self.assertIsNone(ledger.snapshot()["budget_compliant"])
        with self.assertRaises(BudgetStop):
            ledger.settle("r1", {"input_tokens": 1, "output_tokens": 1})

    def test_stop_preserves_known_usage_and_freezes_elapsed(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        ledger.settle("r1", {"input_tokens": 1, "output_tokens": 1})
        self.now += 2
        ledger.stop("unexpected response model")
        self.now += 200
        state = ledger.snapshot()
        self.assertEqual(state["tokens_used"], 2)
        self.assertEqual(state["elapsed_seconds"], 2)
        self.assertEqual(state["remaining_seconds"], 18)
        self.assertFalse(state["usage_unknown"])
        with self.assertRaises(BudgetStop):
            ledger.check()

    def test_stop_with_pending_keeps_unknown_reservation(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        ledger.stop("external cancellation")
        self.assertTrue(ledger.snapshot()["usage_unknown"])
        self.assertEqual(ledger.snapshot()["reserved_tokens"], 30)
        self.assertEqual(self.rows()[-1]["type"], "unknown")

    def test_unknown_outcome_keeps_previous_known_usage(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        ledger.settle("r1", {"input_tokens": 5, "output_tokens": 1})
        ledger.reserve("r2", 20, 10)
        with self.assertRaises(BudgetStop):
            ledger.mark_unknown("request failed after dispatch")
        self.assertEqual(ledger.snapshot()["known_tokens"], 6)
        self.assertIsNone(ledger.snapshot()["tokens_used"])
        self.assertEqual(self.ledger().snapshot()["known_tokens"], 6)

    def test_duplicate_request_ids_cannot_be_replayed(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        ledger.settle("r1", {"input_tokens": 1, "output_tokens": 1})
        with self.assertRaises(BudgetStop):
            ledger.reserve("r1", 20, 10)
        self.assertEqual(ledger.snapshot()["model_calls"], 1)

    def test_unknown_settlement_id_stops_with_pending_retained(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        with self.assertRaises(BudgetStop):
            ledger.settle("other", {"input_tokens": 1, "output_tokens": 1})
        self.assertEqual(ledger.snapshot()["reserved_tokens"], 30)
        self.assertTrue(ledger.snapshot()["usage_unknown"])

    def test_pending_request_prevents_another_model_dispatch(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        with self.assertRaises(BudgetStop):
            ledger.reserve("r2", 20, 10)
        self.assertEqual(ledger.snapshot()["model_calls"], 1)

    def test_pending_request_prevents_tool_dispatch(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        with self.assertRaises(BudgetStop):
            ledger.tool_call()
        self.assertEqual(ledger.snapshot()["tool_calls"], 0)

    def test_token_reservation_cap_stops_before_dispatch(self):
        ledger = self.ledger()
        with self.assertRaises(BudgetStop):
            ledger.reserve("r1", 90, 11)
        self.assertEqual(ledger.snapshot()["model_calls"], 0)
        self.assertEqual(self.rows()[-1]["type"], "stopped")

    def test_model_call_cap_stops_before_next_request(self):
        ledger = self.ledger(max_model_calls=1)
        ledger.reserve("r1", 20, 10)
        ledger.settle("r1", {"input_tokens": 1, "output_tokens": 1})
        with self.assertRaises(BudgetStop):
            ledger.reserve("r2", 20, 10)

    def test_tool_cap_is_durable(self):
        ledger = self.ledger(max_tool_calls=1)
        ledger.tool_call()
        with self.assertRaises(BudgetStop):
            ledger.tool_call()
        self.assertEqual(ledger.snapshot()["tool_calls"], 1)

    def test_time_cap_stops_at_exact_boundary(self):
        ledger = self.ledger()
        self.now += 20
        with self.assertRaises(BudgetStop):
            ledger.check()
        self.assertEqual(ledger.snapshot()["elapsed_seconds"], 20)
        self.assertEqual(self.rows()[-1]["type"], "stopped")

    def test_late_response_keeps_known_usage_before_time_stop(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        self.now += 21
        with self.assertRaises(BudgetStop):
            ledger.settle("r1", {"input_tokens": 11, "output_tokens": 2})
        self.assertEqual(ledger.snapshot()["tokens_used"], 13)
        self.assertEqual([row["type"] for row in self.rows()][-2:], ["settled", "stopped"])

    def test_expired_pending_is_unknown_and_preserved(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        self.now += 20
        with self.assertRaises(BudgetStop):
            ledger.check()
        self.assertIsNone(ledger.snapshot()["tokens_used"])
        self.assertEqual(ledger.snapshot()["reserved_tokens"], 30)

    def test_backwards_clock_stops(self):
        ledger = self.ledger()
        self.now -= 1
        with self.assertRaises(BudgetStop):
            ledger.check()

    def test_invalid_clock_and_reservation_inputs(self):
        with self.assertRaises(ValueError):
            BudgetLedger(self.path, self.limits, clock=lambda: float("nan"))
        ledger = self.ledger()
        for args in (("", 1, 1), ("../r1", 1, 1), ("r1", True, 1), ("r1", 1, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ledger.reserve(*args)
        self.assertEqual(ledger.snapshot()["model_calls"], 0)

    def test_truncated_or_duplicate_json_history_is_not_repaired(self):
        self.path.write_bytes(b'{"sequence":0,"sequence":0}\n')
        for contents in (self.path.read_bytes(), b'{"sequence":0}'):
            self.path.write_bytes(contents)
            with self.assertRaises(BudgetStop):
                self.ledger()
            self.assertEqual(self.path.read_bytes(), contents)

    def test_snapshot_copies_pending_and_limits(self):
        ledger = self.ledger()
        ledger.reserve("r1", 20, 10)
        state = ledger.snapshot()
        state["pending"]["r1"]["reserved_tokens"] = 0
        state["limits"]["max_total_tokens"] = 999
        self.assertEqual(ledger.snapshot()["reserved_tokens"], 30)
        self.assertEqual(ledger.snapshot()["limits"]["max_total_tokens"], 100)


if __name__ == "__main__":
    unittest.main()
