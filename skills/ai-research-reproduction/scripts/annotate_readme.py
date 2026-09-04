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
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MARKER_BEGIN = "<!-- rigorpilot:repro:begin"
MARKER_END = "<!-- rigorpilot:repro:end -->"
MARKER_BLOCK_RE = re.compile(
    r"<!-- rigorpilot:repro:begin\b[^>]*-->.*?<!-- rigorpilot:repro:end -->\r?\n?",
    re.DOTALL,
)
ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*?)(?:[ \t]+#+[ \t]*)?$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

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

METRIC_NOISE_TOKENS = {"lr", "time", "mem", "epoch", "step", "iter"}
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
    """Split README at every ATX heading while retaining original text exactly.

    Lines keep their original line endings. A preamble before the first heading
    is returned as an unheaded block but is not counted as a README section.
    """
    blocks: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {
        "title": None,
        "lines": [],
        "sections": [],
        "level": None,
        "occurrence": 0,
        "start": 0,
        "end": 0,
    }
    occurrences: Dict[str, int] = {}
    fence_char: Optional[str] = None
    fence_length = 0
    offset = 0
    for line in readme_text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        logical_line = line.rstrip("\r\n")
        fence = FENCE_RE.match(logical_line)
        if fence_char is not None:
            current["lines"].append(line)
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_length:
                fence_char = None
                fence_length = 0
            continue
        if fence:
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            current["lines"].append(line)
            continue
        heading = ATX_HEADING_RE.match(logical_line)
        if heading:
            title = heading.group(2).strip()
            if current["lines"] or current["title"] is not None:
                current["end"] = line_start
                blocks.append(current)
            occurrences[title] = occurrences.get(title, 0) + 1
            current = {
                "title": title,
                "lines": [line],
                "sections": [title],
                "level": len(heading.group(1)),
                "occurrence": occurrences[title],
                "start": line_start,
                "end": offset,
            }
            continue
        current["lines"].append(line)
    if current["lines"] or current["title"] is not None:
        current["end"] = len(readme_text)
        blocks.append(current)
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


def result_match_status(context: Dict[str, Any]) -> str:
    comparison = context.get("result_match")
    if not isinstance(comparison, dict):
        return "not_evaluated"
    status = str(comparison.get("status") or "not_evaluated")
    return status if status in {"matched", "mismatched", "not_evaluated"} else "not_evaluated"


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
        match_status = result_match_status(context)
        if match_status == "matched":
            lines.append(text(user_language, "Result comparison: matched the explicit expected metrics.", "结果比较：已匹配显式提供的期望指标。"))
        elif match_status == "mismatched":
            style = "partial"
            headline = text(user_language, "Executed, but expected metrics did not match", "已执行，但期望指标未匹配") + f"（{risk_label(user_language, 'medium')}）"
            lines.append(text(user_language, "Result comparison: at least one expected metric was missing or outside tolerance.", "结果比较：至少一个期望指标缺失或超出容差。"))
        else:
            lines.append(text(user_language, "Result comparison: not evaluated because no explicit expected metrics were supplied.", "结果比较：未提供显式期望指标，因此尚未评估是否匹配。"))
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
        metrics = observed_metric_parts(context)
        if metrics:
            lines.append(text(user_language, "Observed metrics: ", "观测指标：") + " · ".join(metrics))
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

    result_matched = result_match_status(context) == "matched" and status == "success"
    tier = "result-match" if result_matched else ("execution" if status in {"success", "partial", "blocked"} else "code-development")
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


def _marker_attribute(value: Any) -> str:
    return html.escape(str(value), quote=True).replace("--", "&#45;&#45;")


def render_marker_block(
    lines: List[str],
    *,
    kind: str,
    section: str,
    occurrence: int,
    status: str,
    risk: str,
    newline: str,
) -> str:
    begin = (
        f'{MARKER_BEGIN} kind="{_marker_attribute(kind)}" '
        f'section="{_marker_attribute(section)}" occurrence="{occurrence}" '
        f'status="{_marker_attribute(status)}" risk="{_marker_attribute(risk)}" -->'
    )
    return newline.join([begin, "", *lines, "", MARKER_END, ""])


def strip_annotations(annotated_text: str) -> str:
    """Remove only complete RigorPilot marker blocks from an annotated README."""
    begin_count = annotated_text.count(MARKER_BEGIN)
    end_count = annotated_text.count(MARKER_END)
    if begin_count != end_count:
        raise ValueError(f"unbalanced RigorPilot markers: begin={begin_count}, end={end_count}")
    stripped, removed = MARKER_BLOCK_RE.subn("", annotated_text)
    if removed != begin_count or MARKER_BEGIN in stripped or MARKER_END in stripped:
        raise ValueError("malformed or nested RigorPilot annotation markers")
    return stripped


def _dominant_newline(value: str) -> str:
    crlf = value.count("\r\n")
    lf = value.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _sha256_text(value: str, include_utf8_bom: bool = False) -> str:
    payload = value.encode("utf-8", errors="surrogateescape")
    if include_utf8_bom:
        payload = b"\xef\xbb\xbf" + payload
    return hashlib.sha256(payload).hexdigest()


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


def render_header(context: Dict[str, Any], coverage: Dict[str, int], original_sha256: str) -> List[str]:
    user_language = str(context.get("user_language") or "en")
    status = str(context.get("status") or "not_run")
    selected_goal = str(context.get("selected_goal") or "")
    status_style = {"success": "🟢", "partial": "🟡", "blocked": "🔴"}.get(status, "🔵")
    return [
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
        f"<sub>original_sha256: `{original_sha256}` · round-trip: verified</sub>",
        "",
        "---",
    ]


def build_annotated_readme(readme_text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    if MARKER_BEGIN in readme_text or MARKER_END in readme_text:
        raise ValueError("source README already contains reserved RigorPilot markers")
    user_language = str(context.get("user_language") or "en")
    selected_goal = str(context.get("selected_goal") or "")
    newline = _dominant_newline(readme_text)
    include_utf8_bom = bool(context.get("_source_utf8_bom"))
    original_sha256 = _sha256_text(readme_text, include_utf8_bom)
    annotated_blocks: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []
    coverage: Dict[str, Any] = {style: 0 for style in COVERAGE_ORDER}
    tiers: Dict[str, int] = {}
    weight_total = 0.0
    weight_earned = 0.0
    for block in split_readme_blocks(readme_text):
        if block["title"] is None:
            annotated_blocks.append((block, None))
            continue
        annotation = classify_block(block, context)
        coverage[annotation["style"]] += 1
        tier = annotation.get("tier")
        if tier:
            tiers[tier] = tiers.get(tier, 0) + 1
        weight = float(annotation.get("weight") or 0)
        weight_total += weight
        weight_earned += weight * STYLE_EARNED.get(annotation["style"], 0.0)
        annotated_blocks.append((block, annotation))
    coverage["total_sections"] = sum(1 for _, annotation in annotated_blocks if annotation is not None)
    coverage["tiers"] = tiers
    coverage["reproduction_score"] = round(weight_earned / weight_total, 3) if weight_total else None
    coverage["annotation_count"] = coverage["total_sections"]
    coverage["original_sha256"] = original_sha256

    rendered = render_marker_block(
        render_header(context, coverage, original_sha256),
        kind="banner",
        section="__banner__",
        occurrence=1,
        status=str(context.get("status") or "not_run"),
        risk="none",
        newline=newline,
    )
    risk_by_style = {
        "success": "low",
        "info": "low",
        "readonly": "none",
        "partial": "medium",
        "blocked": "high",
        "decision": "high",
    }
    source_cursor = 0
    for block, annotation in annotated_blocks:
        start = int(block["start"])
        end = int(block["end"])
        if start != source_cursor or end < start:
            raise RuntimeError("README block offsets are not contiguous")
        # Copy an immutable slice of the original README. Parsing only decides
        # insertion offsets; it never reconstructs, trims, or rewrites source.
        rendered += readme_text[start:end]
        source_cursor = end
        if annotation is None:
            continue
        rendered += render_marker_block(
            render_annotation(annotation, user_language, selected_goal),
            kind="section",
            section=str(block["title"]),
            occurrence=int(block.get("occurrence") or 1),
            status=str(annotation["style"]),
            risk=risk_by_style[str(annotation["style"])],
            newline=newline,
        )

    if source_cursor != len(readme_text):
        raise RuntimeError("README block offsets did not cover the complete source")

    stripped = strip_annotations(rendered)
    if stripped != readme_text:
        raise RuntimeError("annotated README failed the exact round-trip fidelity check")
    coverage["stripped_sha256"] = _sha256_text(stripped, include_utf8_bom)
    coverage["round_trip_verified"] = True
    return rendered, coverage


def render_annotated_readme(readme_text: str, context: Dict[str, Any]) -> str:
    return build_annotated_readme(readme_text, context)[0]


def write_annotated_readme(readme_path: Path, context: Dict[str, Any], output_path: Path) -> Tuple[Path, Dict[str, Any]]:
    source_bytes = readme_path.read_bytes()
    bom = source_bytes.startswith(b"\xef\xbb\xbf")
    payload = source_bytes[3:] if bom else source_bytes
    readme_text = payload.decode("utf-8", errors="surrogateescape")
    rendered, coverage = build_annotated_readme(
        readme_text,
        {**context, "_source_utf8_bom": bom},
    )
    coverage["source_readme"] = str(readme_path.resolve())
    coverage["source_bytes"] = len(source_bytes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_bytes = rendered.encode("utf-8", errors="surrogateescape")
    output_path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + rendered_bytes)
    if strip_annotated_bytes(output_path.read_bytes()) != source_bytes:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("annotated README failed the byte-for-byte round-trip fidelity check")
    return output_path, coverage


def strip_annotated_bytes(value: bytes) -> bytes:
    bom = value.startswith(b"\xef\xbb\xbf")
    payload = value[3:] if bom else value
    text_value = payload.decode("utf-8", errors="surrogateescape")
    stripped = strip_annotations(text_value).encode("utf-8", errors="surrogateescape")
    return (b"\xef\xbb\xbf" if bom else b"") + stripped


def _run_legacy_annotate(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Render an annotated README from reproduction evidence.")
    parser.add_argument("--readme", required=True, help="Path to the original README file.")
    parser.add_argument("--context-json", required=True, help="Path to the reproduction context JSON (orchestrator payload).")
    parser.add_argument("--output", required=True, help="Path to write the annotated README to.")
    args = parser.parse_args(argv)
    context = json.loads(Path(args.context_json).read_text(encoding="utf-8-sig"))
    if not isinstance(context, dict):
        raise SystemExit("Context JSON must contain a top-level object.")
    written, coverage = write_annotated_readme(Path(args.readme), context, Path(args.output))
    print(json.dumps({"annotated_readme": str(written), "readme_section_coverage": coverage}, ensure_ascii=False))
    return 0


def _run_strip_or_check(command: str, argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=f"{command} RigorPilot README annotations.")
    parser.add_argument("--input", required=True, help="Annotated README path.")
    parser.add_argument("--output", help="Where to write the exact stripped README (strip only).")
    parser.add_argument("--against", help="Original README to compare byte-for-byte.")
    args = parser.parse_args(argv)
    annotated_path = Path(args.input)
    annotated_bytes = annotated_path.read_bytes()
    stripped_bytes = strip_annotated_bytes(annotated_bytes)
    if args.against:
        original_bytes = Path(args.against).read_bytes()
        if stripped_bytes != original_bytes:
            print("round_trip_verified: false", file=sys.stderr)
            return 1
    if command == "strip":
        if not args.output:
            parser.error("--output is required for strip")
        Path(args.output).write_bytes(stripped_bytes)
    print(
        json.dumps(
            {
                "round_trip_verified": True,
                "stripped_sha256": hashlib.sha256(stripped_bytes).hexdigest(),
                "marker_blocks": annotated_bytes.count(MARKER_BEGIN.encode("ascii")),
            }
        )
    )
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in {"strip", "check"}:
        return _run_strip_or_check(argv[0], argv[1:])
    if argv and argv[0] == "annotate":
        argv = argv[1:]
    return _run_legacy_annotate(argv)


if __name__ == "__main__":
    raise SystemExit(main())
