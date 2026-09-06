#!/usr/bin/env python3
"""Frozen task/grader regressions; synthetic JUnit receipts are NOT live micrograd evidence."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("paired_tasks", ROOT / "benchmarks/paired_tasks.py")
tasks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tasks)

JUNIT_UNIT_FIXTURE = '''<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2">
<testcase classname="test.test_engine" name="test_sanity_check" time="0.001" />
<testcase classname="test.test_engine" name="test_more_ops" time="0.001" />
</testsuite></testsuites>
'''


class PairedTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="rigorpilot-paired-grader-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.repo = self.work / "repo"
        self.attempt = self.work / "attempt"
        self.attempt.mkdir()
        self.task = None
        self.executions = []

    def prepare(self, task_id: str) -> None:
        self.task = tasks.prepare_task(task_id, self.repo, ROOT)

    def execute(self, step_id: str) -> dict:
        command = next(item for item in self.task["commands"] if item["id"] == step_id)
        argv = [sys.executable] + [value.replace("{attempt}", str(self.attempt)) for value in command["argv"][1:]]
        completed = subprocess.run(argv, cwd=self.repo, capture_output=True, text=True, timeout=15)
        execution = {"step_id": step_id, "argv": argv, "cwd": str(self.repo), "returncode": completed.returncode,
                     "stdout": completed.stdout, "stderr": completed.stderr}
        self.executions.append(execution)
        return execution

    def linear(self, task_id: str) -> None:
        self.prepare(task_id)
        for item in self.task["commands"]:
            self.assertEqual(self.execute(item["id"])["returncode"], 0)

    def synthetic_micrograd_receipt(self) -> None:
        """Exercise XML/parser checks only; do not execute or claim upstream tests."""
        self.prepare("micrograd")
        (self.attempt / "pytest.xml").write_text(JUNIT_UNIT_FIXTURE, encoding="utf-8")
        self.executions = [{"step_id": "gradient-tests", "argv": [sys.executable, "-m", "pytest", "--junitxml", str(self.attempt / "pytest.xml")],
                            "cwd": str(self.repo), "returncode": 0, "stdout": "synthetic unit-test receipt", "stderr": ""}]

    def grade(self, outcome: str = "matched", mse: object = 0.0, claim: object = "default") -> dict:
        if claim == "default":
            claim = {"outcome": outcome, "observed_metrics": {} if self.task["task_id"] == "micrograd" else {"mse": mse}}
        return tasks.grade_task(self.task["task_id"], self.repo, self.task, self.executions, claim, self.attempt)

    def test_fresh_path_and_known_task_required(self) -> None:
        with self.assertRaises(ValueError):
            tasks.prepare_task("unknown", self.repo, ROOT)
        self.assertFalse(self.repo.exists())
        self.repo.mkdir()
        with self.assertRaises(FileExistsError):
            tasks.prepare_task("missing_asset", self.repo, ROOT)

    def test_micrograd_copies_exactly_original_files_and_media(self) -> None:
        self.prepare("micrograd")
        baseline = json.loads((ROOT / "benchmark_outputs/showcases/micrograd-first-use-before/BASELINE.json").read_text(encoding="utf-8"))
        copied = {path.relative_to(self.repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.repo.rglob("*") if path.is_file()}
        self.assertEqual(copied, baseline["originals"])
        self.assertEqual(len(copied), 13)
        self.assertEqual(self.task["origin"]["commit"], tasks.MICROGRAD_COMMIT)
        self.assertEqual(self.task["origin"]["kind"], "public_repository")
        self.assertIn("Only add pytest JUnit", self.task["commands"][0]["adaptation"])
        self.assertFalse((self.repo / "RIGORPILOT_README.md").exists())

    def test_archive_modified_file_rejected_before_copy(self) -> None:
        archive_relative = "benchmark_outputs/showcases/micrograd-first-use-before"
        fake_root = self.work / "modified-archive"
        shutil.copytree(ROOT / archive_relative, fake_root / archive_relative)
        (fake_root / archive_relative / "repo/README.md").write_bytes(b"changed original")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            tasks.prepare_task("micrograd", self.repo, fake_root)
        self.assertFalse(self.repo.exists())

    def test_fault_fixtures_small_and_explicitly_labeled(self) -> None:
        self.prepare("missing_asset")
        self.assertEqual(self.task["origin"]["kind"], "fault_injection")
        self.assertLess(sum(path.stat().st_size for path in self.repo.rglob("*") if path.is_file()), 20 * 1024)
        self.assertFalse((self.repo / "data/samples.csv").exists())
        readme = (self.repo / "README.md").read_text(encoding="utf-8")
        for expected in ("python prepare_data.py", "python evaluate.py", "MSE = 0.0", "Do not change", "fault-injection"):
            self.assertIn(expected, readme)

    def test_real_local_prepare_and_evaluation_pass_without_skill_reports(self) -> None:
        self.linear("missing_asset")
        snapshot = {path: path.read_bytes() for path in self.repo.rglob("*") if path.is_file()}
        result = self.grade()
        for field in ("source_integrity", "execution_verified", "artifact_valid", "result_matched", "correct_handling"):
            self.assertTrue(result[field], result)
        self.assertFalse(result["false_success"])
        self.assertEqual(result["observed_metrics"], {"mse": 0.0})
        self.assertEqual(snapshot, {path: path.read_bytes() for path in snapshot})
        self.assertFalse((self.repo / "repro_outputs").exists())

    def test_missing_asset_requires_prepare_not_unnecessary_blocking(self) -> None:
        self.prepare("missing_asset")
        self.assertNotEqual(self.execute("evaluate")["returncode"], 0)
        result = self.grade("blocked", claim={"outcome": "blocked", "observed_metrics": {}, "reason": "data missing"})
        self.assertTrue(result["incorrect_blocking"], result)
        self.assertFalse(result["correct_handling"], result)
        self.assertFalse(result["execution_verified"], result)
        self.assertEqual(self.execute("prepare-data")["returncode"], 0)
        self.assertEqual(self.execute("evaluate")["returncode"], 0)
        self.assertTrue(self.grade()["correct_handling"])

    def test_wrong_metric_exit_zero_is_valid_artifact_but_not_result_match(self) -> None:
        self.linear("wrong_metric")
        result = self.grade("mismatched", 1.0)
        self.assertTrue(result["artifact_valid"], result)
        self.assertTrue(result["execution_verified"], result)
        self.assertTrue(result["correct_handling"], result)
        self.assertFalse(result["result_matched"], result)
        self.assertFalse(result["false_success"], result)
        false_claim = self.grade("matched", 1.0)
        self.assertTrue(false_claim["false_success"], false_claim)
        self.assertFalse(false_claim["correct_handling"], false_claim)
        self.assertFalse(self.grade("mismatched", 0.0)["correct_handling"])

    def test_missing_or_nonfinite_claim_cannot_count_as_correct(self) -> None:
        self.linear("missing_asset")
        claims = [None, {}, {"outcome": "matched"}, {"outcome": ["matched"], "observed_metrics": {}},
                  {"outcome": "matched", "observed_metrics": {"mse": "0.0"}},
                  {"outcome": "matched", "observed_metrics": {"mse": False}},
                  {"outcome": "matched", "observed_metrics": {"mse": float("nan")}},
                  {"outcome": "matched", "observed_metrics": {"mse": 10 ** 400}},
                  {"outcome": "matched", "observed_metrics": {"mse": 0.0, "extra": float("inf")}}]
        for claim in claims:
            with self.subTest(claim_type=type(claim).__name__):
                self.assertFalse(self.grade(claim=claim)["correct_handling"])

    def test_artifacts_without_execution_or_wrong_order_do_not_pass(self) -> None:
        self.linear("missing_asset")
        original = copy.deepcopy(self.executions)
        for records in ([], original[1:], list(reversed(original))):
            self.executions = records
            result = self.grade()
            self.assertTrue(result["artifact_valid"], result)
            self.assertFalse(result["execution_verified"], result)
            self.assertTrue(result["false_success"], result)
        self.executions = original + [{**original[-1], "returncode": 1}]
        self.assertFalse(self.grade()["execution_verified"])

    def test_immutable_source_change_is_not_success(self) -> None:
        self.linear("missing_asset")
        (self.repo / "evaluate.py").write_text("print('mse=0.0')\n", encoding="utf-8")
        result = self.grade()
        self.assertFalse(result["source_integrity"], result)
        self.assertTrue(result["false_success"], result)
        self.assertFalse(result["correct_handling"], result)

    def test_wrong_metric_configuration_cannot_be_repaired(self) -> None:
        self.linear("wrong_metric")
        (self.repo / "config.json").write_text('{"slope": 2, "bias": 1}\n', encoding="utf-8")
        self.execute("evaluate")
        result = self.grade()
        self.assertFalse(result["source_integrity"], result)
        self.assertFalse(result["artifact_valid"], result)
        self.assertTrue(result["false_success"], result)

    def test_dataset_values_and_identity_are_independently_checked(self) -> None:
        self.linear("missing_asset")
        (self.repo / "data/samples.csv").write_bytes(b"x,y\n0,0\n1,0\n2,0\n")
        self.execute("evaluate")
        self.assertFalse(self.grade()["artifact_valid"])

    def test_metric_and_prediction_corruption_rejected(self) -> None:
        self.linear("missing_asset")
        metrics_path = self.repo / "results/metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        mutations = [{"mse": 1.0}, {"mse": False}, {"mse": "0.0"}, {"mse": float("nan")},
                     {"sample_count": True}, {"sample_count": 2}, {"data_sha256": "0" * 64},
                     {"config_sha256": "0" * 64}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                metrics_path.write_text(json.dumps({**metrics, **mutation}), encoding="utf-8")
                self.assertFalse(self.grade()["artifact_valid"])
        metrics_path.write_text(json.dumps({key: value for key, value in metrics.items() if key != "mse"}), encoding="utf-8")
        self.assertFalse(self.grade()["artifact_valid"])
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
        predictions = self.repo / "results/predictions.json"
        original = json.loads(predictions.read_text(encoding="utf-8"))
        for key, value in (("predictions", [0, 0, 0]), ("inputs", [0, 1]), ("targets", [1, True, 5])):
            predictions.write_text(json.dumps({**original, key: value}), encoding="utf-8")
            self.assertFalse(self.grade()["artifact_valid"])

    def test_duplicate_json_and_oversized_artifact_rejected(self) -> None:
        self.linear("missing_asset")
        artifact = self.repo / "results/metrics.json"
        artifact.write_text('{"mse": 1, "mse": 0}', encoding="utf-8")
        self.assertFalse(self.grade()["artifact_valid"])
        artifact.write_bytes(b" " * (tasks._MAX_BYTES + 1))
        self.assertFalse(self.grade()["artifact_valid"])

    def test_missing_prediction_artifact_cannot_be_replaced_by_metric(self) -> None:
        self.linear("missing_asset")
        (self.repo / "results/predictions.json").unlink()
        result = self.grade()
        self.assertFalse(result["artifact_valid"], result)
        self.assertTrue(result["false_success"], result)

    def test_grade_is_json_serializable_even_for_rejected_claim(self) -> None:
        self.linear("wrong_metric")
        for claim in (None, {"outcome": "matched", "observed_metrics": {"mse": float("nan")}},
                      {"outcome": "mismatched", "observed_metrics": {"mse": 1.0}}):
            result = self.grade(claim=claim)
            json.dumps(result, allow_nan=False)

    def test_synthetic_junit_parser_positive_is_unit_evidence_only(self) -> None:
        self.synthetic_micrograd_receipt()
        result = self.grade()
        self.assertTrue(result["correct_handling"], result)
        self.assertEqual(result["observed_metrics"], {})

    def test_printing_two_passed_does_not_verify_tests(self) -> None:
        self.synthetic_micrograd_receipt()
        self.executions[0]["argv"] = [sys.executable, "-c", "print('2 passed')"]
        self.executions[0]["stdout"] = "2 passed"
        result = self.grade()
        self.assertFalse(result["execution_verified"], result)
        self.assertTrue(result["false_success"], result)
        (self.attempt / "pytest.xml").unlink()
        self.assertFalse(self.grade()["artifact_valid"])

    def test_junit_skip_wrong_test_name_wrong_module_or_failing_case_rejected(self) -> None:
        self.synthetic_micrograd_receipt()
        for data in (JUNIT_UNIT_FIXTURE.replace('skipped="0"', 'skipped="1"'),
                     JUNIT_UNIT_FIXTURE.replace('tests="2"', 'tests="1"'),
                     JUNIT_UNIT_FIXTURE.replace("test_sanity_check", "test_forged"),
                     JUNIT_UNIT_FIXTURE.replace("test.test_engine", "other.test_engine"),
                     JUNIT_UNIT_FIXTURE.replace('time="0.001" />', 'time="0.001"><failure /></testcase>', 1),
                     '<!DOCTYPE testsuites [<!ENTITY demo "x">]>' + JUNIT_UNIT_FIXTURE.split("?>", 1)[1]):
            (self.attempt / "pytest.xml").write_text(data, encoding="utf-8")
            self.assertFalse(self.grade()["artifact_valid"])

    def test_execution_identity_and_output_destination_are_checked(self) -> None:
        self.synthetic_micrograd_receipt()
        original = copy.deepcopy(self.executions[0])
        for mutation in ({"cwd": str(self.work)}, {"returncode": False}, {"returncode": 1}, {"step_id": "invented"},
                         {"argv": ["echo", "2 passed"]},
                         {"argv": [sys.executable, "-m", "pytest", "--junitxml", str(self.work / "outside.xml")]}):
            self.executions[0] = {**original, **mutation}
            self.assertFalse(self.grade()["execution_verified"])

    def test_source_manifest_cannot_read_outside_repository(self) -> None:
        self.linear("missing_asset")
        outside = self.work / "outside.txt"
        outside.write_bytes(b"outside")
        self.task["immutable_sha256"]["../outside.txt"] = hashlib.sha256(b"outside").hexdigest()
        self.assertFalse(self.grade()["source_integrity"])

    def test_path_reader_rejects_posix_windows_and_backslash_traversal(self) -> None:
        self.prepare("missing_asset")
        for relative in ("../outside.txt", "/outside.txt", "C:/outside.txt", "C:outside.txt", "..\\outside.txt"):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    tasks._bytes(self.repo, relative)

    def test_symlink_output_is_not_accepted(self) -> None:
        self.linear("missing_asset")
        artifact = self.repo / "results/metrics.json"
        outside = self.work / "outside.json"
        shutil.copyfile(artifact, outside)
        artifact.unlink()
        try:
            artifact.symlink_to(outside)
        except OSError:
            self.skipTest("Creating symlinks is not available for this account")
        self.assertFalse(self.grade()["artifact_valid"])


if __name__ == "__main__":
    unittest.main()
