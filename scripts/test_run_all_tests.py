#!/usr/bin/env python3
"""Exercise regression reporting on independent fixture scripts."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


RUNNER = Path(__file__).with_name("run_all_tests.py")


def invoke(fixtures: Path, report: Path, timeout: float = 1.0):
    return subprocess.run(
        [sys.executable, str(RUNNER), "--scripts-dir", str(fixtures), "--report", str(report), "--timeout-seconds", str(timeout)],
        capture_output=True, text=True, timeout=25,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rigorpilot-runner-test-") as temporary:
        root = Path(temporary)
        fixtures = root / "scripts"
        fixtures.mkdir()
        report = root / "report.json"
        (fixtures / "validate_repo.py").write_text("print('valid 中文')\n", encoding="utf-8")
        (fixtures / "test_large.py").write_text("import sys; sys.stdout.buffer.write(('界' * 300000).encode('utf-8'))\n", encoding="utf-8")
        (fixtures / "test_failure.py").write_text("print('failure detail'); raise SystemExit(3)\n", encoding="utf-8")
        (fixtures / "test_timeout.py").write_text(
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', \"import time; time.sleep(2); open(r'%s', 'w').write('orphan')\"])\n"
            "time.sleep(10)\n" % (root / "orphan.txt").as_posix(), encoding="utf-8",
        )
        listed = subprocess.run([sys.executable, str(RUNNER), "--scripts-dir", str(fixtures), "--list"], capture_output=True, text=True, check=True)
        assert len(listed.stdout.splitlines()) == 4
        for invalid in ("nan", "inf", "0"):
            rejected = subprocess.run([sys.executable, str(RUNNER), "--scripts-dir", str(fixtures), "--list", "--timeout-seconds", invalid], capture_output=True, text=True)
            assert rejected.returncode == 2 and "finite and positive" in rejected.stderr, invalid
        result = invoke(fixtures, report, timeout=0.5)
        payload = json.loads(report.read_text(encoding="utf-8"))
        statuses = {row["script"]: row["status"] for row in payload["results"]}
        assert result.returncode == 1 and payload["status"] == "failed", (result, payload)
        assert statuses == {"validate_repo.py": "passed", "test_failure.py": "failed", "test_large.py": "passed", "test_timeout.py": "timed_out"}, (statuses, (root / "report_logs" / "test_timeout.log").read_text(encoding="utf-8"))
        assert payload["selected_count"] == payload["completed_count"] == 4
        for row in payload["results"]:
            assert (report.parent / row["log_path"]).is_file()
        assert "failure detail" in (root / "report_logs" / "test_failure.log").read_text(encoding="utf-8")
        assert (root / "report_logs" / "test_large.log").stat().st_size == 900000
        time.sleep(2.2)
        assert not (root / "orphan.txt").exists(), "timed-out script left a child process"

        (fixtures / "test_failure.py").unlink()
        (fixtures / "test_large.py").unlink()
        (fixtures / "test_timeout.py").unlink()
        good = invoke(fixtures, root / "good.json")
        assert good.returncode == 0 and json.loads((root / "good.json").read_text(encoding="utf-8"))["status"] == "passed"
        (fixtures / "validate_repo.py").unlink()
        missing = invoke(fixtures, root / "missing.json")
        assert missing.returncode == 1 and json.loads((root / "missing.json").read_text(encoding="utf-8"))["results"][0]["status"] == "failed"
    print("ok: runner receipts, logs, timeout tree cleanup, and missing scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
