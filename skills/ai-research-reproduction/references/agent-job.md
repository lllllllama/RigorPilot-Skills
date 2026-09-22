# Short-call reproduction jobs

Use `scripts/repro_job.py` when a host tool call cannot wait for the entire
non-training reproduction lifecycle. It supervises the existing orchestrator;
it does not introduce a model loop, replace the runtime, or relax lane policy.
The synchronous CLI remains supported, especially on hosts whose sandbox kills
all child processes when a tool call ends.

## Review, hand off, observe

First run the usual read-only plan with the intended user timeout and output:

```bash
python scripts/orchestrate_repro.py --repo /path/to/repo --plan-only --agent-output --timeout 30 --source-adjacent-readme
```

Paths above are relative to the installed skill. Review the README candidate and
its side effects, then pass the returned `agent_handoff.start_argv` as an argv
array with `shell=False`. Once start returns, use the **receipt's** `status_argv`
and `cancel_argv`: they bind the output directory to its exact `job_id`. A stale
receipt cannot accept or cancel a replacement job at the same path. Do not invent another shell wrapper or recursively
invoke an agent. Unsupported options/training plans do not offer this handoff.

The equivalent manual calls are:

```bash
python scripts/repro_job.py start --repo /path/to/repo --command-id cmd-01 --plan-fingerprint REVIEWED_SHA256 --timeout 30 --source-adjacent-readme
python scripts/repro_job.py status --output-dir /path/to/repo/repro_outputs --job-id RETURNED_JOB_ID
python scripts/repro_job.py cancel --output-dir /path/to/repo/repro_outputs --job-id RETURNED_JOB_ID
```

`REVIEWED_SHA256` is a placeholder for the actual plan fingerprint, not a value
to execute literally. `RETURNED_JOB_ID` comes from the start receipt. A path-only
status query is supported to recover a lost start response and explicitly reports
`identity_checked=false`; inspect the request identity before taking further action.
`start` requires an empty output directory and returns
before task completion. Redirect a planning preview outside that directory.

## Guarantees and boundaries

| Contract | Behavior |
|---|---|
| One request per directory | An atomic `.repro_job/` ownership claim and a one-use worker claim prevent duplicate dispatch through this API. Repeating the same request returns the same receipt; different parameters fail with `job_conflict`. |
| Receipt identity | Follow-up argv include `--job-id`. A different job at the same path is rejected before returning its result or writing a cancellation marker. This is a consistency check, not authentication against a hostile same-user process. |
| Reviewed target | The worker re-plans without target execution, checks the fingerprint, rejects training, then the original orchestrator checks the fingerprint again before execution. No arbitrary argv, installation, or download endpoint is added. |
| Bounded execution | `--timeout` remains the target timeout. The supervisor separately budgets 30 s for planning, target timeout + 60 s for execution/finalization, and 30 s for verification. Launch/termination latency is additional; this is not an OS or billing quota. |
| Cancellation | `cancel` records intent. During execution the supervisor uses the existing runtime `CANCEL` mechanism and allows the orchestrator to write terminal evidence. A command that already finished may still report success. |
| Disconnect | Subsequent calls query the saved job. A missing/dead/stale supervisor is reported conservatively; it does not cause automatic replay. A stale PID is never used by `status` or `cancel` to kill a process. |
| Output | Full runtime evidence stays under `_runtime/`. `.repro_job/` contains the request, worker claim, receipt, heartbeat and phase stdout/stderr. Python output is unbuffered; full host environment and credentials are not copied into receipts. |

`lifecycle=completed` includes valid task failures. A completed timeout should
have `result.runtime_status=timed_out`, `result.evidence_valid=true`, and
`result.accepted=false`. Acceptance also requires task/runtime success, unchanged
source, current-format manifest coverage, no configured metric mismatch, and the
source-adjacent README when requested. This is bounded task acceptance, not a
paper-reproduction claim.

`result` is a verification snapshot at `verified_at`. `status` does not rehash an
entire repository on every poll. Use the ordinary `--verify-output --agent-output`
for a fresh check after files may have changed. Never treat a cached receipt as
a new attestation or `evidence_valid` alone as scientific success.

The host must permit a bounded child supervisor to outlive the calling CLI. No
breakaway-from-sandbox flag is used. A host kill-on-close job, forced process-tree
termination, machine shutdown, or hostile same-user file edits can interrupt the
worker. On uncertainty preserve the directory and inspect the processes; no
exactly-once guarantee across machines/crashes or cryptographic authenticity is
claimed. Native shell commands and target programs still run with local rights.

## 中文说明

这是短工具调用的执行交接入口，不是新模型后端。先审阅计划，再执行返回的 argv，
之后查询同一任务；相同输出目录和相同参数不会重复执行。超时、取消和指标不匹配
可以正常产生终态证据，但不能被计为任务成功。状态中的结果是完成时的验证快照，
后续改动需要再次 `--verify-output`。宿主不允许子进程存活时应使用其原生持久执行
会话，不绕过沙箱，也不在状态不明时自动换目录重跑。训练仍使用原有训练通道。
