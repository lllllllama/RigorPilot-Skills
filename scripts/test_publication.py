#!/usr/bin/env python3
"""A local-only evidence file must fail publication validation."""
import json
import subprocess
import tempfile
from pathlib import Path
from check_publication import check, inventory, MANIFEST


def main():
    with tempfile.TemporaryDirectory(prefix="rigorpilot-publish-test-") as tmp:
        root = Path(tmp)
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        git("init")
        evidence = root / "benchmark_outputs/showcases/test/repo/repro_outputs/SUMMARY.md"
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(b"published evidence\n")
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)
        assert any("not published" in error for error in check(root, ""))
        git("add", evidence.relative_to(root).as_posix())
        assert not check(root, "")
        calibration = root / "benchmark_outputs/paired_pilot_calibration/REPORT.json"
        calibration.parent.mkdir(parents=True)
        calibration.write_bytes(b'{"mode":"offline_calibration"}\n')
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)
        assert any("not published" in error and "paired_pilot_calibration" in error for error in check(root, ""))
        git("add", calibration.relative_to(root).as_posix())
        assert not check(root, "")
        controller = root / "benchmark_outputs/controller_smoke/REPORT.json"
        controller.parent.mkdir(parents=True)
        controller.write_bytes(b'{"mode":"offline_controller_acceptance"}\n')
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)
        assert any("not published" in error and "controller_smoke" in error for error in check(root, ""))
        git("add", controller.relative_to(root).as_posix())
        assert not check(root, "")
        evidence.write_bytes(b"corrupted evidence\n")
        git("add", evidence.relative_to(root).as_posix())
        assert any("bytes changed" in error for error in check(root, ""))
    print("ok: True; index omission and corruption detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
