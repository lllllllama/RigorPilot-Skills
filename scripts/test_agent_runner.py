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
        paused_status = json.loads((out / "status.json").read_text(encoding="utf-8"))
        assert paused_status["status"] == "partial"
        assert paused_status["agent"]["controller_status"] == "paused"
        assert paused_status["agent"]["task_outcome"] == "partial" and paused_status["agent"]["resumable"]
        assert paused_status["agent"]["verification"] == {}, "pause claimed final verification"
        assert "--resume" in paused_status["next_safe_action"]
        assert "Normal session pause" in (out / "SUMMARY.md").read_text(encoding="utf-8")
        assert "🟡 `partial`" in (out / "ANNOTATED_README.md").read_text(encoding="utf-8")
        assert json.loads((out / "agent_state.json").read_text(encoding="utf-8"))["controller_status"] == "paused"
        assert len(list((out / "_runtime").iterdir())) == 1
        second = agent.run(task, repo, out, profile, provider, resume=True)
        assert second["status"] == "success" and second["model_calls"] == 3
        assert second["usage"]["input_tokens"] == 150
        completed_status = json.loads((out / "status.json").read_text(encoding="utf-8"))
        assert completed_status["status"] == "success"
        assert completed_status["agent"]["controller_status"] == "finished"
        assert completed_status["agent"]["task_outcome"] == "accepted" and not completed_status["agent"]["resumable"]
        assert "Normal session pause" not in (out / "SUMMARY.md").read_text(encoding="utf-8")
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
        assert collision["verification"]["commands"] == {"source_unchanged": False}
        assert collision["verification"]["source_unchanged"] is True
        assert collision["verification"]["details"]["source_unchanged"]["passed"] is False
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
        # Chinese, before any command: pause is neither a failure nor success.
        zh_out = base / "zh-pause"
        zh_provider = ScriptedProvider([[call("read_file", path="README.md")],
                                      [call("run_command", command_id="test")], [call("finish", summary="完成")]])
        zh_task = {**task, "language": "zh-CN"}
        zh_pause = agent.run(zh_task, repo, zh_out, profile, zh_provider, pause_after_tools=1)
        zh_status = json.loads((zh_out / "status.json").read_text(encoding="utf-8"))
        assert zh_pause["task_outcome"] == "not_run" and zh_status["status"] == "not_run"
        assert "会话正常暂停" in (zh_out / "SUMMARY.md").read_text(encoding="utf-8")
        assert "--resume" in zh_status["next_safe_action"]
        assert "🔵 `not_run`" in (zh_out / "ANNOTATED_README.md").read_text(encoding="utf-8")
        zh_done = agent.run(zh_task, repo, zh_out, profile, zh_provider, resume=True)
        assert zh_done["status"] == "success"
        assert "独立任务验收已通过" in (zh_out / "SUMMARY.md").read_text(encoding="utf-8")
        test_structured_verification(base, profile)
        test_source_adjacent(base, profile)
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


