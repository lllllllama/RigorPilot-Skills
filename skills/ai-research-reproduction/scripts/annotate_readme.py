#!/usr/bin/env python3
"""Render an annotated copy of the target README with per-section reproduction evidence.

The original README content is preserved verbatim. The file is split into
heading-level blocks, and each block is followed by a GitHub-renderable
annotation describing what the reproduction run did there, colored by risk:

- [!TIP]       green  - executed successfully, low risk
- [!NOTE]      blue   - informational: read-only, planned, or not executed
- [!WARNING]   yellow - partial result or conservative assumptions
- [!CAUTION]   red    - blocked or failed, researcher attention required
- [!IMPORTANT] purple - an explicit researcher decision is required
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def evidence_line(user_language: str, selected_goal: str) -> str:
    links = " · ".join(f"[{label}]({target})" for label, target in EVIDENCE_LINKS)
    if selected_goal == "training":
        links += " · [train status](../train_outputs/status.json)"
    return text(user_language, f"Evidence: {links}", f"证据：{links}")


def selected_command_annotation(context: Dict[str, Any], user_language: str) -> Dict[str, Any]:
    status = str(context.get("status") or "not_run")
    command = str(context.get("documented_command") or "")
    lines: List[str] = []

    if status == "success":
        style = "success"
        headline = text(user_language, "Executed successfully · low risk", "已执行且成功 · 低风险")
        lines.append(text(user_language, f"Ran `{command}` to completion.", f"已完整执行 `{command}`。"))
        best_metric = context.get("best_metric")
        if isinstance(best_metric, dict) and best_metric.get("name") is not None:
            lines.append(
                text(
                    user_language,
                    f"Observed metric: `{best_metric['name']}={best_metric['value']}`.",
                    f"观测指标：`{best_metric['name']}={best_metric['value']}`。",
                )
            )
    elif status == "partial":
        style = "partial"
        headline = text(user_language, "Partially completed · review needed", "部分完成 · 需检查")
        lines.append(text(user_language, f"Started `{command}` but it did not finish cleanly.", f"已启动 `{command}`，但未完整成功结束。"))
        lines.append(
            text(
                user_language,
                f"Blocker: {context.get('main_blocker', 'not recorded')}",
                f"阻塞项：{context.get('main_blocker', '未记录')}",
            )
        )
    elif status == "blocked":
        style = "blocked"
        headline = text(user_language, "Blocked · researcher attention required", "被阻塞 · 需要研究者关注")
        lines.append(text(user_language, f"Could not launch `{command}`.", f"无法启动 `{command}`。"))
        lines.append(
            text(
                user_language,
                f"Blocker: {context.get('main_blocker', 'not recorded')}",
                f"阻塞项：{context.get('main_blocker', '未记录')}",
            )
        )
    else:
        style = "info"
        headline = text(user_language, "Selected as the reproduction target · not executed", "已选为复现目标 · 未执行")
        lines.append(
            text(
                user_language,
                f"`{command}` was selected as the smallest trustworthy target; execution was not requested.",
                f"`{command}` 已被选为最小可信目标；本次未请求执行。",
            )
        )

    if context.get("requires_full_training_confirmation"):
        style = "decision"
        headline = text(user_language, "Startup verified · fuller training needs your approval", "启动已验证 · 更完整训练需要你确认")
        lines.append(
            text(
                user_language,
                "Trusted lane stops at startup verification; review the evidence and explicitly authorize fuller training.",
                "trusted lane 在启动验证后停止；请先检查证据，再显式授权更完整的训练。",
            )
        )

    completed_steps = context.get("completed_steps")
    if completed_steps:
        lines.append(text(user_language, f"Completed steps observed: {completed_steps}.", f"已观测到完成步数：{completed_steps}。"))

    return {"style": style, "headline": headline, "lines": lines}


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
    if selected_here:
        return selected_command_annotation(context, user_language)
    # Fall back to section-name matching when the command text was normalized.
    if selected_section is not None and selected_section in set(block["sections"]) and selected_command:
        return selected_command_annotation(context, user_language)

    if matched:
        setup_like = [item for item in matched if item.get("kind") in {"setup", "asset"}]
        if len(setup_like) == len(matched):
            return {
                "style": "info",
                "headline": text(user_language, "Folded into the setup plan · not executed directly", "已纳入 setup 计划 · 未直接执行"),
                "lines": [
                    text(
                        user_language,
                        f"{len(matched)} command(s) recorded as environment/asset preparation; see the setup plan in the evidence bundle.",
                        f"{len(matched)} 条命令已记录为环境/资源准备；详见证据包中的 setup 计划。",
                    )
                ],
            }
        return {
            "style": "info",
            "headline": text(user_language, "Commands recognized · not executed", "已识别命令 · 未执行"),
            "lines": [
                text(
                    user_language,
                    f"{len(matched)} command(s) recognized here; the conservative policy executes only the selected target.",
                    f"此处识别到 {len(matched)} 条命令；保守策略只执行选定目标。",
                )
            ],
        }

    return {
        "style": "readonly",
        "headline": text(user_language, "Read only · no action taken", "仅阅读 · 无执行动作"),
        "lines": [],
    }


def render_annotation(annotation: Dict[str, Any], user_language: str, selected_goal: str) -> List[str]:
    admonition, dot = STYLE_BADGES[annotation["style"]]
    lines = [f"> [!{admonition}]", f"> {dot} **RigorPilot · {annotation['headline']}**"]
    for detail in annotation["lines"]:
        lines.append(f"> {detail}")
    if annotation["style"] != "readonly":
        lines.append(f"> {evidence_line(user_language, selected_goal)}")
    return lines


def render_header(context: Dict[str, Any]) -> List[str]:
    user_language = str(context.get("user_language") or "en")
    status = str(context.get("status") or "not_run")
    status_style = {"success": "🟢", "partial": "🟡", "blocked": "🔴"}.get(status, "🔵")
    return [
        "<!-- RigorPilot annotated README: original content preserved verbatim; annotations added below each section. -->",
        "",
        text(user_language, "# RigorPilot · Annotated README", "# RigorPilot · 批注版 README"),
        "",
        text(
            user_language,
            f"{status_style} Overall status: `{status}` · Selected goal: `{context.get('selected_goal')}` · Lane: `{context.get('lane')}`",
            f"{status_style} 总体状态：`{status}` · 选定目标：`{context.get('selected_goal')}` · Lane：`{context.get('lane')}`",
        ),
        "",
        text(
            user_language,
            "Legend: 🟢 executed successfully · 🔵 informational / not executed · ⚪ read only · 🟡 partial · 🔴 blocked · 🟣 decision required",
            "图例：🟢 已执行成功 · 🔵 信息性 / 未执行 · ⚪ 仅阅读 · 🟡 部分完成 · 🔴 被阻塞 · 🟣 需要决策",
        ),
        "",
        text(
            user_language,
            f"{evidence_line(user_language, str(context.get('selected_goal') or ''))} · Relative links below resolve against the target repo root.",
            f"{evidence_line(user_language, str(context.get('selected_goal') or ''))} · 下方原文中的相对链接以目标仓库根目录为基准。",
        ),
        "",
        "---",
        "",
    ]


def render_annotated_readme(readme_text: str, context: Dict[str, Any]) -> str:
    user_language = str(context.get("user_language") or "en")
    selected_goal = str(context.get("selected_goal") or "")
    output: List[str] = render_header(context)
    for block in split_readme_blocks(readme_text):
        output.extend(block["lines"])
        annotation = classify_block(block, context)
        output.append("")
        output.extend(render_annotation(annotation, user_language, selected_goal))
        output.append("")
    return "\n".join(output).rstrip() + "\n"


def write_annotated_readme(readme_path: Path, context: Dict[str, Any], output_path: Path) -> Path:
    readme_text = readme_path.read_text(encoding="utf-8-sig", errors="replace")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_annotated_readme(readme_text, context), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an annotated README from reproduction evidence.")
    parser.add_argument("--readme", required=True, help="Path to the original README file.")
    parser.add_argument("--context-json", required=True, help="Path to the reproduction context JSON (orchestrator payload).")
    parser.add_argument("--output", required=True, help="Path to write the annotated README to.")
    args = parser.parse_args()

    context = json.loads(Path(args.context_json).read_text(encoding="utf-8-sig"))
    if not isinstance(context, dict):
        raise SystemExit("Context JSON must contain a top-level object.")
    written = write_annotated_readme(Path(args.readme), context, Path(args.output))
    print(json.dumps({"annotated_readme": str(written)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
