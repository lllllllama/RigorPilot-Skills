#!/usr/bin/env python3
"""Regression checks for the Agent Skills metadata rules enforced locally."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_repo import parse_front_matter, validate_agent_skill_frontmatter


def write_skill(root: Path, name: str, description: str = "Use when testing metadata.", **extra: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    fields = ["---", f"name: {name}", f"description: {description}"]
    fields.extend(f"{key}: {value}" for key, value in extra.items())
    fields.extend(["---", "", f"# {name}", ""])
    (skill / "SKILL.md").write_text("\n".join(fields), encoding="utf-8")
    return skill


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rigorpilot-agent-skills-spec-"))
    try:
        valid = write_skill(
            temp_root,
            "valid-skill",
            compatibility="Requires Python 3.11+.",
            **{"allowed-tools": "Read Bash(git:*)"},
        )
        valid_md = valid / "SKILL.md"
        valid_text = valid_md.read_text(encoding="utf-8").replace(
            "---\n\n# valid-skill",
            "metadata:\n  author: rigorpilot\n  version: '1.0'\n---\n\n# valid-skill",
        )
        valid_md.write_text(valid_text, encoding="utf-8")
        valid_errors = validate_agent_skill_frontmatter(valid, parse_front_matter(valid / "SKILL.md"), True)
        if valid_errors:
            raise AssertionError(f"valid Agent Skill metadata was rejected: {valid_errors}")

        bad_name = write_skill(temp_root, "bad--skill")
        name_errors = validate_agent_skill_frontmatter(bad_name, parse_front_matter(bad_name / "SKILL.md"), False)
        if not any("Invalid Agent Skills name" in item for item in name_errors):
            raise AssertionError("consecutive hyphens were not rejected")

        long_description = write_skill(temp_root, "long-description", "x" * 1025)
        description_errors = validate_agent_skill_frontmatter(
            long_description, parse_front_matter(long_description / "SKILL.md"), False
        )
        if not any("exceeds 1024" in item for item in description_errors):
            raise AssertionError("overlong Agent Skills description was not rejected")

        long_public = write_skill(temp_root, "long-public")
        skill_md = long_public / "SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + ("extra\n" * 130), encoding="utf-8")
        public_errors = validate_agent_skill_frontmatter(
            long_public, parse_front_matter(skill_md), True
        )
        if not any("repository convention" in item for item in public_errors):
            raise AssertionError("public SKILL.md line limit was not enforced")

        invalid_metadata = write_skill(temp_root, "invalid-metadata", metadata="not-a-map")
        metadata_errors = validate_agent_skill_frontmatter(
            invalid_metadata, parse_front_matter(invalid_metadata / "SKILL.md"), False
        )
        if not any("string-to-string mapping" in item for item in metadata_errors):
            raise AssertionError("non-mapping Agent Skills metadata was not rejected")

        invalid_tools = write_skill(temp_root, "invalid-tools", **{"allowed-tools": ""})
        tools_errors = validate_agent_skill_frontmatter(
            invalid_tools, parse_front_matter(invalid_tools / "SKILL.md"), False
        )
        if not any("space-separated string" in item for item in tools_errors):
            raise AssertionError("empty Agent Skills allowed-tools was not rejected")

        print("ok: True")
        print("checks: 6")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
