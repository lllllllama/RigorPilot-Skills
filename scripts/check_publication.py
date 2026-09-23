#!/usr/bin/env python3
"""Check published showcase bytes and evidence links in a Git tree, not local residue."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
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


def _git_objects(root: Path, ref: str) -> tuple[dict[bytes, bytes], bytes | None]:
    """Return a pinned tree or stage-0 index map without decoding Git path bytes."""
    if ref == "":
        listing = git_bytes(root, "ls-files", "--stage", "-z")
        objects: dict[bytes, bytes] = {}
        for entry in filter(None, listing.split(b"\0")):
            meta, path = entry.split(b"\t", 1)
            mode, oid, stage = meta.split(b" ")
            if stage != b"0":
                raise ValueError(f"unmerged index entry: {os.fsdecode(path)}")
            objects[path] = oid
        return objects, listing
    tree = git_bytes(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{tree}}").strip()
    listing = git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", tree.decode("ascii"))
    objects = {}
    for entry in filter(None, listing.split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        _, kind, oid = meta.split(b" ")
        if kind == b"blob":
            objects[path] = oid
    return objects, None


def _read_blobs(root: Path, oids: list[bytes]) -> dict[bytes, bytes]:
    unique = list(dict.fromkeys(oids))
    if not unique:
        return {}
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"], input=b"\n".join(unique) + b"\n",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    stream = io.BytesIO(result.stdout)
    blobs = {}
    for oid in unique:
        header = stream.readline().strip().split(b" ")
        if len(header) != 3 or header[0] != oid or header[1] != b"blob":
            raise ValueError(f"unexpected Git object response for {oid.decode('ascii')}")
        size = int(header[2])
        data = stream.read(size)
        if len(data) != size or stream.read(1) != b"\n":
            raise ValueError("truncated Git batch response")
        blobs[oid] = data
    if stream.read(1):
        raise ValueError("extra Git batch response data")
    return blobs


def _manifest_entries(manifest: object) -> tuple[list[dict], list[str]]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0" or not isinstance(manifest.get("files"), list):
        return [], ["invalid publication manifest structure"]
    errors = []
    seen = set()
    entries = []
    for number, entry in enumerate(manifest["files"]):
        if not isinstance(entry, dict):
            errors.append(f"manifest entry {number} must be an object")
            continue
        name, size, digest = entry.get("path"), entry.get("bytes"), entry.get("sha256")
        if not isinstance(name, str) or not name.startswith("benchmark_outputs/") or "\\" in name or "\0" in name or PurePosixPath(name).as_posix() != name or any(part in {".", ".."} for part in name.split("/")):
            errors.append(f"manifest entry {number} has invalid path")
            continue
        if name in seen:
            errors.append(f"duplicate manifest path: {name}")
            continue
        seen.add(name)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            errors.append(f"invalid byte size: {name}")
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"invalid SHA-256: {name}")
            continue
        entries.append(entry)
    return entries, errors


def inventory(root: Path) -> dict:
    files = []
    paths = [path for directory in ["showcases", "agent_canary", "paired_pilot_calibration", "controller_smoke", "skill_acceptance", "real_client", "agent_handoff"]
             for path in (root / "benchmark_outputs" / directory).rglob("*")]
    for filename in ["reviewed_selection_latest.json", "source_integrity_latest.json"]:
        standalone = root / "benchmark_outputs" / filename
        if standalone.is_file():
            paths.append(standalone)
    for path in sorted(paths):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        files.append({"path": path.relative_to(root).as_posix(), "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    return {"schema_version": "1.0", "files": files}


def check(root: Path, ref: str = "HEAD") -> list[str]:
    errors = []
    try:
        objects, index_before = _git_objects(root, ref)
        manifest_oid = objects.get(os.fsencode(MANIFEST))
        if manifest_oid is None:
            return [f"missing/invalid publication manifest in {ref}"]
        manifest = json.loads(_read_blobs(root, [manifest_oid])[manifest_oid])
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
        return [f"missing/invalid publication manifest in {ref}"]
    entries, structure_errors = _manifest_entries(manifest)
    errors.extend(structure_errors)
    paths = {entry["path"]: objects.get(os.fsencode(entry["path"])) for entry in entries}
    for name, oid in paths.items():
        if oid is None:
            errors.append(f"not published: {name}")
    try:
        blobs = _read_blobs(root, [oid for oid in paths.values() if oid is not None])
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return errors + [f"Git batch read failed: {exc}"]
    contents = {}
    for entry in entries:
        name = entry["path"]
        oid = paths[name]
        if oid is None:
            continue
        contents[name] = blobs[oid]
        if len(contents[name]) != entry["bytes"]:
            errors.append(f"published size changed: {name}")
        if hashlib.sha256(contents[name]).hexdigest() != entry["sha256"]:
            errors.append(f"published bytes changed: {name}")
    for name, data in list(contents.items()):
        if not name.endswith("/SHOWCASE.json"):
            continue
        try:
            meta = json.loads(data)
            if not isinstance(meta, dict) or not isinstance(meta.get("tracked_files_retained"), int) or not isinstance(meta.get("original_readme"), str) or not isinstance(meta.get("annotated_readme"), str) or not isinstance(meta.get("original_sha256"), str):
                raise ValueError("invalid SHOWCASE fields")
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f"invalid SHOWCASE metadata: {name}: {exc}")
            continue
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
                try:
                    link = target.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"invalid UTF-8 evidence link: {annotated}")
                    continue
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
    if index_before is not None:
        try:
            if git_bytes(root, "ls-files", "--stage", "-z") != index_before:
                errors.append("index changed during publication validation; rerun check")
        except (OSError, subprocess.CalledProcessError):
            errors.append("index could not be rechecked; rerun publication validation")
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
