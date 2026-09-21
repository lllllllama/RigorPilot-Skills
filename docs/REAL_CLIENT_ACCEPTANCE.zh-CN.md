# 真实客户端验收：显式 Fast Path 通过，自动加载端到端仍未闭环

[English](REAL_CLIENT_ACCEPTANCE.md) · [首页](../README.zh-CN.md) · [最新机器报告](../benchmark_outputs/real_client/20260921/REPORT.json) · [2026-09-20 报告](../benchmark_outputs/real_client/20260920/REPORT.json) · [2026-09-13 历史报告](../benchmark_outputs/real_client/20260913/REPORT.json)

## 2026-09-21 AUTO 复验

用户明确授权本轮不等待历史协议中的 70% quota 启动门槛，因此 quota 百分比只做
观察，不参与自动停止；其他条件保持不变：固定 micrograd `7bc720e`、技能提交
`9a86470`、Codex `0.154.0-alpha.6.2`、`gpt-6-astra` / high、目标命令最多
30 秒、外层 240 秒、最多 16 次工具启动、无自动重试、AUTO 失败后不进入 A/B。

自然语言 prompt 仍未写技能名；trace 再次证明项目级 `ai-research-reproduction`
被自动发现并实际调用 `orchestrate_repro.py`。上一轮的 20 秒问题已经修正：本轮确实
使用了完整 **30 秒** 目标 timeout。**但端到端验收仍失败。**

这次代理又给整个 orchestrator 套了一层同样 30 秒的 `subprocess` timeout。
外层包装约 30.047 秒先超时，orchestrator 因此来不及完成自己的子进程清理与终态
证据落盘。保留的 runtime `state.json` 仍是 `running`，`status.json` 没有生成，
独立 first-use grader 无法通过；随后外层 Codex 客户端在 240 秒 watchdog 处结束，
共 9 次工具启动，没有 `turn.completed`。

| 检查 | 结果 | 证据 |
|---|---|---|
| 自然语言自动加载 | **再次观察到**；prompt 未写技能名，trace 命中项目技能与 orchestrator | [AUTO 报告](../benchmark_outputs/real_client/20260921/AUTO/REPORT.json) · [结束记录](../benchmark_outputs/real_client/20260921/AUTO/client/END.public.json) |
| 用户命令时间上限 | **已保留**为 30 秒 | [orchestrator 命令](../benchmark_outputs/real_client/20260921/AUTO/repo/repro_outputs/orchestrator.command.json) |
| orchestrator 收口 | **失败**；等长外层 timeout 抢先杀死 orchestrator | [runtime 状态](../benchmark_outputs/real_client/20260921/AUTO/repo/repro_outputs/_runtime/20260921T025519Z-09a06136/state.json) |
| 事后验证 | 以 `runtime_incomplete_without_status` **失败关闭**，不自动重放命令 | [postmortem verifier](../benchmark_outputs/real_client/20260921/AUTO/POSTMORTEM_VERIFY.json) |
| 原始源码 | 13 个 baseline 文件仍匹配；这不等于任务完成 | [独立检查](../benchmark_outputs/real_client/20260921/AUTO/EVIDENCE_CHECK.json) |
| 模型用量 / 增益 | 无 `turn.completed`，usage 不可得、费用未知；A/B 未运行，`model_uplift=null` | [机器总报告](../benchmark_outputs/real_client/20260921/REPORT.json) |

对应产品修正不是“再试一次”，而是把 timeout 语义机器化：`--timeout` 只限制**目标
命令**，不限制 orchestrator 全生命周期；`plan-only` 现在明确返回
`timeout_scope=target_command_only`、`orchestrator_must_reach_terminal_state=true`、
`external_timeout_wrapper_allowed=false`。若宿主必须设置外层 watchdog，它必须明显长于
目标 timeout，给子进程清理和终态证据落盘留出时间。`--verify-output` 也会把这种残留
非终态 runtime 识别为 `runtime_incomplete_without_status`，而不是笼统的 missing evidence。

本轮 quota gate 由用户显式授权绕过，因此它不是对前几轮预算协议的同条件替代；失败仍保留，
也不会解锁 A/B。

## 2026-09-20 复验

使用当前技能提交 `184b163`、固定 micrograd `7bc720e`、Codex
`0.154.0-alpha.6.2`、`gpt-6-astra` / high、已有 Python/PyTorch/pytest、CPU，
外层仍使用 240 秒 watchdog。技能从当前本地 Git 提交复制到新仓库的
`.agents/skills/`；因此本次验证真实客户端行为，不重复声称远程安装器验收。

