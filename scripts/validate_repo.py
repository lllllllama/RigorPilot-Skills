#!/usr/bin/env python3
"""Validate repository structure and lightweight skill metadata."""

from __future__ import annotations

import argparse
import json
import py_compile
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_SKILL_NAME_MAX = 64
AGENT_SKILL_DESCRIPTION_MAX = 1024
AGENT_SKILL_COMPATIBILITY_MAX = 500
PUBLIC_SKILL_LINE_MAX = 130
REGISTRY_PATH = Path("references/skill-registry.json")
ALLOWED_TIERS = {"public", "helper"}
ALLOWED_LANES = {"trusted", "explore", "helper"}
ROOT_REQUIRED_FILES = [
    "README.md",
    "README.zh-CN.md",
    "CONTRIBUTING.md",
    "docs/ACCEPTANCE_STATUS.md",
    ".editorconfig",
    ".claude/commands/ai-research-reproduction.md",
    ".claude/commands/ai-research-explore.md",
    ".claude/commands/analyze-project.md",
    ".claude/commands/safe-debug.md",
    "shared/scripts/write_explore_bundle.py",
    "shared/scripts/write_run_bundle.py",
    "shared/scripts/model_adapter.py",
    "shared/scripts/resource_monitor.py",
    "shared/scripts/runtime_runner.py",
    "shared/scripts/task_queue.py",
    "benchmarks/external_cases.json",
    "benchmarks/run_external_reproduction.py",
    "benchmarks/run_external_suite.py",
    "benchmarks/run_reviewed_selection_suite.py",
    "benchmarks/run_source_integrity_benchmark.py",
    "benchmarks/run_agent_handoff_benchmark.py",
    "benchmarks/run_job_micrograd_acceptance.py",
    "skills/ai-research-reproduction/scripts/repro_job.py",
    "skills/ai-research-reproduction/references/agent-job.md",
    "benchmarks/run_queue_smoke.py",
    "scripts/install_skills.py",
    "scripts/sync_reproduction_bundle.py",
    "scripts/validate_repo.py",
    "scripts/test_skill_registry.py",
    "references/agent-operating-principles.md",
    "references/research-rigor-principles.md",
    "references/deep-learning-experiment-principles.md",
    "references/skill-registry.json",
    "references/client-compatibility-policy.md",
    "references/trigger-boundary-policy.md",
    "references/routing-policy.md",
    "references/research-pitfall-checklist.md",
    "references/branch-and-commit-policy.md",
    "references/output-contract.md",
    "skills/ai-research-reproduction/_bundled/MANIFEST.json",
]
ROOT_REQUIRED_TESTS = [
    "scripts/test_bootstrap_env.py",
    "scripts/test_install_targets.py",
    "scripts/test_single_skill_install.py",
    "scripts/test_runtime_runner.py",
    "scripts/test_runtime_atomic_write.py",
    "scripts/test_reproduction_job.py",
    "scripts/test_reproduction_verifier_contract.py",
    "scripts/test_agent_handoff_benchmark.py",
    "scripts/test_runtime_recovery.py",
    "scripts/test_model_adapter.py",
    "scripts/test_task_queue.py",
    "scripts/test_queue_smoke_benchmark.py",
    "scripts/test_external_reproduction_benchmark.py",
    "scripts/test_trigger_boundaries.py",
    "scripts/test_readme_selection.py",
    "scripts/test_output_rendering.py",
    "scripts/test_train_output_rendering.py",
    "scripts/test_setup_planning.py",
    "scripts/test_training_lane_routing.py",
    "scripts/test_explore_output_rendering.py",
    "scripts/test_explore_variant_matrix.py",
    "scripts/test_research_explore_dry_run.py",
    "scripts/test_research_explore_variant_execution.py",
    "scripts/test_research_explore_nontraining_execution.py",
    "scripts/test_research_explore_campaign_flow.py",
    "scripts/test_research_explore_campaign_abandon.py",
    "scripts/test_research_explore_campaign_checkpoint.py",
    "scripts/test_atomic_idea_decomposition.py",
    "scripts/test_idea_seed_generation.py",
    "scripts/test_implementation_fidelity.py",
    "scripts/test_research_explore_contracts.py",
    "scripts/test_orchestrator_dry_run.py",
    "scripts/test_reproduction_benchmarks.py",
    "scripts/test_reproduction_command_selection.py",
    "scripts/test_skill_registry.py",
    "scripts/test_analysis_output_rendering.py",
    "scripts/test_safe_debug_output_rendering.py",
    "scripts/test_claude_command_wrappers.py",
    "scripts/test_operating_principles_structure.py",
    "tests/trigger_cases.json",
    "tests/readme_selection_cases.json",
]
IGNORED_PATH_PARTS = {"tmp", "artifacts", "repro_outputs", "benchmark_outputs", "_bundled", "__pycache__", ".git", ".claude", ".codex"}


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_front_matter(skill_md: Path) -> Dict[str, Any]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{skill_md} is missing YAML front matter.")

    try:
        _, front_matter, _ = text.split("---", 2)
    except ValueError as exc:
        raise ValueError(f"{skill_md} has malformed front matter.") from exc

    data: Dict[str, Any] = {}
    active_mapping: str | None = None
    for raw_line in front_matter.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        indentation = len(raw_line) - len(raw_line.lstrip())
        key, value = line.split(":", 1)
        key = key.strip()
        if indentation:
            if active_mapping == "metadata" and isinstance(data.get("metadata"), dict):
                data["metadata"][key] = _parse_scalar(value)
            continue
        if key == "metadata" and not value.strip():
            data[key] = {}
            active_mapping = key
            continue
        data[key] = _parse_scalar(value)
        active_mapping = None
    return data


