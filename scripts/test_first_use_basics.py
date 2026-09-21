#!/usr/bin/env python3
"""Offline preflight and quota-contract tests; never call Codex or a model."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/ai-research-reproduction/scripts"))
import doctor
from check_codex_quota import quota_snapshot


class FirstUseBasics(unittest.TestCase):
    def test_current_installed_bundle_and_stdlib(self):
        report = doctor.inspect(ROOT / "skills/ai-research-reproduction", ROOT, ("json",))
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["python"], sys.executable)

    def test_missing_bundle_repo_and_module_are_actionable(self):
        with tempfile.TemporaryDirectory() as temp:
            report = doctor.inspect(Path(temp), Path(temp) / "missing", ("rigorpilot_nonexistent_module_xyz",))
            self.assertFalse(report["ok"])
            failures = [item for item in report["checks"] if not item["ok"]]
            self.assertTrue(all(item["next_action"]["en"] and item["next_action"]["zh"] for item in failures))
            self.assertIn("module:rigorpilot_nonexistent_module_xyz", [item["check"] for item in failures])

    def test_no_dotted_module_import(self):
        with self.assertRaises(ValueError):
            doctor.inspect(ROOT / "skills/ai-research-reproduction", modules=("json.decoder",))

    def test_quota_is_minimum_of_reported_windows_and_not_billing_guarantee(self):
        result = quota_snapshot({"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 8},
                                                "secondary": {"usedPercent": 45}, "credits": "private"}})
        self.assertEqual(result["minimum_remaining_percent"], 55)
        self.assertFalse(result["hard_budget_guarantee"])
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(result["model_turns_started"], 0)

    def test_quota_rejects_missing_or_invalid_measurements(self):
        for value in ({}, {"rateLimits": {"primary": {"usedPercent": True}}},
                      {"rateLimits": {"primary": {"usedPercent": float("nan")}}},
                      {"rateLimits": {"limitId": "other", "primary": {"usedPercent": 5}}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                quota_snapshot(value)

    def test_timeout_help_preserves_orchestrator_finalization(self):
        orchestrator = ROOT / "skills/ai-research-reproduction/scripts/orchestrate_repro.py"
        result = subprocess.run(
            [sys.executable, str(orchestrator), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertIn("Target-command timeout", result.stdout)
        self.assertIn("equal or shorter external timeout", result.stdout)
        self.assertIn("terminal evidence finalization", result.stdout)


if __name__ == "__main__":
    unittest.main()
