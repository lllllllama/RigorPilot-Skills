"""Small Anthropic Messages client. Credentials remain in environment variables."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ProviderError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("Provider redirect refused; configure its final endpoint")


class AnthropicProvider:
    def __init__(self, profile: dict):
        self.profile = profile

    def complete(self, messages: list, system: str, tools: list, max_tokens: int, timeout: float) -> dict:
        profile = self.profile
        endpoint = str(profile.get("endpoint") or os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ProviderError("Provider requires HTTPS (except a local test server)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderError("Provider endpoint must not contain credentials, query or fragment")
        credential = os.getenv(profile.get("credential_env") or "ANTHROPIC_API_KEY")
        if not credential:
            raise ProviderError("Configured credential environment variable is missing")
        url = endpoint if endpoint.endswith("/messages") else endpoint + ("/messages" if endpoint.endswith("/v1") else "/v1/messages")
        headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
        if profile.get("metadata", {}).get("auth_scheme") == "bearer":
            headers["Authorization"] = "Bearer " + credential
        else:
            headers["x-api-key"] = credential
        payload = {"model": profile["model"], "system": system, "messages": messages,
                   "tools": tools, "max_tokens": max_tokens}
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ProviderError("Provider response exceeds size limit")
            result = json.loads(data)
        except urllib.error.HTTPError as exc:
            # Never persist provider bodies or headers: gateways may echo credentials.
            raise ProviderError(f"Provider HTTP {exc.code}; request not automatically retried") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ProviderError(f"Provider transport/format failure: {type(exc).__name__}") from None
        if not isinstance(result.get("content"), list):
            raise ProviderError("Provider response has no content blocks")
        return result
