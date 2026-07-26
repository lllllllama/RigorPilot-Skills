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


def evidence_links(selected_goal: str) -> str:
    links = " · ".join(f"[{label}]({target})" for label, target in EVIDENCE_LINKS)
    if selected_goal == "training":
        links += " · [train status](../train_outputs/status.json)"
    return links


def selected_command_annotation(context: Dict[str, Any], user_language: str) -> Dict[str, Any]:
    status = str(context.get("status") or "not_run")
    command = str(context.get("documented_command") or "")
    lines: List[str] = []
    parts: List[str] = [f"`{command}`"]

    if status == "success":
        style = "success"
        headline = text(user_language, "Executed successfully", "执行成功")
        best_metric = context.get("best_metric")
        if isinstance(best_metric, dict) and best_metric.get("name") is not None:
            parts.append(f"`{best_metric['name']}={best_metric['value']}`")
    elif status == "partial":
        style = "partial"
        headline = text(user_language, "Partial", "部分完成")
        lines.append(
            text(
                user_language,
                f"Blocker: {context.get('main_blocker', 'not recorded')}",
                f"阻塞项：{context.get('main_blocker', '未记录')}",
            )
        )
    elif status == "blocked":
        style = "blocked"
        headline = text(user_language, "Blocked", "被阻塞")
        lines.append(
            text(
                user_language,
                f"Blocker: {context.get('main_blocker', 'not recorded')}",
                f"阻塞项：{context.get('main_blocker', '未记录')}",
            )
        )
    else:
        style = "info"
        headline = text(user_language, "Selected target · not executed", "已选为目标 · 未执行")

    if context.get("requires_full_training_confirmation"):
        style = "decision"
        headline = text(user_language, "Startup verified · awaiting your approval for fuller training", "启动已验证 · 等你授权更完整训练")

    completed_steps = context.get("completed_steps")
    if completed_steps:
        parts.append(text(user_language, f"{completed_steps} steps", f"{completed_steps} 步"))

    return {"style": style, "headline": headline, "parts": parts, "lines": lines}


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
                "headline": text(user_language, "Folded into the setup plan", "已纳入 setup 计划"),
                "parts": [
                    text(user_language, f"{len(matched)} command(s), not executed directly", f"{len(matched)} 条命令，未直接执行")
                ],
                "lines": [],
            }
        return {
            "style": "info",
            "headline": text(user_language, "Commands recognized · not executed", "已识别命令 · 未执行"),
            "parts": [
                text(user_language, f"{len(matched)} command(s); only the selected target runs", f"{len(matched)} 条命令；仅执行选定目标")
            ],
            "lines": [],
        }

    return {
        "style": "readonly",
        "headline": text(user_language, "Read only", "仅阅读"),
        "parts": [],
        "lines": [],
    }


def render_annotation(annotation: Dict[str, Any]) -> List[str]:
    admonition, dot = STYLE_BADGES[annotation["style"]]
    if annotation["style"] == "readonly":
        # Keep prose-only sections almost invisible: one small dim line.
        return [f"<sub>{dot} {annotation['headline']}</sub>"]
    summary = f"> {dot} **{annotation['headline']}**"
    if annotation.get("parts"):
        summary += " · " + " · ".join(annotation["parts"])
    lines = [f"> [!{admonition}]", summary]
    for detail in annotation["lines"]:
        lines.append(f"> {detail}")
    return lines


def render_header(context: Dict[str, Any]) -> List[str]:
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
        text(
            user_language,
            "<sub>🟢 success · 🔵 not executed · ⚪ read only · 🟡 partial · 🔴 blocked · 🟣 decision needed — original content unchanged; its relative links resolve against the repo root.</sub>",
            "<sub>🟢 成功 · 🔵 未执行 · ⚪ 仅阅读 · 🟡 部分完成 · 🔴 阻塞 · 🟣 待决策 —— 原文未改动，原文相对链接以仓库根目录为基准。</sub>",
        ),
        "",
        "---",
        "",
    ]


def render_annotated_readme(readme_text: str, context: Dict[str, Any]) -> str:
    output: List[str] = render_header(context)
    for block in split_readme_blocks(readme_text):
        block_lines = list(block["lines"])
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        output.extend(block_lines)
        annotation = classify_block(block, context)
        output.append("")
        output.extend(render_annotation(annotation))
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
