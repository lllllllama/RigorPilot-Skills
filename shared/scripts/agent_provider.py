"""Small Anthropic Messages client. Credentials remain in environment variables."""
from __future__ import annotations

import json
import http.client
import math
import os
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ProviderError(RuntimeError):
    """Public diagnostic fields contain classifications, never response bodies."""

    def __init__(self, message: str, *, code: str = "provider_error", http_status: int | None = None,
                 errno: int | None = None):
        super().__init__(message)
        self.diagnostic = {"code": code}
        if http_status is not None:
            self.diagnostic["http_status"] = http_status
        if errno is not None:
            self.diagnostic["errno"] = errno


def transport_error(error: object) -> ProviderError:
    if isinstance(error, ssl.SSLError):
        code = "tls_error"
    elif isinstance(error, socket.gaierror):
        code = "dns_error"
    elif isinstance(error, TimeoutError):
        code = "timeout"
    elif isinstance(error, http.client.HTTPException):
        code = "invalid_response"
    else:
        code = "connection_error"
    number = getattr(error, "errno", None)
    if code not in {"connection_error", "dns_error"} or type(number) is not int or not -65535 <= number <= 65535:
        number = None
    return ProviderError(f"Provider {code}; request not automatically retried", code=code, errno=number)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("Provider redirect refused; configure its final endpoint",
                            code="redirect_refused", http_status=code)


class AnthropicProvider:
    def __init__(self, profile: dict):
        self.profile = profile
        self.parameters = self._parameters(profile.get("parameters", {}))

    @staticmethod
    def _parameters(parameters: dict) -> dict:
        # Never record an experiment configuration that the transport silently ignores.
        # Model-specific support is still checked by the endpoint; no guessed defaults.
        if not isinstance(parameters, dict) or set(parameters) - {"temperature", "top_p", "stop_sequences"}:
            raise ProviderError("Unsupported provider parameters; supported: temperature, top_p, stop_sequences", code="invalid_configuration")
        if "temperature" in parameters and "top_p" in parameters:
            raise ProviderError("Configure temperature or top_p, not both", code="invalid_configuration")
        for key in ("temperature", "top_p"):
            if key in parameters:
                value = parameters[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ProviderError(f"{key} must be a finite number between 0 and 1", code="invalid_configuration")
        if "stop_sequences" in parameters:
            stops = parameters["stop_sequences"]
            if not isinstance(stops, list) or len(stops) > 16 or any(not isinstance(s, str) or not s or len(s) > 256 for s in stops):
                raise ProviderError("stop_sequences must contain at most 16 nonempty strings of at most 256 characters", code="invalid_configuration")
        return dict(parameters)

    def complete(self, messages: list, system: str, tools: list, max_tokens: int, timeout: float) -> dict:
        profile = self.profile
        endpoint = str(profile.get("endpoint") or os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}):
            raise ProviderError("Provider requires HTTPS (except a local test server)", code="invalid_configuration")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderError("Provider endpoint must not contain credentials, query or fragment", code="invalid_configuration")
        credential = os.getenv(profile.get("credential_env") or "ANTHROPIC_API_KEY")
        if not credential:
            raise ProviderError("Configured credential environment variable is missing", code="missing_credential")
        url = endpoint if endpoint.endswith("/messages") else endpoint + ("/messages" if endpoint.endswith("/v1") else "/v1/messages")
        headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
        if profile.get("metadata", {}).get("auth_scheme") == "bearer":
            headers["Authorization"] = "Bearer " + credential
        else:
            headers["x-api-key"] = credential
        payload = {"model": profile["model"], "system": system, "messages": messages,
                   "tools": tools, "max_tokens": max_tokens, **self.parameters}
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                data = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            # Never persist provider bodies or headers: gateways may echo credentials.
            raise ProviderError(f"Provider HTTP {exc.code}; request not automatically retried",
                                code="http_error", http_status=exc.code) from None
        except urllib.error.URLError as exc:
            raise transport_error(exc.reason) from None
        except (OSError, http.client.HTTPException) as exc:
            raise transport_error(exc) from None
        if len(data) > 2_000_000:
            raise ProviderError("Provider response exceeds size limit", code="response_too_large")
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            raise ProviderError("Provider response is not valid JSON", code="invalid_json") from None
        if not isinstance(result, dict) or not isinstance(result.get("content"), list):
            raise ProviderError("Provider response has no content blocks", code="invalid_response")
        return result
