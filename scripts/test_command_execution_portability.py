#!/usr/bin/env python3
"""Regression checks for direct and explicitly authorized shell execution."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from command_utils import ShellSyntaxRequired, build_command, contains_shell_syntax


def direct_command(argv: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def main() -> int:
    checks = 0
    expected_argument = r"C:\research path\checkpoint model.pt" if os.name == "nt" else "/tmp/research path/checkpoint model.pt"
    command = direct_command(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            expected_argument,
        ]
    )
    argv = build_command(command, "direct")
    result = subprocess.run(argv, capture_output=True, text=True, check=True)
    if result.stdout.strip() != expected_argument:
        raise AssertionError("direct command parsing lost spaces, quotes, or backslashes")
    checks += 1

    for shell_command in ["python a.py | python b.py", "X=1 python a.py", "$env:X='1'; python a.py"]:
        if not contains_shell_syntax(shell_command):
            raise AssertionError(f"shell syntax was not detected: {shell_command}")
        try:
            build_command(shell_command, "direct")
        except ShellSyntaxRequired:
            pass
        else:
            raise AssertionError("direct mode silently accepted shell syntax")
        checks += 2

    if os.name == "nt":
        native_command = "Write-Output 'rigorpilot-native-shell-ok'"
    else:
        native_command = "printf '%s\\n' 'rigorpilot-native-shell-ok'"
    native = subprocess.run(
        build_command(native_command, "native"),
        capture_output=True,
        text=True,
        check=True,
    )
    if native.stdout.strip() != "rigorpilot-native-shell-ok":
        raise AssertionError("explicit native shell mode did not execute through the platform shell")
    checks += 1

    print("ok: True")
    print(f"checks: {checks}")
    print("failures: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
