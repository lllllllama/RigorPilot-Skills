# Model-driven reproduction runner (P1)

`scripts/run_agent.py` adds an optional Anthropic Messages tool loop to the skill.
The existing deterministic orchestrator remains available. No SDK installation
is needed: the client uses Python's standard library. Protocol reference:
https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview

## Contract

The researcher supplies a repository, a reviewed task JSON, and a model profile.
The agent reads files, records a plan, chooses reviewed command IDs, observes
runtime results, and requests final verification. It cannot invent command argv
or edit source through its tools. Every command cites an exact source snippet;
argv changes require a recorded `adaptation`. Read task argv before approving it.

This is local execution with credential environment filtering, not an OS sandbox.
Approved programs can access the host and network; use only trusted repositories
until an isolated executor is configured. Commands that change scientific
conditions must be explicitly reviewed. P1 targets small evaluations, not full
training or autonomous source repair.

## Run

```bash
python skills/ai-research-reproduction/scripts/run_agent.py --repo /path/to/repo --task task.json --model-profile model.json --output /path/to/repro_outputs
```

Task JSON:

```json
{
  "goal": "Read the README, execute the gradient tests and report the evidence.",
  "readme": "README.md",
  "commands": {
    "tests": {
      "argv": ["python", "-m", "pytest"],
      "documented_command": "python -m pytest",
      "source": "README.md",
      "timeout_seconds": 30,
      "expected_stdout": "2 passed"
    }
  },
  "required_commands": ["tests"],
  "budget": {"max_model_calls": 8, "max_tool_calls": 20,
    "max_total_tokens": 60000, "max_output_tokens": 1500,
    "max_seconds": 240, "max_output_bytes": 10000000}
}
```

Profile JSON (put the actual credential in `ANTHROPIC_API_KEY`, never the file):

```json
{
  "adapter_id": "anthropic-messages",
  "provider": "anthropic",
  "model": "YOUR_AVAILABLE_MODEL_ID",
  "credential_env": "ANTHROPIC_API_KEY",
  "capabilities": ["tool_calling"]
}
```

`endpoint` optionally names the final HTTPS endpoint. Without it, the client
uses `ANTHROPIC_BASE_URL` or the official endpoint. For an already configured
Bearer gateway, set `metadata.auth_scheme` to `bearer` and name its credential
environment variable. Redirects are refused so credentials are not forwarded.

## Evidence, recovery and limits

The standard README bundle is accompanied by `agent_state.json` (task/model
identity, messages, plan, pending calls, results), `trajectory.jsonl` (requests,
responses, public reasons, tools and usage), and `_runtime/` process evidence.
The verifier requires all `required_commands` to pass their exit/stdout checks
and the initial source inventory to remain unchanged. These checks demonstrate
the task's execution criteria, not a paper score or an unknown task success rate.

Append `--resume` with the same task/model/output to continue a paused or
interrupted active session. `--pause-after-tools N` creates a deliberate durable
checkpoint for testing or splitting sessions. Completed tool observations are
reused. Uncertain command dispatch is blocked rather than duplicated; a pending
runtime is inspected. A model request interrupted before its response is saved
has unknown usage and cannot silently be replayed. Start a separate bounded run.

Usage and elapsed execution time accumulate across resumes (offline pause time
is excluded). Before each model request, UTF-8 request bytes plus output tokens
and overhead provide a conservative token reservation. Reported usage is stored;
gateway token accounting may differ. Output size is checked between actions,
not an OS disk quota. `CANCEL` is checked between actions; use the runtime CANCEL
file to stop an active process. Credentials are not included in provider errors.
Do not publish traces from private repositories without reviewing their contents.

## 中文操作说明

这是可选的模型执行入口。任务文件预先限定可运行命令及验收条件；模型读取原始
README、选择步骤、观察执行结果，最终由独立验证器决定是否成功。原有确定性
入口继续可用。恢复时使用相同参数并增加 `--resume`，状态和预算跨会话累计。
这是本机执行，不是系统沙箱；P1 不支持自主修改科研代码，也不证明论文指标复现。
