# 小型对照评测：先准备，再测量

[English](PAIRED_PILOT.md) · [工程计划](ENGINEERING_ROADMAP.zh-CN.md) · [评测入口](../benchmarks/README.md)

本工具冻结 **3 个任务 × 2 种条件**，并实际执行本地命令，校准独立验收器。
6 个真实模型试验仍为 `not_run`。离线校准不是 A/B 结果、未知任务成功率，
也不能证明 skill 提高了模型能力。

## 本地运行

在项目根目录执行。要校准全部三个任务，请预先选择**已经具备 `torch` 和
`pytest` 的 Python**。工具不会下载或安装依赖、模型、数据或仓库；两个故障注入
任务只使用 Python 标准库。

```bash
python benchmarks/paired_eval.py prepare --output repro_outputs/paired-pilot --python python
python benchmarks/paired_eval.py preflight --campaign repro_outputs/paired-pilot
python benchmarks/paired_eval.py calibrate --campaign repro_outputs/paired-pilot
python benchmarks/paired_eval.py summarize --campaign repro_outputs/paired-pilot
```

- `prepare` 要求输出目录尚不存在，不覆盖旧证据。`--python` 指定实际任务使用的
  解释器，不只是启动命令行工具的解释器。例如 Windows 可替换为
  `"D:/envs/research/Scripts/python.exe"`，Linux/macOS 可替换为
  `"/path/to/env/bin/python"`。
- 未提供模型和预算配置时，`preflight` **预期退出码为 1**。分别查看
  `input_ready` 和 `configuration_ready`；这不妨碍离线校准。缺少 `torch` 或
  `pytest` 会明确报告，不会自动安装。检测到包版本不等于验证了导入和实际运行。
- `calibrate` 在另建的新仓库中执行经过审定的命令，用明确标注的脚本化结论校准
  验收器。全部请求项通过时退出码为 **0**，至少一项未通过时为 **1**。若只跑标准库
  任务，可追加 `--tasks missing_asset wrong_metric`。
- `summarize` 输出 JSON：真实模型试验仍未运行，完成率、对照增益、token、费用和
  预算合规性均保持未知（`null`）。

以上命令均为 **0 次模型 API 调用**。开发或审查这些代码的宿主代理仍可能消耗
token；这里不测量其订阅用量。磁盘检查采用单个评测目录 32 MiB 的体积阈值，
并要求至少 1 GiB 可用空间；这些是检查门槛，不是持续生效的文件系统配额。

## 任务与独立验收

| 任务 | 来源与操作 | 业务验收标准 |
|---|---|---|
| `micrograd` | 真实公开仓库，固定到 [`7bc720e`](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c)；从保留的本地快照逐哈希复制 13 个原始文件 | 实际执行并通过上游两个梯度测试；核对命令、工作目录、退出码及 JUnit 中的两个具体测试，不依赖 `2 passed` 字符串 |
| `missing_asset` | 明确的故障注入：初始缺少 CSV；执行已授权的本地 `prepare_data.py`，再运行 `evaluate.py` | 保持原代码和协议不变，核对数据/配置身份，独立重算预测和 MSE，并准确报告 `matched`、MSE 0 |
| `wrong_metric` | 明确的故障注入：固定配置使 MSE 为 1，但 `evaluate.py` 正常退出；禁止修补代码或配置 | 产物有效但结果不达标；准确报告 `mismatched`、MSE 1，不误报成功，也不无故阻塞 |

micrograd 仅在原 pytest 命令中增加 `--junitxml <attempt>/pytest.xml`，不修改
两个上游测试。原始 README、图片、notebook 和代码均保留。这是梯度测试验收，
不是论文指标复现。单元测试中的模拟 JUnit 只证明解析器行为，不冒充 micrograd
实际执行证据。

两组都使用相同的中性 `claim.json` 结论格式：

```json
{
  "outcome": "mismatched",
  "observed_metrics": {"mse": 1.0},
  "reason": "评估已完成，但实际 MSE 与要求的 0.0 不一致。"
}
```

`outcome` 只允许 `matched`、`mismatched` 或 `blocked`。micrograd 的
`observed_metrics` 使用 `{}`；线性预测任务须填写实际数值 `mse`。缺少结论不能
算正确处理。验收器分别检查 `source_integrity`、`execution_verified`、
`artifact_valid`、`result_matched`、`correct_handling`、`false_success` 和
`incorrect_blocking`，**不要求 skill 专属报告、彩色 README 或特定写作风格**。
执行记录必须来自操作者控制的采集器，不能用模型自己撰写的说明替代。

## A/B 将比较什么

