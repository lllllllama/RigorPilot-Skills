# P0 / P1 engineering record

## P0: published evidence must survive a checkout

The initial release passed local tests but failed Python 3.11 CI because cleanup
used `shutil.rmtree(onexc=...)`, introduced in Python 3.12. It now uses the
compatible callback. The Unicode runtime test explicitly configures UTF-8 output.
The process-tree test releases the child only after termination returns, avoiding
a false positive caused by slow host termination.

Root and embedded upstream `.gitignore` files omitted reproduction evidence and
five upstream files. Git also normalized the Windows checkout's README line
endings, invalidating the recorded byte hashes on the published branch. Scoped
Git attributes now preserve retained checkout bytes. Original media and README
content have not been reconstructed from text.

`benchmark_outputs/PUBLICATION_MANIFEST.json` records all 361 original showcase
files plus the subsequent live canary reports and snapshots.
`scripts/check_publication.py` reads the selected Git tree, validates every file
hash, counts upstream files, strips annotations against the recorded original,
and checks links inside RigorPilot blocks. It does not rewrite upstream links.
The test deliberately omits and corrupts evidence in an index to prove these
failures are detected. CI validates the committed tree on all platforms.

After regenerating a showcase, review its content, regenerate the manifest with
`python scripts/check_publication.py --write-manifest`, explicitly stage reviewed
files (including ignored evidence), and run
`python scripts/check_publication.py --ref=` to check the index before commit.
Use `python scripts/check_publication.py` to validate the actual committed tree.
Generating a manifest alone does not prove source authenticity: the pinned
source manifest and reviewer remain the provenance boundary.

## P1: model and tools with independent completion checks

Entrypoint: `skills/ai-research-reproduction/scripts/run_agent.py`.
Usage: [agent runner contract](../skills/ai-research-reproduction/references/agent-runner.md).
Example task: [micrograd.json](../examples/agent-tasks/micrograd.json).

The first transport implements the Anthropic Messages protocol, including tool
schemas, tool results and reported usage. Model configuration stays separate from
task logic. A configured model name is not evidence a gateway can serve it.

The agent can read inventoried source, update its plan and choose reviewed
command IDs. Execution uses the existing process runtime. The task declares
required commands and exit/stdout acceptance checks. The verifier checks these
and source identity independently of the model's completion message.

State includes conversation, plan, pending calls, results, command attempts,
task/model/endpoint identity and cumulative budgets. Completed commands are reused
after resume. Ambiguous interrupted dispatch is not repeated. A provider request
with unknown outcome remains blocked rather than being silently retried. A
single-writer lease prevents concurrent controllers from executing the same state.

Tests cover HTTP serialization, usage, redirects, credential-error redaction,
actual subprocess execution, pause/resume, pending-result recovery, source
fidelity, false completion, out-of-scope tools and budget stops. HTTP and decision
tests use local/scripted providers; they are engineering regressions, not
model-quality benchmarks.

Local full regression after implementation: **59/59 scripts passed in 103.0 s**.
The P0 commit `8e50d8f` passed the remote Windows, Ubuntu and macOS jobs, including
the committed-tree publication check. See the current CI badge for subsequent
commits; local success alone is not a remote CI claim.

## Real provider trials and remaining acceptance work

Three explicitly bounded real requests through the existing gateway were made:
two using its configured model and one using an alternate model. All returned
HTTP 502 before a model response or tool action. See [first trial](../benchmark_outputs/agent_canary/first-live/REPORT.json),
[second trial](../benchmark_outputs/agent_canary/second-live/REPORT.json), and
[alternate-model trial](../benchmark_outputs/agent_canary/sonnet-live/REPORT.json).
No successful model trial is claimed.
Zero reported tokens on these failures means no usage response was received,
not proof the gateway charged nothing. A working provider and one successful
real-model trial remain required before calling P1's live acceptance complete.

With a working endpoint and model, run one bounded public-repository trial:

```bash
python benchmarks/run_agent_canary.py --model YOUR_AVAILABLE_MODEL_ID --output benchmark_outputs/agent_canary/new-trial
```

This fetches the pinned micrograd commit, uses host dependencies, runs the model
loop, retains original files and linked evidence, and removes its temporary
checkout. It does not install dependencies or run a broad benchmark matrix.

P1 has a reviewed command set and local-host execution. It is not an OS sandbox,
an arbitrary-code repair agent, a training-checkpoint restorer or evidence of
superiority over the same model without the skill. P2 should measure that last
question using a separate baseline and held-out tasks.

## 中文交付说明

P0 修复 Python 3.11 兼容性、Windows 测试时序和发布文件缺失。新增检查直接读取
Git 文件并校验字节哈希、原 README 还原及批注证据链接，避免把本地残留当作
已发布产物。保留的是原仓库检出文件的字节，不是重新提取的 README 文本。

P1 增加模型—工具执行循环、任务状态、预算和恢复能力。模型只能选择已审核命令，
最终成功由独立验证器判定；安装单独 skill 时也带齐所需运行代码。
自动测试覆盖主要工程行为；真实网关三次请求均返回 502，尚未通过真实模型
端到端验收。失败记录可核查，不能把未返回用量的失败解释为零费用。
