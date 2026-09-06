#!/usr/bin/env python3
"""Read-only, bounded first-use evidence grader; never executes the target repo.

Baseline JSON requires a non-empty ``originals`` mapping of repo-relative paths
to SHA-256 hashes captured before the run. This checks ATX README annotations,
local inserted links, and the orchestrator's single-command runtime evidence.
It is not a scientific metric grader, model benchmark, browser renderer, or a
defence against coordinated evidence forgery / malicious filesystem changes.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit


BEGIN = b"<!-- rigorpilot:repro:begin"
END = b"<!-- rigorpilot:repro:end -->"
LIMIT = 64 * 1024 * 1024


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path.resolve().is_relative_to(root.resolve()) for root in roots)


def existing(path: Path, roots: tuple[Path, ...]) -> Path:
    resolved = path.resolve()
    if not inside(resolved, roots) or not resolved.is_file():
        raise ValueError(f"missing or out-of-scope file: {path}")
    return resolved


def read_bytes(path: Path) -> bytes:
    if path.stat().st_size > LIMIT:
        raise ValueError(f"evidence exceeds {LIMIT} byte read limit: {path}")
    return path.read_bytes()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(read_bytes(path).decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def recorded_path(value: Any, base: Path, roots: tuple[Path, ...]) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("missing recorded evidence path")
    path = Path(value)
    return existing(path if path.is_absolute() else base / path, roots)


def split_insertions(payload: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    """Independent byte scanner: does not import the product's strip/parser."""
    original = bytearray()
    blocks: list[dict[str, Any]] = []
    cursor = 0
    while True:
        start = payload.find(BEGIN, cursor)
        if start < 0:
            original.extend(payload[cursor:])
            break
        original.extend(payload[cursor:start])
        header_end = payload.find(b"-->", start + len(BEGIN))
        end = payload.find(END, header_end + 3) if header_end >= 0 else -1
        if header_end < 0 or end < 0 or BEGIN in payload[start + len(BEGIN):end]:
            raise ValueError("malformed or nested annotation markers")
        header = payload[start + len(BEGIN):header_end].decode("utf-8")
        attributes = {
            key: html.unescape(value)
            for key, value in re.findall(r'(\w+)="([^"]*)"', header)
        }
        blocks.append({
            **attributes,
            "offset": len(original),
            "body": payload[header_end + 3:end].decode("utf-8"),
        })
        cursor = end + len(END)
        if payload[cursor:cursor + 2] == b"\r\n":
            cursor += 2
        elif payload[cursor:cursor + 1] == b"\n":
            cursor += 1
    if BEGIN in original or END in original or not blocks:
        raise ValueError("unbalanced or absent annotation markers")
    return bytes(original), blocks


def heading_blocks(payload: bytes) -> list[dict[str, Any]]:
    """ATX headings outside fenced code, with original byte end offsets."""
    headings: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    offset = 3 if payload.startswith(b"\xef\xbb\xbf") else 0
    fence_char = None
    fence_length = 0
    for line in payload[offset:].splitlines(keepends=True):
        logical = line.rstrip(b"\r\n")
        fence = re.match(rb"^ {0,3}(`{3,}|~{3,})", logical)
        if fence_char is not None:
            if fence and fence[1][:1] == fence_char and len(fence[1]) >= fence_length:
                fence_char = None
        elif fence:
            fence_char, fence_length = fence[1][:1], len(fence[1])
        else:
            heading = re.match(rb"^ {0,3}#{1,6}(?:[ \t]+|$)(.*)", logical)
            if heading:
                title = re.sub(rb"[ \t]+#+[ \t]*$", b"", heading[1]).strip().decode("utf-8")
                if headings:
                    headings[-1]["offset"] = offset
                occurrences[title] = occurrences.get(title, 0) + 1
                headings.append({"section": title, "occurrence": str(occurrences[title]), "offset": len(payload)})
        offset += len(line)
    if not headings:
        raise ValueError("this first-use grader requires at least one ATX heading")
    return headings


