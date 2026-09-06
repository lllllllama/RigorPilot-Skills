# 受控试验：先验证执行边界，再接真实模型

[English](CONTROLLED_TRIALS.md) · [小型对照评测](PAIRED_PILOT.zh-CN.md) · [评测入口](../benchmarks/README.md)

试验内核已连接中立工具循环、受限命令代理、独立评分器和可持久化的单次预算账本。
可直接运行的演示使用**脚本化传输响应与真实本地 Python 进程**，验证控制器行为，
不测量模型智能，也不证明 skill 带来了能力提升。

## 运行与查看

在项目根目录使用已有 Python 执行：

```bash
python benchmarks/run_controller_smoke.py --output repro_outputs/controller-check
```

每次使用尚不存在的输出目录。无需调用模型 API、安装依赖、下载仓库或模型。
任务只使用 Python 标准库，明确属于人工构造的故障注入案例。

查看生成的 `REPORT.json` 及其逐案例证据路径。
[公开报告](../benchmark_outputs/controller_smoke/REPORT.json) 提供已记录的实际结果；
下方案例列表不是通过结果声明。

| 案例 | 实际检查内容 |
|---|---|
| 缺少资产 | 首次评估失败；本地准备数据后再次评估，得到 MSE 0。失败尝试与后续成功命令均保留。 |
| 指标不符 | 命令退出码为 0，但实际 MSE 为 1，不是要求的 0。准确报告 `mismatched` 可以通过处理验收，不等于科学结果达标。 |
| 用量未知 | 脚本化响应没有可接受的用量记录。在执行其工具请求前停止，保留尚未结算的预留。 |
| 路径越界 | 拒绝读取工具范围之外的路径，不泄露私有控制文件。 |

命令日志和产物来自实际执行的预审子进程；结论、工具选择、模型身份及其报告的
token 数来自脚本化测试数据。`accepted` 与测试数据中的 token 数都不能当作真实
模型结果。用于开发项目的宿主代理可能消耗 token，本命令不测量那部分用量。

2026-09-06 实测：**4/4 控制检查通过**，共四次真实命令执行，包含一次保留的失败。
完整快照约 65 KiB，可直接查看：[首次失败](../benchmark_outputs/controller_smoke/missing_asset/evidence/commands/0001/steps/evaluate/stderr.log)、
[准备后完成](../benchmark_outputs/controller_smoke/missing_asset/RESULT.json)、
[指标不匹配](../benchmark_outputs/controller_smoke/wrong_metric/RESULT.json)、
[未知用量停止](../benchmark_outputs/controller_smoke/unknown_usage/RESULT.json)、
[越界请求拒绝轨迹](../benchmark_outputs/controller_smoke/path_denied/evidence/trace.jsonl)。
日志中的历史绝对路径保持原样；公开副本用于浏览，不能直接恢复为活动试验。
`python scripts/check_publication.py` 可验证 Git 提交中这些文件的字节。

## 内核实现了什么

| 组件 | 职责 |
|---|---|
| [试验控制器](../benchmarks/trial_controller.py) | 使用共同的中立系统提示词和工具格式；校验响应，先记用量再执行工具，最后收集独立评分。 |
| [工具访问代理](../benchmarks/trial_broker.py) | 有界读取仓库或技能文件；只执行冻结的命令 ID，不接受自定义参数或 shell 工具；执行记录和评分输入由操作者控制。 |
| [预算账本](../benchmarks/trial_budget.py) | 追加并同步预留、结算和停止事件；执行单次试验的 token、调用次数与耗时检查。 |

提供的工具为 `list_files`、`read_file`、`run_command` 和 `finish`。模型不能通过
这些工具上传执行记录，也不能修改评分器、控制文件、原始 README、媒体、科学代码
或评估标准。命令执行后，只开放采集到且明确允许读取的结果文件。

未来若进行对照，A 可访问仓库，B 额外可读取冻结的技能文件。内核**不会执行技能
随包脚本**。因此应称为“受限工具下的 skill 指引试验”，不能称完整技能包 A/B、
安装验证、客户端自动发现测试或不受限的自主 agent benchmark。

## 用量与停止行为

账本仅覆盖**单次试验，且目录由一个操作者独占**。它不是整个评测批次的总账，也
没有多进程锁。必须明确提供正整数 `max_total_tokens`、`max_model_calls`、
`max_tool_calls` 和 `max_seconds`；不读取订阅余额，也不默认推断可消费额度。

- 派发前预留，并将事件同步到磁盘。基于请求字节数的预留是保守估计，不是已经证明
  的分词器上界。
- 处理响应前先结算有效的输入、输出和缓存用量。实际用量超限时保留数值，停止后续
  动作。缓存计量须按传输协议归一化，不能随意复制其他 API 的字段。
- 用量缺失、格式错误或请求结果不明确时，`tokens_used` 为 `null`，但保留
  `known_tokens` 和待结算预留。不释放该预留，不重发请求，不自动恢复未决运行。
- 控制器报告中的 `model_calls` 统计实际 `complete()` 调用次数；
  `dispatch_reservations` 单独统计已持久化的预留次数。离线运行的
  `live_model_calls` 为 0；`fixture_reported_tokens` 只是测试数据，真实用量字段
  `tokens_used` 和费用 `cost` 均保持 `null`。

模式明确为 `reservation_plus_post_response_stop`，即“预留并在响应后检查停止”。
这是本地控制策略，**不是供应商扣费绝对硬上限**，也不能按订阅剩余百分比停止。

任一轨迹写入失败，都不能把运行记为已验收；即使稍后的最终记录写入成功，
`trace_complete` 仍为 `false`。独立评分和已知用量照实保留，不能用任务结果正确
来掩盖执行证据缺失。

## 接入条件与隔离限制

当前是依赖注入式库：操作者须提供传输实现、明确的供应商/模型/版本身份和预算。
传输需归一化 `model`、文本或工具调用形式的 `content` 及 `usage`；该格式接近
Anthropic Messages，**不是 OpenAI Responses 原始响应适配器**。内核校验返回的
模型标识；配置的版本会被记录，但不能据此证明服务端实际运行了该版本。
这里没有真实 API 命令行入口，也没有完成真实供应商调用验收。

`broker_scoped` 只限制模型通过工具能够访问的范围，`os_sandbox` 明确为
`false`。轨迹默认私有；模型文字和工具输出不保证自动脱敏，公开前须人工检查。
传输异常只记录类型，不记录任意错误正文或鉴权头。
本地 Python 仍使用宿主依赖，未对宿主文件、网络、`PATH` 或
`PYTHONPATH` 做强隔离。预审命令会收到超时限制，但不保证操作系统进程树清理，
也不保证远端请求被取消。不能在这一边界下运行未审查或恶意仓库。

真实试验前，仍须确认模型及明确的费用/token 限额，审计供应商的用量、超时与重试
行为，增加批次总账，并选择适当的真实进程/网络隔离方案。先做一次限额试跑，再
建立新的冻结对照。历史小型评测的六个模型试验仍为 `not_run`；此次冒烟测试不会
改写它们的协议或结果。

设计参考：[OpenAI 函数调用指南](https://developers.openai.com/api/docs/guides/function-calling)
说明由应用执行工具的流程；[Responses API 参考](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
提供响应与用量字段定义。这些只是设计来源，不代表项目已接入或验证 OpenAI 模型
与 API 适配器。
