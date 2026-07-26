#!/usr/bin/env python3
"""Render an annotated copy of the target README with per-section reproduction evidence.

The original README content is preserved verbatim. The file is split into
heading-level blocks, and each block is followed by a GitHub-renderable
annotation describing what the reproduction run did there, colored by risk:

- [!TIP]       green  - executed successfully, low risk
- [!NOTE]      blue   - informational: recognized / planned, not executed
- [!WARNING]   yellow - partial result, missing assets, or assumptions
- [!CAUTION]   red    - blocked or failed, researcher attention required
- [!IMPORTANT] purple - an explicit researcher decision is required

Prose-only sections get a single dim line instead of a box.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BLOCK_SPLIT_MAX_LEVEL = 2

STYLE_BADGES = {
    "success": ("TIP", "🟢"),
    "info": ("NOTE", "🔵"),
    "readonly": ("NOTE", "⚪"),
    "partial": ("WARNING", "🟡"),
    "blocked": ("CAUTION", "🔴"),
    "decision": ("IMPORTANT", "🟣"),
}

EVIDENCE_LINKS = [
    ("SUMMARY", "SUMMARY.md"),
    ("COMMANDS", "COMMANDS.md"),
    ("LOG", "LOG.md"),
    ("status.json", "status.json"),
]

METRIC_NOISE_TOKENS = {"loss", "lr", "time", "mem", "epoch", "step", "iter"}
DATA_SECTION_TOKENS = ("data", "dataset", "数据")

# Evidence tiers follow PaperBench's grading ladder: recognizing/planning work
# (code-development) < actually running it (execution) < comparable observed
# results (result-match). Weights and earned fractions feed a 0-1
# reproduction score over the command-bearing sections.
STYLE_EARNED = {"success": 1.0, "partial": 0.5, "blocked": 0.0, "decision": 0.25, "info": 0.25}


def locale(user_language: str) -> str:
    return "zh" if str(user_language or "").strip().lower().startswith("zh") else "en"


def text(user_language: str, en: str, zh: str) -> str:
    return zh if locale(user_language) == "zh" else en


def split_readme_blocks(readme_text: str) -> List[Dict[str, Any]]:
    """Split README into blocks at level-1/2 headings, ignoring fenced code lines.

    Each block keeps its original lines verbatim and records every heading
    title it contains (including deeper subheadings) for section matching.
    """
    blocks: List[Dict[str, Any]] = [{"title": None, "lines": [], "sections": []}]
    inside_fence = False
    for line in readme_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            inside_fence = not inside_fence
            blocks[-1]["lines"].append(line)
            continue
        if not inside_fence and stripped.startswith("#"):
            marks = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[marks:].strip()
            if 1 <= marks <= 6 and title:
                if marks <= BLOCK_SPLIT_MAX_LEVEL:
                    blocks.append({"title": title, "lines": [line], "sections": [title]})
                else:
                    blocks[-1]["lines"].append(line)
                    blocks[-1]["sections"].append(title)
                continue
        blocks[-1]["lines"].append(line)
    if not blocks[0]["lines"]:
        blocks.pop(0)
    return blocks


def block_commands(block: Dict[str, Any], commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sections = set(block["sections"])
    matched = []
    for item in commands:
        section = item.get("section")
        if section in sections or (section is None and block["title"] is None):
            matched.append(item)
    return matched


def evidence_links(selected_goal: str) -> str:
    links = " · ".join(f"[{label}]({target})" for label, target in EVIDENCE_LINKS)
    if selected_goal == "training":
        links += " · [train status](../train_outputs/status.json)"
    return links


def risk_label(user_language: str, level: str) -> str:
    mapping = {
        "low": ("low risk", "低风险"),
        "medium": ("medium risk", "中风险"),
        "high": ("high risk", "高风险"),
    }
    en, zh = mapping[level]
    return text(user_language, en, zh)


def command_list_lines(matched: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    lines = [f"`{item.get('command', '')}`" for item in matched[:limit]]
    if len(matched) > limit:
        lines.append(f"… +{len(matched) - limit}")
    return lines


def error_excerpt(context: Dict[str, Any]) -> Optional[str]:
    for entry in reversed(list(context.get("execution_log") or [])):
        for line in reversed(str(entry).splitlines()):
            candidate = line.strip()
            if "error" in candidate.lower() or "traceback" in candidate.lower():
                return candidate[:200]
    return None


def observed_metric_parts(context: Dict[str, Any]) -> List[str]:
    observed = context.get("observed_metrics") or {}
    shown = [
        f"`{name}={value}`"
        for name, value in list(observed.items())[:4]
        if not any(token in name.lower() for token in METRIC_NOISE_TOKENS)
    ]
    best_metric = context.get("best_metric")
    if not shown and isinstance(best_metric, dict) and best_metric.get("name") is not None:
        shown = [f"`{best_metric['name']}={best_metric['value']}`"]
    return shown[:4]


def selected_command_annotation(context: Dict[str, Any], user_language: str) -> Dict[str, Any]:
    status = str(context.get("status") or "not_run")
    command = str(context.get("documented_command") or "")
    lines: List[str] = [text(user_language, f"Command: `{command}`", f"命令：`{command}`")]

    if status == "success":
        style = "success"
        headline = text(user_language, "Executed successfully", "执行成功") + f"（{risk_label(user_language, 'low')}）"
        metrics = observed_metric_parts(context)
        if metrics:
            lines.append(text(user_language, "Observed metrics: ", "观测指标：") + " · ".join(metrics))
        completed_steps = context.get("completed_steps")
        if completed_steps:
            lines.append(text(user_language, f"Completed steps: {completed_steps}", f"完成步数：{completed_steps}"))
    elif status in {"partial", "blocked"}:
        style = status
        level = "medium" if status == "partial" else "high"
        headline = (
            text(user_language, "Partially completed", "部分完成")
            if status == "partial"
            else text(user_language, "Blocked", "被阻塞")
        ) + f"（{risk_label(user_language, level)}）"
        lines.append(
            text(
                user_language,
                f"Blocker: {context.get('main_blocker', 'not recorded')}",
                f"阻塞项：{context.get('main_blocker', '未记录')}",
            )
        )
        excerpt = error_excerpt(context)
        if excerpt:
            lines.append(text(user_language, f"Error excerpt: `{excerpt}`", f"错误摘录：`{excerpt}`"))
        next_action = str(context.get("next_action") or "").strip()
        if next_action:
            lines.append(text(user_language, f"Suggested next: {next_action}", f"建议下一步：{next_action}"))
    else:
        style = "info"
        headline = text(user_language, "Selected target · not executed", "已选为目标 · 未执行")
        lines.append(
            text(
                user_language,
                "Chosen as the smallest trustworthy target; execution was not requested in this run.",
                "已选为最小可信目标；本次运行未请求执行。",
            )
        )

    source_file = context.get("documented_command_source_file")
    if source_file:
        lines.append(
            text(user_language, f"Command sourced from linked doc `{source_file}`.", f"命令来自 README 链接的文档 `{source_file}`。")
        )

    if context.get("requires_substitution"):
        style = "decision"
        headline = text(
            user_language,
            "Placeholders need your values before execution",
            "需要你替换占位符后才能执行",
        )
        lines = [
            text(user_language, f"Command: `{command}`", f"命令：`{command}`"),
            text(
                user_language,
                "The documented command contains <...> placeholders; fill them in, then rerun.",
                "文档命令包含 <...> 占位符；请填入真实值后重跑。",
            ),
        ]
        if source_file:
            lines.append(
                text(user_language, f"Command sourced from linked doc `{source_file}`.", f"命令来自 README 链接的文档 `{source_file}`。")
            )
    elif context.get("requires_full_training_confirmation"):
        style = "decision"
        headline = text(
            user_language,
            "Startup verified · fuller training needs your explicit approval",
            "启动已验证 · 更完整训练需要你显式授权",
        )

    metrics_present = bool(observed_metric_parts(context)) and status == "success"
    tier = "result-match" if metrics_present else ("execution" if status in {"success", "partial", "blocked"} else "code-development")
    return {"style": style, "headline": headline, "lines": lines, "tier": tier, "weight": 3}


def training_policy_annotation(matched: List[Dict[str, Any]], user_language: str) -> Dict[str, Any]:
    return {
        "style": "decision",
        "headline": text(
            user_language,
            "Training not run · requires explicit authorization (high-impact)",
            "训练未执行 · 需要显式授权（高影响操作）",
        ),
        "lines": command_list_lines(matched)
        + [
            text(
                user_language,
                "The trusted lane never launches training on its own; it starts with startup verification only after you approve.",
                "trusted lane 不会自行发起训练；获得授权后也只先做启动验证。",
            )
        ],
        "tier": "code-development",
        "weight": 2,
    }


def data_readiness_annotation(matched: List[Dict[str, Any]], user_language: str) -> Dict[str, Any]:
    return {
        "style": "partial",
        "headline": text(user_language, "Data assets not ready", "数据资产未就绪")
        + f"（{risk_label(user_language, 'medium')}）",
        "lines": command_list_lines(matched)
        + [
            text(
                user_language,
                "No local dataset was detected; complete this section before a full evaluation is reproducible.",
                "本地未检测到数据集；需先完成本节准备，完整评测才可复现。",
            )
        ],
        "tier": "code-development",
        "weight": 2,
    }


def dataset_missing(context: Dict[str, Any]) -> bool:
    if "local_dataset_present" in context:
        return not bool(context.get("local_dataset_present"))
    hint = str(context.get("dataset") or "").strip().lower()
    return hint in {"", "none", "unknown", "not-found"}


def classify_block(block: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    user_language = str(context.get("user_language") or "en")
    commands = list(context.get("readme_commands") or [])
    matched = block_commands(block, commands)
    selected_section = context.get("documented_command_section")
    selected_command = str(context.get("documented_command") or "")

    selected_here = bool(selected_command) and any(
        item.get("command") == selected_command
        and (item.get("section") in set(block["sections"]) or (item.get("section") is None and block["title"] is None))
        for item in matched
    )
    if not selected_here and selected_section is not None and selected_command:
        selected_here = selected_section in set(block["sections"])
    if selected_here:
        return selected_command_annotation(context, user_language)

    if matched:
        title = str(block["title"] or "").lower()
        if all(item.get("category") == "training" for item in matched) and context.get("lane") == "trusted":
            return training_policy_annotation(matched, user_language)
        setup_like = [item for item in matched if item.get("kind") in {"setup", "asset"}]
        if len(setup_like) == len(matched):
            if any(token in title for token in DATA_SECTION_TOKENS) and dataset_missing(context):
                return data_readiness_annotation(matched, user_language)
            return {
                "style": "info",
                "headline": text(user_language, "Folded into the setup plan · not executed directly", "已纳入 setup 计划 · 未直接执行"),
                "lines": command_list_lines(matched),
                "tier": "code-development",
                "weight": 1,
            }
        return {
            "style": "info",
            "headline": text(
                user_language,
                "Commands recognized · not executed (only the selected target runs)",
                "已识别命令 · 未执行（保守策略仅执行选定目标）",
            ),
            "lines": command_list_lines(matched),
            "tier": "code-development",
            "weight": 2,
        }

    return {
        "style": "readonly",
        "headline": text(user_language, "Read only", "仅阅读"),
        "lines": [],
        "tier": None,
        "weight": 0,
    }


def render_annotation(annotation: Dict[str, Any], user_language: str, selected_goal: str) -> List[str]:
    admonition, dot = STYLE_BADGES[annotation["style"]]
    if annotation["style"] == "readonly":
        # Keep prose-only sections almost invisible: one small dim line.
        return [f"<sub>{dot} {annotation['headline']}</sub>"]
    lines = [f"> [!{admonition}]", f"> {dot} **{annotation['headline']}**"]
    for detail in annotation["lines"]:
        lines.append(f"> {detail}")
    tier_chip = f" · tier: {annotation['tier']}" if annotation.get("tier") else ""
    lines.append(f"> <sub>{text(user_language, 'Evidence', '证据')}: {evidence_links(selected_goal)}{tier_chip}</sub>")
    return lines


COVERAGE_ORDER = ["success", "partial", "blocked", "decision", "info", "readonly"]


def coverage_line(coverage: Dict[str, Any], user_language: str) -> str:
    chips = [
        f"{STYLE_BADGES[style][1]} {coverage[style]}"
        for style in COVERAGE_ORDER
        if coverage.get(style)
    ]
    total = coverage.get("total_sections", 0)
    score = coverage.get("reproduction_score")
    score_chip = ""
    if score is not None:
        score_chip = text(user_language, f" · score {score}", f" · 复现得分 {score}")
    return text(
        user_language,
        f"Section coverage: {' · '.join(chips)} ({total} sections){score_chip}",
        f"章节覆盖：{' · '.join(chips)}（共 {total} 节）{score_chip}",
    )


def render_header(context: Dict[str, Any], coverage: Dict[str, int]) -> List[str]:
    user_language = str(context.get("user_language") or "en")
    status = str(context.get("status") or "not_run")
    selected_goal = str(context.get("selected_goal") or "")
    status_style = {"success": "🟢", "partial": "🟡", "blocked": "🔴"}.get(status, "🔵")
    return [
        "<!-- RigorPilot annotated README: original content preserved verbatim; annotations added below each section. -->",
        "",
        text(user_language, "# 📄 README · RigorPilot annotations", "# 📄 README · RigorPilot 复现批注"),
        "",
        f"{status_style} `{status}` · `{selected_goal}` · `{context.get('lane')}` · {evidence_links(selected_goal)}",
        "",
        coverage_line(coverage, user_language),
        "",
        text(
            user_language,
            "<sub>🟢 success · 🔵 not executed · ⚪ read only · 🟡 partial / assets missing · 🔴 blocked · 🟣 decision needed — original content unchanged; its relative links resolve against the repo root.</sub>",
            "<sub>🟢 成功 · 🔵 未执行 · ⚪ 仅阅读 · 🟡 部分完成 / 资产缺失 · 🔴 阻塞 · 🟣 待决策 —— 原文未改动，原文相对链接以仓库根目录为基准。</sub>",
        ),
        "",
        "---",
        "",
    ]


def build_annotated_readme(readme_text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    user_language = str(context.get("user_language") or "en")
    selected_goal = str(context.get("selected_goal") or "")
    annotated_blocks: List[Tuple[List[str], Dict[str, Any]]] = []
    coverage: Dict[str, Any] = {style: 0 for style in COVERAGE_ORDER}
    tiers: Dict[str, int] = {}
    weight_total = 0.0
    weight_earned = 0.0
    for block in split_readme_blocks(readme_text):
        block_lines = list(block["lines"])
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        annotation = classify_block(block, context)
        coverage[annotation["style"]] += 1
        tier = annotation.get("tier")
        if tier:
            tiers[tier] = tiers.get(tier, 0) + 1
        weight = float(annotation.get("weight") or 0)
        weight_total += weight
        weight_earned += weight * STYLE_EARNED.get(annotation["style"], 0.0)
        annotated_blocks.append((block_lines, annotation))
    coverage["total_sections"] = len(annotated_blocks)
    coverage["tiers"] = tiers
    coverage["reproduction_score"] = round(weight_earned / weight_total, 3) if weight_total else None

    output: List[str] = render_header(context, coverage)
    for block_lines, annotation in annotated_blocks:
        output.extend(block_lines)
        output.append("")
        output.extend(render_annotation(annotation, user_language, selected_goal))
        output.append("")
    return "\n".join(output).rstrip() + "\n", coverage


def render_annotated_readme(readme_text: str, context: Dict[str, Any]) -> str:
    return build_annotated_readme(readme_text, context)[0]


def write_annotated_readme(readme_path: Path, context: Dict[str, Any], output_path: Path) -> Tuple[Path, Dict[str, int]]:
    readme_text = readme_path.read_text(encoding="utf-8-sig", errors="replace")
    rendered, coverage = build_annotated_readme(readme_text, context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path, coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an annotated README from reproduction evidence.")
    parser.add_argument("--readme", required=True, help="Path to the original README file.")
    parser.add_argument("--context-json", required=True, help="Path to the reproduction context JSON (orchestrator payload).")
    parser.add_argument("--output", required=True, help="Path to write the annotated README to.")
    args = parser.parse_args()

    context = json.loads(Path(args.context_json).read_text(encoding="utf-8-sig"))
    if not isinstance(context, dict):
        raise SystemExit("Context JSON must contain a top-level object.")
    written, coverage = write_annotated_readme(Path(args.readme), context, Path(args.output))
    print(json.dumps({"annotated_readme": str(written), "readme_section_coverage": coverage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