A 接收共同任务说明和仓库；B 额外接收复制的 `ai-research-reproduction` 技能
快照，**包含其随包脚本**。因此这是技能包的端到端比较，不是只改变提示词的因果
消融，也不是安装服务或全新客户端自动发现技能的测试。预审命令集不证明不受限的
自主目标发现能力。

任务、提示词、原文件身份、技能快照和环境身份随冻结协议记录在 `control/`；
`workspaces/` 保留六个尚未执行的试验目录；独立校准的命令日志、脚本化结论、
验收结果和报告位于 `calibration/`。冻结实现或输入变化后须建立新评测目录。
所有尝试都应保留，包括失败和未完成校准，不能只公开成功记录。

这些任务属于**开发集，不是保留测试集**。哈希校验依赖操作者控制的记录，不能
防止协同伪造。新目录与提示词约束不等于操作系统隔离，也不能防止既有客户端的
全局技能、历史上下文或其他试验文件污染未来的对照结果。

## 模型与预算配置不等于执行授权

可选 JSON 配置严格接受以下六个字段。占位符和数值仅演示格式，**不是推荐的
消费或额度分配**，不证明模型可用，也不会启动模型调用：

```json
{
  "provider": "YOUR_PROVIDER",
  "model": "YOUR_MODEL_ID",
  "revision": "YOUR_PINNED_REVISION",
  "max_total_tokens": 6000,
  "max_tokens_per_trial": 1000,
  "max_seconds_per_trial": 60
}
```

```bash
python benchmarks/paired_eval.py preflight --campaign repro_outputs/paired-pilot --configuration pilot-config.json
```

限制值须为正整数；总 token 须能为六个试验预留相同的单次上限。不要在配置中
填写密钥。即使预检退出码为 0，`live_execution_ready` 仍为 `false`，
`budget_enforcement` 仍为 `not_enforced`：本工具目前**没有通用真实模型执行后端，
也没有强制模型预算控制**。它无法读取订阅余额，不能按订阅剩余百分比自动停止。

## 证据与下一道验收

查看[公开校准证据](../benchmark_outputs/paired_pilot_calibration/REPORT.json)，
以其中逐任务结果和范围说明为准；不要把校准通过数解释为模型成功数。

2026-09-06 实测：复用 Python 3.12.7、PyTorch 2.12.1+cu126 和 pytest 7.4.4，
在 CPU 上运行，未做冷安装。三个**评分器校准**均通过。

| 实际执行 | 独立判定 | 原始证据 |
|---|---|---|
| micrograd：两项测试通过，pytest 1.83 s | 原文件不变，JUnit 中两个原始测试均通过 | [原 README](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/micrograd/repo/README.md) · [日志](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/micrograd/steps/gradient-tests/stdout.log) · [JUnit](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/micrograd/pytest.xml) |
| 缺资产：本地准备后 MSE 为 0 | 执行、产物和指标验收通过 | [任务 README](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/missing_asset/repo/README.md) · [指标](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/missing_asset/repo/results/metrics.json) |
| 错指标：退出码为 0，MSE 为 1 | 产物有效但指标不达标；脚本化“不匹配”结论被正确接受 | [任务 README](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/wrong_metric/repo/README.md) · [执行记录](../benchmark_outputs/paired_pilot_calibration/calibration/calibration-835721b0e817/wrong_metric/steps/evaluate/receipt.json) |

[汇总](../benchmark_outputs/paired_pilot_calibration/SUMMARY.json) 保留六个 `not_run`
模型试验，用量与费用仍为未知。公开快照约 220 KiB，包含 micrograd 原始媒体、
真实日志及冻结的评测器源码。原执行记录中的历史绝对路径不改；精简副本没有包含
未使用的六个模型工作目录，不可直接恢复为活动试验。重复实验请按上方命令新建
目录。`python scripts/check_publication.py` 会从 Git 中检查这些公开文件的字节。

真实 A/B 前，先接入隔离的客户端或执行器，固定模型版本与工具权限，并实现
可计量的 token/时间硬限制；用量不可获取时应安全停止。随后按
**一次限额试跑 → 六个对照试验 → 重复有价值的对照**推进，保留失败、人工介入、
完整轨迹、用量和未知值。另设保留测试集后，再讨论一般化能力。
当前校准工具没有提供这些真实模型试验结果。

现已提供[中立控制器基础](CONTROLLED_TRIALS.zh-CN.md)进行离线验收。它只开放
技能文本，不执行随包脚本；真实使用前需另行冻结受限工具对照协议，不会执行或
改写本评测的六个模型试验。
