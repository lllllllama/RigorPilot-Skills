#!/usr/bin/env python3
"""Compatibility wrapper for trusted verify output bundles."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_shared_module():
    module_path = Path(__file__).resolve().parents[3] / "shared" / "scripts" / "write_run_bundle.py"
    spec = importlib.util.spec_from_file_location("write_run_bundle", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load shared writer module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_shared_module()
    return module.main(default_mode="repro", default_output_dir="repro_outputs")


if __name__ == "__main__":
    raise SystemExit(main())
