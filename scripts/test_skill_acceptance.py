#!/usr/bin/env python3
"""Actual installed runtime plus tamper checks, standard library only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from run_skill_acceptance import run, verify_case
from check_first_use import digest, split_insertions, heading_blocks, inserted_links


class SkillAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rigorpilot-acceptance-")
        cls.output = Path(cls.temp.name) / "evidence"
        cls.report = run(cls.output, sys.executable)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_runtime_covers_positive_and_negative_outcomes(self):
        self.assertTrue(self.report["ok"], self.report)
        self.assertEqual(self.report["passed"], 3)
        self.assertEqual(self.report["model_calls"], 0)
        self.assertIsNone(self.report["model_effect"])
        wrong = next(row for row in self.report["rows"] if row["case"] == "wrong_metric")
        self.assertEqual(wrong["task_status"], "partial")
        self.assertTrue(wrong["runtime_success"])
        self.assertTrue(wrong["source_and_readme_verified"])
        # The old success-only grader must still reject this nonmatching task.
        old = json.loads((self.output / "wrong_metric/CHECK.json").read_text(encoding="utf-8"))
        self.assertFalse(old["ok"])

    def test_existing_evidence_is_never_overwritten(self):
        before = (self.output / "REPORT.json").read_bytes()
        with self.assertRaises(ValueError):
            run(self.output, sys.executable)
        self.assertEqual((self.output / "REPORT.json").read_bytes(), before)

    def test_archived_originals_media_and_readme_links(self):
        archive = ROOT / "benchmark_outputs/skill_acceptance"
        cases = list(archive.glob("attempt-*/*/BASELINE.json"))
        self.assertEqual(len(cases), 8)
        for baseline in cases:
            with self.subTest(case=baseline.parent):
                repo = baseline.parent / "repo"
                originals = json.loads(baseline.read_text(encoding="utf-8"))["originals"]
                for name, expected in originals.items():
                    self.assertEqual(digest(repo / name), expected, name)
                document = repo / "RIGORPILOT_README.md"
                restored, blocks = split_insertions(document.read_bytes())
                self.assertEqual(restored, (repo / "README.md").read_bytes())
                expected_sections = heading_blocks(restored)
                actual_sections = [{key: block.get(key) for key in ("section", "occurrence", "offset")}
                                   for block in blocks if block.get("kind") == "section"]
                self.assertEqual(actual_sections, expected_sections)
                self.assertGreater(inserted_links(blocks, document, (repo, baseline.parent / "evidence")), 0)

    def test_tampered_negative_evidence_cannot_pass(self):
        base = self.output / "wrong_metric"
        for relative, mutate in (
            ("evidence/status.json", lambda value: value.update(status="success")),
            ("repo/results/metrics.json", lambda value: value.update(mse=0)),
            ("repo/results/predictions.json", lambda value: value.update(predictions=[1, 3, 5])),
        ):
            with self.subTest(relative=relative):
                path = base / relative
                original = path.read_bytes()
                try:
                    value = json.loads(original)
                    mutate(value)
                    path.write_text(json.dumps(value), encoding="utf-8")
                    self.assertFalse(verify_case("wrong_metric", base / "repo", base / "evidence")["ok"])
                finally:
                    path.write_bytes(original)
        path = next((base / "evidence/_runtime").glob("*/events.jsonl"))
        original = path.read_bytes()
        try:
            path.write_bytes(b"")
            self.assertFalse(verify_case("wrong_metric", base / "repo", base / "evidence")["ok"])
        finally:
            path.write_bytes(original)

    def test_arbitrary_failure_is_not_missing_asset_proof(self):
        base = self.output / "missing_asset"
        path = next((base / "evidence/_runtime").glob("*/stderr.log"))
        original = path.read_bytes()
        try:
            path.write_text("SyntaxError: unrelated failure", encoding="utf-8")
            self.assertFalse(verify_case("missing_asset", base / "repo", base / "evidence")["ok"])
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
