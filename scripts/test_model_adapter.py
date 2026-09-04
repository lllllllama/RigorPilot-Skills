#!/usr/bin/env python3
"""Verify provider-neutral model profile validation and capability gates."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from model_adapter import ModelAdapterError, missing_capabilities, normalize_model_profile, profile_fingerprint


def main() -> int:
    checks = 0
    raw = {
        "adapter_id": "lab-gateway",
        "provider": "openai-compatible",
        "model": "research-model",
        "revision": "2026-09-01",
        "capabilities": {"structured_output": True, "tool_calling": True, "vision": False},
        "credential_env": "LAB_MODEL_API_KEY",
        "parameters": {"temperature": 0},
    }
    profile = normalize_model_profile(raw)
    if profile["capabilities"] != ["structured_output", "tool_calling"] or len(profile["fingerprint"]) != 64:
        raise AssertionError("valid model profile was not normalized deterministically")
    if missing_capabilities(profile, ["tool_calling", "vision"]) != ["vision"]:
        raise AssertionError("model capability gate returned the wrong missing set")
    if profile_fingerprint({**profile, "source_path": "D:/different/location.json"}) != profile["fingerprint"]:
        raise AssertionError("model fingerprint changed with a non-semantic source path")
    checks += 3

    for unsafe in [
        {**raw, "api_key": "inline-secret"},
        {**raw, "metadata": {"authorization": "Bearer inline-secret"}},
        {**raw, "credential_env": "not an env name"},
        {**raw, "endpoint": "https://user:password@example.test/v1"},
    ]:
        try:
            normalize_model_profile(unsafe)
        except ModelAdapterError:
            checks += 1
        else:
            raise AssertionError("unsafe model profile was accepted")

    with tempfile.TemporaryDirectory(prefix="rigorpilot-model-adapter-") as temporary:
        profile_path = Path(temporary) / "profile.json"
        profile_path.write_text(json.dumps(raw), encoding="utf-8")
        compatible = subprocess.run(
            [
                sys.executable,
                str(SHARED_SCRIPTS / "model_adapter.py"),
                "--profile",
                str(profile_path),
                "--require",
                "tool_calling",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        incompatible = subprocess.run(
            [
                sys.executable,
                str(SHARED_SCRIPTS / "model_adapter.py"),
                "--profile",
                str(profile_path),
                "--require",
                "vision",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if compatible.returncode != 0 or json.loads(compatible.stdout)["status"] != "compatible":
            raise AssertionError("compatible model profile failed CLI validation")
        if incompatible.returncode != 3 or json.loads(incompatible.stdout)["missing_capabilities"] != ["vision"]:
            raise AssertionError("incompatible model profile did not fail with a capability report")
        checks += 2

    print("ok: True")
    print(f"checks: {checks}")
    print("failures: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
