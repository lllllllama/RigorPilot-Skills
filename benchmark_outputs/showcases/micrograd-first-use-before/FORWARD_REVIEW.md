# 独立安装后试用记录

本次完成了 micrograd README `Running tests` 章节的最小本地验证：`python -m pytest` 收集 2 个测试，全部通过，pytest 报告 `2 passed in 2.29s`。这是两例标量前向值与梯度的 PyTorch 对照验证，不代表训练、论文结果或 README 全部内容均已复现。

## 入口与隔离范围

- 试用日期：2026-09-06。工作目录：`D:/test_projects/ai-paper-reproduction-skill/repro_outputs/public-first-use-20260906`。
- 任务明确给出 `.agents/skills/ai-research-reproduction/SKILL.md`，执行者直接读取它，并按其指向使用 `scripts/orchestrate_repro.py`。这是明确路径下的技能使用，不能据此声称新客户端自动发现或自动加载成功。
- 父任务说明：技能的 `npx` 安装与 `.venv` 均由父任务预置，非本代理自主完成；本代理没有执行或独立验证该安装过程。
- 读取了安装包内的操作原则、研究原则、实验原则、语言政策、输出规范、README 批注政策，以及目标仓库的 README、自动求导实现、测试和 `setup.py`。查看安装包内入口及命令解析相关行属于已安装运行时检查。
- 未读取产品开发源码、benchmarks、先前试用结果、记忆文件或 `BASELINE.json`。目标仓库路径虽然位于开发工作区的一个交付目录下，任务操作仅在上述工作目录内部进行。
- 复用任务预备的 `.venv`；未安装软件包、下载模型或数据、访问个人凭据、调用独立模型 API 或修改全局配置。
- 每次 shell 命令均设置 `PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`、`RIGORPILOT_LESSONS=0`；未读取或写入个人持久化经验。

## 目标选择依据

README 的 `Example usage` 是一个标量自动求导 Python 代码块；`Running tests` 明确给出 `python -m pytest`。入口的候选列表只提取到测试命令和安装命令，没有把 Python 示例块变成可执行候选。阅读测试文件确认两个测试均只用固定标量和 CPU Tensor，其中 `test_more_ops` 覆盖 README 示例的表达式，并以 PyTorch 的双精度结果检查前向值与两项梯度，容差为 `1e-6`。

现有环境能够找到 `pytest` 与 `torch`，完整测试集仅有两个测试，因而接受入口选择的 `evaluation` 目标。它是本次最小可信的文档化 shell 任务。没有修改原始科学代码，也没有另写替代测试。README Python 示例没有作为独立程序执行。

## 实际命令

以下命令在 PowerShell 7 `C:/Users/17745/AppData/Local/Programs/PowerShell/7/pwsh.exe` 中、上述工作目录下执行。列出与入口发现、环境核实、计划、执行及交付校验直接相关的完整命令；普通文件阅读未被伪装为运行证据。

入口读取与帮助：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; Get-Content -LiteralPath '.agents/skills/ai-research-reproduction/SKILL.md' -Raw
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; Get-Content -LiteralPath 'repo/README.md' -Raw
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; Get-Content -LiteralPath 'repo/micrograd/engine.py','repo/test/test_engine.py','repo/setup.py' -Raw
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; & '.venv/Scripts/python.exe' '.agents/skills/ai-research-reproduction/scripts/orchestrate_repro.py' --help
```

只读环境核实：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; & '.venv/Scripts/python.exe' -c 'import sys, importlib.util, json; print(json.dumps({"python": sys.version, "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix, "pytest_available": importlib.util.find_spec("pytest") is not None, "torch_available": importlib.util.find_spec("torch") is not None}, ensure_ascii=False, indent=2))'
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; & '.venv/Scripts/python.exe' -c 'import importlib.metadata, json; print(json.dumps({name: importlib.metadata.version(name) for name in ("pytest", "torch")}, indent=2))'
```

先运行计划阶段，没有 `--run-selected`：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; & '.venv/Scripts/python.exe' '.agents/skills/ai-research-reproduction/scripts/orchestrate_repro.py' --repo './repo' --output-dir './repro_outputs' --user-language zh-CN --timeout 45 --no-gpu-monitor
```

正式执行及源目录批注副本：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; $env:PATH=(Join-Path (Get-Location) '.venv/Scripts') + [IO.Path]::PathSeparator + $env:PATH; $env:PYTEST_ADDOPTS='-p no:cacheprovider'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:CUDA_VISIBLE_DEVICES=''; & '.venv/Scripts/python.exe' '.agents/skills/ai-research-reproduction/scripts/orchestrate_repro.py' --repo './repo' --output-dir './repro_outputs' --source-adjacent-readme --user-language zh-CN --timeout 45 --no-gpu-monitor --run-selected
```

运行时 `spec.json` 记录了实际子进程参数，工作目录为 `WORK/repo`：

```text
D:\test_projects\ai-paper-reproduction-skill\repro_outputs\public-first-use-20260906\.venv\Scripts\python.EXE -m pytest
```

两份 README 的还原校验：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; & '.venv/Scripts/python.exe' '.agents/skills/ai-research-reproduction/scripts/annotate_readme.py' check --input './repo/RIGORPILOT_README.md' --against './repo/README.md'
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; & '.venv/Scripts/python.exe' '.agents/skills/ai-research-reproduction/scripts/annotate_readme.py' check --input './repro_outputs/ANNOTATED_README.md' --against './repo/README.md'
```

执行前与执行后的源文件检查：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; git -C './repo' status --short --untracked-files=all; git -C './repo' rev-parse HEAD; git -C './repo' ls-files
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:RIGORPILOT_LESSONS='0'; git -C './repo' diff --exit-code HEAD --; git -C './repo' status --short --untracked-files=all; Get-FileHash -LiteralPath 'repo/README.md' -Algorithm SHA256
```

