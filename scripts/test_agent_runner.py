#!/usr/bin/env python3
"""Behavioral agent loop tests: execution, resume, false success, boundaries and budgets."""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/ai-research-reproduction/scripts"))
import run_agent as agent
from model_adapter import normalize_model_profile


def call(name, **args):
    return {"type": "tool_use", "id": "test-" + name, "name": name,
            "input": {"reason": "Test observable behavior", **args}}


class ScriptedProvider:
    """Deterministic transport substitute; never presented as model quality evidence."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, messages, system, tools, max_tokens, timeout):
        self.requests.append(json.loads(json.dumps(messages)))
        return {"model": "scripted-test", "content": self.responses.pop(0),
                "usage": {"input_tokens": 50, "output_tokens": 20}}


def main():
    with tempfile.TemporaryDirectory(prefix="rigorpilot-agent-test-") as tmp:
        base = Path(tmp)
        repo = base / "repo"
        repo.mkdir()
        readme = b"# Test\r\n\r\n## Evaluation\r\n```bash\r\npython verify.py\r\n```\r\n"
        (repo / "README.md").write_bytes(readme)
        (repo / "verify.py").write_text("print('accuracy=0.91')\n", encoding="utf-8")
        task = {"goal": "Verify documented evaluation", "commands": {"test": {
            "argv": ["python", "verify.py"], "documented_command": "python verify.py",
            "expected_stdout": "accuracy=0.91"}}, "required_commands": ["test"]}
        profile = normalize_model_profile({"adapter_id": "test", "provider": "anthropic", "model": "scripted-test"})
        provider = ScriptedProvider([[call("read_file", path="README.md"), call("update_plan", steps=["run evaluation", "verify"])],
                                    [call("run_command", command_id="test")], [call("finish", summary="evaluation completed")]])
        out = base / "success"
        first = agent.run(task, repo, out, profile, provider, pause_after_tools=3)
        assert first["status"] == "paused" and first["results"]["test"]["verified"]
        assert len(list((out / "_runtime").iterdir())) == 1
        second = agent.run(task, repo, out, profile, provider, resume=True)
        assert second["status"] == "success" and second["model_calls"] == 3
        assert second["usage"]["input_tokens"] == 150
        assert len(list((out / "_runtime").iterdir())) == 1, "resume re-executed completed command"
        from annotate_readme import strip_annotated_bytes
        assert strip_annotated_bytes((out / "ANNOTATED_README.md").read_bytes()) == readme
        assert "Recorded command outcomes" in (out / "ANNOTATED_README.md").read_text(encoding="utf-8")
        assert "python verify.py" in (out / "COMMANDS.md").read_text(encoding="utf-8")
        assert all((out / p).exists() for p in ["SUMMARY.md", "LOG.md", "status.json", "trajectory.jsonl", "agent_state.json"])
        # A model declaration cannot bypass independent execution verification.
        fake = agent.run(task, repo, base / "fake", profile, ScriptedProvider([[call("finish", summary="Everything passed!")]]))
        assert fake["status"] == "blocked" and not fake["verification"]["commands"]["test"]
        # User-defined command IDs cannot overwrite independent controller checks.
        collision_task = {**task, "commands": {"source_unchanged": task["commands"]["test"]},
                          "required_commands": ["source_unchanged"]}
        collision = agent.run(collision_task, repo, base / "check-collision", profile,
                              ScriptedProvider([[call("finish", summary="Everything passed!")]]))
        assert collision["schema_version"] == "1.1"
        assert collision["status"] == "blocked" and collision["results"] == {}
        assert collision["verification"] == {"commands": {"source_unchanged": False}, "source_unchanged": True}
        collision_passed = agent.run(collision_task, repo, base / "check-collision-passed", profile,
                                     ScriptedProvider([[call("run_command", command_id="source_unchanged")],
                                                       [call("finish", summary="Executed and checked")]]))
        assert collision_passed["status"] == "success"
        assert collision_passed["verification"]["commands"]["source_unchanged"]
        malicious = ScriptedProvider([[call("read_file", path="../private.txt")],
                                     [call("run_command", command_id="not-approved")], [call("finish", summary="blocked")]])
        denied = agent.run(task, repo, base / "denied", profile, malicious)
        assert denied["status"] == "blocked" and not denied["results"]
        assert '"is_error": true' in json.dumps(malicious.requests)
        # Persisted pending command result is recovered, never blindly repeated.
        recovery_provider = ScriptedProvider([[call("run_command", command_id="test")]])
        recovery_out = base / "recovery"
        state = agent.run(task, repo, recovery_out, profile, recovery_provider, pause_after_tools=1)
        state.update(status="running", pending=[{**call("run_command", command_id="test"), "started": True, "runtime_id": "agent-0001"}], tool_results=[], results={})
        agent.atomic_write_json(recovery_out / "agent_state.json", state)
        recovered = agent.run(task, repo, recovery_out, profile, ScriptedProvider([[call("finish", summary="recovered")]]), resume=True)
        assert recovered["status"] == "success" and len(list((recovery_out / "_runtime").iterdir())) == 1, recovered
        # An actual missing-asset failure can lead to an approved preparation step
        # and a resumed successful retry, retaining every attempt.
        repair_repo = base / "repair-repo"
        repair_repo.mkdir()
        (repair_repo / "README.md").write_text("# Canary\n## Setup\n```bash\npython prepare.py\n```\n## Evaluation\n```bash\npython verify.py\n```\n", encoding="utf-8")
        (repair_repo / "prepare.py").write_text("from pathlib import Path\nPath('ready.txt').write_text('ready')\nprint('prepared')\n", encoding="utf-8")
        (repair_repo / "verify.py").write_text("from pathlib import Path\nassert Path('ready.txt').exists(), 'missing asset'\nprint('verified')\n", encoding="utf-8")
        repair_task = {"goal": "Prepare missing assets and verify", "commands": {
            "prepare": {"argv": ["python", "prepare.py"], "documented_command": "python prepare.py", "expected_stdout": "prepared"},
            "verify": {"argv": ["python", "verify.py"], "documented_command": "python verify.py", "expected_stdout": "verified"}},
            "required_commands": ["verify"]}
        repair_provider = ScriptedProvider([[call("run_command", command_id="verify")],
            [call("update_plan", steps=["prepare missing asset", "retry verification"]), call("run_command", command_id="prepare")],
            [call("run_command", command_id="verify")], [call("finish", summary="verified after preparation")]])
        repair_out = base / "repair-out"
        paused = agent.run(repair_task, repair_repo, repair_out, profile, repair_provider, pause_after_tools=3)
        assert paused["status"] == "paused" and not paused["results"]["verify"]["verified"]
        repaired = agent.run(repair_task, repair_repo, repair_out, profile, repair_provider, resume=True)
        assert repaired["status"] == "success" and len(repaired["attempts"]) == 3
        assert [a["verified"] for a in repaired["attempts"]] == [False, True, True]
        assert len(list((repair_out / "_runtime").iterdir())) == 3
        limited = {**task, "budget": {"max_model_calls": 1}}
        budgeted = agent.run(limited, repo, base / "budget", profile, ScriptedProvider([[call("list_files")]]))
        assert budgeted["status"] == "blocked" and budgeted["model_calls"] == 1
        mismatch = {**task, "commands": {"test": {**task["commands"]["test"], "expected_stdout": "accuracy=1.00"}}}
        failed = agent.run(mismatch, repo, base / "mismatch", profile, ScriptedProvider([[call("run_command", command_id="test")], [call("finish", summary="passed")]]))
        assert failed["status"] == "blocked"
        assert "Task acceptance is not complete" in (base / "mismatch/SUMMARY.md").read_text(encoding="utf-8")
        class UnavailableProvider:
            def complete(self, *args):
                raise agent.ProviderError("Provider HTTP 502")
        unavailable = agent.run(task, repo, base / "unavailable", profile, UnavailableProvider())
        assert unavailable["status"] == "blocked" and unavailable["model_pending"]
        assert not unavailable["usage_complete"] and unavailable["tool_calls"] == 0
        class RawProvider:
            def __init__(self, response):
                self.response = response

            def complete(self, *args):
                return self.response

        # Invalid transport data must persist a blocked state without dispatching
        # the valid-looking tool call earlier in the same malformed batch.
        good_usage = {"input_tokens": 12, "output_tokens": 5}
        malformed_responses = [[], {"usage": [], "content": []},
            {"usage": {**good_usage, "cache_read_input_tokens": -1}, "content": []},
            {"usage": {**good_usage, "input_tokens": True}, "content": []},
            {"usage": good_usage, "content": [call("run_command", command_id="test"), None]},
            {"usage": good_usage, "content": [{"type": "tool_use", "id": "missing-fields"}]},
            {"usage": good_usage, "content": [call("list_files"), call("list_files")]}]
        for index, response in enumerate(malformed_responses):
            malformed_out = base / f"malformed-{index}"
            malformed = agent.run(task, repo, malformed_out, profile, RawProvider(response))
            assert malformed["status"] == "blocked" and malformed["tool_calls"] == 0
            assert json.loads((malformed_out / "agent_state.json").read_text(encoding="utf-8"))["status"] == "blocked"
            assert not (malformed_out / "_runtime").exists()
            assert malformed["usage_complete"] == (index >= 4)
            if index >= 4:
                assert malformed["usage"] == good_usage
        try:
            agent.run(task, repo, base / "unavailable", profile, provider, resume=True)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown model usage was silently retried")
        # Provider fields cannot inject controller-private recovery state.
        injected = call("run_command", command_id="test")
        injected.update(started=True, runtime_id="../../outside")
        clean = agent.run(task, repo, base / "injection", profile,
                          ScriptedProvider([[injected], [call("finish", summary="done")]]))
        assert clean["status"] == "success" and (base / "injection/_runtime/agent-0001/state.json").exists()
        secret_name = "RIGORPILOT_OPAQUE"
        previous = os.environ.get(secret_name)
        os.environ[secret_name] = "test-only-private-value"
        try:
            (repo / "verify.py").write_text("import os\nassert 'RIGORPILOT_OPAQUE' not in os.environ\nprint('accuracy=0.91')\n", encoding="utf-8")
            secret_profile = normalize_model_profile({"adapter_id": "test", "provider": "anthropic", "model": "scripted-test", "credential_env": secret_name})
            secret_run = agent.run(task, repo, base / "filtered", secret_profile,
                                   ScriptedProvider([[call("run_command", command_id="test")], [call("finish", summary="done")]]))
            assert secret_run["status"] == "success"
            assert "test-only-private-value" not in (base / "filtered/agent_state.json").read_text(encoding="utf-8")
        finally:
            if previous is None:
                os.environ.pop(secret_name, None)
            else:
                os.environ[secret_name] = previous
        try:
            agent.run({**task, "goal": "changed"}, repo, out, profile, provider, resume=True)
        except ValueError:
            pass
        else:
            raise AssertionError("resume accepted changed task")
    print("ok: True; execution, resume, source fidelity, false-success, boundaries, budgets, mismatch verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
