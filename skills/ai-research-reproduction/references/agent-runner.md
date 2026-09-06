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

Add `--source-adjacent-readme` to also create `RIGORPILOT_README.md` in the
original README's directory, where relative images, videos and file links keep
their original context. The standard `repro_outputs/ANNOTATED_README.md` remains.
Open the file named by `status.json.source_adjacent_readme.path` when its status
is `written`. Existing original files are never replaced. Collisions report
`blocked` for this optional copy while retaining the task's standard evidence;
this delivery status is separate from task acceptance. Resume with the same flag.
The bundle ownership receipt and saved digest allow only an unchanged generated
copy to refresh; editing or deleting that copy prevents automatic resume.

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

### Optional structured acceptance

Each reviewed command can add a `verification` object. For example, if its
documented evaluation writes these files, add this field to that command:

```json
"verification": {
  "artifacts": [{"path": "results/predictions.json", "min_bytes": 2}],
  "metrics": [{"path": "results/metrics.json", "key": ["eval", "accuracy"],
    "expected": 0.91, "absolute_tolerance": 0.001}]
}
```

- Paths are relative to the repository root, **not** the command's `cwd`.
  Absolute paths, `..`, protected files and symlinks escaping the repo fail.
- Artifact rules require a regular file, at least `min_bytes` (default 1), and
  optionally an exact `sha256`. Digest checks read at most 50 MiB per artifact.
- Metric rules read a JSON object (at most 1 MiB), follow the explicit nonempty
  list of object keys, and require `abs(observed - expected) <= absolute_tolerance`
  (default 0). Booleans, strings, NaN, infinity and negative tolerances are not
  accepted as numeric criteria; arrays are not implicit metric paths.
- Only `artifacts` and `metrics` are supported, each with 1–32 rules when present.
  Empty contracts, unknown rule fields and invalid values fail before model calls.
- The runner checks immediately after execution and re-reads required command
  outputs at `finish`; a later command cannot hide a corrupted metric behind an
  earlier passing verdict. Detailed observations and rejection reasons live in
  `results.<command>.checks` and `verification.details.<command>`.
- Reopening a completed run with `--resume` also rechecks current outputs, without
  model calls or command reruns. Changed or deleted accepted outputs block the
  refreshed report; `trajectory.jsonl` retains old and new checks in an appended
  `reverification` event instead of silently reissuing the old success claim.

The model cannot change this reviewed contract through its tools. The checks
prove current output contents, not that an artifact is fresh or independently
generated: use a fresh target workspace when freshness matters. This is not
automatic scientific comparability or paper-result certification. Without this
optional field, the existing exit-code/stdout acceptance remains unchanged.

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

Optional `parameters` are transmitted, not just recorded: the current transport
supports `temperature` or `top_p` (not both), and `stop_sequences`. Unsupported
fields are rejected before HTTP; `max_tokens` remains controlled by the task
budget. Leave sampling settings absent unless the selected model supports them:
the [Messages API](https://platform.claude.com/docs/en/api/messages/create)
deprecates these controls for newer models. A local protocol test is not a
compatibility claim for every model or gateway.

## Evidence, recovery and limits

The standard README bundle is accompanied by `agent_state.json` (task/model
identity, messages, plan, pending calls, results), `trajectory.jsonl` (requests,
responses, public reasons, tools and usage), and `_runtime/` process evidence.
The verifier requires all `required_commands` to pass their exit/stdout and any
reviewed artifact/metric checks
and the initial source inventory to remain unchanged. These checks demonstrate
the task's execution criteria, not a paper score or an unknown task success rate.
State schema `1.1` separates `verification.commands` from
`verification.source_unchanged`; command IDs cannot overwrite harness checks.
`verification.commands` remains a boolean map; optional additive `details`
contains the individual checks rather than changing those boolean values.
Malformed response batches are blocked before tool dispatch. Harness changes
invalidate older checkpoints: retain their evidence and start a fresh run.

Append `--resume` with the same task/model/output to continue a paused or
interrupted active session. `--pause-after-tools N` creates a deliberate durable
checkpoint for testing or splitting sessions. Completed tool observations are
reused. Uncertain command dispatch is blocked rather than duplicated; a pending
runtime is inspected. A model request interrupted before its response is saved
has unknown usage and cannot silently be replayed. Start a separate bounded run.

Controller progress and task acceptance are separate: `agent.status` keeps its
existing compatibility values, while `agent.controller_status` is `running`,
`paused`, `blocked`, or `finished`, and `agent.task_outcome` is `not_run`,
`partial`, `failed`, or `accepted`. `agent.resumable` describes whether the
recorded controller state permits resume (identity and file checks still apply).
A deliberate pause is **not** an execution failure: top-level bundle `status`
is `not_run` before commands or `partial` afterward, never overall `success`.
Individual completed commands may already be verified. Only successful
independent `finish` yields task outcome `accepted`; `blocked` controllers must
resolve the cause and start a separate run rather than blindly retry `--resume`.

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
正常暂停会保留已执行命令和证据，不再显示为“被阻塞”，也不声称整体验收完成。
`agent.controller_status` 表示控制状态，`agent.task_outcome` 表示任务结果。
命令可增加上述 `verification` 验收产物与 JSON 数值指标；退出码为 0 但产物缺失、
指标超出容差，仍不能通过最终验收。验收条件由任务文件预先审核，模型不能修改。
这些检查不单独保证产物新鲜度或科研可比性；需要时使用全新目标工作目录。
增加 `--source-adjacent-readme` 可在原 README 同目录生成源旁批注副本，保持原有
媒体相对路径；原文不修改、标准证据保留，同名原文件受保护。恢复时保留此参数。
