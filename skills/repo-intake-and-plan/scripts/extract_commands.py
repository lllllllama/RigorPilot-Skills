#!/usr/bin/env python3
"""Extract shell-like commands from README content and classify them."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional


CODE_BLOCK_RE = re.compile(r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)
# Bare ">" is deliberately excluded: it marks markdown blockquotes (prose),
# not shell prompts, and matching it turns README notes into commands.
INLINE_CMD_RE = re.compile(r"^\s*(?:\$|PS> )\s*(.+)$")
# Angle-bracket placeholders (<PATH/TO/DATASET>, <NUM_NODES>) mean the command
# cannot run verbatim: it needs researcher-supplied values first.
PLACEHOLDER_RE = re.compile(r"<[A-Za-z][A-Za-z0-9 _./:-]*>")
HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
COMMAND_PREFIXES = (
    "python ",
    "python3 ",
    "pip ",
    "pip3 ",
    "conda ",
    "bash ",
    "sh ",
    "chmod ",
    "export ",
    "set ",
    "CUDA_VISIBLE_DEVICES=",
    "./",
    "accelerate ",
    "torchrun ",
    "deepspeed ",
    "make ",
    "docker ",
)


def collect_headings(readme_text: str) -> List[Dict[str, object]]:
    headings: List[Dict[str, object]] = []
    offset = 0
    inside_fence = False
    for line in readme_text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            inside_fence = not inside_fence
            offset += len(line)
            continue
        if inside_fence:
            # "# comment" lines inside fenced code blocks are not headings.
            offset += len(line)
            continue
        matched = HEADING_RE.match(line.strip())
        if matched:
            headings.append(
                {
                    "offset": offset,
                    "level": len(matched.group("marks")),
                    "title": matched.group("title").strip(),
                }
            )
        offset += len(line)
    return headings


def nearest_heading(headings: List[Dict[str, object]], offset: int) -> Optional[str]:
    current: Optional[str] = None
    for heading in headings:
        if int(heading["offset"]) > offset:
            break
        current = str(heading["title"])
    return current


def infer_section_category(section: Optional[str]) -> Optional[str]:
    if not section:
        return None
    lowered = section.lower()
    if any(word in lowered for word in ["inference", "usage", "demo", "example", "text-to-image", "image-to-image", "transcribe"]):
        return "inference"
    if any(word in lowered for word in ["evaluation", "evaluate", "benchmark", "metrics", "validation"]):
        return "evaluation"
    if any(word in lowered for word in ["training", "train", "finetune", "fine-tune", "pretrain"]):
        return "training"
    return None


def infer_section_kind(section: Optional[str]) -> Optional[str]:
    if not section:
        return None
    lowered = section.lower()
    if any(word in lowered for word in ["install", "installation", "setup", "environment", "requirements"]):
        return "setup"
    if any(word in lowered for word in ["download", "checkpoint", "weights", "dataset", "data preparation"]):
        return "asset"
    if any(word in lowered for word in ["usage", "demo", "example", "inference", "evaluation", "training", "text-to-image", "image-to-image", "quick start", "quickstart", "getting started"]):
        return "run"
    return None


# The entrypoint script name is the strongest category signal: flags like
# --eval_iters on a train.py command must not flip training into evaluation
# (that would bypass the training-authorization gate downstream).
SCRIPT_CATEGORY_HINTS = [
    (re.compile(r"\b(?:pre)?train\w*\.py\b"), "training"),
    (re.compile(r"\b(?:eval\w*|benchmark\w*|validate|test)\.py\b"), "evaluation"),
    (re.compile(r"\b(?:sample|generate|infer\w*|predict|demo)\w*\.py\b"), "inference"),
]


def classify(command: str, section: Optional[str] = None) -> str:
    section_category = infer_section_category(section)
    if section_category:
        return section_category

    lowered = command.lower()
    for pattern, category in SCRIPT_CATEGORY_HINTS:
        if pattern.search(lowered):
            return category

    def any_word(words: List[str]) -> bool:
        return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in words)

    if any_word(["infer", "inference", "predict", "generate", "sample", "demo", "transcribe"]) or any(
        token in lowered for token in ["txt2img", "img2img", "whisper ", "amg.py"]
    ):
        return "inference"
    if any_word(["eval", "evaluate", "evaluation", "validation", "validate", "benchmark", "score"]):
        return "evaluation"
    if any_word(["train", "training", "finetune", "pretrain"]) or any(
        token in lowered for token in ["fine-tune", "pre-train"]
    ):
        return "training"
    return "other"


def command_kind(command: str, section: Optional[str] = None) -> str:
    section_kind = infer_section_kind(section)
    if section_kind:
        return section_kind

    lowered = command.lower().strip()
    setup_prefixes = (
        "pip install",
        "pip3 install",
        "conda install",
        "conda env create",
        "conda create",
        "conda activate",
        "python -m pip install",
        "git clone",
        "cd ",
    )
    asset_prefixes = ("wget ", "curl ", "mkdir ", "tar ", "unzip ", "7z ", "aria2c ")
    if lowered.startswith(setup_prefixes):
        return "setup"
    if lowered.startswith(asset_prefixes):
        return "asset"
    if "--help" in lowered or " -h" in lowered:
        return "smoke"
    return "run"


def looks_like_command(line: str) -> bool:
    candidate = re.sub(r"^(?:\$|PS> )\s*", "", line.strip())
    if not candidate or candidate.startswith("#"):
        return False
    if candidate.startswith(("python", "pip", "conda", "bash", "sh", "make", "docker")):
        return True
    if candidate.startswith(COMMAND_PREFIXES):
        return True
    if re.search(r"\s--[A-Za-z0-9_-]+", candidate):
        return True
    if re.search(r"\b(?:python|pip|conda|torchrun|deepspeed|accelerate|bash|sh)\b", candidate):
        return True
    if re.search(r"[\\/].+\.(?:py|sh|bat)", candidate):
        return True
    if candidate.startswith(("cd ", "ls ", "mkdir ", "wget ", "curl ", "git ")):
        return True
    return False


def join_continuations(block: str) -> List[str]:
    """Join backslash-continued shell lines into single logical commands."""
    joined: List[str] = []
    buffer = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        buffer = f"{buffer} {line}".strip() if buffer else line
        if buffer.endswith("\\"):
            buffer = buffer[:-1].rstrip()
            continue
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def clean_lines(block: str) -> List[str]:
    commands: List[str] = []
    for line in join_continuations(block):
        if not line or line.startswith("#"):
            continue
        if not looks_like_command(line):
            continue
        line = re.sub(r"^(?:\$|PS> )\s*", "", line)
        commands.append(line)
    return commands


def extract_commands(readme_text: str) -> Dict[str, object]:
    commands: List[Dict[str, str]] = []
    warnings: List[str] = []
    seen = set()
    headings = collect_headings(readme_text)

    for match in CODE_BLOCK_RE.finditer(readme_text):
        lang = (match.group("lang") or "").strip().lower()
        if lang and lang not in {"bash", "shell", "sh", "zsh", "powershell", "cmd"}:
            continue

        section = nearest_heading(headings, match.start())
        lines = clean_lines(match.group("body"))
        if not lines:
            continue

        for line in lines:
            if line not in seen:
                commands.append(
                    {
                        "command": line,
                        "category": classify(line, section),
                        "kind": command_kind(line, section),
                        "section": section,
                        "source": "code_block",
                        "needs_substitution": bool(PLACEHOLDER_RE.search(line)),
                    }
                )
                seen.add(line)

    running_offset = 0
    for line in readme_text.splitlines(keepends=True):
        matched = INLINE_CMD_RE.match(line)
        if not matched:
            running_offset += len(line)
            continue
        command = matched.group(1).strip()
        if not looks_like_command(command):
            running_offset += len(line)
            continue
        section = nearest_heading(headings, running_offset)
        if command and command not in seen:
            commands.append(
                {
                    "command": command,
                    "category": classify(command, section),
                    "kind": command_kind(command, section),
                    "section": section,
                    "source": "inline",
                    "needs_substitution": bool(PLACEHOLDER_RE.search(command)),
                }
            )
            seen.add(command)
        running_offset += len(line)

    if not commands:
        warnings.append("No shell-like commands were extracted from the README.")

    counts: Dict[str, int] = {}
    for item in commands:
        category = item["category"]
        counts[category] = counts.get(category, 0) + 1

    return {
        "commands": commands,
        "counts": counts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract shell-like commands from a README.")
    parser.add_argument("--readme", required=True, help="Path to the README file.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    readme_path = Path(args.readme)
    text = readme_path.read_text(encoding="utf-8", errors="replace")
    data = extract_commands(text)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        for item in data["commands"]:
            print(f"[{item['category']}] {item['command']}")
        if data["warnings"]:
            print("Warnings:")
            for warning in data["warnings"]:
                print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
