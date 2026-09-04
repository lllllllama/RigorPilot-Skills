#!/usr/bin/env python3
"""Check shared operating-principle wiring and main skill concision."""

from __future__ import annotations

import json
from pathlib import Path


PUBLIC_PRINCIPLES_REF = "../../references/agent-operating-principles.md"
RESEARCH_RIGOR_REF = "../../references/research-rigor-principles.md"
DL_EXPERIMENT_REF = "../../references/deep-learning-experiment-principles.md"
SELF_CONTAINED_PRINCIPLES_REF = "references/agent-operating-principles.md"
SELF_CONTAINED_RESEARCH_RIGOR_REF = "references/research-rigor-principles.md"
SELF_CONTAINED_DL_EXPERIMENT_REF = "references/deep-learning-experiment-principles.md"
MAIN_SKILL_LIMITS = {
    "ai-research-reproduction": 130,
    "ai-research-explore": 125,
}


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    registry = json.loads((repo_root / "references" / "skill-registry.json").read_text(encoding="utf-8"))
    public_names = [item["name"] for item in registry["skills"] if item.get("tier") == "public"]

    failures: list[str] = []

    principles = (repo_root / "references" / "agent-operating-principles.md").read_text(encoding="utf-8")
    for phrase in [
        "Think before acting",
        "Keep the solution small",
        "Change only what is necessary",
        "Work toward verifiable goals",
        "Apply freedom at the right level",
    ]:
        if phrase not in principles:
            failures.append(f"agent-operating-principles.md missing `{phrase}`")
    for phrase in [
        "RigorPilot",
        "research-rigor-principles.md",
        "deep-learning-experiment-principles.md",
        "must not reduce strong model capability",
    ]:
        if phrase not in principles:
            failures.append(f"agent-operating-principles.md missing RigorPilot wiring phrase `{phrase}`")

    research_rigor = (repo_root / "references" / "research-rigor-principles.md").read_text(encoding="utf-8")
    for phrase in [
        "Do not chase scores blindly",
        "Do not claim novelty lightly",
        "Novelty and significance remain hypotheses",
        "Non-degradation Principle",
    ]:
        if phrase not in research_rigor:
            failures.append(f"research-rigor-principles.md missing `{phrase}`")

    dl_principles = (repo_root / "references" / "deep-learning-experiment-principles.md").read_text(encoding="utf-8")
    for phrase in [
        "Preserve baseline meaning",
        "Preserve evaluation protocol",
        "Record experiment context",
        "not a rigid checklist",
    ]:
        if phrase not in dl_principles:
            failures.append(f"deep-learning-experiment-principles.md missing `{phrase}`")

    for name in public_names:
        skill_text = (repo_root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        valid_refs = [PUBLIC_PRINCIPLES_REF]
        if name == "ai-research-reproduction":
            valid_refs.append(SELF_CONTAINED_PRINCIPLES_REF)
        if not any(ref in skill_text for ref in valid_refs):
            failures.append(f"{name} does not link to the shared operating principles")

    for name, limit in MAIN_SKILL_LIMITS.items():
        skill_text = (repo_root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        line_count = len(skill_text.splitlines())
        if line_count > limit:
            failures.append(f"{name} has {line_count} lines, expected <= {limit}")

    for name in ["ai-research-reproduction", "ai-research-explore"]:
        skill_text = (repo_root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        required_refs = [
            (RESEARCH_RIGOR_REF, SELF_CONTAINED_RESEARCH_RIGOR_REF),
            (DL_EXPERIMENT_REF, SELF_CONTAINED_DL_EXPERIMENT_REF),
        ]
        for shared_ref, local_ref in required_refs:
            accepted = [shared_ref, local_ref] if name == "ai-research-reproduction" else [shared_ref]
            if not any(ref in skill_text for ref in accepted):
                failures.append(f"{name} does not link to {shared_ref}")

    explore_text = (repo_root / "skills" / "ai-research-explore" / "SKILL.md").read_text(encoding="utf-8")
    for overfit_heading in ["## Variant Spec Hints", "## Ranking Semantics"]:
        if overfit_heading in explore_text:
            failures.append(f"ai-research-explore should not expose `{overfit_heading}` in the entrypoint")

    campaign_text = (
        repo_root / "skills" / "ai-research-explore" / "references" / "research-campaign-spec.md"
    ).read_text(encoding="utf-8")
    for phrase in ["advanced reference", "Durable Core Fields", "Optional Guidance Fields"]:
        if phrase not in campaign_text:
            failures.append(f"research-campaign-spec.md missing `{phrase}`")
    if "not fields the agent must invent on every run" not in campaign_text:
        failures.append("research_campaign optional fields are not clearly downgraded from required")

    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    for phrase in [
        "RigorPilot Skills",
        "Research-first Agent Skills for Deep Learning Experiments",
        "Suggested Research Evidence",
        "Lifecycle View",
        "agent-operating-principles.md",
    ]:
        if phrase not in readme:
            failures.append(f"README.md missing `{phrase}`")

    readme_zh = (repo_root / "README.zh-CN.md").read_text(encoding="utf-8")
    for phrase in ["RigorPilot Skills", "不只是更高分数", "建议的科研证据体系"]:
        if phrase not in readme_zh:
            failures.append(f"README.zh-CN.md missing `{phrase}`")

    print(f"ok: {not failures}")
    print(f"public_skills: {len(public_names)}")
    print(f"failures: {len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
