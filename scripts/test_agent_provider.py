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
            self.send_response(200 if mode[0] == "ok" else 401)
            self.end_headers()
            self.wfile.write(json.dumps({"content": [{"type": "tool_use", "id": "one", "name": "list_files", "input": {"reason": "inspect"}}],
                                        "usage": {"input_tokens": 8, "output_tokens": 9}, "private_echo": "test-credential"}).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous = os.environ.get("RIGORPILOT_PROVIDER_TEST_KEY")
    os.environ["RIGORPILOT_PROVIDER_TEST_KEY"] = "test-credential"
    try:
        client = AnthropicProvider({"model": "local-test", "credential_env": "RIGORPILOT_PROVIDER_TEST_KEY",
                                    "endpoint": f"http://127.0.0.1:{server.server_port}"})
        response = client.complete([{"role": "user", "content": "test"}], "system", [], 32, 5)
        assert response["usage"]["output_tokens"] == 9
        assert requests[0]["max_tokens"] == 32 and requests[0]["model"] == "local-test"
        for failure in ["unauthorized", "redirect"]:
            mode[0] = failure
            try:
                client.complete([], "system", [], 32, 5)
            except ProviderError as exc:
                assert "test-credential" not in str(exc)
            else:
                raise AssertionError("provider did not stop on error/redirect")
        assert len(requests) == 3, "provider silently retried"
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
