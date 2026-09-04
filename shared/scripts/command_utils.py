#!/usr/bin/env python3
"""Cross-platform command construction with explicit shell authorization."""

from __future__ import annotations

import ctypes
import os
import re
import shlex
import shutil
from ctypes import wintypes
from typing import List


class ShellSyntaxRequired(ValueError):
    """Raised when a direct command contains syntax that requires a shell."""


ENV_PREFIX_RE = re.compile(
    r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*\S+\s+|^\s*\$env:[A-Za-z_][A-Za-z0-9_]*\s*=",
    flags=re.IGNORECASE,
)


def contains_shell_syntax(command: str) -> bool:
    """Return True for unquoted operators or environment-assignment prefixes."""

    if "\n" in command or "\r" in command or ENV_PREFIX_RE.search(command):
        return True
    quote: str | None = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in {"|", "&", ";", "<", ">", "(", ")"}:
            return True
    return False


def split_windows_command_line(command: str) -> List[str]:
    """Parse a command with the same quoting rules used by Windows CreateProcess."""

    if os.name != "nt":
        raise RuntimeError("Windows command-line parsing is only available on Windows")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    argc = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(command, ctypes.byref(argc))
    if not argv:
        raise OSError(ctypes.get_last_error(), "CommandLineToArgvW failed")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        kernel32.LocalFree(argv)


def build_command(command: str, shell_mode: str = "direct") -> List[str]:
    """Build subprocess argv, requiring explicit opt-in for native shell syntax."""

    if shell_mode not in {"direct", "native"}:
        raise ValueError(f"Unsupported shell mode: {shell_mode}")
    if shell_mode == "native":
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
            return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
        return ["/bin/sh", "-lc", command]

    if contains_shell_syntax(command):
        raise ShellSyntaxRequired(
            "The documented command contains shell syntax. Re-run with --shell-mode native only after reviewing the command."
        )
    if os.name == "nt":
        return split_windows_command_line(command)
    return shlex.split(command, posix=True)