| 门槛 | 实际结果 | 证据 |
|---|---|---|
| 显式 named-skill Fast Path | **通过**。客户端返回 0 且有 `turn.completed`；6 次工具启动，128.094 s。README 的 `python -m pytest` 两项原测试均通过，源码完整性不变，独立首次使用 grader 与 `--verify-output` 均通过。 | [B 报告](../benchmark_outputs/real_client/20260920/B/REPORT.json) · [结束记录](../benchmark_outputs/real_client/20260920/B/client/END.public.json) · [独立验收](../benchmark_outputs/real_client/20260920/B/EVIDENCE_CHECK.json) |
| 新客户端自然语言自动加载 | **自动发现通过，但端到端任务验收失败。** prompt 未写技能名；trace 明确出现项目级技能与 `orchestrate_repro.py`，客户端也正常完成：8 次工具启动，157.281 s。但代理在用户允许“单命令最多 30 秒”时自行选择 `--timeout 20`，pytest 停在 `collecting ...` 后被如实记录为 `partial` / `timeout`。 | [AUTO 报告](../benchmark_outputs/real_client/20260920/AUTO/REPORT.json) · [结束记录](../benchmark_outputs/real_client/20260920/AUTO/client/END.public.json) · [状态](../benchmark_outputs/real_client/20260920/AUTO/repo/repro_outputs/status.json) |
| 30 秒无模型诊断 | 新 checkout 上 **通过**：两项测试 10.61 s 内完成。该结果支持把 AUTO 失败视为本次选择的 timeout 过严；它不是把 AUTO 改判为通过，也不是模型重试。 | [诊断](../benchmark_outputs/real_client/20260920/TIMEOUT_DIAGNOSTIC.json) |
| A/B 模型对照 | **未运行**。AUTO gate 未通过后按协议停止扩展，`model_uplift` 仍为 `null`。 | [总报告](../benchmark_outputs/real_client/20260920/REPORT.json) |

两次真实 turn 都返回了完整 usage：显式运行 145,689 input tokens（其中
116,224 cached）和 3,087 output tokens；AUTO 为 222,679 input tokens（189,952
cached）和 3,337 output tokens。provider 费用仍未知。私人额度百分比不发布，
也不用于反推 token 或费用。

这次失败直接产生一项修正：Fast Path 现在明确要求保留用户给出的单命令 timeout
上限，不应在普通可信执行中自行缩得更严；非训练 timeout 的安全下一步也改为保持
同一已审核命令和协议，只在用户既有预算允许时增大 `--timeout`，而不是修改依赖、输入或评测语义。

上面的 2026-09-21 复验已经使用 30 秒 timeout，并暴露了新的“等长外层 wrapper”问题。
两次 AUTO 失败都会永久保留；A/B 继续阻塞。

## 2026-09-13 历史试用

2026-09-13：从公开入口安装固定版本，在全新 Codex 会话中运行 micrograd。
**原始测试和证据验收通过，但客户端未在 240 秒内结束，因此整体不通过。**
这是一例真实模型工具调用记录，不是脚本代演；也不是模型增益或论文级复现证明。

## 直接看实际产物

| 检查 | 结果 | 原始证据 |
|---|---|---|
| 公开安装 | TLS 校验开启；46 个技能文件与固定提交内容匹配 | [安装与哈希](../benchmark_outputs/real_client/20260913/INSTALL-secure.json) · [安装日志](../benchmark_outputs/real_client/20260913/setup/public-npx-install-verified/stdout.log) |
| 实际执行 | 模型自行选择 `python -m pytest`；原有 2 项测试通过，pytest 自报 14.45 秒 | [完整测试输出](../benchmark_outputs/real_client/20260913/B/repo/repro_outputs/_runtime/20260913T125713Z-fd901d8d/stdout.log) · [调用记录](../benchmark_outputs/real_client/20260913/B/repo/repro_outputs/invocation.json) |
| 原文与媒体 | 全部 13 个原文件保留；8 个标题块对应 8 条批注，另有一个摘要插入块 | [原 README](../benchmark_outputs/real_client/20260913/B/repo/README.md) · [完整批注 README](../benchmark_outputs/real_client/20260913/B/repo/RIGORPILOT_README.md) |
| 独立验收 | 原文件哈希、逐块插入、字节还原、插入链接和运行日志一致性通过 | [独立检查](../benchmark_outputs/real_client/20260913/B/EVIDENCE_CHECK.json) |
| 客户端结束 | **未通过**；241.516 秒时已停止，没有 `turn.completed` | [结束记录](../benchmark_outputs/real_client/20260913/B/client/END.public.json) · [完整动作轨迹](../benchmark_outputs/real_client/20260913/B/client/TRACE.jsonl) |

