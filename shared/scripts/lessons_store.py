#!/usr/bin/env python3
"""User-owned lesson store backing the continuous-learning policy.

Appends compact JSONL lessons under ~/.rigorpilot/ and distills them into
PERSONAL_RIGOR.md. Lessons are an advisory overlay: they never modify skill
files and never relax rigor gates. See references/continuous-learning-policy.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_KINDS = {"failure-fix", "user-correction", "preference", "generalization"}
# Best-effort blocklist: keyword shapes plus common bare-credential formats.
# This is a guardrail, not a guarantee — callers still must not pass secrets.
SECRET_RE = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|bearer\s+\S|-----BEGIN"
    r"|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}"
    r"|xox[a-z]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})",
    re.IGNORECASE,
)
MAX_FIELD_CHARS = 300
SUMMARY_LIMIT_PER_KIND = 12
# Staleness windows for prune, in days; doubled once a lesson proves useful
# (use_count >= 3), mirroring usage-driven curation in self-improving skills.
PRUNE_WINDOW_DAYS = {
    "failure-fix": 90,
    "user-correction": 180,
    "preference": 365,
    "generalization": 365,
}


def lessons_home() -> Path:
    root = os.environ.get("RIGORPILOT_HOME")
    return Path(root).expanduser() if root else Path.home() / ".rigorpilot"


def lessons_enabled() -> bool:
    return os.environ.get("RIGORPILOT_LESSONS", "1") != "0"


def lessons_path() -> Path:
    return lessons_home() / "lessons.jsonl"


def overlay_path() -> Path:
    return lessons_home() / "PERSONAL_RIGOR.md"


def repo_fingerprint(repo: Path) -> str:
    name = repo.name
    readme = repo / "README.md"
    digest = ""
    if readme.exists():
        digest = hashlib.sha1(readme.read_bytes()).hexdigest()[:10]
    return f"{name}@{digest}" if digest else name


def sanitize(text: str) -> Optional[str]:
    cleaned = " ".join(str(text or "").split())[:MAX_FIELD_CHARS]
    if not cleaned:
        return None
    if SECRET_RE.search(cleaned):
        return None
    return cleaned


def load_lessons(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    target = path or lessons_path()
    if not target.exists():
        return []
    lessons: List[Dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("summary"):
            lessons.append(item)
    return lessons


def record_lesson(
    *,
    kind: str,
    skill: str,
    summary: str,
    detail: str = "",
    fingerprint: str = "",
) -> Optional[Path]:
    """Append one lesson. Returns the store path, or None if skipped."""
    if not lessons_enabled():
        return None
    if kind not in VALID_KINDS:
        raise ValueError(f"Unknown lesson kind: {kind}")
    clean_summary = sanitize(summary)
    if clean_summary is None:
        return None
    clean_detail = sanitize(detail) or ""

    existing = load_lessons()
    for item in existing[-50:]:
        if item.get("kind") == kind and item.get("skill") == skill and item.get("summary") == clean_summary:
            return lessons_path()

    entry = {
        "ts": int(time.time()),
        "kind": kind,
        "skill": sanitize(skill) or "unknown",
        "summary": clean_summary,
        "detail": clean_detail,
        "fingerprint": sanitize(fingerprint) or "",
    }
    path = lessons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def rewrite_store(lessons: List[Dict[str, Any]]) -> Path:
    path = lessons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in lessons),
        encoding="utf-8",
    )
    return path


def touch_lesson(summary: str) -> bool:
    """Mark a lesson as used: bump use_count, refresh last_used."""
    lessons = load_lessons()
    hit = False
    now = int(time.time())
    for item in reversed(lessons):
        if item.get("summary") == summary:
            item["use_count"] = int(item.get("use_count", 0)) + 1
            item["last_used"] = now
            hit = True
            break
    if hit:
        rewrite_store(lessons)
    return hit


def prune(now: Optional[int] = None) -> int:
    """Drop stale lessons per kind-specific windows; useful lessons live longer."""
    lessons = load_lessons()
    current = now if now is not None else int(time.time())
    kept: List[Dict[str, Any]] = []
    for item in lessons:
        window_days = PRUNE_WINDOW_DAYS.get(str(item.get("kind")), 180)
        if int(item.get("use_count", 0)) >= 3:
            window_days *= 2
        reference = int(item.get("last_used") or item.get("ts") or current)
        if (current - reference) <= window_days * 86400:
            kept.append(item)
    removed = len(lessons) - len(kept)
    if removed:
        rewrite_store(kept)
    return removed


def summarize(path: Optional[Path] = None) -> Path:
    lessons = load_lessons(path)
    lines = [
        "# Personal Rigor Overlay",
        "",
        "Advisory lessons distilled from real runs. On any conflict with the",
        "RigorPilot references or SKILL.md contracts, the repository wins.",
        "",
    ]
    for kind in ("generalization", "preference", "user-correction", "failure-fix"):
        matching = [item for item in lessons if item.get("kind") == kind]
        if not matching:
            continue
        lines.append(f"## {kind}")
        lines.append("")
        seen: set = set()
        shown = 0
        for item in reversed(matching):
            key = item.get("summary")
            if key in seen:
                continue
            seen.add(key)
            suffix = f" `{item['fingerprint']}`" if item.get("fingerprint") else ""
            lines.append(f"- {item['summary']}{suffix}")
            shown += 1
            if shown >= SUMMARY_LIMIT_PER_KIND:
                break
        lines.append("")
    target = overlay_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Record or summarize RigorPilot lessons.")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="Append one lesson to the store.")
    rec.add_argument("--kind", required=True, choices=sorted(VALID_KINDS))
    rec.add_argument("--skill", required=True)
    rec.add_argument("--summary", required=True)
    rec.add_argument("--detail", default="")
    rec.add_argument("--repo", default="", help="Repo path used to derive a fingerprint.")

    sub.add_parser("summarize", help="Distill the store into PERSONAL_RIGOR.md.")
    sub.add_parser("list", help="Print stored lessons as JSON lines.")
    touch = sub.add_parser("touch", help="Mark a lesson as used (bumps use_count).")
    touch.add_argument("--summary", required=True)
    sub.add_parser("prune", help="Drop stale lessons per kind-specific windows.")

    args = parser.parse_args()
    if args.command == "touch":
        hit = touch_lesson(args.summary)
        print(json.dumps({"touched": hit}, ensure_ascii=False))
        return 0
    if args.command == "prune":
        removed = prune()
        print(json.dumps({"pruned": removed}, ensure_ascii=False))
        return 0
    if args.command == "record":
        fingerprint = repo_fingerprint(Path(args.repo).resolve()) if args.repo else ""
        path = record_lesson(
            kind=args.kind,
            skill=args.skill,
            summary=args.summary,
            detail=args.detail,
            fingerprint=fingerprint,
        )
        print(json.dumps({"recorded": path is not None, "store": str(path) if path else None}, ensure_ascii=False))
        return 0
    if args.command == "summarize":
        target = summarize()
        print(json.dumps({"overlay": str(target)}, ensure_ascii=False))
        return 0
    for item in load_lessons():
        print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