另检查了标准证据文件、交付收据、三项 README 本地媒体文件均存在；`git status --short --untracked-files=all --ignored` 只列出新增的 `RIGORPILOT_README.md`，没有 pytest 缓存或字节码产物。

## 结果与证据

| 项目 | 实际结果 |
|---|---|
| 目标提交 | `7bc720e951fe422b8f8814aa5aa1b64121d26b4c` |
| 解释器 | Python `3.12.7`，`.venv/Scripts/python.exe`；base prefix 为 `D:/Anaconda3` |
| 已有依赖 | pytest `7.4.4`；torch 包元数据 `2.12.1+cu126` |
| 运行结果 | `2 passed in 2.29s`；return code `0` |
| 运行时 | `20260906T084802Z-decf5099`；状态 `success`；技能记录 duration `3.437s` |
| 限时 | 45 秒；未超时、未取消；外层正式命令约 5.17 秒 |
| 运行日志 | stdout 完整、未截断；stderr 0 字符 |
| 模型适配器 | `unconfigured`、`model=unspecified`，没有独立模型 API 调用 |
| 结果匹配字段 | `result_match.status=not_evaluated`；没有向入口提供期望指标 |
| 原文件 | 执行前 Git 工作树干净；执行后 13 个原始跟踪文件无 diff，只有新增批注副本 |
| README 校验 | 两份批注均通过 round trip，各含 9 个标记块（横幅 1 个、章节 8 个） |

时间口径：`2.29s` 是 pytest 自身输出的测试会话耗时；`3.437s` 是技能 `duration_seconds` 记录的运行任务耗时，包含运行时管理边界，二者不是同一个计时器。约 `5.17s` 是工具所见的外层 orchestration 命令墙钟时间，另含扫描、计划与报告写入等开销。均为这次运行的观测值，不是性能基准。

原 README 及两份批注剥离后的 SHA-256 均为：

```text
d9d2ec92f63d8deae6260bd2a535a5e633566b73169ccde0a416a5b0cd3f4118
```

主要交付与原始运行证据：

- [源目录批注副本](repo/RIGORPILOT_README.md)
- [标准摘要](repro_outputs/SUMMARY.md)、[机器状态](repro_outputs/status.json)、[标准批注副本](repro_outputs/ANNOTATED_README.md)
- [运行参数](repro_outputs/_runtime/20260906T084802Z-decf5099/spec.json)、[终态](repro_outputs/_runtime/20260906T084802Z-decf5099/state.json)、[事件流](repro_outputs/_runtime/20260906T084802Z-decf5099/events.jsonl)
- [完整 stdout](repro_outputs/_runtime/20260906T084802Z-decf5099/stdout.log)、[完整 stderr](repro_outputs/_runtime/20260906T084802Z-decf5099/stderr.log)
- [README 交付收据](repro_outputs/readme_delivery.json)

## 问题与干预

没有运行失败、重试、人工修补或等待用户批准。初始“未执行”状态来自有意调用计划阶段，随后才执行一次正式目标。

执行者做了以下环境适配：临时把已有 `.venv/Scripts` 放到 PATH 前端，确保子命令解析到目标解释器；临时关闭 pytest 缓存和第三方插件自动加载；设置空的 `CUDA_VISIBLE_DEVICES` 并关闭 GPU 遥测。测试科学代码未变，影响限于进程环境和 pytest 外围行为。这些额外环境变量没有被生成的 `COMMANDS.md` 或运行时 `spec.json` 自动收录，因而在本文件保留完整命令。

首次使用时观察到的报告问题（保留原始生成物，不在试用中修复产品）：

1. 自动 `COMMANDS.md` 的 Setup 部分列出创建 venv、激活和 `python -m pip install -e .`，但本次均未执行。后者标记为 `documented`，实际 README 命令是 `pip install micrograd`，来源标注不够准确。不能把这份命令计划当成已执行的安装日志。
2. bootstrap 自动写入 `WORK/artifacts/assets/asset_manifest.json`，位于指定主证据目录外；它把 datasets、data、checkpoints、weights、cache、.cache 六类通用资源标为 `missing`。所选两个标量测试不需要这些资源，所以这不是真实运行阻塞。
3. 自动报告显示 `protocol_deviations=[]` 和 `Comparability status: preserved`，未收录本次预先提供的宿主依赖及 pytest 环境适配。可确认相同源码的两个测试通过；不能据此确认全新环境安装、训练或论文级比较条件。
4. 入口把纯 Python 示例留为“仅阅读”，并只执行了 8 个 README 章节中的 1 个。横幅中的 `复现得分 0.812` 是工具内部汇总值，不应解释成模型质量、精确复现率或整个项目的完成比例。
5. 生成报告使用中英文混合标题和文字；关键结果和批注主体为中文，可读，但尚非全中文交付。

## 边界

这次验证证明明确指定路径的已安装技能能够读取目标 README、调用随包运行时、选择并执行一个小型文档命令、保存实际进程日志，并在保留原始 README 全部字节和本地媒体上下文的前提下交付批注副本。

本次未验证新客户端自动加载、独立冷安装、其他宿主或系统、依赖版本矩阵、神经网络训练、GPT 外部例子、图形渲染、论文指标或完整项目复现。没有创建原始模型调用轨迹、推理过程、token 数、模型费用或模型性能计量。运行时资源记录仅有其声明的 root process 范围，未把它换算成整棵进程树、GPU 或模型成本。