批注 README 中的绿色 `success` 指选定命令成功，不代表外层客户端完成。
其中的内部“复现得分”也不是论文指标、模型增益或这次端到端验收分数。
产物保持当时的原样，不将超时试用重新包装成全通过案例。

## 如何运行的

- 技能固定在 [`3f4ff41`](https://github.com/lllllllama/RigorPilot-Skills/commit/3f4ff415bc678fc83db673288d33b1a8fb5458aa)，其 [Windows / Linux / macOS CI](https://github.com/lllllllama/RigorPilot-Skills/actions/runs/34757822033) 均通过。
- 目标是新拉取的 [micrograd 固定提交](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c)，不是重写 README 的简化替身。
- 使用 `skills@1.5.26`、临时便携 Node 22.20.0，项目内安装单个技能；不改全局安装。
- 明确调用已安装技能；新会话禁用用户配置、记忆、其他全局技能与多 Agent。
  请求模型 `gpt-6-astra` / `high`，使用现有 Codex 登录；没有把订阅转成 API 余额。
- 提供任务和限制，**没有提供预选测试命令或参考答案**。模型实际读取技能和 README，
  产生 8 次 shell 执行及 1 次文件修改工具调用；新增的证据脚本位于输出目录，原文件未改。
- 使用已有 Python / PyTorch / pytest 环境和 CPU，禁止任务安装、下载、训练。
  这不是从空白依赖环境自主搭建的验证，也不是陌生任务的留出评测。

[冻结启动参数](../benchmark_outputs/real_client/20260913/B/client/START.json) ·
[原始用户提示](../benchmark_outputs/real_client/20260913/B/client/PROMPT.txt) ·
[当时的采集器](../benchmark_outputs/real_client/20260913/B/client/COLLECTOR.py)

采集器是保留的 Windows 单次实验脚本，含宿主路径，不是通用产品入口。
外层设置 240 秒墙钟停止条件；已观察到超时后的进程树终止。16 次上限实际计数
shell 执行，文件修改另计。原生 token 预算功能仍属实验性，不能宣传为硬额度保证。
额度快照只覆盖服务返回的窗口；缺失的最终 token 用量和费用均记为未知，不用百分比反推。

## 失败也公开

1. 首次安装继承宿主的 `NODE_TLS_REJECT_UNAUTHORIZED=0`，因此不接受为安全安装通过。
   [原始警告](../benchmark_outputs/real_client/20260913/setup/public-npx-install/stderr.log) 保留；
   随后仅在子进程开启校验，换新缓存、新目标目录，重新安装。
2. Codex `0.150.1` 的真实请求被服务端 HTTP 400 拒绝，明确要求更新客户端才能运行该模型。
   [失败轨迹](../benchmark_outputs/real_client/20260913/B/client-cli-0.150.1-rejected/TRACE.jsonl) 保留，
   没有执行仓库命令。随后使用机器已有的 `0.154.0-alpha.6.1`，未更新全局 CLI，也未换模型。
3. 新客户端成功执行测试并生成证据，但没有按时结束。最终 token 用量未知，
   **停止继续试跑；无 Skill 的 A 组未执行，模型增益仍为 `null`。**

轨迹显示模型在执行前多次阅读随包实现，产生较大的工具输出；但没有逐请求耗时或
内部推理记录，不能断言超时全部由 Skill、模型思考或服务延迟中的某一个因素造成。
启动日志中还有遥测和远程 MCP 连接警告；没有据此宣称服务故障，也不宣称客户端完全离线。

## 根据观察做了什么修正

成功报告原先仍建议“继续下一步验证”。现在改为核验现有证据、交付本次结果后停止。
上面的 2026-09-20 显式 named-skill 复验已经证明该 Fast Path 可以正常完成外层客户端；
自然语言 AUTO 则进一步暴露了“自行把 30 秒上限缩成 20 秒”的新问题，因此 A/B 仍需等
修正后的 AUTO gate 通过后再启动。

公开快照约 0.5 MB；原文件、媒体和 notebook 均保留。
[文件字节清单](../benchmark_outputs/real_client/20260913/FILES.json) 标记原样复制的文件；
只省略 Node 二进制、npm 缓存、Git 元数据、重复技能包、测试缓存和私人额度快照。
结束记录明确注明省略字段及本地原件哈希；凭据与完整宿主环境从未收录。
绝对路径保留运行时原值，复制后的快照用于浏览，不能沿旧路径恢复任务。
