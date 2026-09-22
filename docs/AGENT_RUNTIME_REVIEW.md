# Agent-developer review: verifiable execution handoff

[中文概要](#中文概要) · [Home](../README.md) · [Job contract](../skills/ai-research-reproduction/references/agent-job.md)

Reviewed against base commit `7e882b9` on 2026-09-22. This is an engineering
assessment and controlled execution experiment, not a paper or a model-effect
claim. Historical live failures remain unchanged.

## What the existing project gets right

The skill separates README-grounded intent, conservative setup observations,
target execution, source fidelity, evidence consistency, and explicit metric
acceptance. The standalone installed skill ships its dependencies, and the
annotated README keeps original bytes/media rather than a text-only surrogate.
These are useful research controls; replacing them with a generic autonomous
shell loop would lose the project's strongest properties.

## Findings and changes

| Finding | Evidence / impact | Change |
|---|---|---|
| Controller lifetime was only advisory | In the [September 21 live attempt](../benchmark_outputs/real_client/20260921/AUTO/REPORT.json), a target-sized external wrapper killed the orchestrator before finalization. More prompt prose alone cannot own a process lifecycle. | Add a bounded local supervisor. The short caller receives a durable receipt; subsequent calls query the same job. The original orchestrator still owns target timeout, cleanup and bundle generation. |
| An uncertain call could encourage duplicate execution | A tool disconnection gives the agent incomplete knowledge of whether work ran. Re-running a CLI blindly can repeat training/evaluation or overwrite evidence. | Freeze the request; use atomic directory ownership and a one-use worker claim. Same output/request returns the existing receipt. Conflicts, stale plans and lost workers never trigger replay. |
| A pathname is not a durable job identity | A client holding an old output path can otherwise observe or cancel a new job after that directory has been reused. | Receipts return follow-up argv bound to `--job-id`; mismatches fail before returning another job's result or creating a cancellation marker. Path-only queries explicitly report that identity was not checked. |
| Verification was not closed under malformed inputs | A legal JSON array in `status.json` raised `AttributeError`; a nonempty manifest could omit required labels; matching `running` runtime states were not themselves rejected. | Return structured failure, require expected path bindings and terminal runtime, and test invalid JSON shapes, omissions and rebinding. |
| Delivery and diagnostics had coverage gaps | Source-adjacent delivery/ownership and runtime spec were not all hashed; a supposedly bounded log diagnostic used `read_bytes()` before slicing. | Manifest `1.1` adds those bindings; legacy `1.0` reports reduced coverage. Diagnostic reads seek to the file tail instead of loading the whole log. |
| Windows file lifetime matters | Polling overlaps heartbeat replacement; sharing locks and short temporary-name collisions must not corrupt JSON or another writer's staged data. | Exclusively claim a temporary file, fsync, retry bounded sharing locks and replace atomically. After replacement, do not unlink a staging name another writer may have reclaimed. Deterministic collision/reuse/failure tests exercise these cases. |
| Context load and task acceptance were easily conflated | Historical traces repeatedly loaded implementation/reference material; a completed outer turn or a green verifier was insufficient to prove the target passed. | Keep ordinary evaluation guidance in the entrypoint, return exact argv, and expose controller lifecycle, runtime/task result and evidence validity separately. No measured token-saving claim is made. |

## Design choices

`repro_job.py` is optional and deliberately narrow: trusted non-training tasks,
one finite worker, existing runtime, ordinary files, no service installation,
no model provider, no new skill slug, and no arbitrary command-argv endpoint.
Plan extraction and fingerprint validation still happen before target execution.
The generated handoff is omitted for unsupported orchestration options.

The supervisor has separate planning, execution/finalization and verification
budgets. It does not raise the user's target timeout. Cooperative cancellation
goes through the runtime marker, not an immediate kill of the evidence writer.
If the larger supervisor deadline is exhausted, it reports failed/incomplete
state rather than manufacturing a successful terminal bundle.

The result predicate requires task/runtime success, unchanged source, current
manifest coverage, no configured metric mismatch, and requested adjacent README
delivery. Valid timeout evidence is valuable, but `accepted` remains false.
Status polling returns a completion-time snapshot; a fresh `--verify-output` is
needed after source/evidence changes.

An explicit host requirement is part of the interface: child supervisors must
be allowed to outlive a short caller. Otherwise use the host's native persistent
execution session. No sandbox breakaway is used. Host process-tree destruction,
power failure, PID reuse, or hostile same-user filesystem changes remain outside
any authenticity/exactly-once guarantee. On uncertain state, inspect rather than
replay. Static README classification is not an arbitrary-shell security boundary.

## Verifiable usefulness, not a fabricated novelty claim

The project-specific contribution is the composition of **reviewed command
identity + reusable execution receipt + cancellation-aware finalization +
explicit task/evidence acceptance**. It replaces a recurring prompt-level
failure with an executable contract and a reproducible fault comparison.
Durable task handles and process supervision are established ideas; no claim of
industry-first design, scientific algorithm novelty, or model superiority is made.

Relevant primary references are the [Python subprocess contract](https://docs.python.org/3.11/library/subprocess.html)
(outer timeout kills its subprocess, not a transactional evidence workflow) and
the [MCP Tasks draft](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks)
(durable handles and polling). This local CLI is not an implementation or
conformance claim for that evolving MCP extension.

## Evidence and reproducibility

| Evidence | What it can establish | What it cannot establish |
|---|---|---|
| [Controlled fault comparison](../benchmark_outputs/agent_handoff/faults-final.json) | Same synthetic source, real subprocesses, interrupted-wrapper evidence loss versus identity-bound receipt/poll completion; one execution despite repeated submission | Real-model behavior, workload-wide speedup, an OS sandbox |
| [Separate bridge calls](../benchmark_outputs/agent_handoff/bridge-final.json) | Actual `ckrao` start returned in 0.172 s; a later identity-bound tool call observed acceptance, and a repeated start returned the same job with execution count 1 | Codex sandbox compatibility or behavior under every host kill-on-close policy |
| [First installed micrograd attempt](../benchmark_outputs/agent_handoff/micrograd-attempt-1.json) | Original target selection and 13-file fidelity; a 30 s target timeout with complete terminal evidence and explicit rejection | Passing gradient tests; this attempt is retained as failed |
| [Second installed micrograd attempt](../benchmark_outputs/agent_handoff/micrograd-attempt-2.json) | Unbuffered stdout retains `2 passed in 29.86s`, but the process did not exit within 30 s; terminal `timed_out`, valid evidence and `accepted=false` remain distinct | End-to-end task acceptance; a success-looking log line does not override the process deadline |
| [Separate import diagnostic](../benchmark_outputs/agent_handoff/micrograd-import-diagnostic.json) | A separate observed import took about 21.8 s, with a sampled stack in PyTorch DLL loading | The unique cause of the failed attempt, a cold-start performance distribution, a retroactive pass |
| [Installed micrograd review validation](../benchmark_outputs/agent_handoff/micrograd-final-review.json) | Same pinned source and existing interpreter, 30 s target limit unchanged: pytest reports `2 passed in 24.82s`, terminal runtime and independent grader pass; start returns in 0.281 s and total lifecycle is 30.093 s | A new live-model AUTO pass, an A/B benefit, a claim that earlier attempts passed, or a general latency guarantee |
| [Full regression receipt](../benchmark_outputs/agent_handoff/final-validation/report.json) | 80/80 scripts passed in 354.5 s; retained command exit codes, logs and source hashes bind the local verification to its tested code | Remote CI, universal cross-platform compatibility or model effectiveness |

Run the fault comparison without network or model calls:

```bash
python benchmarks/run_agent_handoff_benchmark.py --output tmp/agent-handoff.json
python scripts/test_reproduction_job.py
python scripts/test_reproduction_verifier_contract.py
python scripts/test_runtime_atomic_write.py
```

For the retained pinned micrograd task, select an **existing** interpreter with
torch and pytest; the helper never installs dependencies or downloads a model:

```bash
python benchmarks/run_job_micrograd_acceptance.py --python /path/to/python --output tmp/job-micrograd.json
```

This copies only the retained upstream files after checking every baseline hash,
installs the current skill into a separate directory, selects the README target,
uses the handoff, and invokes the independent first-use grader. Its report embeds
the target stdout, source/skill hashes and observations. Reports retain temporary
paths as provenance, not resumable artifact links. A successful later attempt
does not erase earlier failure or establish a general success rate.

## 中文概要

当前瓶颈不是“技能发现不了”，而是代理把短工具调用、目标进程、证据写入和任务验收
当成同一个生命周期。新的入口将它们拆开：先取得固定回执，再查询同一任务；重复
请求不重跑，取消会让原有运行时清理，控制器结束不自动等于任务成功。

研究层面没有新算法或模型提升结论。工程层面的新增价值是把 README 审阅身份、
任务回执、终态证据和验收条件连成可测试接口，而不依靠更多强制提示词。前两次真实
micrograd 运行均未在 30 秒内完成进程退出；第二次虽然输出 `2 passed in 29.86s`，
仍保持超时和验收失败。本轮新的独立安装验证保留 30 秒目标上限，pytest 报告
`2 passed in 24.82s`，进程、证据和独立验收全部通过；控制器总耗时 30.093 秒包含收尾，
不等于放宽目标命令时限。成功的新记录不改变前两次失败，也不是新的模型 AUTO 验收。
独立导入诊断发现明显的 PyTorch DLL 加载耗时，但不能据此断言所有超时只有一个原因。

当前 `ckrao` 的不同工具调用之间已经实际验证：0.172 秒拿到回执，之后绑定任务身份查询成功，
重复提交仍是同一任务且执行计数为 1。该结果只证明当前桥接宿主，不外推到 Codex 沙箱。

下一步的真实客户端检验应先确认宿主允许监督器跨工具调用存活。若宿主终止整个
进程树，就使用其原生持久执行会话，不绕过沙箱。新的本地机制证据不能替代一次新的
完整 AUTO canary，更不能替代相同条件、独立评分的模型 A/B。
