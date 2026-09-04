# Runtime And Model Adapter Contract

Read this reference when an executed run must survive controller restarts, be
retried with provenance, expose resource evidence, or record the model/runtime
identity used by the surrounding agent.

## Recovery semantics

- A live process with a fresh heartbeat remains `running`.
- A live process with a stale heartbeat becomes `orphaned`. Do not launch a
  duplicate; inspect or terminate it deliberately.
- A stale `created` or `running` record whose PID is gone becomes
  `interrupted`.
- Retry is always explicit and creates a new run ID. Its `spec.json` records
  `retry_of` and an incremented `attempt`; prior evidence is immutable.
- Successful runs are not retryable unless the caller explicitly allows an
  intentional repeat.

From a repository checkout:

```bash
python shared/scripts/runtime_runner.py --runtime-root repro_outputs/_runtime list
python shared/scripts/runtime_runner.py --runtime-root repro_outputs/_runtime recover --stale-after 30
python shared/scripts/runtime_runner.py --runtime-root repro_outputs/_runtime retry --run-id <run-id>
```

`cancel` writes the control file consumed by an active runtime loop. An
orphaned process has no loop consuming that file, so it requires deliberate
process inspection instead of an automatic retry.

## Resource evidence

Each run writes `resources.jsonl`. Process CPU and RSS samples apply to the
root executed process, not an inferred sum of all descendants. NVIDIA samples,
when enabled and available, are device-global; do not attribute them solely to
the run. These scopes are recorded explicitly in `resource_summary`.

## Model profile

The profile records identity and capabilities; it does not silently choose or
invoke a provider. This keeps a run comparable as hosted models and revisions
change.

```json
{
  "adapter_id": "lab-openai-compatible",
  "provider": "openai-compatible",
  "model": "example-model",
  "revision": "2026-09-01",
  "capabilities": ["text", "tool_calling", "structured_output"],
  "endpoint": "https://gateway.example/v1",
  "credential_env": "LAB_MODEL_API_KEY",
  "parameters": {"temperature": 0},
  "metadata": {"deployment": "research"}
}
```

Use `--model-profile-json <path>` to attach the normalized profile and its
SHA-256 fingerprint to run evidence. Use repeatable
`--require-model-capability <name>` gates when a workflow truly requires a
capability. Capability names are extensible so model upgrades do not require a
hardcoded model allowlist.

Profiles must name credentials only through `credential_env`. Inline API keys,
tokens, passwords, or bearer values are rejected and never copied into runtime
evidence.

## Persistent task queue

Use the queue only when a reproduction needs multiple dependency-aware local
commands or bounded parallel work. A queue keeps each job's command, lane,
dependencies, resource request, status, runtime run ID, and retry lineage in an
atomic `queue.json`; transitions are appended to `events.jsonl`.

```bash
python shared/scripts/task_queue.py --queue-root repro_outputs/_queue add --spec-json jobs.json
python shared/scripts/task_queue.py --queue-root repro_outputs/_queue run --max-workers 2 --cpu-slots 2 --gpu-slots 0 --memory-mib 8192
python shared/scripts/task_queue.py --queue-root repro_outputs/_queue list
python shared/scripts/task_queue.py --queue-root repro_outputs/_queue recover
python shared/scripts/task_queue.py --queue-root repro_outputs/_queue retry --job-id <job-id>
```

Job specs accept `job_id`, `command`, `cwd`, `lane`, `timeout_seconds`,
`shell_mode`, `priority`, `depends_on`, `resource_request`, `runtime_root`,
`monitor_gpu`, `model_adapter`, and free-form `metadata`. `resource_request`
contains integer `cpu_slots`, `gpu_slots`, and `memory_mib` values.

Important boundaries:

- This is a single-host, single-writer scheduler, not a distributed cluster
  queue. A live lease prevents two schedulers from launching duplicate work.
- Resource values are request-based admission budgets. They do not enforce OS
  CPU, memory, or GPU isolation; observed runtime telemetry remains separate.
- Missing dependencies, cycles, and requests larger than the total budget are
  recorded as `blocked`. A failed dependency makes downstream work `skipped`.
- Recovery reconciles linked runtime state and never auto-replays work. A live
  process that cannot be safely reattached remains `orphaned`; explicit retry
  creates a new job and runtime ID.
- `cancel` creates a durable control marker. Queued work is cancelled before
  launch; a monitored running job receives the runtime's normal cancel request.
