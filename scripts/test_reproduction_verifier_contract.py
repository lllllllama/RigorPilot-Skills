#!/usr/bin/env python3
"""Negative contracts: incomplete evidence never becomes positive verification."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/ai-research-reproduction/scripts"))
import orchestrate_repro as orch


class VerifierContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rigorpilot-verifier-contract-"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_nonobject_status_is_structured_failure(self):
        for value in ([], None, True, "not a mapping", {"runtime": []}):
            (self.root / "status.json").write_text(json.dumps(value), encoding="utf-8")
            payload = orch.verify_existing_output(self.root, self.root)
            self.assertIs(payload["evidence_valid"], False)
            self.assertIn("error", payload)

    def test_manifest_cannot_omit_or_rebind_required_files(self):
        path = self.root / "evidence_manifest.json"
        (self.root / "unrelated.txt").write_text("not a bundle", encoding="utf-8")
        record = orch._evidence_record(self.root / "unrelated.txt", self.root, self.root)
        for value in ([], {"files": []}, {"files": {}},
                      {"schema_version": "1.1", "files": {"unrelated": record}},
                      {"schema_version": "1.1", "files": {"status": record}}):
            path.write_text(json.dumps(value), encoding="utf-8")
            result = orch.verify_evidence_manifest(self.root, self.root)
            self.assertIs(result["valid"], False, result)

    def test_matching_nonterminal_runtime_is_rejected(self):
        state = self.root / "state.json"
        state.write_text(json.dumps({"status": "running", "run_id": "one"}), encoding="utf-8")
        (self.root / "stdout.log").touch()
        (self.root / "stderr.log").touch()
        (self.root / "status.json").write_text(json.dumps({
            "target_repo": str(self.root), "runtime": {"status": "running", "run_id": "one",
                "state_path": str(state), "stdout_log_path": str(self.root / "stdout.log"),
                "stderr_log_path": str(self.root / "stderr.log")}}), encoding="utf-8")
        result = orch.verify_existing_output(self.root, self.root)
        self.assertIs(result["checks"]["runtime"], False)

    def test_bounded_diagnostics_do_not_read_entire_log(self):
        path = self.root / "large.log"
        path.write_bytes(b"x" * (3 * 1024 * 1024) + b"\nModuleNotFoundError: example\n")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")):
            tail = orch._bounded_log_text({"stderr_log_path": str(path)}, limit=1024)
        self.assertLessEqual(len(tail), 1024)
        self.assertIn("ModuleNotFoundError", tail)

    def test_legacy_manifest_coverage_is_explicit(self):
        records = {}
        for label, name in {"summary": "SUMMARY.md", "status": "status.json", "commands": "COMMANDS.md", "log": "LOG.md",
                            "scientific_changelog": "SCIENTIFIC_CHANGELOG.md", "comparability_report": "COMPARABILITY_REPORT.md",
                            "invocation": "invocation.json"}.items():
            path = self.root / name
            path.write_text("retained legacy bytes", encoding="utf-8")
            records[label] = orch._evidence_record(path, self.root, self.root)
        manifest = self.root / "evidence_manifest.json"
        manifest.write_text(json.dumps({"schema_version": "1.0", "files": records}), encoding="utf-8")
        legacy = orch.verify_evidence_manifest(self.root, self.root, {"runtime_spec": self.root / "missing-spec.json"})
        self.assertTrue(legacy["valid"])
        self.assertEqual(legacy["coverage"], "legacy_core_only")
        manifest.write_text(json.dumps({"schema_version": "1.1", "files": records}), encoding="utf-8")
        current = orch.verify_evidence_manifest(self.root, self.root, {"runtime_spec": self.root / "missing-spec.json"})
        self.assertFalse(current["valid"])


if __name__ == "__main__":
    unittest.main()
