#!/usr/bin/env python3
"""Shared writer for trusted verify and trusted training output bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def load_context(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bullets(items: Iterable[str]) -> str:
    values = [item for item in items if item]
    if not values:
        return "- None."
    return "\n".join(f"- {item}" for item in values)


def command_block(items: Iterable[Any]) -> str:
    values = [item for item in items if item]
    if not values:
        return "# No command recorded."

    rendered: List[str] = []
    for item in values:
        if isinstance(item, dict):
            rendered.append(f"# [{item.get('label', 'inferred')}]")
            platforms = item.get("platforms")
            if platforms:
                rendered.append(f"# platforms: {', '.join(str(platform) for platform in platforms)}")
            rendered.append(str(item.get("command", "")))
        else:
            rendered.append(str(item))
    return "\n".join(rendered)


def render_commit(item: Dict[str, Any]) -> List[str]:
    commit = item.get("commit", "unknown")
    summary = item.get("summary", "No summary provided.")
    files = item.get("files", [])
    why = item.get("why", [])
    verification = item.get("verification", [])
    risk = item.get("risk", "unknown")
    fidelity = item.get("readme_fidelity_effect")

    lines = [f"### `{commit}` {summary}", ""]
    lines.append(f"- Risk level: `{risk}`")
    lines.append("- Changed files:")
    if files:
        lines.extend(f"  - `{path}`" for path in files)
    else:
        lines.append("  - None.")
    lines.append("- Why it changed:")
    if why:
        lines.extend(f"  - {entry}" for entry in why)
    else:
        lines.append("  - None.")
    lines.append("- How it was verified:")
    if verification:
        lines.extend(f"  - {entry}" for entry in verification)
    else:
        lines.append("  - None.")
    if fidelity:
        lines.append(f"- README fidelity effect: `{fidelity}`")
    lines.append("")
    return lines


def write_repro_summary(output_dir: Path, context: Dict[str, Any]) -> None:
    lines = [
        "# Reproduction Summary",
        "",
        f"- Target repo: `{context['target_repo']}`",
        f"- Selected goal: `{context['selected_goal']}`",
        f"- Goal priority: `{context['goal_priority']}`",
        f"- Overall status: `{context['status']}`",
        f"- README-first: `{context['readme_first']}`",
        f"- Main documented command: `{context['documented_command']}`",
        f"- Command source: `{context.get('documented_command_source', 'none')}`",
        f"- Command section: `{context.get('documented_command_section') or 'none'}`",
        f"- Patches applied: `{context.get('patches_applied', False)}`",
    ]
    if context.get("patches_applied"):
        lines.extend(
            [
                f"- Patch branch: `{context.get('patch_branch', '')}`",
                f"- README fidelity impact: `{context.get('readme_fidelity', 'preserved')}`",
                f"- Highest patch risk: `{context.get('highest_patch_risk', 'low')}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Result",
            "",
            context["result_summary"],
            "",
            "## Main blocker",
            "",
            context["main_blocker"],
            "",
            "## Next action",
            "",
            context["next_action"],
            "",
        ]
    )
    (output_dir / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def write_repro_commands(output_dir: Path, context: Dict[str, Any]) -> None:
    lines = [
        "# Commands",
        "",
        "## Setup",
        "",
        "```bash",
        command_block(context.get("setup_commands", [])),
        "```",
        "",
        "## Assets",
        "",
        "```bash",
        command_block(context.get("asset_commands", [])),
        "```",
        "",
        "## Main run",
        "",
        "```bash",
        command_block(context.get("run_commands", [])),
        "```",
        "",
        "## Verification",
        "",
        "```bash",
        command_block(context.get("verification_commands", [])),
        "```",
        "",
        "## Notes",
        "",
        bullets(context.get("command_notes", [])),
        "",
    ]
    (output_dir / "COMMANDS.md").write_text("\n".join(lines), encoding="utf-8")


def write_repro_log(output_dir: Path, context: Dict[str, Any]) -> None:
    lines = [
        "# Reproduction Log",
        "",
        "## Context",
        "",
        f"- Target repo: `{context['target_repo']}`",
        f"- Selected goal: `{context['selected_goal']}`",
        f"- User language: `{context['user_language']}`",
        f"- Evidence level: `{context.get('evidence_level', 'mixed')}`",
        "",
        "## Timeline",
        "",
        bullets(context.get("timeline", [])),
        "",
        "## Assumptions",
        "",
        bullets(context.get("assumptions", [])),
        "",
        "## Unverified inferences",
        "",
        bullets(context.get("unverified_inferences", [])),
        "",
        "## Evidence",
        "",
        bullets(context.get("evidence", [])),
        "",
        "## Protocol deviations",
        "",
        bullets(context.get("protocol_deviations", [])),
        "",
        "## Command provenance",
        "",
        bullets(
            [
                f"Main documented command: `{context.get('documented_command', 'None extracted')}`",
                f"Source: `{context.get('documented_command_source', 'none')}`",
                f"Section: `{context.get('documented_command_section') or 'none'}`",
                f"Kind: `{context.get('documented_command_kind', 'none')}`",
            ]
        ),
        "",
        "## Human review checkpoints",
        "",
        bullets(context.get("human_decisions_required", [])),
        "",
        "## Failures or blockers",
        "",
        bullets(context.get("blockers", [])),
        "",
        "## Next safe action",
        "",
        context.get("next_safe_action", "None."),
        "",
    ]
    (output_dir / "LOG.md").write_text("\n".join(lines), encoding="utf-8")


def write_repro_status(output_dir: Path, context: Dict[str, Any]) -> None:
    payload = {
        "schema_version": context.get("schema_version", "1.0"),
        "generated_at": context.get("generated_at"),
        "user_language": context.get("user_language", "en"),
        "target_repo": context.get("target_repo"),
        "readme_first": context.get("readme_first", True),
        "selected_goal": context.get("selected_goal", "unknown"),
        "goal_priority": context.get("goal_priority", "other"),
        "status": context.get("status", "not_run"),
        "documented_command_status": context.get("documented_command_status", "not_run"),
        "documented_command": context.get("documented_command", "None extracted"),
        "documented_command_kind": context.get("documented_command_kind", "none"),
        "documented_command_source": context.get("documented_command_source", "none"),
        "documented_command_section": context.get("documented_command_section"),
        "patches_applied": context.get("patches_applied", False),
        "patch_branch": context.get("patch_branch") if context.get("patches_applied") else None,
        "readme_fidelity": context.get("readme_fidelity") if context.get("patches_applied") else None,
        "highest_patch_risk": context.get("highest_patch_risk") if context.get("patches_applied") else None,
        "evidence_level": context.get("evidence_level", "mixed"),
        "assumptions": context.get("assumptions", []),
        "unverified_inferences": context.get("unverified_inferences", []),
        "protocol_deviations": context.get("protocol_deviations", []),
        "human_decisions_required": context.get("human_decisions_required", []),
        "next_safe_action": context.get("next_safe_action"),
        "artifact_provenance": context.get("artifact_provenance", []),
        "full_training_command": context.get("full_training_command"),
        "training_duration_hint": context.get("training_duration_hint"),
        "verified_commit_count": len(context.get("verified_commits", [])),
        "readme_section_coverage": context.get("readme_section_coverage", {}),
        "outputs": {
            "summary": "repro_outputs/SUMMARY.md",
            "commands": "repro_outputs/COMMANDS.md",
            "log": "repro_outputs/LOG.md",
            "scientific_changelog": "repro_outputs/SCIENTIFIC_CHANGELOG.md",
            "comparability_report": "repro_outputs/COMPARABILITY_REPORT.md",
            "status": "repro_outputs/status.json",
            "annotated_readme": "repro_outputs/ANNOTATED_README.md" if context.get("annotated_readme") else None,
            "patches": "repro_outputs/PATCHES.md" if context.get("patches_applied") else None,
        },
        "notes": context.get("notes", []),
    }
    (output_dir / "status.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_repro_patches(output_dir: Path, context: Dict[str, Any]) -> None:
    if not context.get("patches_applied"):
        return

    lines = [
        "# Patch Record",
        "",
        "## Patch overview",
        "",
        f"- Patch branch: `{context.get('patch_branch', '')}`",
        f"- README fidelity impact: `{context.get('readme_fidelity', 'preserved')}`",
        f"- Highest patch risk: `{context.get('highest_patch_risk', 'low')}`",
        "",
        "## Verified commits",
        "",
    ]

    commits = context.get("verified_commits", [])
    if not commits:
        lines.append("- None.")
        lines.append("")
    else:
        for item in commits:
            lines.extend(render_commit(item))

    lines.extend(
        [
            "## Validation summary",
            "",
            context.get("validation_summary", "No validation summary recorded."),
            "",
            "## Notes",
            "",
            bullets(context.get("patch_notes", [])),
            "",
        ]
    )
    (output_dir / "PATCHES.md").write_text("\n".join(lines), encoding="utf-8")


def meaningful_deviations(context: Dict[str, Any]) -> List[str]:
    deviations = []
    for item in context.get("protocol_deviations", []):
        text = str(item)
        lowered = text.lower().strip()
        if lowered == "none" or "no protocol deviation" in lowered:
            continue
        deviations.append(text)
    return deviations


def comparability_status(context: Dict[str, Any], mode: str) -> str:
    explicit = context.get("comparability_status")
    if explicit:
        return str(explicit)
    if meaningful_deviations(context):
        return "needs-review"
    if context.get("patches_applied") and context.get("readme_fidelity") not in {None, "", "preserved"}:
        return "qualified"
    if mode == "train" and context.get("run_mode") not in {None, "", "startup_verification"}:
        return "qualified"
    return "preserved"


def write_scientific_changelog(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    lines = [
        "# Scientific Changelog",
        "",
        f"- Mode: `{mode}`",
        f"- Target repo: `{context.get('target_repo', 'unknown')}`",
        f"- Selected goal: `{context.get('selected_goal', 'unknown')}`",
        f"- Overall status: `{context.get('status', 'unknown')}`",
        f"- Comparability status: `{comparability_status(context, mode)}`",
        "",
        "## Recorded Changes",
        "",
    ]
    commits = context.get("verified_commits", [])
    if commits:
        for item in commits:
            lines.extend(render_commit(item))
            lines.append(f"- Scientific meaning effect: `{item.get('scientific_meaning_effect', 'not-assessed')}`")
            lines.append(f"- Comparability effect: `{item.get('comparability_effect', item.get('readme_fidelity_effect', 'not-assessed'))}`")
            lines.append("")
    elif mode == "train":
        lines.extend(
            [
                "- Training execution was recorded as evidence; no repository file change was recorded by this writer.",
                f"- Run mode: `{context.get('run_mode', 'startup_verification')}`",
                f"- Dataset: `{context.get('dataset', 'unknown')}`",
                f"- Checkpoint source: `{context.get('checkpoint_source', 'none')}`",
                "",
            ]
        )
    else:
        lines.extend(["- No repository file change was recorded by this writer.", ""])

    lines.extend(
        [
            "## Why The Changes Matter",
            "",
            bullets(context.get("patch_notes", []) or context.get("command_notes", []) or context.get("notes", [])),
            "",
            "## Scientific Meaning",
            "",
            bullets(
                context.get("scientific_meaning_notes", [])
                or [
                    "Engineering fixes and execution records are not method contributions unless separate evidence supports that claim."
                ]
            ),
            "",
            "## Evidence",
            "",
            bullets(context.get("evidence", [])),
            "",
        ]
    )
    (output_dir / "SCIENTIFIC_CHANGELOG.md").write_text("\n".join(lines), encoding="utf-8")


def write_comparability_report(output_dir: Path, context: Dict[str, Any], mode: str) -> None:
    deviations = meaningful_deviations(context)
    lines = [
        "# Comparability Report",
        "",
        f"- Mode: `{mode}`",
        f"- Target repo: `{context.get('target_repo', 'unknown')}`",
        f"- Comparability status: `{comparability_status(context, mode)}`",
        f"- README-first: `{context.get('readme_first', mode == 'repro')}`",
        f"- Documented command: `{context.get('documented_command', 'None extracted')}`",
        f"- Command source: `{context.get('documented_command_source', 'none')}`",
        f"- Command section: `{context.get('documented_command_section') or 'none'}`",
        "",
        "## Comparison Anchors",
        "",
        bullets(
            context.get("comparison_anchors", [])
            or [
                "README documented command",
                "repository files used to interpret the README",
                "paper or baseline references only when explicitly resolved",
            ]
        ),
        "",
        "## Protocol Deviations",
        "",
        bullets(deviations),
        "",
        "## Patch And Execution Effects",
        "",
        bullets(
            [
                f"patches_applied={context.get('patches_applied', False)}",
                f"readme_fidelity={context.get('readme_fidelity', 'preserved')}",
                f"highest_patch_risk={context.get('highest_patch_risk', 'none')}",
                f"run_mode={context.get('run_mode', 'not-applicable')}",
                f"dataset={context.get('dataset', 'not-recorded')}",
                f"checkpoint_source={context.get('checkpoint_source', 'not-recorded')}",
            ]
        ),
        "",
        "## Assumptions And Gaps",
        "",
        bullets(context.get("assumptions", [])),
        "",
        "## Interpretation",
        "",
        context.get(
            "comparability_interpretation",
            "Treat results as directly comparable only when the documented command, data, preprocessing, checkpoint, metric, and baseline conditions remain aligned.",
        ),
        "",
    ]
    (output_dir / "COMPARABILITY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_train_summary(output_dir: Path, context: Dict[str, Any]) -> None:
    steps = f"{context.get('completed_steps', 0)} / {context.get('max_steps', 0)}"
    best_metric = context.get("best_metric")
    lines = [
        "# Training Run Summary",
        "",
        f"- Target repo: `{context['target_repo']}`",
        f"- Selected goal: `{context.get('selected_goal', 'training')}`",
        f"- Overall status: `{context['status']}`",
        f"- Lane: `{context.get('lane', 'trusted')}`",
        f"- Run mode: `{context.get('run_mode', 'startup_verification')}`",
        f"- Main documented command: `{context['documented_command']}`",
        f"- Dataset: `{context.get('dataset', 'unknown')}`",
        f"- Resume from: `{context.get('resume_from') or 'none'}`",
        f"- Checkpoint source: `{context.get('checkpoint_source', 'none')}`",
        f"- Completed steps: `{steps}`",
        f"- Last epoch: `{context.get('last_epoch') if context.get('last_epoch') is not None else 'none'}`",
        f"- Last step: `{context.get('last_step') if context.get('last_step') is not None else 'none'}`",
        f"- Best metric: `{json.dumps(best_metric, ensure_ascii=False) if best_metric is not None else 'none'}`",
        f"- Best checkpoint: `{context.get('best_checkpoint') or 'none'}`",
        f"- Stop reason: `{context.get('stop_reason', 'none')}`",
        f"- Monitoring scope: `{context.get('monitoring_scope', 'unknown')}`",
        "",
        "## Result",
        "",
        context["result_summary"],
        "",
        "## Main blocker",
        "",
        context["main_blocker"],
        "",
        "## Next action",
        "",
        context["next_action"],
        "",
    ]
    (output_dir / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def write_train_commands(output_dir: Path, context: Dict[str, Any]) -> None:
    lines = [
        "# Training Commands",
        "",
        "## Setup",
        "",
        "```bash",
        command_block(context.get("setup_commands", [])),
        "```",
        "",
        "## Assets",
        "",
        "```bash",
        command_block(context.get("asset_commands", [])),
        "```",
        "",
        "## Training run",
        "",
        "```bash",
        command_block(context.get("run_commands", [])),
        "```",
        "",
        "## Verification",
        "",
        "```bash",
        command_block(context.get("verification_commands", [])),
        "```",
        "",
        "## Notes",
        "",
        bullets(context.get("command_notes", [])),
        "",
    ]
    (output_dir / "COMMANDS.md").write_text("\n".join(lines), encoding="utf-8")


def write_train_log(output_dir: Path, context: Dict[str, Any]) -> None:
    lines = [
        "# Training Log",
        "",
        "## Context",
        "",
        f"- Target repo: `{context['target_repo']}`",
        f"- Selected goal: `{context.get('selected_goal', 'training')}`",
        f"- Lane: `{context.get('lane', 'trusted')}`",
        f"- Run mode: `{context.get('run_mode', 'startup_verification')}`",
        f"- Dataset: `{context.get('dataset', 'unknown')}`",
        f"- Resume from: `{context.get('resume_from') or 'none'}`",
        f"- Checkpoint source: `{context.get('checkpoint_source', 'none')}`",
        f"- Evidence level: `{context.get('evidence_level', 'mixed')}`",
        "",
        "## Timeline",
        "",
        bullets(context.get("timeline", [])),
        "",
        "## Assumptions",
        "",
        bullets(context.get("assumptions", [])),
        "",
        "## Evidence",
        "",
        bullets(context.get("evidence", [])),
        "",
        "## Observed metrics",
        "",
        bullets(
            [
                f"{name}: {value}"
                for name, value in (context.get("observed_metrics") or {}).items()
            ]
        ),
        "",
        "## Failures or blockers",
        "",
        bullets(context.get("blockers", [])),
        "",
        "## Human review checkpoints",
        "",
        bullets(context.get("human_decisions_required", [])),
        "",
        "## Next safe action",
        "",
        context.get("next_safe_action", "None."),
        "",
    ]
    (output_dir / "LOG.md").write_text("\n".join(lines), encoding="utf-8")


def write_train_status(output_dir: Path, context: Dict[str, Any]) -> None:
    payload = {
        "schema_version": context.get("schema_version", "1.0"),
        "generated_at": context.get("generated_at"),
        "user_language": context.get("user_language", "en"),
        "target_repo": context.get("target_repo"),
        "selected_goal": context.get("selected_goal", "training"),
        "status": context.get("status", "not_run"),
        "documented_command_status": context.get("documented_command_status", "not_run"),
        "documented_command": context.get("documented_command", "None extracted"),
        "documented_command_kind": context.get("documented_command_kind", "train"),
        "documented_command_source": context.get("documented_command_source", "none"),
        "documented_command_section": context.get("documented_command_section"),
        "lane": context.get("lane", "trusted"),
        "run_mode": context.get("run_mode", "startup_verification"),
        "full_training_authorized": context.get("full_training_authorized", False),
        "requires_full_training_confirmation": context.get("requires_full_training_confirmation", False),
        "resume_from": context.get("resume_from"),
        "dataset": context.get("dataset"),
        "checkpoint_source": context.get("checkpoint_source"),
        "full_training_command": context.get("full_training_command"),
        "training_duration_hint": context.get("training_duration_hint"),
        "max_steps": context.get("max_steps"),
        "completed_steps": context.get("completed_steps"),
        "last_epoch": context.get("last_epoch"),
        "last_step": context.get("last_step"),
        "best_metric": context.get("best_metric"),
        "best_checkpoint": context.get("best_checkpoint"),
        "stop_reason": context.get("stop_reason"),
        "observed_metrics": context.get("observed_metrics", {}),
        "checkpoint_candidates": context.get("checkpoint_candidates", []),
        "monitoring_scope": context.get("monitoring_scope"),
        "evidence_level": context.get("evidence_level", "mixed"),
        "human_decisions_required": context.get("human_decisions_required", []),
        "next_safe_action": context.get("next_safe_action"),
        "assumptions": context.get("assumptions", []),
        "artifact_provenance": context.get("artifact_provenance", []),
        "outputs": {
            "summary": "train_outputs/SUMMARY.md",
            "commands": "train_outputs/COMMANDS.md",
            "log": "train_outputs/LOG.md",
            "scientific_changelog": "train_outputs/SCIENTIFIC_CHANGELOG.md",
            "comparability_report": "train_outputs/COMPARABILITY_REPORT.md",
            "status": "train_outputs/status.json",
        },
        "notes": context.get("notes", []),
    }
    (output_dir / "status.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_bundle(mode: str, output_dir: Path, context: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if mode == "repro":
        write_repro_summary(output_dir, context)
        write_repro_commands(output_dir, context)
        write_repro_log(output_dir, context)
        write_scientific_changelog(output_dir, context, mode)
        write_comparability_report(output_dir, context, mode)
        write_repro_status(output_dir, context)
        write_repro_patches(output_dir, context)
        return

    if mode == "train":
        write_train_summary(output_dir, context)
        write_train_commands(output_dir, context)
        write_train_log(output_dir, context)
        write_scientific_changelog(output_dir, context, mode)
        write_comparability_report(output_dir, context, mode)
        write_train_status(output_dir, context)
        return

    raise ValueError(f"Unsupported mode: {mode}")


def main(default_mode: str = "repro", default_output_dir: Optional[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Write standardized trusted run bundles.")
    parser.add_argument("--context-json", required=True, help="Path to a context JSON file.")
    parser.add_argument("--mode", choices=["repro", "train"], default=default_mode)
    parser.add_argument(
        "--output-dir",
        default=default_output_dir or ("repro_outputs" if default_mode == "repro" else "train_outputs"),
        help="Directory where output files will be written.",
    )
    args = parser.parse_args()

    context = load_context(Path(args.context_json).resolve())
    write_bundle(args.mode, Path(args.output_dir).resolve(), context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