def validate_openai_yaml(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8")
    required_keys = ["display_name:", "short_description:", "default_prompt:"]
    return [f"Missing `{key[:-1]}` in {path}" for key in required_keys if key not in text]


def validate_agent_skill_frontmatter(skill_dir: Path, front_matter: Dict[str, Any], public: bool) -> List[str]:
    """Validate the Agent Skills metadata constraints used by this repository."""
    errors: List[str] = []
    skill_md = skill_dir / "SKILL.md"
    declared_name = front_matter.get("name", "")
    description = front_matter.get("description", "")

    if not declared_name:
        errors.append(f"Missing name in {skill_md}")
    else:
        if len(declared_name) > AGENT_SKILL_NAME_MAX:
            errors.append(
                f"Skill name in {skill_md} exceeds {AGENT_SKILL_NAME_MAX} characters"
            )
        if not SKILL_NAME_RE.fullmatch(declared_name):
            errors.append(
                f"Invalid Agent Skills name `{declared_name}` in {skill_md}; "
                "use lowercase letters/digits separated by single hyphens"
            )
        if declared_name != skill_dir.name:
            errors.append(
                f"Front matter name mismatch for {skill_md}: `{declared_name}` != `{skill_dir.name}`"
            )

    if not description:
        errors.append(f"Missing description in {skill_md}")
    elif len(description) > AGENT_SKILL_DESCRIPTION_MAX:
        errors.append(
            f"Description in {skill_md} exceeds {AGENT_SKILL_DESCRIPTION_MAX} characters"
        )

    compatibility = front_matter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility:
            errors.append(f"Empty compatibility field in {skill_md}")
        elif len(compatibility) > AGENT_SKILL_COMPATIBILITY_MAX:
            errors.append(
                f"Compatibility in {skill_md} exceeds {AGENT_SKILL_COMPATIBILITY_MAX} characters"
            )

    metadata = front_matter.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            errors.append(f"Metadata in {skill_md} must be a string-to-string mapping")
        elif any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
            errors.append(f"Metadata in {skill_md} must be a string-to-string mapping")

    allowed_tools = front_matter.get("allowed-tools")
    if allowed_tools is not None and (not isinstance(allowed_tools, str) or not allowed_tools.strip()):
        errors.append(f"Allowed-tools in {skill_md} must be a non-empty space-separated string")

    if public:
        line_count = len(skill_md.read_text(encoding="utf-8").splitlines())
        if line_count > PUBLIC_SKILL_LINE_MAX:
            errors.append(
                f"Public {skill_md} has {line_count} lines; repository convention allows "
                f"at most {PUBLIC_SKILL_LINE_MAX}"
            )
    return errors


def validate_python_files(root: Path) -> List[str]:
    errors: List[str] = []
    for path in root.rglob("*.py"):
        if any(part in IGNORED_PATH_PARTS for part in path.parts):
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"Python compile failed for {path}: {exc.msg}")
    return errors


