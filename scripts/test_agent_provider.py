#!/usr/bin/env python3
"""Exercise real HTTP serialization and fail-closed provider error handling locally."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared/scripts"))
from agent_provider import AnthropicProvider, ProviderError


def main():
    requests = []
    mode = ["ok"]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            assert self.headers["x-api-key"] == "test-credential"
            if mode[0] == "redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/not-allowed")
                self.end_headers()
                return
            self.send_response(200 if mode[0] in {"ok", "non_object"} else 401)
            if mode[0] == "non_object":
                # A gateway can return valid JSON of the wrong shape with HTTP 200.
                self.end_headers()
                self.wfile.write(b"[]")
                return
            self.end_headers()
            self.wfile.write(json.dumps({"content": [{"type": "tool_use", "id": "one", "name": "list_files", "input": {"reason": "inspect"}}],
                                        "usage": {"input_tokens": 8, "output_tokens": 9}, "private_echo": "test-credential"}).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous = os.environ.get("RIGORPILOT_PROVIDER_TEST_KEY")
    os.environ["RIGORPILOT_PROVIDER_TEST_KEY"] = "test-credential"
    try:
        profile = {"model": "local-test", "credential_env": "RIGORPILOT_PROVIDER_TEST_KEY",
                   "endpoint": f"http://127.0.0.1:{server.server_port}",
                   "parameters": {"temperature": 1.0, "stop_sequences": ["STOP"]}}
        client = AnthropicProvider(profile)
        response = client.complete([{"role": "user", "content": "test"}], "system", [], 32, 5)
        assert response["usage"]["output_tokens"] == 9
        assert requests[0]["max_tokens"] == 32 and requests[0]["model"] == "local-test"
        assert requests[0]["temperature"] == 1.0 and requests[0]["stop_sequences"] == ["STOP"]
        for failure in ["unauthorized", "redirect"]:
            mode[0] = failure
            try:
                client.complete([], "system", [], 32, 5)
            except ProviderError as exc:
                assert "test-credential" not in str(exc)
            else:
                raise AssertionError("provider did not stop on error/redirect")
        assert len(requests) == 3, "provider silently retried"
        for parameters in ({"max_tokens": 999999}, {"thinking": {"type": "adaptive"}},
                           {"temperature": True}, {"top_p": float("nan")}, {"temperature": -1},
                           {"temperature": 1, "top_p": 1}, {"stop_sequences": "STOP"}):
            try:
                AnthropicProvider({**profile, "parameters": parameters})
            except ProviderError:
                pass
            else:
                raise AssertionError("unsupported/invalid parameters were silently accepted")
        assert len(requests) == 3, "invalid configuration sent an HTTP request"
        mode[0] = "ok"
        AnthropicProvider({**profile, "parameters": {"top_p": 1}}).complete([], "system", [], 32, 5)
        assert requests[-1]["top_p"] == 1 and "temperature" not in requests[-1]
        mode[0] = "non_object"
        try:
            client.complete([], "system", [], 32, 5)
        except ProviderError:
            pass
        else:
            raise AssertionError("non-object response escaped fail-closed handling")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if previous is None:
            os.environ.pop("RIGORPILOT_PROVIDER_TEST_KEY", None)
        else:
            os.environ["RIGORPILOT_PROVIDER_TEST_KEY"] = previous
    print("ok: True; HTTP tool messages, usage, auth errors and redirects verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
