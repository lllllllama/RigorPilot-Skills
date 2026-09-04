#!/usr/bin/env python3
"""Dependency-free resource snapshots for the persistent command runtime."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _windows_process_sample(pid: int) -> Dict[str, Any]:
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]

    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return {"pid": pid, "available": False, "reason": "process-unavailable", "scope": "root_process"}
    try:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        memory_ok = bool(psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb))
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        times_ok = bool(kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)))

        def filetime_seconds(value: wintypes.FILETIME) -> float:
            ticks = (value.dwHighDateTime << 32) | value.dwLowDateTime
            return ticks / 10_000_000

        return {
            "pid": pid,
            "available": memory_ok or times_ok,
            "rss_bytes": int(counters.WorkingSetSize) if memory_ok else None,
            "peak_rss_bytes": int(counters.PeakWorkingSetSize) if memory_ok else None,
            "cpu_seconds": round(filetime_seconds(kernel) + filetime_seconds(user), 6) if times_ok else None,
            "scope": "root_process",
        }
    finally:
        kernel32.CloseHandle(handle)


def _linux_process_sample(pid: int) -> Dict[str, Any]:
    statm = Path(f"/proc/{pid}/statm")
    stat = Path(f"/proc/{pid}/stat")
    if not statm.is_file() or not stat.is_file():
        return {"pid": pid, "available": False, "reason": "process-unavailable", "scope": "root_process"}
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        rss_pages = int(statm.read_text(encoding="utf-8").split()[1])
        stat_text = stat.read_text(encoding="utf-8")
        fields_after_comm = stat_text[stat_text.rfind(")") + 2 :].split()
        clock_ticks = os.sysconf("SC_CLK_TCK")
        cpu_seconds = (int(fields_after_comm[11]) + int(fields_after_comm[12])) / clock_ticks
        return {
            "pid": pid,
            "available": True,
            "rss_bytes": rss_pages * page_size,
            "peak_rss_bytes": None,
            "cpu_seconds": round(cpu_seconds, 6),
            "scope": "root_process",
        }
    except (OSError, ValueError, IndexError) as exc:
        return {"pid": pid, "available": False, "reason": f"sample-failed:{type(exc).__name__}", "scope": "root_process"}


def process_sample(pid: int) -> Dict[str, Any]:
    if os.name == "nt":
        return _windows_process_sample(pid)
    if Path("/proc").is_dir():
        return _linux_process_sample(pid)
    return {"pid": pid, "available": False, "reason": "unsupported-platform", "scope": "root_process"}


def system_sample() -> Dict[str, Any]:
    total_memory = None
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total_memory = int(status.ullTotalPhys)
    else:
        try:
            total_memory = int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
        except (AttributeError, OSError, ValueError):
            pass
    return {"logical_cpu_count": os.cpu_count(), "total_memory_bytes": total_memory}


def nvidia_gpu_sample(timeout: float = 1.0) -> Dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"provider": "nvidia", "available": False, "scope": "device_global", "devices": []}
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "provider": "nvidia",
            "available": False,
            "scope": "device_global",
            "devices": [],
            "reason": f"query-failed:{type(exc).__name__}",
        }
    devices = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 5:
                continue
            try:
                devices.append(
                    {
                        "index": int(parts[0]),
                        "uuid": parts[1],
                        "memory_used_mib": float(parts[2]),
                        "memory_total_mib": float(parts[3]),
                        "utilization_percent": float(parts[4]),
                    }
                )
            except ValueError:
                continue
    return {
        "provider": "nvidia",
        "available": result.returncode == 0,
        "scope": "device_global",
        "devices": devices,
        "reason": None if result.returncode == 0 else "nvidia-smi-nonzero",
    }


def sample_resources(pid: int, include_gpu: bool = True) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "timestamp": utc_now(),
        "process": process_sample(pid),
        "system": system_sample(),
        "accelerators": nvidia_gpu_sample() if include_gpu else {
            "provider": "nvidia",
            "available": False,
            "scope": "device_global",
            "devices": [],
            "reason": "sampling-disabled",
        },
    }


def append_resource_sample(path: Path, sample: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