def test_structured_verification(base, profile):
    """Real subprocesses can exit zero and still fail artifact/metric acceptance."""
    metric = {"path": "results/metrics.json", "key": ["eval", "accuracy"], "expected": 0.91, "absolute_tolerance": 0.001}
    verification = {"artifacts": [{"path": "results/predictions.txt", "min_bytes": 3}], "metrics": [metric]}
    valid_program = "from pathlib import Path\nimport json\nPath('results').mkdir(exist_ok=True)\nPath('results/predictions.txt').write_text('yes')\nPath('results/metrics.json').write_text(json.dumps({'eval': {'accuracy': 0.9105}}))\nprint('complete')\n"
    for label, program, expected in [
        ("valid", valid_program, True),
        ("valid-deleted-artifact", valid_program, True),
        ("missing", "print('complete')\n", False),
        ("wrong-metric", valid_program.replace("0.9105", "0.50"), False),
        ("bool-metric", valid_program.replace("0.9105", "True"), False),
        ("nonfinite-metric", valid_program.replace("0.9105", "float('nan')"), False),
        ("missing-key", valid_program.replace("'accuracy':", "'wrong':"), False),
        ("empty-artifact", valid_program.replace("write_text('yes')", "write_text('')"), False),
    ]:
        repo = base / f"structured-{label}-repo"
        repo.mkdir()
        (repo / "README.md").write_text("# Evaluation\n```bash\npython evaluate.py\n```\n", encoding="utf-8")
        (repo / "evaluate.py").write_text(program, encoding="utf-8")
        task = {"goal": "Verify structured evaluation outputs", "commands": {"eval": {
            "argv": ["python", "evaluate.py"], "documented_command": "python evaluate.py",
            "expected_stdout": "complete", "verification": verification}}, "required_commands": ["eval"]}
        output = base / f"structured-{label}-out"
        result = agent.run(task, repo, output, profile, ScriptedProvider([
            [call("run_command", command_id="eval")], [call("finish", summary="Everything is correct")]]))
        runtime = result["results"]["eval"]
        assert runtime["returncode"] == 0 and runtime["runtime_status"] == "success"
        assert result["verification"]["commands"]["eval"] is expected
        assert result["status"] == ("success" if expected else "blocked"), label
        assert result["task_outcome"] == ("accepted" if expected else "failed")
        status = json.loads((output / "status.json").read_text(encoding="utf-8"))
        detail = status["agent"]["verification"]["details"]["eval"]
        assert detail["runtime"] and detail["stdout"] and detail["passed"] is expected
        if expected:
            assert detail["metrics"][0]["observed"] == 0.9105
            runtime_count = len(list((output / "_runtime").iterdir()))
            no_calls = ScriptedProvider([])
            unchanged = agent.run(task, repo, output, profile, no_calls, resume=True)
            assert unchanged["status"] == "success" and not no_calls.requests
            assert unchanged["model_calls"] == result["model_calls"] and unchanged["tool_calls"] == result["tool_calls"]
            assert len(list((output / "_runtime").iterdir())) == runtime_count
            if label == "valid":
                (repo / "results/metrics.json").write_text('{"eval":{"accuracy":0.1}}', encoding="utf-8")
            else:
                (repo / "results/predictions.txt").unlink()
            changed = agent.run(task, repo, output, profile, no_calls, resume=True)
            assert changed["status"] == "blocked" and not changed["verification"]["commands"]["eval"]
            assert changed["task_outcome"] == "failed" and not no_calls.requests
            assert changed["model_calls"] == result["model_calls"] and changed["tool_calls"] == result["tool_calls"]
            assert len(list((output / "_runtime").iterdir())) == runtime_count
            current_status = json.loads((output / "status.json").read_text(encoding="utf-8"))
            assert current_status["status"] == "blocked"
            events = [json.loads(line) for line in (output / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()]
            assert events[-1]["type"] == "reverification"
            assert events[-1]["previous_checks"]["commands"]["eval"] is True
            assert events[-1]["checks"]["commands"]["eval"] is False
        else:
            assert any(not check["passed"] for kind in ("artifacts", "metrics") for check in detail[kind])
    # A later approved command can corrupt a formerly accepted metric. finish
    # must re-read it, not trust the command's earlier cached verified=True.
    repo = base / "structured-overwrite-repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Evaluate\npython evaluate.py\n## Postprocess\npython postprocess.py\n", encoding="utf-8")
    (repo / "evaluate.py").write_text(valid_program, encoding="utf-8")
    (repo / "postprocess.py").write_text("from pathlib import Path\nPath('results/metrics.json').write_text('{\"eval\": {\"accuracy\": 0.1}}')\n", encoding="utf-8")
    task = {"goal": "Verify final outputs", "commands": {
        "eval": {"argv": ["python", "evaluate.py"], "documented_command": "python evaluate.py", "verification": verification},
        "postprocess": {"argv": ["python", "postprocess.py"], "documented_command": "python postprocess.py"}}, "required_commands": ["eval"]}
    overwritten = agent.run(task, repo, base / "structured-overwrite-out", profile, ScriptedProvider([
        [call("run_command", command_id="eval")], [call("run_command", command_id="postprocess")], [call("finish", summary="done")]]))
    assert overwritten["attempts"][0]["verified"] is True
    assert overwritten["status"] == "blocked" and not overwritten["verification"]["commands"]["eval"]
    assert overwritten["verification"]["details"]["eval"]["metrics"][0]["observed"] == 0.1
    # Strict contract validation happens before a provider call or subprocess.
    invalid_specs = [{}, [], {"unexpected": []}, {"metrics": []}, {"artifacts": []},
        {"artifacts": [{"path": "../outside"}]}, {"artifacts": [{"path": ""}]},
        {"artifacts": [{"path": "results/predictions.txt", "min_bytes": True}]},
        {"artifacts": [{"path": "results/predictions.txt", "min_bytes": -1}]},
        {"artifacts": [{"path": "results/predictions.txt", "sha256": "not-a-digest"}]},
        {"artifacts": [{"path": "results/predictions.txt", "unknown": 1}]},
        *[{"metrics": [{**metric, "expected": bad}]} for bad in (True, float("nan"), float("inf"), "0.91")],
        *[{"metrics": [{**metric, "absolute_tolerance": bad}]} for bad in (-1, True, float("nan"), float("inf"))],
        *[{"metrics": [{**metric, "key": bad}]} for bad in ([], [""], [True], "accuracy")],
        {"metrics": [{**metric, "path": str(repo / "results/metrics.json")}]},
        {"metrics": [{**metric, "unknown": 1}]}]
    for index, spec in enumerate(invalid_specs):
        invalid = {**task, "commands": {"eval": {**task["commands"]["eval"], "verification": spec}}}
        provider = ScriptedProvider([])
        try:
            agent.run(invalid, repo, base / f"invalid-verification-{index}", profile, provider)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid verification accepted: {spec}")
        assert not provider.requests
    # Artifact hashes and JSON decoding errors are independent of stdout.
    artifact = repo / "results/predictions.txt"
    good_hash = agent.hashlib.sha256(artifact.read_bytes()).hexdigest()
    runtime = {"runtime_status": "success", "returncode": 0, "stdout": "complete"}
    for digest, expected in ((good_hash, True), ("0" * 64, False)):
        checked = agent.command_checks(repo.resolve(), {"verification": {"artifacts": [
            {"path": "results/predictions.txt", "sha256": digest}]}}, runtime)
        assert checked["passed"] is expected
        assert checked["artifacts"][0]["observed_sha256"] == good_hash
    metric_path = repo / "results/metrics.json"
    for invalid_json in ("not JSON", '[1, 2]', '{"eval": {"accuracy": "0.91"}}', "{" + " " * (1024 * 1024)):
        metric_path.write_text(invalid_json, encoding="utf-8")
        checked = agent.command_checks(repo.resolve(), {"verification": {"metrics": [metric]}}, runtime)
        assert not checked["passed"] and checked["metrics"][0]["reason"]
    for language in ("en", "zh-CN"):
        interrupted = agent.delivery_fields({"language": language}, {"status": "running", "results": {}})
        assert interrupted["status"] == "not_run"
        assert "--resume" in interrupted["next_action"]
        assert ("interrupted or still active" if language == "en" else "已中断或仍在运行") in interrupted["result_summary"]
    # Symlink escapes are rejected both before execution and at final checking.
    escape = repo / "outside-link"
    try:
        escape.symlink_to(base, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    else:
        escaped = {"verification": {"artifacts": [{"path": "outside-link/private.txt"}]}}
        try:
            agent.validate_verification(escaped, repo.resolve())
        except ValueError:
            pass
        else:
            raise AssertionError("Verification followed an escaping symlink")
        detail = agent.command_checks(repo.resolve(), escaped, {"runtime_status": "success", "returncode": 0})
        assert not detail["passed"]


def test_source_adjacent(base, profile):
    from annotate_readme import strip_annotated_bytes
    repo = base / "adjacent-repo"
    (repo / "docs/media").mkdir(parents=True)
    original = b"# Real README\r\n\r\n![plot](media/plot.svg)\r\n<video src='media/demo.mp4'></video>\r\n## Evaluation\r\npython evaluate.py\r\n"
    (repo / "docs/README.md").write_bytes(original)
    (repo / "docs/media/plot.svg").write_text("<svg/>", encoding="utf-8")
    (repo / "docs/media/demo.mp4").write_bytes(b"test-placeholder-not-playable-video")
    (repo / "evaluate.py").write_text("print('complete')\n", encoding="utf-8")
    task = {"goal": "Evaluate and preserve README context", "readme": "docs/README.md", "commands": {
        "eval": {"argv": ["python", "evaluate.py"], "documented_command": "python evaluate.py", "expected_stdout": "complete"}},
        "required_commands": ["eval"]}
    provider = ScriptedProvider([[call("run_command", command_id="eval")], [call("finish", summary="done")]])
    output = base / "adjacent-out"
    first = agent.run(task, repo, output, profile, provider, pause_after_tools=1, source_adjacent_readme=True)
    destination = repo / "docs/RIGORPILOT_README.md"
    assert first["readme_delivery"]["status"] == "written"
    assert "docs/RIGORPILOT_README.md" not in first["files"]
    assert strip_annotated_bytes(destination.read_bytes()) == original
    assert "🟡 `partial`" in destination.read_text(encoding="utf-8")
    resumed = agent.run(task, repo, output, profile, provider, resume=True, source_adjacent_readme=True)
    assert resumed["status"] == "success" and resumed["verification"]["source_unchanged"]
    assert len(list((output / "_runtime").iterdir())) == 1
    assert strip_annotated_bytes(destination.read_bytes()) == original
    assert "🟢 `success`" in destination.read_text(encoding="utf-8")
    assert "../../adjacent-out/SUMMARY.md" in destination.read_text(encoding="utf-8")
    assert (repo / "docs/README.md").read_bytes() == original
    assert (repo / "docs/media/plot.svg").read_text(encoding="utf-8") == "<svg/>"
    delivery_status = json.loads((output / "status.json").read_text(encoding="utf-8"))
    assert delivery_status["outputs"]["source_adjacent_readme"] == str(destination.resolve())
    assert delivery_status["source_adjacent_readme"] == delivery_status["readme_delivery"]
    # Any same-named original is protected, even if an ownership receipt from
    # another bundle exists. A new run never excludes it from source checks.
    original_copy = destination.read_bytes()
    collision_out = base / "adjacent-collision"
    collision = agent.run(task, repo, collision_out, profile, ScriptedProvider([
        [call("run_command", command_id="eval")], [call("finish", summary="done")]]), source_adjacent_readme=True)
    assert collision["status"] == "success" and collision["readme_delivery"]["status"] == "blocked"
    assert collision["verification"]["source_unchanged"]
    assert destination.read_bytes() == original_copy
    assert (collision_out / "ANNOTATED_README.md").is_file()
    assert "standard evidence was retained" in (collision_out / "SUMMARY.md").read_text(encoding="utf-8")
    # A user's edit to our generated copy while paused cannot be overwritten or
    # hidden by changing the mutable ownership receipt to match that edit.
    for label in ("changed", "deleted", "receipt-forged"):
        case_repo = base / f"adjacent-{label}"
        case_repo.mkdir()
        (case_repo / "README.md").write_text("# Evaluate\npython evaluate.py\n", encoding="utf-8")
        (case_repo / "evaluate.py").write_text("print('complete')\n", encoding="utf-8")
        case_task = {**task, "readme": "README.md"}
        case_output = base / f"adjacent-{label}-out"
        script = ScriptedProvider([[call("run_command", command_id="eval")], [call("finish", summary="done")]])
        agent.run(case_task, case_repo, case_output, profile, script, pause_after_tools=1, source_adjacent_readme=True)
        copy = case_repo / "RIGORPILOT_README.md"
        if label == "deleted":
            copy.unlink()
        else:
            copy.write_text("User replacement, preserve me", encoding="utf-8")
            if label == "receipt-forged":
                receipt_path = case_output / "readme_delivery.json"
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["sha256"] = agent.hashlib.sha256(copy.read_bytes()).hexdigest()
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        request_count = len(script.requests)
        try:
            agent.run(case_task, case_repo, case_output, profile, script, resume=True, source_adjacent_readme=True)
        except ValueError as exc:
            assert "ownership changed" in str(exc)
        else:
            raise AssertionError(f"Resume ignored changed generated README: {label}")
        assert len(script.requests) == request_count
        assert not copy.exists() if label == "deleted" else copy.read_text(encoding="utf-8") == "User replacement, preserve me"


if __name__ == "__main__":
    raise SystemExit(main())
