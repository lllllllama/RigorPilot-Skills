#!/usr/bin/env python3
"""Restricted tool tests. Real standard-library subprocesses; no model/network calls."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import trial_broker as broker_module
from paired_tasks import prepare_task
from trial_broker import BrokerError, TrialBroker


class TrialBrokerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rigorpilot-trial-broker-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.repo, self.evidence = self.work / "repo", self.work / "evidence"

    def create(self, task_id="missing_asset", skill=False):
        self.task = prepare_task(task_id, self.repo, ROOT)
        skill_root = None
        if skill:
            skill_root = self.work / "skill"
            skill_root.mkdir()
            (skill_root / "SKILL.md").write_text("# Read-only unit fixture\n", encoding="utf-8")
        self.broker = TrialBroker(self.repo, self.evidence, self.task, sys.executable, skill_root)
        return self.broker

    def run_command(self, command_id):
        return self.broker.dispatch("run_command", {"command_id": command_id})

    def finish(self, outcome="matched", mse=0):
        return self.broker.dispatch("finish", {"claim": {
            "outcome": outcome, "observed_metrics": {"mse": mse}, "reason": "Unit-test scripted claim, not a model response."}})

    def test_real_missing_asset_prepare_evaluate_and_read_generated_metrics(self):
        self.create()
        with self.assertRaises(BrokerError):
            self.broker.dispatch("read_file", {"scope": "repo", "path": "data/samples.csv"})
        self.assertEqual(self.run_command("prepare-data")["returncode"], 0)
        self.assertEqual(self.run_command("evaluate")["returncode"], 0)
        content = self.broker.dispatch("read_file", {"scope": "repo", "path": "results/metrics.json"})
        self.assertEqual(json.loads(content["content"])["mse"], 0)
        result = self.finish()
        self.assertTrue(result["grade"]["correct_handling"])
        self.assertTrue(self.broker.finished)
        self.assertTrue((self.evidence / "GRADE.json").is_file())

    def test_real_wrong_metric_is_honest_mismatch(self):
        self.create("wrong_metric")
        self.assertEqual(self.run_command("evaluate")["returncode"], 0)
        grade = self.finish("mismatched", 1)["grade"]
        self.assertTrue(grade["correct_handling"])
        self.assertFalse(grade["result_matched"])
        self.assertTrue(grade["artifact_valid"])

    def test_exit_zero_does_not_support_false_success(self):
        self.create("wrong_metric")
        self.run_command("evaluate")
        grade = self.finish("matched", 1)["grade"]
        self.assertTrue(grade["false_success"])
        self.assertFalse(grade["correct_handling"])

    def test_failed_attempts_preserved_and_latest_ordered_receipts_grade(self):
        self.create()
        self.assertNotEqual(self.run_command("evaluate")["returncode"], 0)
        self.assertNotEqual(self.run_command("evaluate")["returncode"], 0)
        self.run_command("prepare-data")
        self.run_command("evaluate")
        self.assertEqual(len(self.broker.executions), 4)
        self.assertEqual(len(list((self.evidence / "commands").glob("*/steps/*/receipt.json"))), 4)
        self.assertTrue(self.finish()["grade"]["correct_handling"])
        first = json.loads((self.evidence / "commands/0001/steps/evaluate/receipt.json").read_text())
        self.assertNotEqual(first["returncode"], 0)

    def test_prepare_after_evaluate_is_not_valid_final_order(self):
        self.create()
        for command in ("prepare-data", "evaluate", "prepare-data"):
            self.run_command(command)
        self.assertFalse(self.finish()["grade"]["execution_verified"])

    def test_collection_failure_keeps_attempt_and_retry_uses_fresh_directory(self):
        self.create()
        with mock.patch.object(broker_module, "execute_step", side_effect=OSError("unit-test launch failure")), \
                self.assertRaises(BrokerError):
            self.run_command("prepare-data")
        self.assertTrue((self.evidence / "commands/0001/ERROR.json").is_file())
        self.assertEqual(self.broker.executions, [])
        self.assertEqual(self.run_command("prepare-data")["returncode"], 0)
        self.assertTrue((self.evidence / "commands/0002/steps/prepare-data/receipt.json").is_file())

    def test_controller_timeout_is_forwarded_and_recorded(self):
        self.create()
        self.assertEqual(self.broker.timeout_seconds, 45)
        self.broker.timeout_seconds = 10.5
        with mock.patch.object(broker_module, "execute_step", wraps=broker_module.execute_step) as execute:
            self.assertEqual(self.run_command("prepare-data")["returncode"], 0)
        self.assertEqual(execute.call_args.kwargs, {"timeout_seconds": 10.5})
        self.assertEqual(self.broker.executions[0]["timeout_seconds"], 10.5)

    def test_invalid_operator_timeout_rejected_before_process_or_attempt(self):
        self.create()
        for timeout in (0, -1, 46, True, float("nan"), float("inf"), "5", 10 ** 400):
            self.broker.timeout_seconds = timeout
            with self.subTest(timeout=timeout), mock.patch.object(broker_module, "execute_step") as execute, \
                    self.assertRaises(BrokerError) as failure:
                self.run_command("prepare-data")
            self.assertEqual(failure.exception.code, "invalid_timeout")
            execute.assert_not_called()
        self.assertEqual(list((self.evidence / "commands").iterdir()), [])
        with self.assertRaises(BrokerError):
            self.broker.dispatch("run_command", {"command_id": "prepare-data", "timeout_seconds": 5})

    def test_finish_without_execution_and_after_bad_tool_is_not_a_pass(self):
        self.create()
        with self.assertRaises(BrokerError):
            self.run_command("shell")
        grade = self.finish("blocked")["grade"]
        self.assertFalse(grade["correct_handling"])
        self.assertTrue(grade["incorrect_blocking"])
        self.assertEqual(self.broker.executions, [])

    def test_unknown_tool_extra_fields_and_fake_receipts_never_execute(self):
        self.create()
        requests = [("execute", {"argv": ["python", "--version"]}),
                    ("run_command", {"command_id": "evaluate", "argv": ["python", "--version"]}),
                    ("run_command", {"command_id": "evaluate", "cwd": str(self.work)}),
                    ("run_command", {"command_id": "evaluate", "env": {}}),
                    ("run_command", {"command_id": ["evaluate"]}),
                    ("finish", {"claim": {}, "executions": [{"returncode": 0}]}),
                    ("read_file", {"scope": "repo", "path": "README.md", "extra": True})]
        with mock.patch.object(broker_module, "execute_step") as execute:
            for name, args in requests:
                with self.subTest(name=name, args=args), self.assertRaises(BrokerError):
                    self.broker.dispatch(name, args)
            execute.assert_not_called()
        self.assertFalse(self.broker.finished)

    def test_traversal_absolute_windows_ads_and_control_files_denied(self):
        self.create()
        for path in ("../evidence/GRADE.json", "/tmp/readme", "C:/secret", "C:secret", "README.md:secret",
                     "sub/../README.md", "sub\\README.md", "README.md/", "./README.md", "pytest.xml", "control/manifest.json"):
            with self.subTest(path=path), self.assertRaises(BrokerError):
                self.broker.dispatch("read_file", {"scope": "repo", "path": path})
        with self.assertRaises(BrokerError):
            self.broker.dispatch("list_files", {"scope": "evidence"})

    def test_A_cannot_read_skill_and_B_has_only_read_namespace(self):
        self.create(skill=True)
        self.assertEqual(self.broker.dispatch("list_files", {"scope": "skill"})["files"], ["SKILL.md"])
        self.assertIn("Read-only", self.broker.dispatch("read_file", {"scope": "skill", "path": "SKILL.md"})["content"])
        with self.assertRaises(BrokerError):
            self.run_command("skill-helper")
        another = self.work / "other-repo"
        task = prepare_task("wrong_metric", another, ROOT)
        baseline = TrialBroker(another, self.work / "other-evidence", task, sys.executable)
        with self.assertRaises(BrokerError):
            baseline.dispatch("list_files", {"scope": "skill"})

    def test_changed_skill_blocks_execution(self):
        self.create(skill=True)
        (self.work / "skill/SKILL.md").write_text("changed", encoding="utf-8")
        with mock.patch.object(broker_module, "execute_step") as execute, self.assertRaises(BrokerError):
            self.run_command("evaluate")
        execute.assert_not_called()

    def test_initial_tree_rejects_added_conftest_or_empty_directory(self):
        self.task = prepare_task("missing_asset", self.repo, ROOT)
        for relative, is_directory in (("conftest.py", False), (".hidden", True)):
            target = self.repo / relative
            target.mkdir() if is_directory else target.write_text("# injection", encoding="utf-8")
            with self.assertRaises(BrokerError):
                TrialBroker(self.repo, self.evidence, self.task, sys.executable)
            target.rmdir() if is_directory else target.unlink()

    def test_readme_mutation_rejected_before_execute(self):
        self.create()
        (self.repo / "README.md").write_text("mutated", encoding="utf-8")
        with mock.patch.object(broker_module, "execute_step") as execute, self.assertRaises(BrokerError):
            self.run_command("evaluate")
        execute.assert_not_called()

    def test_added_pytest_config_shadow_file_or_directory_rejected(self):
        self.create()
        for relative, is_directory in (("conftest.py", False), ("pytest.ini", False), ("json.py", False), ("injected", True)):
            target = self.repo / relative
            target.mkdir() if is_directory else target.write_text("# injection", encoding="utf-8")
            with mock.patch.object(broker_module, "execute_step") as execute, self.assertRaises(BrokerError):
                self.run_command("evaluate")
            execute.assert_not_called()
            target.rmdir() if is_directory else target.unlink()

    def test_external_generated_artifact_changes_are_not_trusted(self):
        self.create()
        self.run_command("prepare-data")
        (self.repo / "data/samples.csv").write_text("x,y\n0,7\n", encoding="utf-8")
        with self.assertRaises(BrokerError):
            self.run_command("evaluate")
        with self.assertRaises(BrokerError):
            self.finish()

    def test_interpreter_resolution_change_blocks_process(self):
        self.create()
        with mock.patch.object(broker_module.shutil, "which", return_value=None), \
                mock.patch.object(broker_module, "execute_step") as execute, self.assertRaises(BrokerError):
            self.run_command("evaluate")
        execute.assert_not_called()

    def test_sources_list_preserves_micrograd_media_and_read_limits(self):
        self.create("micrograd")
        files = self.broker.dispatch("list_files", {"scope": "repo"})["files"]
        self.assertEqual(set(files), set(self.task["immutable_sha256"]))
        self.assertEqual(len(files), 13)
        images = [name for name in files if Path(name).suffix == ".png"]
        self.assertTrue(images)
        with self.assertRaises(BrokerError) as failure:
            self.broker.dispatch("read_file", {"scope": "repo", "path": images[0]})
        self.assertIn(failure.exception.code, ("binary_file", "file_too_large"))

    def test_skill_large_file_is_listed_but_read_is_bounded(self):
        task = prepare_task("wrong_metric", self.repo, ROOT)
        skill = self.work / "skill"
        skill.mkdir()
        (skill / "large.md").write_bytes(b"x" * (broker_module.MAX_READ_BYTES + 1))
        instance = TrialBroker(self.repo, self.evidence, task, sys.executable, skill)
        self.assertEqual(instance.dispatch("list_files", {"scope": "skill"})["files"], ["large.md"])
        with self.assertRaises(BrokerError) as failure:
            instance.dispatch("read_file", {"scope": "skill", "path": "large.md"})
        self.assertEqual(failure.exception.code, "file_too_large")

    def test_symlink_scope_or_file_rejected(self):
        self.create()
        linked = self.repo / "linked.txt"
        try:
            linked.symlink_to(self.repo / "README.md")
        except (OSError, NotImplementedError):
            self.skipTest("Account cannot create symlinks; supported on Linux/macOS")
        with self.assertRaises(BrokerError):
            self.broker.dispatch("list_files", {"scope": "repo"})

    def test_python311_reparse_point_fallback_rejects_junctions(self):
        path = mock.Mock()
        path.is_symlink.return_value = False
        path.is_junction.return_value = False
        path.lstat.return_value = SimpleNamespace(st_file_attributes=0x400)
        self.assertTrue(broker_module._linked(path))
        path.lstat.return_value = SimpleNamespace(st_file_attributes=0)
        self.assertFalse(broker_module._linked(path))

    def test_operator_parent_alias_resolves_but_linked_selected_root_rejected(self):
        physical = self.work / "physical"
        physical.mkdir()
        alias = self.work / "alias"
        try:
            alias.symlink_to(physical, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Account cannot create parent alias; supported on Linux/macOS")
        task = prepare_task("wrong_metric", physical / "repo", ROOT)
        instance = TrialBroker(alias / "repo", alias / "evidence", task, sys.executable)
        self.assertEqual(instance.repo, physical / "repo")
        self.assertEqual(instance.evidence, physical / "evidence")
        self.assertEqual(instance.dispatch("run_command", {"command_id": "evaluate"})["returncode"], 0)
        linked_root = self.work / "linked-repo"
        linked_root.symlink_to(physical / "repo", target_is_directory=True)
        with self.assertRaises(BrokerError) as failure:
            TrialBroker(linked_root, self.work / "new-evidence", task, sys.executable)
        self.assertEqual(failure.exception.code, "unsafe_path")

    def test_overlapping_scopes_and_existing_command_evidence_rejected(self):
        self.task = prepare_task("missing_asset", self.repo, ROOT)
        with self.assertRaises(BrokerError):
            TrialBroker(self.repo, self.repo / "evidence", self.task, sys.executable)
        TrialBroker(self.repo, self.evidence, self.task, sys.executable)
        with self.assertRaises(BrokerError):
            TrialBroker(self.repo, self.evidence, self.task, sys.executable)

    def test_task_copy_and_receipt_copies_cannot_mutate_collected_evidence(self):
        self.create()
        self.task["commands"][0]["argv"] = ["python", "--version"]
        self.run_command("prepare-data")
        records = self.broker.executions
        records[0]["returncode"] = 99
        self.assertEqual(self.broker.executions[0]["returncode"], 0)
        self.run_command("evaluate")
        self.assertTrue(self.finish()["grade"]["correct_handling"])

    def test_invalid_claim_never_finishes_and_final_is_terminal(self):
        self.create()
        for value in (True, float("nan"), float("inf"), "0"):
            with self.subTest(value=value), self.assertRaises(BrokerError):
                self.finish(mse=value)
            self.assertFalse(self.broker.finished)
        self.run_command("prepare-data")
        self.run_command("evaluate")
        self.finish()
        with self.assertRaises(BrokerError):
            self.run_command("evaluate")


if __name__ == "__main__":
    unittest.main()