def inserted_links(blocks: list[dict[str, Any]], document: Path, roots: tuple[Path, ...]) -> int:
    count = 0
    for block in blocks:
        body = block["body"]
        markdown = re.findall(r"\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+\"[^\"]*\")?\s*\)", body)
        markup = re.findall(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', body, flags=re.IGNORECASE)
        for raw in markdown + markup:
            target = urlsplit(html.unescape(raw.strip("<>")))
            if target.scheme or target.netloc or target.query:
                raise ValueError(f"non-local inserted evidence link: {raw}")
            path_text = unquote(target.path)
            path = document if not path_text else document.parent / path_text
            existing(path, roots)
            count += 1
    if not count:
        raise ValueError(f"no checkable inserted evidence links: {document}")
    return count


def grade(baseline_path: Path, repo: Path, output_dir: Path, expected_stdout: str | None = None) -> dict[str, Any]:
    repo, output_dir = repo.resolve(), output_dir.resolve()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "grader": "first-use-log-and-readme-fidelity",
        "inputs": {"baseline": str(baseline_path.resolve()), "repo": str(repo), "output_dir": str(output_dir)},
        "limits": [
            "Requires a trusted pre-run baseline; does not authenticate its provenance or completeness.",
            "Independent marker scanner and ATX parser; not a full Markdown/browser or fragment-anchor validator.",
            "Runtime/log consistency is not proof against coordinated forgery or malicious OS/filesystem changes.",
            "Explicit stdout containment is a task-specific log condition, not independent scientific metric verification.",
            "No model capability, automatic skill discovery, installation or clean dependency-environment claim.",
        ],
        "checks": {},
    }

    def check(name: str, function: Callable[[], Any]) -> Any:
        try:
            details = function()
            report["checks"][name] = {"ok": True, "details": details}
            return details
        except (OSError, ValueError, KeyError, TypeError) as error:
            report["checks"][name] = {"ok": False, "error": str(error)}
            return None

    def originals() -> dict[str, Any]:
        baseline = read_json(baseline_path)
        original_files = baseline.get("originals")
        if not isinstance(original_files, dict) or not original_files:
            raise ValueError("baseline requires non-empty originals path-to-SHA256 mapping")
        errors = []
        for name, sha in original_files.items():
            if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
                errors.append(f"unsafe baseline path: {name}")
                continue
            try:
                path = existing(repo / name, (repo,))
                if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha) or digest(path) != sha.lower():
                    errors.append(f"original SHA256 mismatch: {name}")
            except (OSError, ValueError) as error:
                errors.append(str(error))
        if errors:
            raise ValueError("; ".join(errors))
        return {"files_checked": len(original_files), "baseline_sha256": digest(baseline_path)}

    check("original_files", originals)
    status = check("status_file", lambda: read_json(existing(output_dir / "status.json", (output_dir,))))
    if status is not None:
        # Keep the report small: status is consumed below, never presented as proof.
        report["checks"]["status_file"]["details"] = {"sha256": digest(output_dir / "status.json")}

    def readmes() -> dict[str, Any]:
        if status is None:
            raise ValueError("status evidence unavailable")
        coverage = status["readme_section_coverage"]
        source = recorded_path(coverage["source_readme"], repo, (repo,))
        baseline = read_json(baseline_path)
        if source.relative_to(repo).as_posix() not in baseline["originals"]:
            raise ValueError("source README is not in pre-run baseline")
        source_bytes = read_bytes(source)
        expected_sections = heading_blocks(source_bytes)
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        if coverage.get("original_sha256") != source_sha or coverage.get("stripped_sha256") != source_sha:
            raise ValueError("reported README hashes disagree with source")
        if coverage.get("annotation_count") != len(expected_sections) or coverage.get("total_sections") != len(expected_sections):
            raise ValueError("reported section/annotation counts disagree with source")
        receipt = read_json(existing(output_dir / "readme_delivery.json", (output_dir,)))
        adjacent = existing(source.parent / "RIGORPILOT_README.md", (repo,))
        delivery = status["source_adjacent_readme"]
        if delivery.get("status") != "written":
            raise ValueError("source-adjacent README not reported written")
        for record in (receipt, delivery):
            if recorded_path(record["path"], repo, (repo,)) != adjacent:
                raise ValueError("source-adjacent receipt path mismatch")
            if recorded_path(record["source_readme"], repo, (repo,)) != source:
                raise ValueError("source-adjacent receipt source mismatch")
            if record.get("sha256") != digest(adjacent):
                raise ValueError("source-adjacent receipt hash mismatch")
        results = {}
        for document in (existing(output_dir / "ANNOTATED_README.md", (output_dir,)), adjacent):
            restored, blocks = split_insertions(read_bytes(document))
            if restored != source_bytes:
                raise ValueError(f"README bytes changed outside insertions: {document}")
            banners = [block for block in blocks if block.get("kind") == "banner"]
            sections = [block for block in blocks if block.get("kind") == "section"]
            if len(banners) != 1 or len(blocks) != 1 + len(sections):
                raise ValueError("expected exactly one banner and one annotation per heading")
            if banners[0]["offset"] != (3 if source_bytes.startswith(b"\xef\xbb\xbf") else 0):
                raise ValueError("banner is not before original content")
            if banners[0].get("status") != status.get("status"):
                raise ValueError("banner status disagrees with status.json")
            actual_sections = [{key: block.get(key) for key in ("section", "occurrence", "offset")} for block in sections]
            if actual_sections != expected_sections:
                raise ValueError("annotations do not follow their original heading blocks one-for-one")
            results[str(document)] = {
                "source_sha256": source_sha, "stripped_sha256": hashlib.sha256(restored).hexdigest(),
                "sections": len(sections), "inserted_links_checked": inserted_links(blocks, document, (repo, output_dir)),
            }
        return results

    check("readme_fidelity_and_links", readmes)

    def runtime() -> dict[str, Any]:
        if status is None:
            raise ValueError("status evidence unavailable")
        run = status["runtime"]
        run_id = run["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("invalid runtime run_id")
        runtime_dir = output_dir / "_runtime" / run_id
        files = {}
        for field, name in (("state_path", "state.json"), ("events_path", "events.jsonl"), ("stdout_log_path", "stdout.log"), ("stderr_log_path", "stderr.log")):
            path = recorded_path(run[field], output_dir, (output_dir,))
            if path != (runtime_dir / name).resolve():
                raise ValueError(f"runtime file does not match run_id: {field}")
            files[name] = path
        state = read_json(files["state.json"])
        spec = read_json(existing(runtime_dir / "spec.json", (output_dir,)))
        if state.get("run_id") != run_id or spec.get("run_id") != run_id:
            raise ValueError("runtime state/spec run_id mismatch")
        if state.get("status") != "success" or type(state.get("returncode")) is not int or state["returncode"] != 0:
            raise ValueError("runtime does not record successful terminal execution")
        if not state.get("finished_at") or state.get("cancelled") or state.get("timed_out") or state.get("launch_error"):
            raise ValueError("runtime has missing finish time or cancellation/timeout/launch failure")
        if any(value != "success" for value in (run.get("status"), status.get("status"), status.get("documented_command_status"))):
            raise ValueError("report status disagrees with successful runtime")
        if run.get("cancelled"):
            raise ValueError("report claims cancellation despite successful runtime")
        metric_status = status.get("result_match", {}).get("status", "not_evaluated")
        if metric_status not in ("matched", "not_evaluated"):
            raise ValueError("reported metric comparison is unsuccessful despite successful overall status")
        if spec.get("command") != status.get("documented_command"):
            raise ValueError("reported command differs from actual runtime spec")
        if Path(spec["cwd"]).resolve() != repo or Path(status["target_repo"]).resolve() != repo:
            raise ValueError("runtime/report target repository mismatch")
        events = [json.loads(line) for line in read_bytes(files["events.jsonl"]).decode("utf-8-sig").splitlines() if line.strip()]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("runtime event must be a JSON object")
        completions = [event for event in events if event.get("type") == "completed"]
        if not completions or events[-1].get("type") != "completed" or completions[-1].get("data", {}).get("status") != state["status"] or completions[-1].get("data", {}).get("returncode") != state["returncode"]:
            raise ValueError("completion event missing or inconsistent with runtime state")
        stdout = read_bytes(files["stdout.log"]).decode("utf-8", errors="replace")
        if expected_stdout is not None and (not expected_stdout or expected_stdout not in stdout):
            raise ValueError("explicit expected stdout not found in full raw runtime stdout")
        return {"run_id": run_id, "command": spec["command"], "returncode": state["returncode"],
                "stdout_sha256": digest(files["stdout.log"]), "stdout_bytes": files["stdout.log"].stat().st_size,
                "expected_stdout": expected_stdout, "stdout_condition": "passed" if expected_stdout is not None else "not_configured"}

    runtime_result = check("runtime_and_stdout", runtime)
    report["ok"] = all(item["ok"] for item in report["checks"].values())
    report["task_log_condition"] = "not_evaluated" if expected_stdout is None else ("passed" if runtime_result is not None else "failed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="new JSON file outside source repo and evidence output")
    parser.add_argument("--expected-stdout", help="explicit task-specific substring in complete runtime stdout; omission makes no task-completion claim")
    args = parser.parse_args()
    destination = args.report.resolve()
    if destination == args.baseline.resolve() or inside(destination, (args.repo, args.output_dir)) or destination.exists():
        parser.error("report must be new and outside source repo, baseline and evidence output")
    report = grade(args.baseline, args.repo, args.output_dir, args.expected_stdout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects an existing report; the grader never edits evidence.
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"ok": report["ok"], "task_log_condition": report["task_log_condition"], "report": str(destination)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
