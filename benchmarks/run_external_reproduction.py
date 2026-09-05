#!/usr/bin/env python3
"""Run one pinned, fresh-workspace external repository reproduction case."""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = REPO_ROOT / "shared" / "scripts"
sys.path.insert(0, str(SHARED_SCRIPTS))

from runtime_runner import run_persistent_command  # noqa: E402


REQUIRED_EVIDENCE = {
    "SUMMARY.md",
    "COMMANDS.md",
    "LOG.md",
    "SCIENTIFIC_CHANGELOG.md",
    "COMPARABILITY_REPORT.md",
    "status.json",
    "ANNOTATED_README.md",
}
SECRET_NAME_RE = re.compile(r"(?:key|token|secret|password|credential)", re.IGNORECASE)
ANNOTATION_BEGIN = "<!-- rigorpilot:repro:begin"
ANNOTATION_END = "<!-- rigorpilot:repro:end -->"
ANNOTATION_BLOCK_RE = re.compile(
    r"<!-- rigorpilot:repro:begin\b[^>]*-->.*?<!-- rigorpilot:repro:end -->\r?\n?",
    re.DOTALL,
)
HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def command_for(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def relative(path: Optional[str | Path], base: Path) -> Optional[str]:
    if not path:
        return None
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(base.resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved)


@contextmanager
def temporary_environment(overrides: Dict[str, str], remove: set[str]) -> Iterator[None]:
    affected = set(overrides).union(remove)
    prior = {key: os.environ.get(key) for key in affected}
    try:
        for key in remove:
            os.environ.pop(key, None)
        os.environ.update(overrides)
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def safe_environment(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("step environment must be an object")
    result = {str(key): str(value) for key, value in raw.items()}
    unsafe = [key for key in result if SECRET_NAME_RE.search(key)]
    if unsafe:
        raise ValueError(f"external benchmark refuses secret-bearing environment fields: {unsafe}")
    return result


def phase_record(name: str, command: str, result: Dict[str, Any], case_root: Path, source: str) -> Dict[str, Any]:
    return {
        "name": name,
        "source": source,
        "command": command,
        "status": result.get("runtime_status"),
        "returncode": result.get("returncode"),
        "duration_seconds": result.get("duration_seconds"),
        "runtime_dir": relative(result.get("runtime_dir"), case_root),
        "stdout_tail": str(result.get("stdout") or "")[-4000:],
        "stderr_tail": str(result.get("stderr") or "")[-4000:],
        "resource_summary": result.get("resource_summary", {}),
    }


def run_phase(
    *,
    name: str,
    argv: list[str],
    cwd: Path,
    runtime_root: Path,
    case_root: Path,
    timeout: int,
    source: str,
    environment: Optional[Dict[str, str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    command = command_for(argv)
    sensitive_names = {key for key in os.environ if SECRET_NAME_RE.search(key)}
    with temporary_environment(environment or {}, sensitive_names):
        result = run_persistent_command(
            repo=cwd,
            command=command,
            timeout=timeout,
            runtime_root=runtime_root,
            shell_mode="direct",
            monitor_gpu=False,
        )
    return result, phase_record(name, command, result, case_root, source)


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def load_case(manifest_path: Path, case_name: str) -> tuple[Dict[str, Any], str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    cases = manifest.get("cases")
    if not isinstance(cases, dict) or case_name not in cases:
        raise ValueError(f"Unknown external benchmark case: {case_name}")
    case = cases[case_name]
    if case.get("status") != "ready":
        raise ValueError(f"Case {case_name} is {case.get('status')}, not ready for execution")
    commit = str(case.get("commit") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise ValueError(f"Case {case_name} must pin a Git commit")
    return case, str(manifest.get("schema_version") or "1.0")


def format_step_argv(values: list[Any], python_path: Path, repo: Path, case_root: Path) -> list[str]:
    replacements = {"{python}": str(python_path), "{repo}": str(repo), "{case_root}": str(case_root)}
    formatted: list[str] = []
    for raw in values:
        value = str(raw)
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        formatted.append(value)
    return formatted


def write_report(output_path: Path, report: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for candidate in path.rglob("*"):
        try:
            if candidate.is_file():
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


def safe_remove_workspace(case_root: Path, work_root: Path) -> None:
    resolved_case = case_root.resolve()
    resolved_work = work_root.resolve()
    if resolved_case.parent != resolved_work or not resolved_case.name:
        raise RuntimeError(f"refusing to clean unexpected benchmark path: {resolved_case}")
    if resolved_case.exists():
        def remove_readonly(function: Any, path: str, _excinfo: Any) -> None:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)

        shutil.rmtree(resolved_case, onerror=remove_readonly)


def archive_evidence(evidence_dir: Path, archive_dir: Path) -> Dict[str, Any]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    files: list[Dict[str, Any]] = []
    for name in sorted(REQUIRED_EVIDENCE):
        source = evidence_dir / name
        target = archive_dir / name
        if not source.is_file():
            if target.exists():
                target.unlink()
            continue
        shutil.copy2(source, target)
        payload = target.read_bytes()
        files.append({"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return {
        "directory": relative(archive_dir, REPO_ROOT),
        "files": files,
        "total_bytes": sum(item["bytes"] for item in files),
    }


def safe_remove_showcase(target: Path, showcase_root: Path) -> None:
    resolved_target = target.resolve()
    resolved_root = showcase_root.resolve()
    if resolved_target.parent != resolved_root or not resolved_target.name:
        raise RuntimeError(f"refusing to replace unexpected showcase path: {resolved_target}")
    if resolved_target.exists():
        def remove_readonly(function: Any, path: str, _excinfo: Any) -> None:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)

        shutil.rmtree(resolved_target, onerror=remove_readonly)


def tracked_repository_files(repo: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "git ls-files failed")
    return [Path(item.decode("utf-8", errors="surrogateescape")) for item in result.stdout.split(b"\0") if item]


def rebase_inserted_evidence_links(annotated_bytes: bytes, evidence_prefix: str, train_prefix: str) -> bytes:
    bom = annotated_bytes.startswith(b"\xef\xbb\xbf")
    payload = annotated_bytes[3:] if bom else annotated_bytes
    decoded = payload.decode("utf-8", errors="surrogateescape")

    def replace_links(match: re.Match[str]) -> str:
        block = match.group(0)
        for _label, target in [
            ("SUMMARY", "SUMMARY.md"),
            ("COMMANDS", "COMMANDS.md"),
            ("LOG", "LOG.md"),
            ("status.json", "status.json"),
        ]:
            block = block.replace(f"]({target})", f"]({evidence_prefix}{target})")
        block = block.replace("](../train_outputs/status.json)", f"]({train_prefix}status.json)")
        return block

    rebased = ANNOTATION_BLOCK_RE.sub(replace_links, decoded).encode("utf-8", errors="surrogateescape")
    return (b"\xef\xbb\xbf" if bom else b"") + rebased


def preserve_showcase(
    *,
    repo: Path,
    case_root: Path,
    evidence_dir: Path,
    source_readme: Path,
    showcase_root: Path,
    case_name: str,
    repository_url: str,
    commit: str,
) -> Dict[str, Any]:
    showcase_root.mkdir(parents=True, exist_ok=True)
    target = showcase_root / case_name
    safe_remove_showcase(target, showcase_root)
    snapshot_repo = target / "repo"
    snapshot_repo.mkdir(parents=True)
    tracked = tracked_repository_files(repo)
    for relative_path in tracked:
        source = (repo / relative_path).resolve()
        destination = (snapshot_repo / relative_path).resolve()
        try:
            source.relative_to(repo.resolve())
            destination.relative_to(snapshot_repo.resolve())
        except ValueError:
            raise RuntimeError(f"tracked showcase path escapes repository: {relative_path}")
        if not source.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    shutil.copytree(evidence_dir, snapshot_repo / "repro_outputs", dirs_exist_ok=True)
    train_dir = case_root / "train_outputs"
    if train_dir.is_dir():
        shutil.copytree(train_dir, snapshot_repo / "train_outputs", dirs_exist_ok=True)

    readme_relative = source_readme.resolve().relative_to(repo.resolve())
    snapshot_readme = snapshot_repo / readme_relative
    showcase_readme = snapshot_readme.parent / "RIGORPILOT_README.md"
    evidence_prefix = os.path.relpath(snapshot_repo / "repro_outputs", showcase_readme.parent).replace("\\", "/") + "/"
    train_prefix = os.path.relpath(snapshot_repo / "train_outputs", showcase_readme.parent).replace("\\", "/") + "/"
    rebased = rebase_inserted_evidence_links(
        (evidence_dir / "ANNOTATED_README.md").read_bytes(),
        evidence_prefix,
        train_prefix,
    )
    if strip_annotation_bytes(rebased)[0] != snapshot_readme.read_bytes():
        raise RuntimeError("showcase README did not round-trip to the retained repository README")
    showcase_readme.write_bytes(rebased)
    manifest = {
        "schema_version": "1.0",
        "repository": repository_url,
        "commit": commit,
        "tracked_files_retained": len(tracked),
        "original_readme": readme_relative.as_posix(),
        "annotated_readme": showcase_readme.relative_to(target).as_posix(),
        "original_sha256": hashlib.sha256(snapshot_readme.read_bytes()).hexdigest(),
        "stripped_sha256": hashlib.sha256(strip_annotation_bytes(rebased)[0]).hexdigest(),
        "retained_content_bytes": directory_size(snapshot_repo),
    }
    (target / "SHOWCASE.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def strip_annotation_bytes(value: bytes) -> tuple[bytes, int, int]:
    bom = value.startswith(b"\xef\xbb\xbf")
    payload = value[3:] if bom else value
    decoded = payload.decode("utf-8", errors="surrogateescape")
    begin_count = decoded.count(ANNOTATION_BEGIN)
    end_count = decoded.count(ANNOTATION_END)
    if begin_count != end_count:
        raise ValueError(f"unbalanced annotation markers: begin={begin_count}, end={end_count}")
    stripped, removed = ANNOTATION_BLOCK_RE.subn("", decoded)
    if removed != begin_count:
        raise ValueError(f"only {removed}/{begin_count} annotation blocks were strippable")
    section_count = decoded.count('rigorpilot:repro:begin kind="section"')
    result = stripped.encode("utf-8", errors="surrogateescape")
    return ((b"\xef\xbb\xbf" if bom else b"") + result, removed, section_count)


def count_atx_headings(value: bytes) -> int:
    payload = value[3:] if value.startswith(b"\xef\xbb\xbf") else value
    decoded = payload.decode("utf-8", errors="surrogateescape")
    count = 0
    fence_char: Optional[str] = None
    fence_length = 0
    for line in decoded.splitlines():
        fence = FENCE_RE.match(line)
        if fence_char is not None:
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_length:
                fence_char = None
                fence_length = 0
            continue
        if fence:
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            continue
        if HEADING_RE.match(line):
            count += 1
    return count


def content_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted({item.resolve() for item in paths}, key=lambda item: str(item).lower()):
        label = relative(path, REPO_ROOT) or str(path)
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def harness_fingerprint(orchestrator: Path) -> tuple[str, int]:
    roots = [
        REPO_ROOT / "shared" / "scripts",
        REPO_ROOT / "skills" / "ai-research-reproduction",
        REPO_ROOT / "skills" / "repo-intake-and-plan",
        REPO_ROOT / "skills" / "env-and-assets-bootstrap",
        REPO_ROOT / "skills" / "minimal-run-and-audit",
        REPO_ROOT / "skills" / "run-train",
        REPO_ROOT / "skills" / "analyze-project",
    ]
    files = [Path(__file__).resolve(), orchestrator.resolve()]
    for root in roots:
        files.extend(
            path for path in root.rglob("*")
            if path.is_file() and "_bundled" not in path.parts and path.suffix.lower() in {".py", ".md", ".json"}
        )
    unique = sorted(set(files))
    return content_fingerprint(unique), len(unique)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="Ready case name from the manifest.")
    parser.add_argument("--manifest", default="benchmarks/external_cases.json")
    parser.add_argument("--work-root", default="tmp/external-benchmark-runs")
    parser.add_argument("--output", help="Machine-readable summary; defaults under benchmark_outputs/.")
    parser.add_argument("--keep-workspace", action="store_true", help="Retain checkout, venv, and raw logs for debugging.")
    parser.add_argument(
        "--showcase-root",
        help="Retain a tracked-file repository snapshot with a source-adjacent RIGORPILOT_README.md.",
    )
    parser.add_argument("--max-workspace-mb", type=int, default=0, help="Override the case workspace cap.")
    parser.add_argument("--min-free-disk-gb", type=float, default=0.0, help="Override the minimum free-space gate.")
    parser.add_argument(
        "--orchestrator",
        default="skills/ai-research-reproduction/scripts/orchestrate_repro.py",
        help="Harness orchestrator to evaluate.",
    )
    args = parser.parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    case, manifest_version = load_case(manifest_path, args.case)
    orchestrator = Path(args.orchestrator).expanduser().resolve()
    if not orchestrator.is_file():
        parser.error(f"orchestrator does not exist: {orchestrator}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work_root = Path(args.work_root).expanduser().resolve()
    case_root = work_root / f"{args.case}-{stamp}-{os.getpid()}"
    case_root.mkdir(parents=True, exist_ok=False)
    def cleanup() -> str:
        if args.keep_workspace:
            return "retained"
        safe_remove_workspace(case_root, work_root)
        return "removed"

    def cleanup_fallback() -> None:
        try:
            cleanup()
        except OSError:
            pass

    atexit.register(cleanup_fallback)
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (REPO_ROOT / "benchmark_outputs" / f"external_{args.case}.json")
    )
    runtime_root = case_root / "phase_runtime"
    repo = case_root / "repo"
    phases: list[Dict[str, Any]] = []
    started = time.monotonic()
    harness_sha256, harness_file_count = harness_fingerprint(orchestrator)
    limits = case.get("limits") or {}
    max_workspace_mb = int(args.max_workspace_mb or limits.get("max_workspace_mb", 512))
    min_free_disk_gb = float(args.min_free_disk_gb or limits.get("min_free_disk_gb", 5.0))
    if max_workspace_mb <= 0 or min_free_disk_gb < 0:
        parser.error("workspace and free-disk limits must be positive")
    initial_disk = shutil.disk_usage(work_root)
    report: Dict[str, Any] = {
        "schema_version": "1.0",
        "benchmark": "rigorpilot-external-reproduction",
        "case": args.case,
        "case_manifest_schema_version": manifest_version,
        "generated_at": utc_now(),
        "status": "running",
        "source": {
            "repository": case["repository"],
            "expected_commit": case["commit"],
            "actual_commit": None,
            "target_subdir": case.get("target_subdir", "."),
            "fresh_checkout": True,
        },
        "identity": {
            "harness_sha256": harness_sha256,
            "harness_file_count": harness_file_count,
            "case_sha256": hashlib.sha256(
                json.dumps(case, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        "scope": {
            "tier": case.get("tier"),
            "dependency_mode": (case.get("environment") or {}).get("dependency_mode"),
            "cache_policy": (case.get("environment") or {}).get("cache_policy"),
            "api_calls": 0,
            "gpu_required": False,
            "network_required": bool(case.get("network_required", True)),
            "workspace": relative(case_root, REPO_ROOT),
            "workspace_retained": bool(args.keep_workspace),
            "evidence_retained": True,
        },
        "limits": {
            "max_workspace_mb": max_workspace_mb,
            "min_free_disk_gb": min_free_disk_gb,
            "initial_free_disk_bytes": initial_disk.free,
            "peak_workspace_bytes": 0,
        },
        "known_adaptations": case.get("known_adaptations", []),
        "environment": {
            "base_python": sys.version.split()[0],
            "system_site_packages": bool((case.get("environment") or {}).get("system_site_packages")),
            "dependency_versions": {},
            "inheritance_policy": "strip-secret-named-variables",
            "secret_environment_variables_stripped": sum(
                1 for key in os.environ if SECRET_NAME_RE.search(key)
            ),
        },
        "phases": phases,
        "selection": {},
        "execution": {},
        "evidence": {},
        "target_repo_changes": {},
        "dimensions": {},
        "limitations": [
            "One repository case does not establish broad paper-reproduction generalization.",
            "Host package and network caches are retained unless the case says otherwise.",
            "A host-reuse dependency mode is not a fully cold dependency installation.",
        ],
    }

    def fail(reason: str) -> int:
        report["status"] = "failed"
        report["main_blocker"] = reason
        report["wall_duration_seconds"] = round(time.monotonic() - started, 6)
        try:
            report["scope"]["workspace_cleanup"] = cleanup()
        except OSError as exc:
            report["scope"]["workspace_cleanup"] = "failed"
            report["scope"]["workspace_cleanup_error"] = f"{type(exc).__name__}: {exc}"
        write_report(output_path, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    def enforce_storage_gate() -> Optional[str]:
        current_size = directory_size(case_root)
        report["limits"]["peak_workspace_bytes"] = max(
            int(report["limits"]["peak_workspace_bytes"]), current_size
        )
        free = shutil.disk_usage(work_root).free
        report["limits"]["final_free_disk_bytes"] = free
        if initial_disk.free < int(min_free_disk_gb * 1024**3) or free < int(min_free_disk_gb * 1024**3):
            return f"free disk is below the {min_free_disk_gb:g} GiB safety floor"
        if current_size > max_workspace_mb * 1024**2:
            return f"workspace exceeded the {max_workspace_mb} MiB case limit"
        return None

    storage_blocker = enforce_storage_gate()
    if storage_blocker:
        return fail(storage_blocker)

    repo.mkdir()
    init_result, init_phase = run_phase(
        name="init-repository",
        argv=["git", "init", str(repo)],
        cwd=case_root,
        runtime_root=runtime_root,
        case_root=case_root,
        timeout=60,
        source="benchmark isolation policy",
    )
    phases.append(init_phase)
    storage_blocker = enforce_storage_gate()
    if storage_blocker:
        return fail(storage_blocker)
    if init_result["runtime_status"] != "success":
        return fail("repository initialization failed")
    fetch_result, fetch_phase = run_phase(
        name="fetch-pinned-commit",
        argv=["git", "-C", str(repo), "fetch", "--depth", "1", str(case["repository"]), str(case["commit"])],
        cwd=case_root,
        runtime_root=runtime_root,
        case_root=case_root,
        timeout=180,
        source="case manifest pinned commit",
    )
    phases.append(fetch_phase)
    storage_blocker = enforce_storage_gate()
    if storage_blocker:
        return fail(storage_blocker)
    if fetch_result["runtime_status"] != "success":
        return fail("pinned commit fetch failed")
    checkout_result, checkout_phase = run_phase(
        name="checkout-pinned-commit",
        argv=["git", "-C", str(repo), "checkout", "--detach", "FETCH_HEAD"],
        cwd=case_root,
        runtime_root=runtime_root,
        case_root=case_root,
        timeout=60,
        source="case manifest pinned commit",
    )
    phases.append(checkout_phase)
    storage_blocker = enforce_storage_gate()
    if storage_blocker:
        return fail(storage_blocker)
    if checkout_result["runtime_status"] != "success":
        return fail("pinned commit checkout failed")
    actual_commit = git_output(repo, "rev-parse", "HEAD")
    report["source"]["actual_commit"] = actual_commit
    if actual_commit.lower() != str(case["commit"]).lower():
        return fail("checked-out commit does not match manifest")

    venv = case_root / ".venv"
    venv_argv = [sys.executable, "-m", "venv"]
    if bool((case.get("environment") or {}).get("system_site_packages")):
        venv_argv.append("--system-site-packages")
    venv_argv.append(str(venv))
    venv_result, venv_phase = run_phase(
        name="create-venv",
        argv=venv_argv,
        cwd=case_root,
        runtime_root=runtime_root,
        case_root=case_root,
        timeout=180,
        source="benchmark isolation policy",
    )
    phases.append(venv_phase)
    storage_blocker = enforce_storage_gate()
    if storage_blocker:
        return fail(storage_blocker)
    if venv_result["runtime_status"] != "success":
        return fail("virtual environment creation failed")
    python_path = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    scripts_path = python_path.parent

    probes = list((case.get("environment") or {}).get("dependency_probes") or [])
    if probes:
        invalid_probes = [name for name in probes if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(name))]
        if invalid_probes:
            return fail(f"invalid dependency probe names: {invalid_probes}")
        probe_code = (
            "import importlib.metadata as m,json,sys; "
            f"names={json.dumps(probes)}; "
            "print(json.dumps({'python':sys.version.split()[0],'packages':{name:m.version(name) for name in names}},sort_keys=True))"
        )
        probe_result, probe_phase = run_phase(
            name="dependency-probe",
            argv=[str(python_path), "-c", probe_code],
            cwd=case_root,
            runtime_root=runtime_root,
            case_root=case_root,
            timeout=120,
            source="case manifest",
        )
        phases.append(probe_phase)
        storage_blocker = enforce_storage_gate()
        if storage_blocker:
            return fail(storage_blocker)
        if probe_result["runtime_status"] != "success":
            return fail("required dependency probe failed")
        try:
            probe_payload = json.loads(str(probe_result.get("stdout") or "").strip())
            report["environment"]["venv_python"] = probe_payload["python"]
            report["environment"]["dependency_versions"] = probe_payload["packages"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return fail("dependency probe did not emit version evidence")

    for index, step in enumerate(case.get("setup_steps") or []):
        if not isinstance(step, dict) or not isinstance(step.get("argv"), list):
            return fail(f"invalid setup step at index {index}")
        step_env = safe_environment(step.get("environment"))
        step_result, step_phase = run_phase(
            name=str(step.get("name") or f"setup-{index + 1}"),
            argv=format_step_argv(step["argv"], python_path, repo, case_root),
            cwd=repo,
            runtime_root=runtime_root,
            case_root=case_root,
            timeout=int(step.get("timeout_seconds", 180)),
            source=str(step.get("source") or "case manifest"),
            environment=step_env,
        )
        step_phase["environment_overrides"] = sorted(step_env)
        phases.append(step_phase)
        storage_blocker = enforce_storage_gate()
        if storage_blocker:
            return fail(storage_blocker)
        if step_result["runtime_status"] != "success":
            return fail(f"setup step failed: {step_phase['name']}")

    target_repo = (repo / str(case.get("target_subdir") or ".")).resolve()
    tracked_before = git_output(repo, "diff", "--name-only")
    orchestration = case.get("orchestrator") or {}
    execute_selected = bool(orchestration.get("execute", True))
    report["scope"]["verification_mode"] = "execution" if execute_selected else "selection-only"
    harness_argv = [
        str(python_path),
        str(orchestrator),
        "--repo",
        str(target_repo),
        "--output-dir",
        str(case_root / "repro_outputs"),
        "--timeout",
        str(int(orchestration.get("timeout_seconds", 180))),
        "--train-timeout",
        str(int(orchestration.get("train_timeout_seconds", orchestration.get("timeout_seconds", 180)))),
        "--user-language",
        "en",
    ]
    if execute_selected:
        harness_argv.append("--run-selected")
    if orchestration.get("include_analysis_pass"):
        harness_argv.append("--include-analysis-pass")
    for expected_metric in orchestration.get("expected_metrics") or []:
        harness_argv.extend(["--expected-metric", str(expected_metric)])
    harness_env = {
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "VIRTUAL_ENV": str(venv),
        "PATH": str(scripts_path) + os.pathsep + os.environ.get("PATH", ""),
    }
    harness_result, harness_phase = run_phase(
        name="rigorpilot-orchestrator",
        argv=harness_argv,
        cwd=REPO_ROOT,
        runtime_root=runtime_root,
        case_root=case_root,
        timeout=max(
            int(orchestration.get("timeout_seconds", 180)),
            int(orchestration.get("train_timeout_seconds", orchestration.get("timeout_seconds", 180))),
        ) + 60,
        source="RigorPilot ai-research-reproduction",
        environment=harness_env,
    )
    harness_phase["environment_overrides"] = ["PATH-prepend", "PYTHONUTF8", "PYTHONUNBUFFERED", "VIRTUAL_ENV"]
    phases.append(harness_phase)
    storage_blocker = enforce_storage_gate()
    if storage_blocker:
        return fail(storage_blocker)
    if harness_result["runtime_status"] != "success":
        return fail("RigorPilot orchestrator process failed")
    try:
        context = json.loads(harness_result["stdout"])
    except json.JSONDecodeError:
        return fail("RigorPilot orchestrator did not emit parseable JSON")

    expected_command = str(orchestration.get("expected_command") or "")
    expected_goal = str(orchestration.get("expected_goal") or "")
    expected_status = str(orchestration.get("expected_status") or "success")
    selection = {
        "expected_command": expected_command,
        "actual_command": context.get("documented_command"),
        "command_match": context.get("documented_command") == expected_command,
        "expected_goal": expected_goal,
        "actual_goal": context.get("selected_goal"),
        "goal_match": context.get("selected_goal") == expected_goal,
    }
    report["selection"] = selection
    stdout_log = Path(context["stdout_log_path"]) if context.get("stdout_log_path") else None
    executed_stdout = stdout_log.read_text(encoding="utf-8", errors="replace") if stdout_log and stdout_log.is_file() else ""
    expected_stdout = str(orchestration.get("expected_stdout_contains") or "")
    execution = {
        "requested": execute_selected,
        "expected_status": expected_status,
        "actual_status": context.get("status"),
        "status_match": context.get("status") == expected_status,
        "expected_stdout_contains": expected_stdout,
        "stdout_match": not expected_stdout or expected_stdout in executed_stdout,
        "result_match": context.get("result_match"),
        "runtime_status": context.get("runtime_status"),
        "runtime_duration_seconds": context.get("duration_seconds"),
        "resource_summary": context.get("resource_summary", {}),
    }
    report["execution"] = execution
    evidence_dir = case_root / "repro_outputs"
    present = {path.name for path in evidence_dir.iterdir() if path.is_file()} if evidence_dir.is_dir() else set()
    missing = sorted(REQUIRED_EVIDENCE - present)
    report["evidence"] = {
        "complete": not missing,
        "missing": missing,
        "output_dir": relative(evidence_dir, case_root),
        "runtime_dir": relative(context.get("runtime_dir"), case_root),
    }
    source_readme_path = None
    for artifact in context.get("artifact_provenance") or []:
        if artifact.get("kind") == "repo_file" and artifact.get("artifact") == "readme":
            source_readme_path = Path(str(artifact.get("source")))
            break
    annotated_readme_path = evidence_dir / "ANNOTATED_README.md"
    fidelity: Dict[str, Any] = {
        "source_readme": relative(source_readme_path, case_root) if source_readme_path else None,
        "annotated_readme": relative(annotated_readme_path, case_root),
        "round_trip_verified": False,
        "one_annotation_per_heading": False,
    }
    if source_readme_path and source_readme_path.is_file() and annotated_readme_path.is_file():
        original_bytes = source_readme_path.read_bytes()
        annotated_bytes = annotated_readme_path.read_bytes()
        try:
            stripped_bytes, marker_blocks, section_markers = strip_annotation_bytes(annotated_bytes)
            heading_count = count_atx_headings(original_bytes)
            fidelity.update(
                {
                    "original_bytes": len(original_bytes),
                    "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
                    "stripped_sha256": hashlib.sha256(stripped_bytes).hexdigest(),
                    "marker_blocks": marker_blocks,
                    "section_markers": section_markers,
                    "atx_heading_blocks": heading_count,
                    "round_trip_verified": stripped_bytes == original_bytes,
                    "one_annotation_per_heading": section_markers == heading_count,
                }
            )
        except (UnicodeError, ValueError) as exc:
            fidelity["error"] = f"{type(exc).__name__}: {exc}"
    report["evidence"]["readme_fidelity"] = fidelity
    report["evidence"]["archive"] = archive_evidence(
        evidence_dir,
        output_path.parent / "evidence" / args.case,
    )
    showcase_complete = not bool(args.showcase_root)
    if args.showcase_root:
        try:
            report["showcase"] = preserve_showcase(
                repo=repo,
                case_root=case_root,
                evidence_dir=evidence_dir,
                source_readme=source_readme_path,
                showcase_root=Path(args.showcase_root).expanduser().resolve(),
                case_name=args.case,
                repository_url=str(case["repository"]),
                commit=actual_commit,
            )
            showcase_complete = True
        except (OSError, RuntimeError, ValueError) as exc:
            report["showcase"] = {"error": f"{type(exc).__name__}: {exc}"}
            showcase_complete = False
    tracked_after = git_output(repo, "diff", "--name-only")
    untracked_after = git_output(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    report["target_repo_changes"] = {
        "tracked_before": tracked_before.splitlines() if tracked_before else [],
        "tracked_after": tracked_after.splitlines() if tracked_after else [],
        "untracked_after": untracked_after,
        "tracked_source_unchanged": not tracked_before and not tracked_after,
    }
    dimensions = {
        "source_pinned": actual_commit.lower() == str(case["commit"]).lower(),
        "command_selected": selection["command_match"],
        "goal_classified": selection["goal_match"],
        "execution_expectation_met": execution["status_match"] and execution["stdout_match"],
        "evidence_complete": not missing,
        "readme_round_trip": bool(fidelity["round_trip_verified"]),
        "one_annotation_per_heading": bool(fidelity["one_annotation_per_heading"]),
        "showcase_snapshot_complete": showcase_complete,
        "tracked_source_unchanged": not tracked_before and not tracked_after,
    }
    report["dimensions"] = dimensions
    report["intervention_accounting"] = {
        "discovery_adaptations_recorded": len(case.get("known_adaptations") or []),
        "manual_interventions_during_final_run": 0,
        "autonomous_after_manifest": True,
    }
    report["status"] = "passed" if all(dimensions.values()) else "failed"
    report["main_blocker"] = None if report["status"] == "passed" else "one or more benchmark dimensions failed"
    report["wall_duration_seconds"] = round(time.monotonic() - started, 6)
    try:
        report["scope"]["workspace_cleanup"] = cleanup()
    except OSError as exc:
        report["scope"]["workspace_cleanup"] = "failed"
        report["scope"]["workspace_cleanup_error"] = f"{type(exc).__name__}: {exc}"
        report["status"] = "failed"
        report["main_blocker"] = "workspace cleanup failed"
    write_report(output_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
