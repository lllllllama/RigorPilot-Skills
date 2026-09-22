# Current acceptance status

[README](../README.md) · [Real-client evidence](REAL_CLIENT_ACCEPTANCE.md) · [Agent runtime review](AGENT_RUNTIME_REVIEW.md) · [Engineering roadmap](ENGINEERING_ROADMAP.md)

This page is the compact current-state ledger. Detailed reports keep their
historical narrative; update this page when a gate changes instead of repeating
the same status across every overview.

| Gate | Current state | Evidence boundary |
|---|---|---|
| Reviewed README planning | **Passed** on the four pinned planning cases | Planning only; not four completed reproductions |
| Explicit named-skill real client | **Passed** on pinned micrograd | One real client/task, not model uplift |
| Fresh-client natural-language AUTO | **Passed** on 2026-09-22; two earlier failures remain retained | Proves loading + bounded task acceptance, not an A/B benefit |
| Optional short-call handoff | **Passed** in real local bridge/fault tests and installed-layout micrograd | Host-dependent supervisor path; the successful AUTO turn used the direct orchestrator instead |
| Core local regression | **20/20 passed in 63.6 s** on the latest simplification run | Fast iteration subset; not a substitute for full regression |
| Full local regression | **80/80 passed in 354.8 s** on the latest recorded Windows run | Local regression, not remote CI or model effectiveness |
| Same-model A/B effectiveness | **Not run** | `model_uplift` remains `null` |
| Optional standalone Anthropic transport | **No successful live-provider acceptance recorded** | Separate from the default Codex/client skill route |

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
`model_uplift` 仍为 `null`。历史失败继续保留，不用后续成功覆盖。
