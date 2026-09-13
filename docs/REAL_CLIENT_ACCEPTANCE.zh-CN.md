# 真实客户端首次使用：测试通过，整轮超时

[English](REAL_CLIENT_ACCEPTANCE.md) · [首页](../README.zh-CN.md) · [机器报告](../benchmark_outputs/real_client/20260913/REPORT.json)

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

成功报告原先仍建议“继续下一步验证”。现在改为核验现有证据、交付本次结果后停止，
不自动追加实验；技能说明也明确完成边界，常规使用从入口与帮助开始，遇具体问题再读实现。
回归覆盖中英文成功报告、干运行和真实失败，指标不匹配与训练确认边界仍保留。
**这是有证据依据的修正，但尚未通过新的真实模型试跑证明能减少超时。**

下一步只需在预算允许时，以同样任务、新目录重试修正版本，验收必须同时满足：
命令通过、原文保真、证据通过、客户端正常结束。通过后再跑同条件 A 组，不能只比较产物数量。

公开快照约 0.5 MB；原文件、媒体和 notebook 均保留。
[文件字节清单](../benchmark_outputs/real_client/20260913/FILES.json) 标记原样复制的文件；
只省略 Node 二进制、npm 缓存、Git 元数据、重复技能包、测试缓存和私人额度快照。
结束记录明确注明省略字段及本地原件哈希；凭据与完整宿主环境从未收录。
绝对路径保留运行时原值，复制后的快照用于浏览，不能沿旧路径恢复任务。
