"""Execution feasibility and smoke-validation pass for ai-research-explore."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence


UNSAFE_RUNTIME_IMPORT_FILES = {
    "train.py",
    "eval.py",
    "main.py",
    "__main__.py",
}


def exec_module_silenced(spec: importlib.machinery.ModuleSpec, module: Any) -> None:
    # Probed repo modules may print at import time; swallow that output so the
    # orchestrator's stdout stays a clean JSON payload.
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        spec.loader.exec_module(module)


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def memory_info() -> Dict[str, Any]:
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "available_gb": round(vm.available / (1024 ** 3), 2),
            "percent_used": round(vm.percent, 2),
        }
    except Exception:
        return {
            "total_gb": None,
            "available_gb": None,
            "percent_used": None,
        }


def disk_info(root: Path) -> Dict[str, Any]:
    usage = shutil.disk_usage(root)
    return {
        "total_gb": round(usage.total / (1024 ** 3), 2),
        "available_gb": round(usage.free / (1024 ** 3), 2),
        "percent_used": round((usage.used / usage.total) * 100.0, 2) if usage.total else 0.0,
    }


def detect_nvidia() -> List[Dict[str, Any]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    gpus: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if not parts:
            continue
        gpus.append(
            {
                "name": parts[0],
                "memory_gb": round(safe_float(parts[1]) / 1024.0, 2) if len(parts) > 1 else None,
                "backend": "CUDA",
            }
        )
    return gpus


def detect_rocm() -> List[Dict[str, Any]]:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    gpus: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        lowered = line.lower()
        if "card series" in lowered:
            gpus.append({"name": line.split(":", 1)[-1].strip(), "memory_gb": None, "backend": "ROCm"})
    return gpus


def detect_resources(root: Path) -> Dict[str, Any]:
    nvidia_gpus = detect_nvidia()
    rocm_gpus = detect_rocm()
    available_backends = sorted({gpu["backend"] for gpu in nvidia_gpus + rocm_gpus})
    return {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "cpu": {
            "logical_cores": os.cpu_count(),
        },
        "memory": memory_info(),
        "disk": disk_info(root),
        "gpu": {
            "nvidia_gpus": nvidia_gpus,
            "amd_gpus": rocm_gpus,
            "available_backends": available_backends,
            "total_gpus": len(nvidia_gpus) + len(rocm_gpus),
        },
    }


def parse_command_paths(command: str) -> List[str]:
    paths: List[str] = []
    for token in re.findall(r"[\w./\\-]+\.(?:py|ya?ml|json|toml|ini)", command):
        cleaned = token.strip().strip("\"'").replace("\\", "/")
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
    return paths


def syntax_check(repo_path: Path, smoke_plan: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    python_files: List[str] = []
    for check in smoke_plan:
        if check.get("name") == "syntax-parse":
            python_files.extend(check.get("scope", []))
    unique_files: List[str] = []
    for item in python_files:
        if item not in unique_files:
            unique_files.append(item)
    blockers: List[str] = []
    passed: List[str] = []
    for rel in unique_files:
        path = repo_path / rel
        if not path.exists():
            blockers.append(f"missing:{rel}")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            passed.append(rel)
        except SyntaxError as exc:
            blockers.append(f"syntax:{rel}:{exc.lineno}")
    return {
        "name": "syntax-parse",
        "status": "passed" if not blockers else "failed",
        "passed": passed,
        "blockers": blockers,
    }


def config_check(repo_path: Path, base_command: str) -> Dict[str, Any]:
    blockers: List[str] = []
    passed: List[str] = []
    for rel in parse_command_paths(base_command):
        path = repo_path / rel
        if path.exists():
            passed.append(rel)
        else:
            blockers.append(rel)
    return {
        "name": "config-path",
        "status": "passed" if not blockers else "failed",
        "passed": passed,
        "blockers": blockers,
    }


def surface_check(name: str, values: Sequence[str], *, optional: bool = False) -> Dict[str, Any]:
    if values:
        return {
            "name": name,
            "status": "passed",
            "passed": list(values),
            "blockers": [],
        }
    if optional:
        return {
            "name": name,
            "status": "passed",
            "passed": [],
            "blockers": [],
            "notes": [f"missing-{name}"],
        }
    return {
        "name": name,
        "status": "planned",
        "passed": [],
        "blockers": [f"missing-{name}"],
    }


def import_resolution_check(target_location_map: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    scopes = [item["file"] for item in target_location_map if str(item["file"]).endswith(".py")]
    return {
        "name": "import-resolution",
        "status": "passed" if scopes else "planned",
        "passed": scopes,
        "blockers": [] if scopes else ["no-python-targets"],
    }


def safe_runtime_targets(target_location_map: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for item in target_location_map:
        file_name = Path(str(item.get("file") or "")).name.lower()
        if str(item.get("role") or "") != "code":
            continue
        if not str(item.get("file") or "").endswith(".py"):
            continue
        if file_name in UNSAFE_RUNTIME_IMPORT_FILES:
            continue
        targets.append(item)
    return targets


def import_probe_check(repo_path: Path, target_location_map: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    targets = safe_runtime_targets(target_location_map)
    if not targets:
        return {
            "name": "import-probe",
            "status": "passed",
            "passed": [],
            "blockers": [],
            "notes": ["no-safe-import-targets"],
        }
    passed: List[str] = []
    blockers: List[str] = []
    sys_path_added = False
    repo_root = str(repo_path)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
        sys_path_added = True
    try:
        for item in targets:
            rel = str(item.get("file") or "")
            module_path = repo_path / rel
            if not module_path.exists():
                blockers.append(f"missing:{rel}")
                continue
            module_name = f"_research_explore_smoke_{hashlib.sha1(rel.encode('utf-8')).hexdigest()[:12]}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    blockers.append(f"import-spec:{rel}")
                    continue
                module = importlib.util.module_from_spec(spec)
                exec_module_silenced(spec, module)
                passed.append(rel)
            except ModuleNotFoundError as exc:
                blockers.append(f"missing-dependency:{rel}:{exc.name or 'unknown'}")
            except Exception as exc:  # pragma: no cover - defensive, exercised via repo fixtures
                blockers.append(f"import-error:{rel}:{exc.__class__.__name__}")
            finally:
                sys.modules.pop(module_name, None)
    finally:
        if sys_path_added:
            try:
                sys.path.remove(repo_root)
            except ValueError:
                pass
    hard_blockers = [item for item in blockers if not item.startswith("missing-dependency:")]
    soft_blockers = [item for item in blockers if item.startswith("missing-dependency:")]
    return {
        "name": "import-probe",
        "status": "failed" if hard_blockers else "planned" if soft_blockers else "passed",
        "passed": passed,
        "blockers": hard_blockers,
        "notes": soft_blockers,
    }


def constructor_probe_check(repo_path: Path, target_location_map: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    targets = safe_runtime_targets(target_location_map)
    if not targets:
        return {
            "name": "constructor-probe",
            "status": "passed",
            "passed": [],
            "blockers": [],
            "notes": ["constructor-probe-not-applicable"],
        }
    passed: List[str] = []
    blockers: List[str] = []
    soft_notes: List[str] = []
    sys_path_added = False
    repo_root = str(repo_path)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
        sys_path_added = True
    try:
        for item in targets:
            rel = str(item.get("file") or "")
            target_symbol = str(item.get("target_symbol") or "")
            symbol_root = target_symbol
            if ":" in symbol_root:
                symbol_root = symbol_root.split(":", 1)[1]
            symbol_root = symbol_root.split(".", 1)[0].strip()
            if not symbol_root or symbol_root == "unspecified-symbol":
                soft_notes.append(f"unresolved-target-symbol:{rel}")
                continue
            module_path = repo_path / rel
            module_name = f"_research_explore_ctor_{hashlib.sha1(rel.encode('utf-8')).hexdigest()[:12]}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    blockers.append(f"constructor-spec:{rel}")
                    continue
                module = importlib.util.module_from_spec(spec)
                exec_module_silenced(spec, module)
                if hasattr(module, symbol_root):
                    passed.append(f"{rel}:{symbol_root}")
                else:
                    blockers.append(f"missing-symbol:{rel}:{symbol_root}")
            except ModuleNotFoundError as exc:
                soft_notes.append(f"missing-dependency:{rel}:{exc.name or 'unknown'}")
            except Exception as exc:  # pragma: no cover - defensive, exercised via repo fixtures
                blockers.append(f"constructor-error:{rel}:{exc.__class__.__name__}")
            finally:
                sys.modules.pop(module_name, None)
    finally:
        if sys_path_added:
            try:
                sys.path.remove(repo_root)
            except ValueError:
                pass
    return {
        "name": "constructor-probe",
        "status": "failed" if blockers else "passed",
        "passed": passed,
        "blockers": blockers,
        "notes": soft_notes,
    }


def short_run_check(executed_runs: Sequence[Dict[str, Any]], variant_matrix: Dict[str, Any]) -> Dict[str, Any]:
    if executed_runs:
        statuses = [item.get("status", "unknown") for item in executed_runs]
        return {
            "name": "short-run-command",
            "status": "passed" if any(status in {"success", "partial"} for status in statuses) else "failed",
            "passed": [item.get("id", "unknown") for item in executed_runs],
            "blockers": [] if any(status in {"success", "partial"} for status in statuses) else statuses,
        }
    if variant_matrix.get("base_command"):
        return {
            "name": "short-run-command",
            "status": "planned",
            "passed": [],
            "blockers": ["not-executed-yet"],
        }
    return {
        "name": "short-run-command",
        "status": "failed",
        "passed": [],
        "blockers": ["missing-base-command"],
    }


def recommend_strategy(resources: Dict[str, Any]) -> Dict[str, Any]:
    logical_cores = resources["cpu"].get("logical_cores") or 1
    available_memory = resources["memory"].get("available_gb") or 0.0
    backends = resources["gpu"].get("available_backends", [])
    if logical_cores >= 8:
        parallel_strategy = "high-parallelism"
        suggested_workers = max(1, logical_cores - 2)
    elif logical_cores >= 4:
        parallel_strategy = "moderate-parallelism"
        suggested_workers = max(1, logical_cores - 1)
    else:
        parallel_strategy = "low-parallelism"
        suggested_workers = 1
    memory_strategy = "memory-abundant" if available_memory >= 16 else "moderate-memory" if available_memory >= 4 else "memory-constrained"
    acceleration = (
        f"Use {', '.join(backends)} acceleration for short-run probes."
        if backends
        else "No GPU backend detected; keep early exploratory runs small and CPU-safe."
    )
    return {
        "parallel_strategy": parallel_strategy,
        "suggested_workers": suggested_workers,
        "memory_strategy": memory_strategy,
        "acceleration_suggestion": acceleration,
    }


def feasibility_decision(
    *,
    campaign: Dict[str, Any],
    variant_matrix: Dict[str, Any],
    resources: Dict[str, Any],
) -> Dict[str, Any]:
    budget_hours = safe_float((campaign.get("compute_budget") or {}).get("max_runtime_hours")) or 0.0
    executed_budget = safe_float((campaign.get("execution_policy") or {}).get("max_executed_variants")) * safe_float(
        (campaign.get("execution_policy") or {}).get("variant_timeout")
    )
    estimated_hours = executed_budget / 3600.0 if executed_budget else 0.0
    short_run_status = "proceed"
    full_run_status = "proceed"
    blockers: List[str] = []
    if not variant_matrix.get("base_command"):
        short_run_status = "blocked"
        full_run_status = "blocked"
        blockers.append("missing-base-command")
    if budget_hours and estimated_hours > budget_hours:
        full_run_status = "borderline"
    if resources["gpu"].get("total_gpus", 0) == 0 and variant_matrix.get("variant_count", 0) > 2:
        full_run_status = "borderline"
    return {
        "short_run_feasibility": short_run_status,
        "full_run_feasibility": full_run_status,
        "estimated_short_run_hours": round(estimated_hours, 4),
        "budget_hours": budget_hours,
        "blockers": blockers,
    }


def write_resource_plan(output_dir: Path, resources: Dict[str, Any], recommendations: Dict[str, Any], feasibility: Dict[str, Any]) -> Path:
    lines = [
        "# Resource Plan",
        "",
        f"- OS: `{resources['os']['system']} {resources['os']['release']}`",
        f"- CPU logical cores: `{resources['cpu'].get('logical_cores')}`",
        f"- Memory available (GB): `{resources['memory'].get('available_gb')}`",
        f"- Disk available (GB): `{resources['disk'].get('available_gb')}`",
        f"- GPU backends: `{', '.join(resources['gpu'].get('available_backends', [])) or 'none'}`",
        f"- Short-run feasibility: `{feasibility['short_run_feasibility']}`",
        f"- Full-run feasibility: `{feasibility['full_run_feasibility']}`",
        "",
        "## Recommendations",
        "",
        f"- Parallel strategy: `{recommendations['parallel_strategy']}` with `{recommendations['suggested_workers']}` workers",
        f"- Memory strategy: `{recommendations['memory_strategy']}`",
        f"- Acceleration: {recommendations['acceleration_suggestion']}",
        "",
    ]
    if feasibility["blockers"]:
        lines.extend(["## Blockers", "", *[f"- {item}" for item in feasibility["blockers"]], ""])
    path = output_dir / "RESOURCE_PLAN.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def summarize_smoke(checks: Sequence[Dict[str, Any]], ignored_blockers: Sequence[str]) -> Dict[str, Any]:
    blockers = [
        blocker
        for item in checks
        for blocker in item.get("blockers", [])
        if blocker not in ignored_blockers
    ]
    statuses = {item["status"] for item in checks}
    if statuses <= {"passed"}:
        status = "passed"
    elif statuses <= {"passed", "planned"}:
        status = "planned"
    else:
        status = "failed"
    return {
        "checks": list(checks),
        "status": status,
        "blockers": blockers,
    }


def run_execution_feasibility_pass(
    *,
    analysis_output_dir: Path,
    repo_path: Path,
    campaign: Dict[str, Any],
    analysis_data: Dict[str, Any],
    variant_matrix: Dict[str, Any],
    source_mapping: Dict[str, Any],
    executed_runs: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    resources = detect_resources(analysis_output_dir.parent)
    recommendations = recommend_strategy(resources)
    feasibility = feasibility_decision(campaign=campaign, variant_matrix=variant_matrix, resources=resources)
    static_checks = [
        syntax_check(repo_path, source_mapping.get("smoke_plan", [])),
        import_resolution_check(source_mapping.get("target_location_map", [])),
        config_check(repo_path, str(variant_matrix.get("base_command") or "")),
        surface_check("constructor-surface", analysis_data.get("constructor_candidates", [])[:4], optional=True),
        surface_check("forward-surface", analysis_data.get("forward_candidates", [])[:4], optional=True),
    ]
    runtime_checks = [
        import_probe_check(repo_path, source_mapping.get("target_location_map", [])),
        constructor_probe_check(repo_path, source_mapping.get("target_location_map", [])),
        short_run_check(executed_runs, variant_matrix),
    ]
    static_smoke = summarize_smoke(
        static_checks,
        ignored_blockers=("no-python-targets", "missing-constructor-surface", "missing-forward-surface"),
    )
    runtime_smoke = summarize_smoke(runtime_checks, ignored_blockers=("not-executed-yet",))
    overall_status = "failed"
    if static_smoke["status"] == "passed" and runtime_smoke["status"] == "passed":
        overall_status = "passed"
    elif static_smoke["status"] in {"passed", "planned"} and runtime_smoke["status"] in {"passed", "planned"}:
        overall_status = "planned"
    smoke_report = {
        "static_smoke": static_smoke,
        "runtime_smoke": runtime_smoke,
        "status": overall_status,
        "blockers": [*static_smoke["blockers"], *runtime_smoke["blockers"]],
    }
    resource_plan_path = write_resource_plan(analysis_output_dir, resources, recommendations, feasibility)
    return {
        "schema_version": "1.0",
        "artifact_path": str(resource_plan_path),
        "resources": resources,
        "recommendations": recommendations,
        "feasibility": feasibility,
        "static_smoke": static_smoke,
        "runtime_smoke": runtime_smoke,
        "smoke_report": smoke_report,
    }

