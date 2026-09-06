#!/usr/bin/env python3
"""Provider-neutral model identity and capability contract for harness runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit


CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
SECRET_KEY_TOKENS = {"api_key", "apikey", "secret", "password", "access_token", "bearer_token"}


class ModelAdapterError(ValueError):
    """Raised when a model profile is unsafe or violates the adapter contract."""


def _reject_secrets(value: Any, path: str = "profile") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered != "credential_env" and any(token in lowered for token in SECRET_KEY_TOKENS):
                raise ModelAdapterError(f"Secret-bearing field is not allowed: {path}.{key}")
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str) and (value.startswith("sk-") or value.lower().startswith("bearer ")):
        raise ModelAdapterError(f"Credential-like value is not allowed: {path}")


def _capabilities(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        values = [str(name) for name, enabled in raw.items() if enabled]
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    else:
        raise ModelAdapterError("capabilities must be a list or boolean map")
    normalized = sorted({item.strip().lower() for item in values if item.strip()})
    invalid = [item for item in normalized if not CAPABILITY_RE.fullmatch(item)]
    if invalid:
        raise ModelAdapterError(f"Invalid capability names: {invalid}")
    return normalized


def profile_fingerprint(profile: Dict[str, Any]) -> str:
    canonical = {key: value for key, value in profile.items() if key not in {"fingerprint", "source_path"}}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_model_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ModelAdapterError("model profile must be a JSON object")
    _reject_secrets(raw)
    if "parameters" in raw and not isinstance(raw["parameters"], dict):
        raise ModelAdapterError("parameters must be a JSON object")
    adapter_id = str(raw.get("adapter_id") or "").strip()
    provider = str(raw.get("provider") or "").strip()
    model = str(raw.get("model") or "").strip()
    if not adapter_id or not provider or not model:
        raise ModelAdapterError("configured model profiles require adapter_id, provider, and model")
    credential_env = str(raw.get("credential_env") or "").strip() or None
    if credential_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", credential_env):
        raise ModelAdapterError("credential_env must name an environment variable, not contain a credential")
    endpoint = str(raw.get("endpoint") or "").strip() or None
    if endpoint and "://" in endpoint:
        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.username or parsed_endpoint.password:
            raise ModelAdapterError("endpoint must not contain embedded credentials")
    profile: Dict[str, Any] = {
        "schema_version": "1.0",
        "status": "configured",
        "adapter_id": adapter_id,
        "provider": provider,
        "model": model,
        "revision": str(raw.get("revision") or "").strip() or None,
        "capabilities": _capabilities(raw.get("capabilities")),
        "endpoint": endpoint,
        "credential_env": credential_env,
        "parameters": raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {},
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    }
    profile["fingerprint"] = profile_fingerprint(profile)
    return profile


def default_model_profile() -> Dict[str, Any]:
    profile: Dict[str, Any] = {
        "schema_version": "1.0",
        "status": "unconfigured",
        "adapter_id": "external-agent",
        "provider": "host",
        "model": "unspecified",
        "revision": None,
        "capabilities": [],
        "endpoint": None,
        "credential_env": None,
        "parameters": {},
        "metadata": {},
    }
    profile["fingerprint"] = profile_fingerprint(profile)
    return profile


def load_model_profile(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return default_model_profile()
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelAdapterError(f"Could not read model profile: {exc}") from exc
    profile = normalize_model_profile(raw)
    profile["source_path"] = str(source)
    return profile


def missing_capabilities(profile: Dict[str, Any], required: Iterable[str]) -> list[str]:
    available = set(profile.get("capabilities") or [])
    normalized = sorted({str(item).strip().lower() for item in required if str(item).strip()})
    invalid = [item for item in normalized if not CAPABILITY_RE.fullmatch(item)]
    if invalid:
        raise ModelAdapterError(f"Invalid required capability names: {invalid}")
    return [item for item in normalized if item not in available]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a provider-neutral model adapter profile.")
    parser.add_argument("--profile", required=True, help="Path to the model profile JSON file.")
    parser.add_argument("--require", action="append", default=[], help="Required capability; repeat as needed.")
    args = parser.parse_args()
    try:
        profile = load_model_profile(Path(args.profile))
        missing = missing_capabilities(profile, args.require)
    except ModelAdapterError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "compatible" if not missing else "incompatible", "missing_capabilities": missing, "profile": profile}, indent=2, ensure_ascii=False))
    return 0 if not missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
