#!/usr/bin/env python3
"""Check published showcase bytes and evidence links in a Git tree, not local residue."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/ai-research-reproduction/scripts"))
from annotate_readme import strip_annotated_bytes

MANIFEST = "benchmark_outputs/PUBLICATION_MANIFEST.json"


def git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def inventory(root: Path) -> dict:
    files = []
    paths = [path for directory in ["showcases", "agent_canary", "paired_pilot_calibration", "controller_smoke"]
             for path in (root / "benchmark_outputs" / directory).rglob("*")]
    for path in sorted(paths):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        files.append({"path": path.relative_to(root).as_posix(), "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    return {"schema_version": "1.0", "files": files}


def check(root: Path, ref: str = "HEAD") -> list[str]:
    errors = []
    def read(name: str) -> bytes:
        return git_bytes(root, "show", f"{ref}:{name}")
    try:
        manifest = json.loads(read(MANIFEST))
    except (subprocess.CalledProcessError, ValueError):
        return [f"missing/invalid publication manifest in {ref}"]
    contents = {}
    for entry in manifest["files"]:
        name = entry["path"]
        try:
            contents[name] = read(name)
        except subprocess.CalledProcessError:
            errors.append(f"not published: {name}")
            continue
        if hashlib.sha256(contents[name]).hexdigest() != entry["sha256"]:
            errors.append(f"published bytes changed: {name}")
    for name, data in list(contents.items()):
        if not name.endswith("/SHOWCASE.json"):
            continue
        meta = json.loads(data)
        base = PurePosixPath(name).parent
        upstream = [p for p in contents if p.startswith(str(base / "repo") + "/")
                    and not any(part in {"repro_outputs", "train_outputs", "RIGORPILOT_README.md"} for part in PurePosixPath(p).parts)]
        if len(upstream) != meta["tracked_files_retained"]:
            errors.append(f"upstream file count differs from source manifest: {name}")
        original = str(base / "repo" / meta["original_readme"])
        annotated = str(base / meta["annotated_readme"])
        if original not in contents or annotated not in contents:
            errors.append(f"missing README pair: {name}")
            continue
        try:
            restored = strip_annotated_bytes(contents[annotated])
            if restored != contents[original] or hashlib.sha256(restored).hexdigest() != meta["original_sha256"]:
                errors.append(f"README round trip failed: {name}")
        except ValueError as exc:
            errors.append(f"invalid annotations: {name}: {exc}")
        # Validate RigorPilot's own links only; upstream links remain untouched.
        blocks = re.findall(rb'<!-- rigorpilot:repro:begin.*?<!-- rigorpilot:repro:end -->', contents[annotated], re.S)
        for block in blocks:
            for target in re.findall(rb'\]\(([^)]+)\)', block):
                link = target.decode("utf-8")
                if "://" in link or link.startswith("#"):
                    continue
                resolved = (root / PurePosixPath(annotated).parent / link.split("#")[0]).resolve()
                try:
                    relative = resolved.relative_to(root.resolve()).as_posix()
                except ValueError:
                    errors.append(f"link escapes publication: {link}")
                    continue
                if relative not in contents:
                    errors.append(f"unpublished evidence link: {annotated} -> {link}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Git tree/commit; use an empty string for the index")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        payload = inventory(ROOT)
        (ROOT / MANIFEST).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"manifest_files: {len(payload['files'])}")
        return 0
    errors = check(ROOT, args.ref)
    print(json.dumps({"ok": not errors, "ref": args.ref, "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
