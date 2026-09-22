# 当前技能：功能验收

[English](SKILL_ACCEPTANCE.md) · [首页](../README.zh-CN.md) · [协议源码](../benchmarks/run_skill_acceptance.py)

2026-09-13：实际调用安装目录中的复现主技能，**4/4 功能检查通过**。
证明的是执行、如实报告失败和证据交付能力，不是模型增益或论文级复现。

本地 Windows 全量回归：**71/71 脚本通过，168.3 秒**。
公开归档通过字节/链接检查及独立临时索引中的 Git 发布检查，未改变正式暂存区。
后续已发布到 [`3f4ff41`](https://github.com/lllllllama/RigorPilot-Skills/commit/3f4ff415bc678fc83db673288d33b1a8fb5458aa)，
[三平台 CI](https://github.com/lllllllama/RigorPilot-Skills/actions/runs/34757822033) 均通过。
另见[真实客户端复验](REAL_CLIENT_ACCEPTANCE.zh-CN.md)：修正后的显式 named-skill
Fast Path 已正常完成并通过独立验收；在保留前两次 AUTO 失败的同时，2026-09-22 的
fresh-client 自然语言 AUTO 也已端到端通过：任务/runtime、独立 grader、源码完整性、
证据验证和外层 turn 完成同时满足。

## 直接查看结果

| 用例 | 真实执行结果 | 技能应如何报告 | 证据 |
|---|---|---|---|
| 缺少数据（合成用例） | `FileNotFoundError`，非零退出码 | `partial`，不编造指标、不修改源码 | [批注 README](../benchmark_outputs/skill_acceptance/attempt-2/missing_asset/repo/RIGORPILOT_README.md) · [验收](../benchmark_outputs/skill_acceptance/attempt-2/missing_asset/ACCEPTANCE.json) |
| 数据已准备（合成用例） | 退出码 0；独立重算 MSE = 0 | `success`，指标 `matched` | [批注 README](../benchmark_outputs/skill_acceptance/attempt-2/matching_metric/repo/RIGORPILOT_README.md) · [验收](../benchmark_outputs/skill_acceptance/attempt-2/matching_metric/ACCEPTANCE.json) |
| 指标错误（合成用例） | 退出码 0；独立重算 MSE = 1 | `partial`，指标 `mismatched`，保留真实结果 | [批注 README](../benchmark_outputs/skill_acceptance/attempt-2/wrong_metric/repo/RIGORPILOT_README.md) · [验收](../benchmark_outputs/skill_acceptance/attempt-2/wrong_metric/ACCEPTANCE.json) |
| micrograd（公开仓库） | 未修改的两项上游测试通过 | `success`；论文指标为 `not_evaluated` | [批注 README](../benchmark_outputs/skill_acceptance/attempt-2/micrograd/repo/RIGORPILOT_README.md) · [验收](../benchmark_outputs/skill_acceptance/attempt-2/micrograd/ACCEPTANCE.json) |

[完整报告](../benchmark_outputs/skill_acceptance/attempt-2/REPORT.json) ·
[冻结输入、实现哈希及运行环境](../benchmark_outputs/skill_acceptance/attempt-2/START.json)

三个合成用例的技能执行耗时分别为 0.766 / 0.688 / 0.734 秒；micrograd 为
5.968 秒（pytest 自报 4.18 秒）。这是复用已有环境的单次观测，不含准备、复制与
验收耗时，不能作为加速结论。两轮归档合计 **768,723 字节**，未下载模型/数据或安装包。
micrograd 全部 13 个原文件，包括媒体与 notebook，字节保持不变。
四份批注 README 均可在剥离 RigorPilot 插入后精确还原；相对链接仍处于保留的原目录中。

## 本地重复运行

```bash
python benchmarks/run_skill_acceptance.py --output tmp/skill-check
```

需要 Python 3.11+ 和 Git；默认三个用例仅使用标准库。
所选环境已有 PyTorch 和 pytest 时：

```bash
python benchmarks/run_skill_acceptance.py --output tmp/skill-check-with-micrograd --include-micrograd
```

目标环境不同时可加 `--python /path/to/python`；程序记录该解释器并放到子进程 PATH
首位。每次必须使用新输出目录。准入要求至少 1 GiB 空闲，用例间检查证据总量不超过
32 MiB；这不是文件系统硬配额或安全沙箱。

合成任务的期望指标与容差由操作者明确提供。正例单独记录了操作者执行
`prepare_data.py` 的步骤；缺数据用例故意不准备，因此都不证明自主环境搭建。
公开用例使用保留的、经过哈希校验的
[micrograd 固定提交](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c)，
没有重新联网拉取。复制安装目录不等于验证远程安装器或新客户端自动发现技能。

## 验收器出错也保留

[第一轮记录](../benchmark_outputs/skill_acceptance/attempt-1/REPORT.json)为 3/4：新脚本误用了
只接受成功任务的首次使用检查器，要求它接受故意不匹配的用例。技能当时已经正确报告
该失败；这轮报告与原始日志均原样保留。

第二轮增加独立的正负例精确验收；旧的成功检查器没有放宽，在负例的 `CHECK.json`
中仍拒绝通过。此时应查看 `ACCEPTANCE.json`，它要求失败原因与预设故障一致。
回归测试会拒绝篡改预测/MSE、伪造成功、缺失完成事件，以及把无关错误冒充缺资产。
日志与哈希依赖可信操作者，不能防御协同伪造。

归档日志保留当时的运行路径；复制后的快照用于浏览，不是可从旧路径恢复的活动任务。
公开目录不重复存放整个已安装技能；`START.json` 保留其逐文件哈希。
未收录凭据或完整宿主环境。Git 发布检查覆盖归档文件；对应提交的 CI 链接见上文。

## 可选：Codex 额度快照

```bash
python scripts/check_codex_quota.py
```

需要已登录的 Codex CLI；Windows 下使用 `--codex /path/to/native/codex.exe`，
不要传 `.cmd` 包装器。该工具通过官方
[app-server 的 account/rateLimits/read 接口](https://learn.chatgpt.com/docs/app-server)
查询，不发起模型轮次，只输出白名单中的用量窗口字段。
未返回的窗口保持未知。快照既不预留 token，也不能保证运行中的请求结束后仍高于 60%，
目前没有接入执行器自动停止机制。

本功能套件的**额外模型调用为 0**；宿主助手的用量不在此计量。
模型收益仍需要同条件 A/B、真实轨迹及独立任务评分，因此报告中保持 `model_effect: null`。
