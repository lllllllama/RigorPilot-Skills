#!/usr/bin/env python3
"""Deterministic transient-sharing-lock regression for runtime journals."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared/scripts"))
import runtime_runner as runner


class AtomicWriteTests(unittest.TestCase):
    def test_success_does_not_unlink_a_reused_staging_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            replace = runner.os.replace
            def reused(source, destination):
                replace(source, destination)
                Path(source).write_text("new writer owns this name", encoding="utf-8")
            with patch.object(runner.uuid, "uuid4", return_value=SimpleNamespace(hex="cccc")):
                with patch.object(runner.os, "replace", side_effect=reused):
                    runner.atomic_write_json(path, {"status": "success"})
            self.assertEqual(json.loads(path.read_text())["status"], "success")
            self.assertEqual((Path(directory) / ".cccc.tmp").read_text(), "new writer owns this name")

    def test_staging_collision_never_truncates_another_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            staging = Path(directory) / ".aaaa.tmp"
            staging.write_text("owned by another writer", encoding="utf-8")
            with patch.object(runner.uuid, "uuid4", side_effect=[SimpleNamespace(hex="aaaa"), SimpleNamespace(hex="bbbb")]):
                runner.atomic_write_json(path, {"status": "success"})
            self.assertEqual(json.loads(path.read_text())["status"], "success")
            self.assertEqual(staging.read_text(), "owned by another writer")
            self.assertFalse((Path(directory) / ".bbbb.tmp").exists())

    def test_serialization_failure_preserves_old_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            runner.atomic_write_json(path, {"status": "running"})
            with self.assertRaises(TypeError):
                runner.atomic_write_json(path, {"invalid": object()})
            self.assertEqual(json.loads(path.read_text())["status"], "running")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_transient_replacement_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            runner.atomic_write_json(path, {"status": "running"})
            replace = runner.os.replace
            attempts = []
            def transient(source, destination):
                attempts.append(1)
                if len(attempts) < 3:
                    self.assertEqual(json.loads(path.read_text())["status"], "running")
                    raise PermissionError("simulated sharing lock")
                replace(source, destination)
            with patch.object(runner.os, "replace", side_effect=transient):
                runner.atomic_write_json(path, {"status": "success"})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(json.loads(path.read_text())["status"], "success")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_permanent_failure_keeps_old_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            runner.atomic_write_json(path, {"status": "running"})
            with patch.object(runner.os, "replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    runner.atomic_write_json(path, {"status": "success"})
            self.assertEqual(json.loads(path.read_text())["status"], "running")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
