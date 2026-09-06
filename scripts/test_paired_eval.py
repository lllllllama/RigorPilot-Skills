#!/usr/bin/env python3
"""Offline pilot-protocol regressions; no models, network, or dependency installs.

Environment availability is a labelled unit-test fixture. Only the synthetic
standard-library calibration commands execute; this is not model A/B evidence.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks/paired_eval.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("paired_eval_under_test", SCRIPT)
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)

ENVIRONMENT_FIXTURE = {
    "executable": sys.executable,
    "requested_executable": str(Path(sys.executable).absolute()),
    "version": sys.version,
    "packages": {"torch": "unit-test-fixture-not-a-probe", "pytest": "unit-test-fixture-not-a-probe"},
    "dependency_scope": "unit-test metadata fixture; not evidence of usable dependencies",
}


class PairedEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="rigorpilot-paired-protocol-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.campaign = cls.work / "campaign"
        # One campaign keeps file copying bounded. Mutation tests restore each
        # touched file and the real calibration writes only fresh run folders.
        with mock.patch.object(pilot, "python_environment", return_value=ENVIRONMENT_FIXTURE):
            cls.prepared = pilot.prepare(cls.campaign, sys.executable)
        cls.manifest = pilot.frozen(cls.campaign)

    def setUp(self) -> None:
        probe = mock.patch.object(pilot, "python_environment", return_value=ENVIRONMENT_FIXTURE)
        probe.start()
        self.addCleanup(probe.stop)

    def workspace(self, task: str = "missing_asset", arm: str = "A") -> Path:
        slot = next(item for item in self.manifest["planned_live_slots"]
                    if item["task_id"] == task and item["arm"] == arm)
        return self.campaign / slot["workspace"]

    @contextmanager
    def changed(self, path: Path, payload: bytes):
        previous = path.read_bytes() if path.exists() else None
        path.write_bytes(payload)
        try:
            yield
        finally:
            if previous is None:
                path.unlink()
            else:
                path.write_bytes(previous)

    @contextmanager
    def configuration(self, **changes):
        value = {
            "provider": "unit-test-provider",
            "model": "unit-test-model",
            "revision": "unit-test-revision",
            "max_total_tokens": 6000,
            "max_tokens_per_trial": 1000,
            "max_seconds_per_trial": 30,
        }
        value.update(changes)
        path = self.work / "CONFIGURATION.json"
        with self.changed(path, json.dumps(value).encode("utf-8")):
            yield path

    def cli(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=10)

    def test_six_frozen_fresh_slots_and_identical_sources(self) -> None:
        slots = self.manifest["planned_live_slots"]
        self.assertEqual(len(slots), 6)
        self.assertEqual(len({item["slot_id"] for item in slots}), 6)
        self.assertEqual(self.prepared["live_trials_started"], 0)
        self.assertEqual(self.prepared["model_calls"], 0)
        self.assertEqual(self.manifest["comparison_kind"], "end_to_end_skill_package")
        for task_id in pilot.TASK_IDS:
            left, right = self.workspace(task_id, "A"), self.workspace(task_id, "B")
            with self.subTest(task=task_id):
                self.assertEqual(pilot.inventory(left / "repo"), pilot.inventory(right / "repo"))
                for relative in pilot.inventory(left / "repo"):
                    self.assertEqual((left / "repo" / relative).read_bytes(),
                                     (right / "repo" / relative).read_bytes())
                self.assertFalse((left / ".agents").exists())
                installed = right / ".agents/skills/ai-research-reproduction"
                self.assertEqual(pilot.inventory(installed), self.manifest["skill_files"])
                self.assertTrue((installed / "SKILL.md").is_file())
                self.assertTrue((installed / "_bundled/shared/scripts/write_run_bundle.py").is_file())
                self.assertFalse((left / "repo/results").exists())
                self.assertFalse((right / "repo/results").exists())
        self.assertFalse((self.workspace() / "repo/data/samples.csv").exists())
        self.assertTrue(pilot.preflight(self.campaign)["input_ready"])

    def test_prepare_never_replaces_existing_evidence(self) -> None:
        before = (self.campaign / "control/manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "fresh directory"):
            pilot.prepare(self.campaign, sys.executable)
        self.assertEqual((self.campaign / "control/manifest.json").read_bytes(), before)

    def test_frozen_manifest_tampering_is_rejected(self) -> None:
        path = self.campaign / "control/manifest.json"
        with self.changed(path, path.read_bytes() + b" "):
            with self.assertRaisesRegex(ValueError, "frozen protocol changed"):
                pilot.preflight(self.campaign)

    def test_implementation_is_frozen_and_changed_grader_is_rejected(self) -> None:
        expected = pilot.implementation_hashes()
        self.assertEqual(set(expected), {"benchmarks/paired_eval.py", "benchmarks/paired_tasks.py"})
        self.assertEqual(self.manifest["implementation_files"], expected)
        self.assertEqual(self.manifest["implementation_sha256"], pilot.sha(pilot.encoded(expected)))
        altered = {**expected, "benchmarks/paired_tasks.py": "0" * 64}
        # Do not mutate a shared product file while other agents/tests use it.
        with mock.patch.object(pilot, "implementation_hashes", return_value=altered):
            with self.assertRaisesRegex(ValueError, "implementation|changed"):
                pilot.frozen(self.campaign)

    def test_malformed_duplicate_and_nonfinite_control_json_is_rejected(self) -> None:
        path = self.work / "INVALID_CONTROL.json"
        for payload in (b'{"missing":', b'{"same":1,"same":2}',
                        b'{"nested":{"same":1,"same":2}}', b'{"number":NaN}', b'[]'):
            with self.subTest(payload=payload), self.changed(path, payload):
                with self.assertRaises(ValueError):
                    pilot.load(path)

    def test_duplicate_configuration_key_is_not_silently_accepted(self) -> None:
        with self.configuration() as path:
            payload = path.read_bytes().rstrip()
            with self.changed(path, payload[:-1] + b',"model":"shadow-model"}'):
                with self.assertRaises(ValueError):
                    pilot.preflight(self.campaign, path)

    def test_inconsistent_manifest_fields_fail_even_with_refreshed_file_hash(self) -> None:
        manifest_path = self.campaign / "control/manifest.json"
        freeze_path = self.campaign / "control/freeze.json"
        variants = []
        for field in ("environment_sha256", "skill_sha256", "implementation_sha256"):
            value = json.loads(pilot.encoded(self.manifest))
            value[field] = "0" * 64
            variants.append((field, value))
        value = json.loads(pilot.encoded(self.manifest))
        value["planned_live_slots"][1]["arm"] = "A"
        variants.append(("slot identity", value))
        value = json.loads(pilot.encoded(self.manifest))
        value["planned_live_slots"][1]["task"]["goal_en"] += " changed condition"
        variants.append(("paired task identity", value))
        for name, value in variants:
            payload = pilot.encoded(value)
            freeze = pilot.encoded({"protocol_sha256": pilot.sha(payload)})
            # Fixture-only refreezing reaches semantic consistency checks; it
            # does not assert protection against coordinated evidence forgery.
            with self.subTest(field=name), self.changed(manifest_path, payload), self.changed(freeze_path, freeze):
                with self.assertRaises(ValueError):
                    pilot.frozen(self.campaign)

    def test_incomplete_calibration_retains_start_and_no_model_success(self) -> None:
        root = self.campaign / "calibration"
        previous = set(root.glob("*"))
        with mock.patch.object(pilot, "execute_step", side_effect=OSError("unit-test local execution failure")):
            with self.assertRaisesRegex(OSError, "unit-test local execution failure"):
                pilot.calibrate(self.campaign, ["missing_asset"])
        added = set(root.glob("*")) - previous
        self.assertEqual(len(added), 1)
        directory = added.pop()
        start = pilot.load(directory / "START.json")
        self.assertEqual(start["mode"], "offline_calibration")
        self.assertEqual(start["model_calls"], 0)
        self.assertFalse((directory / "REPORT.json").exists())
        self.assertTrue((directory / "missing_asset/repo/README.md").is_file())
        summary = pilot.summarize(self.campaign)
        retained = next(item for item in summary["offline_calibrations"] if item["run_id"] == directory.name)
        self.assertEqual(retained["status"], "incomplete")
        self.assertIsNone(retained["passed"])
        self.assertEqual(summary["live_trials_not_run"], 6)
        self.assertEqual(summary["live_trials_started"], 0)
        self.assertIsNone(summary["paired_effect"])

    def test_changed_prompt_and_source_are_not_ready(self) -> None:
        cases = [(self.workspace() / "TASK.md", "changed task prompt"),
                 (self.workspace() / "repo/README.md", "changed/non-fresh repository"),
                 (self.workspace() / "repo/unexpected-result.json", "changed/non-fresh repository")]
        for path, message in cases:
            with self.subTest(path=path.name), self.changed(path, b"changed input\n"):
                result = pilot.preflight(self.campaign)
                self.assertFalse(result["input_ready"])
                self.assertTrue(any(message in item for item in result["problems"]), result)

    def test_skill_mutation_or_baseline_contamination_is_not_ready(self) -> None:
        path = self.workspace(arm="B") / ".agents/skills/ai-research-reproduction/SKILL.md"
        with self.changed(path, b"changed skill\n"):
            result = pilot.preflight(self.campaign)
            self.assertFalse(result["input_ready"])
            self.assertTrue(any("changed/missing skill" in item for item in result["problems"]), result)
        baseline_skills = self.workspace() / ".agents"
        baseline_skills.mkdir()
        try:
            result = pilot.preflight(self.campaign)
            self.assertFalse(result["input_ready"])
            self.assertTrue(any("skill contamination" in item for item in result["problems"]), result)
        finally:
            baseline_skills.rmdir()

    def test_missing_model_budget_never_reads_credentials_or_claims_readiness(self) -> None:
        secret = "test-only-sentinel-do-not-persist"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": secret, "OPENAI_API_KEY": secret}), \
             mock.patch.object(os, "getenv", side_effect=AssertionError("credential lookup is unnecessary")):
            result = pilot.preflight(self.campaign)
        self.assertTrue(result["input_ready"], result)
        self.assertFalse(result["configuration_ready"])
        self.assertFalse(result["live_execution_ready"])
        self.assertEqual(result["model_calls"], 0)
        self.assertIsNone(result["budget_compliant"])
        self.assertNotIn(secret, json.dumps(result))

    def test_invalid_budget_types_values_and_unknown_fields_are_rejected(self) -> None:
        changes = ({"max_total_tokens": True}, {"max_tokens_per_trial": "1000"},
                   {"max_seconds_per_trial": 1.5}, {"max_seconds_per_trial": 0},
                   {"max_total_tokens": 5999}, {"api_key": "test-only-not-a-real-key"},
                   {"revision": " "})
        for change in changes:
            with self.subTest(change=change), self.configuration(**change) as path:
                result = pilot.preflight(self.campaign, path)
                self.assertFalse(result["configuration_ready"], result)
                self.assertFalse(result["live_execution_ready"])
                self.assertIsNone(result["budget_compliant"])

    def test_valid_configuration_is_not_an_enforced_live_budget(self) -> None:
        with self.configuration() as path:
            result = pilot.preflight(self.campaign, path)
        self.assertTrue(result["input_ready"], result)
        self.assertTrue(result["configuration_ready"], result)
        self.assertFalse(result["live_execution_ready"])
        self.assertEqual(result["budget_enforcement"], "not_enforced")
        self.assertIsNone(result["budget_compliant"])
        self.assertEqual(result["model_calls"], 0)

    def test_changed_environment_and_missing_dependencies_are_not_ready(self) -> None:
        altered = {**ENVIRONMENT_FIXTURE, "packages": {"torch": None, "pytest": None}}
        with mock.patch.object(pilot, "python_environment", return_value=altered):
            result = pilot.preflight(self.campaign)
        self.assertFalse(result["input_ready"])
        self.assertIn("selected Python environment changed", result["problems"])
        self.assertTrue(any("requires existing torch and pytest" in item for item in result["problems"]))

    def test_real_fixture_calibration_is_append_only_and_not_model_evidence(self) -> None:
        live_before = pilot.inventory(self.campaign / "workspaces")
        reports = []
        for _ in range(2):
            result = pilot.calibrate(self.campaign, ["missing_asset", "wrong_metric"])
            self.assertEqual(result["passed"], 2, result)
            self.assertEqual(result["calibrated_tasks"], 2)
            self.assertEqual(result["model_calls"], 0)
            report_path = Path(result["path"])
            report = pilot.load(report_path)
            self.assertEqual(report["mode"], "offline_calibration")
            self.assertEqual(report["live_trial_count"], 0)
            self.assertIn("scripted", report["claim_origin"])
            self.assertEqual({row["task_id"] for row in report["rows"]}, {"missing_asset", "wrong_metric"})
            receipts = list(report_path.parent.glob("*/steps/*/receipt.json"))
            self.assertEqual(len(receipts), 3)
            for receipt_path in receipts:
                receipt = pilot.load(receipt_path)
                self.assertEqual(receipt["returncode"], 0, receipt)
                self.assertIn(receipt["step_id"], {"prepare-data", "evaluate"})
                self.assertNotIn("pip", receipt["argv"])
                self.assertTrue((receipt_path.parent / "stdout.log").is_file())
            reports.append((report_path, pilot.inventory(report_path.parent)))
        self.assertNotEqual(reports[0][0], reports[1][0])
        self.assertEqual(pilot.inventory(reports[0][0].parent), reports[0][1])
        self.assertEqual(pilot.inventory(self.campaign / "workspaces"), live_before)
        summary = pilot.summarize(self.campaign)
        self.assertEqual(summary["planned_live_trials"], 6)
        self.assertEqual(summary["live_trials_started"], 0)
        self.assertEqual(summary["live_trials_not_run"], 6)
        self.assertEqual(len(summary["slots"]), 6)
        self.assertTrue(all(slot["status"] == "not_run" for slot in summary["slots"]))
        for field in ("live_completion_rate", "paired_effect", "tokens_used", "cost", "budget_compliant"):
            self.assertIsNone(summary[field], field)
        completed = [item for item in summary["offline_calibrations"] if item["status"] == "completed"]
        self.assertEqual(len(completed), 2)

    def test_cli_help_and_failures(self) -> None:
        help_result = self.cli("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("preflight", help_result.stdout)
        for arguments in (("prepare", "--output", str(self.campaign)),
                          ("preflight", "--campaign", str(self.campaign)),
                          ("calibrate", "--campaign", str(self.campaign), "--tasks", "wrong_metric", "wrong_metric")):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(json.loads(result.stdout)["model_calls"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
