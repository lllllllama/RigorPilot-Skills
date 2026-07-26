#!/usr/bin/env python3
"""Conservative research debugging without automatic patching."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


CATEGORY_RULES = [
    ("cuda_oom", ["cuda out of memory", "outofmemoryerror", "out of memory"]),
    ("checkpoint_mismatch", ["size mismatch", "missing key", "unexpected key", "checkpoint"]),
    ("distributed_issue", ["nccl", "distributed", "ddp", "rank"]),
    ("device_mismatch", ["expected all tensors to be on the same device", "same device"]),
    ("shape_mismatch", ["shape", "dimension", "size mismatch"]),
    ("loss_nan", ["loss is nan", "nan", "not converging"]),
    ("file_missing", ["filenotfounderror", "no such file", "cannot find path"]),
]


def classify_error(text: str) -> str:
    lower = text.lower()
    for category, signals in CATEGORY_RULES:
        if any(signal in lower for signal in signals):
            return category
    if "traceback" in lower or "runtimeerror" in lower or "valueerror" in lower:
        return "runtime_failure"
    return "unknown"


def suggested_actions(category: str) -> List[str]:
    mapping = {
        "cuda_oom": [
            "Check effective batch size, input resolution, and mixed-precision settings before patching model code.",
            "Prefer a configuration-only reduction before touching architecture.",
        ],
        "checkpoint_mismatch": [
            "Verify checkpoint source, model variant, and load strictness assumptions.",
            "Confirm whether the mismatch is expected before introducing compatibility code.",
        ],
        "distributed_issue": [
            "Inspect launch command, world size, and environment variables before patching training logic.",
            "Reproduce with a single process when possible to narrow the issue safely.",
        ],
        "device_mismatch": [
            "Trace where tensors and modules move across CPU and GPU boundaries.",
            "Prefer a minimal device-placement fix over a broad refactor.",
        ],
        "shape_mismatch": [
            "Log tensor shapes at the failing boundary without changing unrelated code paths.",
            "Check config, dataset, and head dimensions before editing model internals.",
        ],
        "loss_nan": [
            "Inspect data ranges, loss inputs, mixed precision, and learning rate before changing architecture.",
            "Use a shorter controlled run to confirm whether NaNs appear at startup or later.",
        ],
        "file_missing": [
            "Validate dataset, checkpoint, and config paths before editing code.",
            "Prefer a path fix or documented setup correction over logic changes.",
        ],
        "runtime_failure": [
            "Trace the failing file and symbol before proposing any patch.",
            "Confirm whether the failure is environment-related, config-related, or code-related.",
        ],
        "unknown": [
            "Collect the full command, stack trace, and recent code change before patching anything.",
            "Narrow the failure surface with the smallest reproducible example available.",
        ],
    }
    return mapping[category]


def analyze_error(text: str) -> Dict[str, object]:
    category = classify_error(text)
    needs_savepoint = category in {"checkpoint_mismatch", "distributed_issue", "shape_mismatch", "loss_nan"}
    return {
        "category": category,
        "summary": f"Detected debug category: `{category}`.",
        "needs_explicit_patch_approval": True,
        "needs_savepoint_before_patch": needs_savepoint,
        "actions": suggested_actions(category),
        "error_excerpt": "\n".join(text.splitlines()[:12]) or text,
    }


def write_outputs(output_dir: Path, data: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    diagnosis = [
        "# Debug Diagnosis",
        "",
        f"- Category: `{data['category']}`",
        f"- Patch authorized: `False`",
        f"- Savepoint recommended before patching: `{data['needs_savepoint_before_patch']}`",
        "",
        "## Error excerpt",
        "",
        "```text",
        data["error_excerpt"],
        "```",
        "",
        "## Conservative analysis",
        "",
        data["summary"],
        "",
    ]
    (output_dir / "DIAGNOSIS.md").write_text("\n".join(diagnosis), encoding="utf-8")

    patch_plan = [
        "# Patch Plan",
        "",
        "- Do not modify repository code until the researcher approves the proposed fix.",
        "- Prefer the smallest configuration or path fix before touching core model logic.",
        f"- Savepoint recommended: `{data['needs_savepoint_before_patch']}`",
        "",
        "## Suggested actions",
        "",
        *[f"- {item}" for item in data["actions"]],
        "",
    ]
    (output_dir / "PATCH_PLAN.md").write_text("\n".join(patch_plan), encoding="utf-8")

    status = {
        "schema_version": "1.0",
        "status": "diagnosed",
        "category": data["category"],
        "patch_authorized": False,
        "needs_explicit_patch_approval": data["needs_explicit_patch_approval"],
        "needs_savepoint_before_patch": data["needs_savepoint_before_patch"],
        "suggested_actions": data["actions"],
        "outputs": {
            "diagnosis": "debug_outputs/DIAGNOSIS.md",
            "patch_plan": "debug_outputs/PATCH_PLAN.md",
            "status": "debug_outputs/status.json",
        },
    }
    (output_dir / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Conservative deep learning research debugging.")
    parser.add_argument("--error-file", help="Path to a text file containing the error or symptom.")
    parser.add_argument("--error-text", help="Inline error or symptom text.")
    parser.add_argument("--output-dir", default="debug_outputs", help="Directory for debug outputs.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout instead of writing files.")
    args = parser.parse_args()

    if not args.error_file and not args.error_text:
        raise SystemExit("Provide --error-file or --error-text.")

    text = args.error_text or Path(args.error_file).read_text(encoding="utf-8", errors="ignore")
    data = analyze_error(text)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    write_outputs(Path(args.output_dir).resolve(), data)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