def load_skill_registry(root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    registry_path = root / REGISTRY_PATH
    if not registry_path.exists():
        return [], [f"Missing registry file: {REGISTRY_PATH.as_posix()}"]

    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"Invalid JSON in {registry_path}: {exc}"]

    if payload.get("schema_version") != "1.0":
        errors.append(f"Unsupported registry schema_version in {registry_path}")

    skills = payload.get("skills")
    if not isinstance(skills, list) or not skills:
        errors.append(f"Registry {registry_path} must contain a non-empty `skills` list")
        return [], errors

    names = set()
    for item in skills:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            errors.append("Registry entry missing string `name`")
            continue
        if name in names:
            errors.append(f"Duplicate registry skill name: {name}")
        names.add(name)

        display_name = item.get("display_name")
        if not isinstance(display_name, str) or not display_name:
            errors.append(f"{name} missing string display_name")

        rigor_slug = item.get("rigor_slug")
        if rigor_slug is not None and (not isinstance(rigor_slug, str) or not rigor_slug.startswith("rigor-")):
            errors.append(f"{name} has invalid rigor_slug `{rigor_slug}`")

        rigor_modes = item.get("rigor_modes")
        if rigor_modes is not None:
            if not isinstance(rigor_modes, list) or not rigor_modes:
                errors.append(f"{name} has invalid rigor_modes")
            elif any(not isinstance(mode, str) or not mode.startswith("rigor-") for mode in rigor_modes):
                errors.append(f"{name} has invalid rigor_modes entries")
            elif rigor_slug and rigor_slug not in rigor_modes:
                errors.append(f"{name} rigor_modes must include rigor_slug")

        if item.get("tier") not in ALLOWED_TIERS:
            errors.append(f"{name} has invalid tier `{item.get('tier')}`")
        if item.get("lane") not in ALLOWED_LANES:
            errors.append(f"{name} has invalid lane `{item.get('lane')}`")
        if item.get("tier") == "public" and not rigor_slug:
            errors.append(f"{name} public skill missing rigor_slug")

        compat = item.get("compat")
        if not isinstance(compat, dict):
            errors.append(f"{name} missing compat object")
        else:
            if compat.get("preserve_name") is not True:
                errors.append(f"{name} must set compat.preserve_name true")
            aliases = compat.get("aliases", [])
            if not isinstance(aliases, list):
                errors.append(f"{name} has invalid compat.aliases")
            elif any(str(alias).startswith("rigor-") for alias in aliases):
                errors.append(f"{name} must not advertise rigor-* as install aliases in compat.aliases")

        if not isinstance(item.get("can_call", []), list):
            errors.append(f"{name} has invalid can_call list")
        if not isinstance(item.get("required_files", []), list):
            errors.append(f"{name} has invalid required_files list")

        output_mode = item.get("output_mode")
        if not isinstance(output_mode, dict):
            errors.append(f"{name} missing output_mode object")
        else:
            if "kind" not in output_mode:
                errors.append(f"{name} missing output_mode.kind")
            if not isinstance(output_mode.get("artifacts", []), list):
                errors.append(f"{name} has invalid output_mode.artifacts")

    for item in skills:
        name = item.get("name")
        for callee in item.get("can_call", []):
            if callee not in names:
                errors.append(f"{name} references unknown callee `{callee}`")

    return skills, errors


def validate_repo(root: Path) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    for rel in ROOT_REQUIRED_FILES:
        if not (root / rel).exists():
            errors.append(f"Missing repository file: {rel}")

    for rel in ROOT_REQUIRED_TESTS:
        if not (root / rel).exists():
            errors.append(f"Missing repository file: {rel}")

    skills_root = root / "skills"
    if not skills_root.exists():
        errors.append("Missing `skills/` directory.")
        return errors, warnings

    registry_skills, registry_errors = load_skill_registry(root)
    errors.extend(registry_errors)
    registry_by_name = {item["name"]: item for item in registry_skills if "name" in item}

    skill_dirs = sorted(
        path for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    )
    discovered_names = {path.name for path in skill_dirs}

    for required_name in registry_by_name:
        if required_name not in discovered_names:
            errors.append(f"Missing required skill directory: skills/{required_name}")

    for discovered_name in discovered_names:
        if discovered_name not in registry_by_name:
            errors.append(f"Unregistered skill directory: skills/{discovered_name}")

    for skill_dir in skill_dirs:
        if not SKILL_NAME_RE.match(skill_dir.name):
            errors.append(f"Invalid skill directory name: {skill_dir.name}")

        try:
            front_matter = parse_front_matter(skill_dir / "SKILL.md")
        except ValueError as exc:
            errors.append(str(exc))
            continue

        errors.extend(
            validate_agent_skill_frontmatter(
                skill_dir,
                front_matter,
                public=registry_by_name.get(skill_dir.name, {}).get("tier") == "public",
            )
        )

        required_files = registry_by_name.get(skill_dir.name, {}).get("required_files", [])
        for rel in required_files:
            if not (skill_dir / rel).exists():
                errors.append(f"Missing required file for {skill_dir.name}: {rel}")

        agent_yaml = skill_dir / "agents" / "openai.yaml"
        if agent_yaml.exists():
            errors.extend(validate_openai_yaml(agent_yaml))

    errors.extend(validate_python_files(root))

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository structure and skill metadata.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    errors, warnings = validate_repo(root)
    payload = {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"ok: {payload['ok']}")
        print(f"errors: {payload['error_count']}")
        print(f"warnings: {payload['warning_count']}")
        for item in errors:
            print(f"ERROR: {item}")
        for item in warnings:
            print(f"WARN: {item}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

