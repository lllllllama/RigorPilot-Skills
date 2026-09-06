#!/usr/bin/env python3
"""Positive and fault-injection tests for the read-only first-use grader."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "check_first_use.py"
SPEC = importlib.util.spec_from_file_location("check_first_use", SCRIPT)
grader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grader)


class FirstUseVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rigorpilot-first-use-grader-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.repo = self.work / "repo"
        self.output = self.work / "evidence"
        self.repo.mkdir()
        self.output.mkdir()
        self.source = self.repo / "README.md"
        self.source.write_bytes(b'# Demo\n![image](image.png)\n## Test\n```bash\npython -m pytest\n```\n')
        (self.repo / "image.png").write_bytes(b"binary\x00\xff")
        self.baseline = self.work / "BASELINE.json"
        self.write_json(self.baseline, {"originals": {path.name: grader.digest(path) for path in self.repo.iterdir()}})
        self.run_dir = self.output / "_runtime" / "test-1"
        self.run_dir.mkdir(parents=True)
        state = {"run_id": "test-1", "status": "success", "returncode": 0, "finished_at": "2026-09-06T00:00:00Z", "cancelled": False, "timed_out": False}
        self.write_json(self.run_dir / "state.json", state)
        self.write_json(self.run_dir / "spec.json", {"run_id": "test-1", "command": "python -m pytest", "cwd": str(self.repo)})
        (self.run_dir / "events.jsonl").write_text(json.dumps({"type": "completed", "data": {"status": "success", "returncode": 0}}) + "\n", encoding="utf-8")
        (self.run_dir / "stdout.log").write_text("2 passed\n" + "long output\n" * 5000, encoding="utf-8")
        (self.run_dir / "stderr.log").write_text("", encoding="utf-8")
        (self.output / "SUMMARY.md").write_text("not a task acceptance oracle\n", encoding="utf-8")
        self.status = {
            "status": "success", "documented_command_status": "success", "documented_command": "python -m pytest",
            "target_repo": str(self.repo), "result_match": {"status": "not_evaluated"},
            "runtime": {"run_id": "test-1", "status": "success", **{key: str(self.run_dir / name) for key, name in (
                ("state_path", "state.json"), ("events_path", "events.jsonl"), ("stdout_log_path", "stdout.log"), ("stderr_log_path", "stderr.log"))}},
        }
        self.regenerate()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def regenerate(self) -> None:
        source = self.source.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        sections = grader.heading_blocks(source)
        def annotation(kind: str, title: str, occurrence: str, prefix: str) -> bytes:
            body = f'<!-- rigorpilot:repro:begin kind="{kind}" section="{title}" occurrence="{occurrence}" status="success" -->\n[report]({prefix}SUMMARY.md)\n<!-- rigorpilot:repro:end -->\n'
            return body.encode()
        for destination, prefix in ((self.output / "ANNOTATED_README.md", ""), (self.repo / "RIGORPILOT_README.md", "../evidence/")):
            bom = 3 if source.startswith(b"\xef\xbb\xbf") else 0
            result = source[:bom] + annotation("banner", "__banner__", "1", prefix)
            cursor = bom
            for section in sections:
                result += source[cursor:section["offset"]] + annotation("section", section["section"], section["occurrence"], prefix)
                cursor = section["offset"]
            result += source[cursor:]
            destination.write_bytes(result)
        receipt = {"path": str(self.repo / "RIGORPILOT_README.md"), "source_readme": str(self.source), "sha256": grader.digest(self.repo / "RIGORPILOT_README.md")}
        self.write_json(self.output / "readme_delivery.json", receipt)
        self.status["source_adjacent_readme"] = {"status": "written", **receipt}
        self.status["readme_section_coverage"] = {"source_readme": str(self.source), "original_sha256": digest, "stripped_sha256": digest, "annotation_count": len(sections), "total_sections": len(sections)}
        self.write_json(self.output / "status.json", self.status)

    def result(self, expected: str | None = "2 passed") -> dict:
        return grader.grade(self.baseline, self.repo, self.output, expected)

    def assert_failed(self, check: str) -> None:
        result = self.result()
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["checks"][check]["ok"], result)

    def test_complete_full_stdout_and_no_paper_metric(self) -> None:
        before = {path: grader.digest(path) for path in self.work.rglob("*") if path.is_file()}
        result = self.result()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["task_log_condition"], "passed")
        self.assertEqual(before, {path: grader.digest(path) for path in before})

    def test_no_explicit_task_condition_makes_no_completion_claim(self) -> None:
        result = self.result(None)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["task_log_condition"], "not_evaluated")

    def test_missing_or_empty_baseline(self) -> None:
        self.baseline.unlink()
        self.assert_failed("original_files")
        self.write_json(self.baseline, {"originals": {}})
        self.assert_failed("original_files")

    def test_binary_media_modified_or_missing(self) -> None:
        media = self.repo / "image.png"
        media.write_bytes(b"changed")
        self.assert_failed("original_files")
        media.unlink()
        self.assert_failed("original_files")

    def test_wrong_hash(self) -> None:
        value = grader.read_json(self.baseline)
        value["originals"]["README.md"] = "0" * 64
        self.write_json(self.baseline, value)
        self.assert_failed("original_files")

    def test_outside_baseline_path(self) -> None:
        outside = self.work / "outside.txt"
        outside.write_text("must not accept", encoding="utf-8")
        self.write_json(self.baseline, {"originals": {"../outside.txt": grader.digest(outside)}})
        self.assert_failed("original_files")

    def test_original_text_or_marker_changed(self) -> None:
        annotated = self.output / "ANNOTATED_README.md"
        original = annotated.read_bytes()
        annotated.write_bytes(original.replace(b"# Demo", b"# Forged"))
        self.assert_failed("readme_fidelity_and_links")
        annotated.write_bytes(original.replace(grader.END, b"", 1))
        self.assert_failed("readme_fidelity_and_links")

    def test_presentation_failure_does_not_relabel_passing_task_log(self) -> None:
        (self.output / "ANNOTATED_README.md").write_bytes(b"broken presentation")
        result = self.result()
        self.assertFalse(result["ok"])
        self.assertEqual(result["task_log_condition"], "passed")

    def test_correct_count_wrong_section_or_placement(self) -> None:
        annotated = self.output / "ANNOTATED_README.md"
        original = annotated.read_bytes()
        annotated.write_bytes(original.replace(b'section="Test"', b'section="Other"'))
        self.assert_failed("readme_fidelity_and_links")
        restored, _ = grader.split_insertions(original)
        start = original.index(grader.BEGIN, original.index(grader.END) + len(grader.END))
        end = original.index(grader.END, start) + len(grader.END) + 1
        marker = original[start:end]
        annotated.write_bytes(original[:start] + original[end:] + marker)
        self.assertEqual(grader.split_insertions(annotated.read_bytes())[0], restored)
        self.assert_failed("readme_fidelity_and_links")

    def test_missing_outside_or_external_inserted_link(self) -> None:
        annotated = self.output / "ANNOTATED_README.md"
        original = annotated.read_bytes()
        outside = self.work / "outside.txt"
        outside.write_text("outside allowed roots", encoding="utf-8")
        for target in (b"missing.md", b"../outside.txt", b"https://example.com/report"):
            annotated.write_bytes(original.replace(b"](SUMMARY.md)", b"](" + target + b")"))
            self.assert_failed("readme_fidelity_and_links")

    def test_missing_adjacent_or_bad_receipt(self) -> None:
        self.write_json(self.output / "readme_delivery.json", {**self.status["source_adjacent_readme"], "sha256": "0" * 64})
        self.assert_failed("readme_fidelity_and_links")
        (self.repo / "RIGORPILOT_README.md").unlink()
        self.assert_failed("readme_fidelity_and_links")

    def test_runtime_failure_not_hidden_by_success_report(self) -> None:
        for mutation in ({"returncode": 1}, {"status": "running"}, {"cancelled": True}, {"finished_at": None}, {"returncode": False}):
            state = {"run_id": "test-1", "status": "success", "returncode": 0, "finished_at": "now", **mutation}
            self.write_json(self.run_dir / "state.json", state)
            self.assert_failed("runtime_and_stdout")

    def test_report_command_or_status_forged(self) -> None:
        self.status["documented_command"] = "invented command"
        self.write_json(self.output / "status.json", self.status)
        self.assert_failed("runtime_and_stdout")
        self.status["documented_command"] = "python -m pytest"
        self.status["status"] = "blocked"
        self.write_json(self.output / "status.json", self.status)
        self.assert_failed("runtime_and_stdout")

    def test_stdout_missing_or_wrong_even_with_claimed_success(self) -> None:
        (self.run_dir / "stdout.log").write_text("2 failed\n", encoding="utf-8")
        self.assert_failed("runtime_and_stdout")
        (self.run_dir / "stdout.log").unlink()
        self.assert_failed("runtime_and_stdout")

    def test_missing_completion_event(self) -> None:
        (self.run_dir / "events.jsonl").write_text("", encoding="utf-8")
        self.assert_failed("runtime_and_stdout")

    def test_completion_must_be_terminal_event(self) -> None:
        events = self.run_dir / "events.jsonl"
        events.write_text(events.read_text(encoding="utf-8") + json.dumps({"type": "started", "data": {}}) + "\n", encoding="utf-8")
        self.assert_failed("runtime_and_stdout")

    def test_explicit_metric_mismatch_cannot_be_overall_success(self) -> None:
        self.status["result_match"] = {"status": "mismatched", "comparisons": [{"expected": 1.0, "observed": 0.0}]}
        self.write_json(self.output / "status.json", self.status)
        self.assert_failed("runtime_and_stdout")

    def test_evidence_path_cannot_point_elsewhere(self) -> None:
        outside = self.work / "stdout.log"
        outside.write_text("2 passed\n", encoding="utf-8")
        self.status["runtime"]["stdout_log_path"] = str(outside)
        self.write_json(self.output / "status.json", self.status)
        self.assert_failed("runtime_and_stdout")

    def test_bom_crlf_and_fenced_fake_heading(self) -> None:
        self.source.write_bytes(b'\xef\xbb\xbf# Demo\r\n```python\r\n# Not a section\r\n```\r\n## Test\r\nNo final newline')
        value = grader.read_json(self.baseline)
        value["originals"]["README.md"] = grader.digest(self.source)
        self.write_json(self.baseline, value)
        self.regenerate()
        self.assertTrue(self.result()["ok"], self.result())

    def test_cli_report_is_new_and_never_overwrites_evidence(self) -> None:
        report = self.work / "GRADE.json"
        command = [sys.executable, str(SCRIPT), "--baseline", str(self.baseline), "--repo", str(self.repo), "--output-dir", str(self.output), "--expected-stdout", "2 passed", "--report"]
        result = subprocess.run(command + [str(report)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for destination in (report, self.baseline, self.output / "new-report.json", self.repo / "new-report.json"):
            with self.subTest(destination=destination):
                result = subprocess.run(command + [str(destination)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
        (self.run_dir / "stdout.log").write_text("2 failed\n", encoding="utf-8")
        result = subprocess.run(command + [str(self.work / "FAILED.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(grader.read_json(self.work / "FAILED.json")["ok"])


if __name__ == "__main__":
    unittest.main()
