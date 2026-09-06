# 离线 Harness 学习实验

这是一个**模拟模型决策、真实执行进程**的教学仓库，不是科研 benchmark，
也不证明某个模型具备自主诊断能力。它不联网、不调用 API、不下载依赖。
只需要 Python 3.10+ 和 Git；请在 RigorPilot 项目根目录运行：

```bash
python scripts/run_harness_lab.py --output repro_outputs/harness-lab
```

输出目录必须不存在；再次实验请换一个目录，已有文件不会被覆盖。
通常数秒完成，输出小于 1 MiB。运行器会复制本 README 和两个脚本到输出的
`repo/`，原始文件保持不变。这里是本地教学 fixture，不是公开科研仓库复现。

## 1. 先理解任务

目标是运行[评估脚本](evaluate.py)，检查准备文件中的数字能否得到预期结果。
预置模拟器会故意先评估，遇到缺失资产，再调用已审核的准备命令。
它的决策是写死的；失败、文件生成、进程退出码和恢复检查都是真实发生的。

## 2. 准备资产

```bash
python prepare.py
```

[准备脚本](prepare.py)只在当前工作目录创建一个很小的 `ready.json`。
不安装软件、不请求网络、不修改源码；已存在文件会导致失败，避免隐式覆盖。

## 3. 执行评估

```bash
python evaluate.py
```

没有 `ready.json` 时，程序以非零退出码报告 `missing asset: ready.json`。
准备完成后，它检查数据和结果，输出 `verified: sum=6`。
这只是确定性教学验收条件，不是模型精度或论文指标。

## 4. 按证据学习

一次运行会经历：读取 README → 记录计划 → 评估失败 → 准备资产 → 暂停 →
新 Python 进程恢复 → 再次评估 → 独立验证。

| 打开输出目录中的文件 | 观察什么 |
| --- | --- |
| `REPORT.json` | 明确区分模拟模型与真实进程，查看验收结果和体积 |
| `CHECKPOINT.json` | 暂停时已经完成的两次命令，不应在恢复时重复 |
| `repo/repro_outputs/trajectory.jsonl` | 公开决策理由、工具输入输出、暂停和恢复事件 |
| `repo/repro_outputs/_runtime/` | 三次真实命令各自的状态、stdout 和 stderr |
| `repo/repro_outputs/agent_state.json` | 最终计划、尝试历史和独立验收结果 |
| `repo/RIGORPILOT_README.md` | 原文逐块增量批注；原有相对文件链接仍可打开 |

先对照 `run_harness_lab.py` 的模拟器和真正的 `run_agent.py`，解释两者分别
负责什么。再检查“模型声称完成”和“验证器判定成功”为何不是同一件事。
最后在副本中改变预期输出，观察验证失败；不要把修改后的实验混入原证据。

## 5. 这个实验能证明什么

它检验本机的命令调度、失败记录、跨进程恢复、未重复执行、源码完整性和
README 批注链路。它不能证明真实模型推理、陌生仓库泛化、科研结果复现、
安全沙箱或者 harness 比无 skill 基线更好。真正的模型评估需要另行调用
可用的模型服务，并使用固定任务、统一预算和独立验收标准。
