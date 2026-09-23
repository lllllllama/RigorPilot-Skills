#!/usr/bin/env python3
"""A local-only evidence file must fail publication validation."""
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path
from check_publication import check, inventory, MANIFEST
import check_publication as publication


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
        acceptance = root / "benchmark_outputs/skill_acceptance/attempt-2/REPORT.json"
        acceptance.parent.mkdir(parents=True)
        acceptance.write_bytes(b'{"scope":"deterministic_runtime_acceptance_not_model_gain"}\n')
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)
        assert any("not published" in error and "skill_acceptance" in error for error in check(root, ""))
        git("add", acceptance.relative_to(root).as_posix())
        assert not check(root, "")
        live = root / "benchmark_outputs/real_client/20260913/REPORT.json"
        live.parent.mkdir(parents=True)
        live.write_bytes(b'{"client_completed":false,"overall_pass":false}\n')
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)
        assert any("not published" in error and "real_client" in error for error in check(root, ""))
        git("add", live.relative_to(root).as_posix())
        assert not check(root, "")
        reviewed = root / "benchmark_outputs/reviewed_selection_latest.json"
        reviewed.write_bytes(b'{"status":"passed","passed":4,"failed":0}\n')
        integrity = root / "benchmark_outputs/source_integrity_latest.json"
        integrity.write_bytes(b'{"status":"passed","cases":[]}\n')
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)
        assert any("not published" in error and "reviewed_selection_latest" in error for error in check(root, ""))
        assert any("not published" in error and "source_integrity_latest" in error for error in check(root, ""))
        git("add", reviewed.relative_to(root).as_posix(), integrity.relative_to(root).as_posix())
        assert not check(root, "")
        evidence.write_bytes(b"corrupted evidence\n")
        git("add", evidence.relative_to(root).as_posix())
        assert any("bytes changed" in error for error in check(root, ""))
        special = root / "benchmark_outputs/showcases/test/repo/空 格.bin"
        special.write_bytes(b"\x00\xff\n---\r\n")
        empty = root / "benchmark_outputs/showcases/test/repo/empty.txt"
        empty.write_bytes(b"")
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", "benchmark_outputs")
        assert not check(root, ""), "binary, Unicode, and empty blobs must round-trip"

        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        manifest["files"].append(dict(manifest["files"][0]))
        (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        git("add", MANIFEST)
        assert any("duplicate manifest path" in error for error in check(root, ""))
        manifest["files"].pop()
        manifest["files"][0]["bytes"] = "unknown"
        (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        git("add", MANIFEST)
        assert any("invalid byte size" in error for error in check(root, ""))
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", MANIFEST)

        original_read = publication._read_blobs
        reads = 0
        def change_index_during_read(*args):
            nonlocal reads
            reads += 1
            if reads == 2:
                evidence.write_bytes(b"index changed during check\n")
                git("add", evidence.relative_to(root).as_posix())
            return original_read(*args)
        publication._read_blobs = change_index_during_read
        try:
            assert any("index changed" in error for error in check(root, ""))
        finally:
            publication._read_blobs = original_read

        invalid = root / "benchmark_outputs/showcases/invalid"
        (invalid / "repo").mkdir(parents=True)
        (invalid / "repo/README.md").write_bytes(b"source\n")
        (invalid / "ANNOTATED_README.md").write_bytes(b"<!-- rigorpilot:repro:begin -->[x](\xff)<!-- rigorpilot:repro:end -->")
        (invalid / "SHOWCASE.json").write_text(json.dumps({
            "tracked_files_retained": 1, "original_readme": "README.md",
            "annotated_readme": "ANNOTATED_README.md",
            "original_sha256": hashlib.sha256(b"source\n").hexdigest(),
        }), encoding="utf-8")
        (root / MANIFEST).write_text(json.dumps(inventory(root)), encoding="utf-8")
        git("add", "benchmark_outputs")
        assert any("invalid UTF-8 evidence link" in error for error in check(root, ""))
    print("ok: True; index omission and corruption detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
