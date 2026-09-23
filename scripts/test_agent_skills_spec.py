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
        for existing in (ROOT / "skills").glob("*/SKILL.md"):
            assert not validate_agent_skill_frontmatter(existing.parent, parse_front_matter(existing), True if existing.parent.name == "ai-research-reproduction" else False), existing

        def metadata_case(name: str, body: str) -> tuple[Path, dict]:
            skill = temp_root / name
            skill.mkdir()
            path = skill / "SKILL.md"
            path.write_text(f"---\n{body}\n---\n# Test\n", encoding="utf-8")
            return skill, parse_front_matter(path)

        for quoted in ("'Single: quote'", '"Double: quote"'):
            _, parsed = metadata_case("quote-" + str(len(list(temp_root.glob("quote-*")))), f"name: quoted\ndescription: {quoted}")
            assert parsed["description"] == ("Single: quote" if quoted.startswith("'") else "Double: quote")
        _, folded = metadata_case("folded", "name: folded\ndescription: >\n  First line\n  second: line")
        assert folded["description"] == "First line second: line\n", folded
        _, literal = metadata_case("literal", "name: literal\ndescription: |\n  First line\n  second: line")
        assert literal["description"] == "First line\nsecond: line\n", literal
        _, unicode_case = metadata_case("unicode-case", "name: unicode-case\ndescription: '中文: 合法' # comment")
        assert unicode_case["description"] == "中文: 合法"

        for name, body, expected in (
            ("null-name", "name:\ndescription: okay", "name"),
            ("numeric-description", "name: numeric-description\ndescription: 123", "description"),
            ("null-compatibility", "name: null-compatibility\ndescription: okay\ncompatibility:", "compatibility"),
            ("numeric-metadata", "name: numeric-metadata\ndescription: okay\nmetadata:\n  version: 123", "Metadata"),
            ("numeric-metadata-key", "name: numeric-metadata-key\ndescription: okay\nmetadata:\n  123: version", "Metadata"),
            ("list-tools", "name: list-tools\ndescription: okay\nallowed-tools: [Read, Bash]", "Allowed-tools"),
        ):
            skill, parsed = metadata_case(name, body)
            assert any(expected in error for error in validate_agent_skill_frontmatter(skill, parsed, False)), name

        for name, body, expected in (
            ("duplicate", "name: duplicate\nname: repeated\ndescription: okay", "duplicate"),
            ("non-mapping", "- name: non-mapping\n- description: okay", "mapping"),
            ("bad-yaml", "name: [unclosed", "Invalid YAML"),
            ("no-closing", "name: no-closing\ndescription: okay", "malformed"),
        ):
            path = temp_root / name / "SKILL.md"
            path.parent.mkdir()
            path.write_text(f"---\n{body}\n" + ("" if name == "no-closing" else "---\n"), encoding="utf-8")
            try:
                parse_front_matter(path)
            except ValueError as exc:
                assert expected in str(exc), (name, exc)
            else:
                raise AssertionError(f"{name} was accepted")

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

        mismatched = write_skill(temp_root, "directory-name")
        (mismatched / "SKILL.md").write_text("---\nname: declared-name\ndescription: okay\n---\n", encoding="utf-8")
        mismatch_errors = validate_agent_skill_frontmatter(mismatched, parse_front_matter(mismatched / "SKILL.md"), False)
        if not any("name mismatch" in item for item in mismatch_errors):
            raise AssertionError("directory/name mismatch was not rejected")

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
        print("checks: current skills and metadata edge cases")
        print("failures: 0")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
