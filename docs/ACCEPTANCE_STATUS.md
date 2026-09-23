# Current acceptance status

[README](../README.md) · [Real-client evidence](REAL_CLIENT_ACCEPTANCE.md) · [Agent runtime review](AGENT_RUNTIME_REVIEW.md) · [Engineering roadmap](ENGINEERING_ROADMAP.md)

This page is the compact current-state ledger. Detailed reports keep their
historical narrative; update this page when a gate changes instead of repeating
the same status across every overview.

| Gate | Current state | Evidence boundary |
|---|---|---|
| Reviewed README planning | **Passed** on the four pinned planning cases | Planning only; not four completed reproductions |
| Explicit named-skill real client | **Passed** on pinned micrograd | One real client/task, not model uplift |
| Fresh-client natural-language AUTO | **Passed** on 2026-09-22 at skill commit `7590f36`; two earlier failures remain retained | Historical client/task result, not a live test of current working-tree code or an A/B benefit |
| Optional short-call handoff | **Passed** in real local bridge/fault tests and installed-layout micrograd | Host-dependent supervisor path; the successful AUTO turn used the direct orchestrator instead |
| Core local regression | **20/20 passed in 52.4 s** on 2026-09-23 | Fast iteration subset; not a substitute for full regression |
| Full local regression | **82/82 passed in 304.3 s** on 2026-09-23 | Local working-tree regression with D: for test temporaries; not remote CI or model effectiveness |
| Same-model A/B effectiveness | **Not run** | `model_uplift` remains `null` |
| Optional standalone Anthropic transport | **No successful live-provider acceptance recorded** | Separate from the default Codex/client skill route |

## Evidence identity and scope

| Verification | Tested version and task | Host/date | Raw report and boundary |
|---|---|---|---|
| Core offline | Base commit `4fb7d14`; working-tree source snapshot SHA-256 `7d366a852a364fe583baa1d03a5d266894743874212a244b321ca92b81921c7b`; 20 selected scripts at that snapshot | Windows, Python 3.12.11; 2026-09-23 | Local receipt `C:\Users\17745\AppData\Local\Temp\rigorpilot-audit-core-20260923.json`; subset only |
| Full offline | Base commit `3d2b82c`; working-tree source snapshot SHA-256 `78e192cc912503ad5978066242b7b48b17fabb7d64870c391ce87feee2e0cd5c`; 82 discovered scripts | Windows, Python 3.12.11; 2026-09-23 | Local receipt `C:\Users\17745\AppData\Local\Temp\rigorpilot-merge-full-d-20260923.json`; no remote CI or model turn |
| Fresh-client AUTO | Skill commit `7590f36`, micrograd commit `7bc720e`; natural-language task | Codex CLI 0.154.0-alpha.6.2, `gpt-6-astra`; 2026-09-22 | [Original report](../benchmark_outputs/real_client/20260922/AUTO/REPORT.json) and [trace-derived counts](../benchmark_outputs/real_client/20260922/TRACE_ANALYSIS.json); one task/client only |

The offline receipts and logs are local to the named host, not published benchmark artifacts.
An initial same-source run with C: temporaries passed 81/82 scripts; the external
benchmark stopped at its 5 GiB free-disk floor. With temporaries on D:, the
same source snapshot passed all 82 scripts.
The historical trace contains 10 command events but 5 unique calls; the derived report
retains the trace hash and analyzer version. Provider usage is preserved as reported:
141,255 cumulative input tokens, including 90,880 cached input tokens. Cost remains unknown.
The previous 80/80 full-suite result remains historical evidence for its earlier version.

Default product path: `plan -> reviewed command -> run -> verify -> result`.
Short-call hosts may explicitly request `--include-agent-handoff`; it is not part
of the default planning payload. On the retained micrograd fixture, this reduced
the current plan JSON from 4,324 to 2,103 bytes (51.4%) without changing target
selection; this is a payload-size observation, not a token-usage claim.

Historical failures remain evidence, not regressions to erase:
[2026-09-20](../benchmark_outputs/real_client/20260920/REPORT.json) ·
[2026-09-21](../benchmark_outputs/real_client/20260921/REPORT.json) ·
[2026-09-22 pass](../benchmark_outputs/real_client/20260922/REPORT.json).

## 中文概要

当前默认路径已经收敛为 `计划 → 审核命令 → 执行 → 验证 → 结果`。显式技能调用与
fresh-client 自然语言 AUTO 均已有真实客户端通过记录；短调用 handoff 作为按需兼容层，
由独立桥接/故障测试验证，不再默认暴露给每次计划。模型 A/B 尚未运行，因此
`model_uplift` 仍为 `null`。2026-09-23 的较早快照 core 回归为 20/20；当前工作树
在 D 盘临时目录下完成完整套件 82/82。历史真实客户端成功对应 `7590f36`，
不代表当前工作树已做 live 复验。
历史失败继续保留，不用后续成功覆盖。
