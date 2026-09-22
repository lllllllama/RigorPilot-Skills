#!/usr/bin/env python3
"""Real subprocess tests for short-call handoff; no model or network requests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/ai-research-reproduction/scripts"
JOB = SCRIPTS / "repro_job.py"
ORCHESTRATOR = SCRIPTS / "orchestrate_repro.py"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", RIGORPILOT_LESSONS="0")
sys.path.insert(0, str(SCRIPTS))
import repro_job as job_module


def remove_tree(path: Path) -> None:
    def writable(function, name, _error):
        os.chmod(name, 0o700)
        function(name)
    shutil.rmtree(path, onerror=writable)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="rigorpilot-job-"))
        self.repo = self.temp / "repo"
        self.repo.mkdir()
        self.output = self.repo / "repro_outputs"
        (self.repo / "README.md").write_text("# Test\n\n## Evaluation\n\n```bash\npython evaluate.py\n```\n", encoding="utf-8")
        self.script("print('score=1.0', flush=True)\n")
        for args in (["init"], ["config", "user.name", "Test"], ["config", "user.email", "test@example.invalid"],
                     ["add", "."], ["commit", "-m", "fixture"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, env=ENV)
        self.jobs = []

    def tearDown(self):
        # Do not leave long-lived children on assertion failure.
        for output in self.jobs:
            try:
                self.call("cancel", "--output-dir", str(output))
                self.wait(output, timeout=30)
            except (OSError, ValueError, AssertionError, subprocess.SubprocessError):
                continue
        if os.getenv("RIGORPILOT_TEST_KEEP_TMP"):
            print("retained_test_directory:", self.temp)
        else:
            # A terminal receipt is written immediately before the supervisor exits.
            for attempt in range(30):
                try:
                    remove_tree(self.temp)
                    break
                except PermissionError:
                    if attempt == 29:
                        raise
                    time.sleep(0.1)

    def script(self, body):
        (self.repo / "evaluate.py").write_text(
            "from pathlib import Path\n"
            "counter=Path('execution_count.txt')\n"
            "counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')\n" + body,
            encoding="utf-8")

    def call(self, *args, expected=0):
        proc = subprocess.run([sys.executable, str(JOB), *args], cwd=self.temp, env=ENV,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def start_args(self, timeout=5, *extra):
        proc = subprocess.run([sys.executable, str(ORCHESTRATOR), "--repo", str(self.repo),
                               "--plan-only", "--agent-output", "--timeout", str(timeout)],
                              cwd=self.temp, env=ENV, capture_output=True, text=True, encoding="utf-8", check=True, timeout=20)
        plan = json.loads(proc.stdout)
        return ["start", "--repo", str(self.repo), "--output-dir", str(self.output),
                "--command-id", plan["selected_command_id"], "--plan-fingerprint", plan["selection_fingerprint"],
                "--timeout", str(timeout), *extra]

    def launch(self, timeout=5, *extra):
        args = self.start_args(timeout, *extra)
        receipt = self.call(*args)
        self.jobs.append(self.output)
        return receipt, args

    def wait(self, output=None, timeout=30):
        output = output or self.output
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.call("status", "--output-dir", str(output))
            if result["terminal"]:
                return result
            time.sleep(0.2)
        self.fail("Job did not reach a terminal state; retained status: " + json.dumps(result))

    def test_disconnect_and_idempotent_reconnect(self):
        self.script("import time\nprint('started', flush=True)\ntime.sleep(2)\nprint('score=1.0', flush=True)\n")
        receipt, args = self.launch(8, "--source-adjacent-readme", "--expected-metric", "score=1.0")
        self.assertFalse(receipt["terminal"])
        # The CLI that launched the job has exited. Independent subsequent calls reconnect to the same receipt.
        again = self.call(*args)
        self.assertTrue(again["reused"])
        self.assertEqual(receipt["job_id"], again["job_id"])
        final = self.wait()
        self.assertEqual(final["lifecycle"], "completed", final)
        self.assertTrue(final["result"]["accepted"], final)
        self.assertTrue((self.repo / "RIGORPILOT_README.md").is_file())
        self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")
        last = self.call(*args)
        self.assertTrue(last["reused"])
        self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")
        conflict = self.call(*args, "--timeout", "9", expected=2)
        self.assertEqual(conflict["error"]["code"], "job_conflict")
        # Even a direct repeated worker invocation cannot replay the completed job.
        repeated = self.call("_work", "--output-dir", str(self.output), "--job-id", receipt["job_id"],
                             "--request-sha256", receipt["request_sha256"], expected=2)
        self.assertEqual(repeated["error"]["code"], "worker_already_claimed")
        self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")

    def test_timeout_finalizes_but_is_not_accepted(self):
        self.script("import time\nprint('2 passed; score=1.0', flush=True)\ntime.sleep(30)\n")
        self.launch(1, "--expected-metric", "score=1.0")
        final = self.wait()
        self.assertEqual(final["lifecycle"], "completed", final)
        self.assertEqual(final["result"]["runtime_status"], "timed_out")
        self.assertTrue(final["result"]["evidence_valid"])
        self.assertFalse(final["result"]["accepted"])
        self.assertTrue((self.output / "status.json").is_file())
        stdout = next((self.output / "_runtime").glob("*/stdout.log"))
        self.assertIn("2 passed", stdout.read_text(encoding="utf-8"))

    def test_cancel_preserves_finalization(self):
        self.script("import time\nprint('started', flush=True)\ntime.sleep(30)\n")
        self.launch(20)
        deadline = time.monotonic() + 15
        while not list((self.output / "_runtime").glob("*/state.json")) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(list((self.output / "_runtime").glob("*/state.json")))
        self.assertTrue(self.call("cancel", "--output-dir", str(self.output))["cancel_requested"])
        final = self.wait()
        self.assertEqual(final["result"]["runtime_status"], "cancelled", final)
        self.assertTrue(final["result"]["evidence_valid"])
        self.assertFalse(final["result"]["accepted"])
        self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")

    def test_metrics_are_not_process_success(self):
        self.launch(5, "--expected-metric", "score=2.0")
        final = self.wait()
        self.assertEqual(final["result"]["runtime_status"], "success")
        self.assertEqual(final["result"]["result_match"], "mismatched")
        self.assertTrue(final["result"]["evidence_valid"])
        self.assertFalse(final["result"]["accepted"])

    def test_changed_plan_never_executes(self):
        args = self.start_args()
        (self.repo / "README.md").write_text("# Test\n\n```bash\npython different.py\n```\n", encoding="utf-8")
        self.call(*args)
        self.jobs.append(self.output)
        final = self.wait()
        self.assertEqual(final["error"]["code"], "plan_changed", final)
        self.assertFalse((self.repo / "execution_count.txt").exists())
        self.assertFalse((self.output / "_runtime").exists())

    def test_conflicting_evidence_is_not_overwritten(self):
        args = self.start_args()
        self.output.mkdir()
        sentinel = self.output / "status.json"
        sentinel.write_text("existing evidence", encoding="utf-8")
        result = self.call(*args, expected=2)
        self.assertEqual(result["error"]["code"], "output_not_empty")
        self.assertEqual(sentinel.read_text(), "existing evidence")

    def test_concurrent_start_has_one_execution(self):
        args = self.start_args()
        calls = [subprocess.Popen([sys.executable, str(JOB), *args], cwd=self.temp, env=ENV,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for _ in range(2)]
        results = [proc.communicate(timeout=20) for proc in calls]
        self.assertTrue(any(proc.returncode == 0 for proc in calls), results)
        self.jobs.append(self.output)
        final = self.wait()
        self.assertTrue(final["result"]["accepted"], final)
        self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")
        self.assertEqual(len(list((self.output / "_runtime").glob("*/state.json"))), 1)

    def test_training_never_runs_through_short_call_lane(self):
        (self.repo / "README.md").write_text("# Test\n\n## Training\n\n```bash\npython train.py\n```\n", encoding="utf-8")
        self.launch()
        final = self.wait()
        self.assertEqual(final["error"]["code"], "training_job_not_supported")
        self.assertFalse((self.output / "_runtime").exists())

    def test_plan_provides_exact_installed_handoff_argv(self):
        ordinary = subprocess.run([sys.executable, str(ORCHESTRATOR), "--repo", str(self.repo),
                                   "--plan-only", "--timeout", "7", "--source-adjacent-readme"],
                                  env=ENV, capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertNotIn("agent_handoff", json.loads(ordinary.stdout))
        proc = subprocess.run([sys.executable, str(ORCHESTRATOR), "--repo", str(self.repo),
                               "--plan-only", "--include-agent-handoff", "--timeout", "7", "--source-adjacent-readme"],
                              env=ENV, capture_output=True, text=True, encoding="utf-8", check=True)
        plan = json.loads(proc.stdout)
        handoff = plan["agent_handoff"]
        self.assertEqual(Path(handoff["start_argv"][1]), JOB)
        self.assertIn("--source-adjacent-readme", handoff["start_argv"])
        self.assertEqual(handoff["start_argv"][handoff["start_argv"].index("--timeout") + 1], "7")
        self.assertFalse(self.output.exists(), "planning must not create the job or evidence")

    def test_altered_request_is_rejected_without_replay(self):
        self.launch()
        self.wait()
        path = self.output / ".repro_job/request.json"
        original = path.read_bytes()
        data = json.loads(original)
        data["timeout"] += 1
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            result = self.call("status", "--output-dir", str(self.output), expected=2)
            self.assertEqual(result["error"]["code"], "invalid_job_record")
            self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")
        finally:
            path.write_bytes(original)

    def test_lost_worker_never_triggers_automatic_replay(self):
        receipt, args = self.launch()
        self.wait()
        path = self.output / ".repro_job/state.json"
        original = path.read_bytes()
        state = json.loads(original)
        # Synthetic lost-worker receipt: no process is killed or PID reused by the test.
        state.update(lifecycle="working", worker_pid=2147483647, result=None)
        path.write_text(json.dumps(state), encoding="utf-8")
        try:
            lost = self.call("status", "--output-dir", str(self.output))
            self.assertEqual(lost["lifecycle"], "interrupted")
            self.assertFalse(lost["automatic_replay_allowed"])
            again = self.call(*args)
            self.assertTrue(again["reused"])
            self.assertEqual(receipt["job_id"], again["job_id"])
            self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")
        finally:
            path.write_bytes(original)

    def test_unknown_job_query_has_no_side_effect(self):
        self.call("status", "--output-dir", str(self.output), expected=2)
        self.assertFalse(self.output.exists())

    def test_control_record_read_retries_transient_windows_lock(self):
        record = self.temp / "record.json"
        record.write_text('{"ok": true}\n', encoding="utf-8")
        original_open = Path.open
        attempts = []

        def transient(path, *args, **kwargs):
            if path == record and len(attempts) < 2:
                attempts.append(1)
                raise PermissionError("simulated sharing lock")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=transient):
            self.assertEqual(job_module.read_object(record), {"ok": True})
        self.assertEqual(len(attempts), 2)

    def test_receipt_identity_binds_poll_and_cancel(self):
        receipt, _args = self.launch()
        for action in ("status", "cancel"):
            argv = receipt[action + "_argv"]
            self.assertEqual(argv[-2:], ["--job-id", receipt["job_id"]])
            denied = self.call(action, "--output-dir", str(self.output), "--job-id", "0" * 32, expected=2)
            self.assertEqual(denied["error"]["code"], "job_identity_mismatch")
            self.assertFalse((self.output / ".repro_job/CANCEL").exists())
        final = self.wait()
        self.assertTrue(final["result"]["accepted"], final)
        checked = self.call("status", "--output-dir", str(self.output), "--job-id", receipt["job_id"])
        self.assertTrue(checked["identity_checked"])
        # Simulate a different job having acquired the same filesystem location.
        # A stale client must not accept the replacement's positive result.
        path = self.output / ".repro_job/state.json"
        original = path.read_bytes()
        replacement = json.loads(original)
        replacement["job_id"] = "f" * 32
        path.write_text(json.dumps(replacement), encoding="utf-8")
        try:
            denied = self.call("status", "--output-dir", str(self.output), "--job-id", receipt["job_id"], expected=2)
            self.assertEqual(denied["error"]["code"], "job_identity_mismatch")
            self.assertEqual((self.repo / "execution_count.txt").read_text(), "1")
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
