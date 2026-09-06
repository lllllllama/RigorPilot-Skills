# 安装后首次使用：micrograd

[English](FIRST_USE_ACCEPTANCE.md) · [工程计划](ENGINEERING_ROADMAP.zh-CN.md) · [首页](../README.zh-CN.md)

2026-09-06：独立代理使用安装后的技能，从原始 README 选择并执行 `python -m pytest`，
两项测试通过。修正报告误导后，在新目录复测通过，另用独立 pytest 进程核验通过。
这是小型自动求导测试的执行验收，不是论文指标复现、模型增益或客户端自动加载证明。

## 直接看真实结果

| 尝试 | 实际结果 | 完整证据 |
|---|---|---|
| 修改前：独立代理使用已安装技能 | 2 项测试通过；pytest 2.29 s，运行时 3.437 s | [批注 README](../benchmark_outputs/showcases/micrograd-first-use-before/repo/RIGORPILOT_README.md) · [独立试用记录](../benchmark_outputs/showcases/micrograd-first-use-before/FORWARD_REVIEW.md) · [验收](../benchmark_outputs/showcases/micrograd-first-use-before/CHECK.json) |
| 修改后：父任务第一次回放 | 未设置虚拟环境 PATH，子进程找不到 pytest；正确记录 `partial` / `failed` | [失败状态](../benchmark_outputs/showcases/micrograd-first-use-failed/repo/repro_outputs/status.json) · [原始错误](../benchmark_outputs/showcases/micrograd-first-use-failed/repo/repro_outputs/_runtime/20260906T085408Z-0e53ec0f/stderr.log) · [未通过的验收](../benchmark_outputs/showcases/micrograd-first-use-failed/CHECK.json) |
| 修改后：按原代理的环境设置重新回放 | 2 项测试通过；pytest 1.83 s，运行时 2.640 s | [批注 README](../benchmark_outputs/showcases/micrograd-first-use-after/repo/RIGORPILOT_README.md) · [实际命令报告](../benchmark_outputs/showcases/micrograd-first-use-after/repo/repro_outputs/COMMANDS.md) · [验收](../benchmark_outputs/showcases/micrograd-first-use-after/CHECK.json) |
| 独立核验原仓库行为 | 原始两个测试再次通过，未修改测试或科学代码 | [JUnit](../benchmark_outputs/showcases/micrograd-first-use-after/independent/pytest.xml) · [核验记录](../benchmark_outputs/showcases/micrograd-first-use-after/independent/RESULT.json) |

三个仓库副本均保留全部 13 个原文件，包括图片、SVG 和 notebook；原文件 SHA-256
与运行前一致。两个成功尝试的两份批注分别含 8 条正确就地插入，每份 12 个插入链接
可在对应原始工作目录解析。公开副本只调整插入块的证据链接，原 README 不变。
上述耗时来自单次记录，不能据此声称加速；回放配置错误不归因于模型。

## 实际修正

- 环境命令标注为未执行建议；常见资产目录不存在，不再生成“运行前必须准备”的指令。
- 普通环境发现缺口放进 `setup_advisories`，不自动要求人工决策；真实缺依赖/资产仍有失败证据。
- `command_reporting` 独立记录实际运行状态；命令正常结束但显式指标缺失或超差时，
  整体状态为 `partial`，保留进程成功事实，并明确提示验收未通过。
- 新增独立的字节扫描与日志一致性验收器，区分任务日志条件与 README 展示质量。
  工程 fixture 覆盖错指标、缺指标、缺依赖、缺资产等负例，不冒充外部科研任务。

## 安装、环境与成本边界

- 上游固定为 [micrograd 的 7bc720e 提交](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c)。每次使用新目录拉取，无源码补丁。
- 实际执行 `npx skills@1.5.23 add <本地技能快照> --skill ai-research-reproduction --agent codex --copy --yes`。
  首轮快照来自产品提交 `caa9ac6`；修复后使用工作树快照，逐文件身份见各次 `BASELINE.json`。
  这不是从远程项目发布版安装的测试。安装进程启用 TLS 校验并关闭遥测。
- Node 22.17.0 低于安装器声明的 22.20.0 要求；虽安装成功，不能宣称该版本受支持。
  [原始安装日志](../benchmark_outputs/showcases/micrograd-first-use-before/SETUP.json) 保留警告。
- Python 3.12.7，新建虚拟环境复用宿主 PyTorch 2.12.1+cu126 和 pytest 7.4.4；测试使用 CPU。
  未下载模型/数据或重装大型依赖，不是冷启动依赖安装。子进程根据 PATH 选择解释器，
  仅用虚拟环境 Python 启动编排器不等于已激活该环境。
- 父任务预置安装和环境；独立代理自行阅读、选择和执行，未获预先指定的测试命令。
  任务明确提供技能路径，没有验证新客户端自然语言自动加载，也没有完整 provider 轨迹。
- 三次公开快照合计约 0.6 MiB，含失败记录；本地工作目录合计约 22.3 MiB，含安装缓存。
  无额外独立模型 API 调用；宿主代理的 token/费用未计量，不能记为零或推算订阅余额。
- 原始日志保留当时的绝对路径；浏览请使用本页链接。移动后的快照不是可直接恢复的活动任务，
  不应复用其中旧的所有权凭据。公开回放记录省略了无关的完整宿主 PATH，原记录留在本地。

## 可重复检查与下一步

本地 `python scripts/run_all_tests.py`：63/63 个脚本通过，108.9 s；包括新增报告与验收器回归。
从 Git 提交核查已公开的原文、媒体和插入链接：

```bash
python scripts/check_publication.py
```

新实验可复用 [首次使用验收器](../benchmarks/README.md#installed-skill-first-use-check)。它不执行
目标仓库，不认证基线来源，不验证外部媒体服务、浏览器渲染、科学指标或抗协同伪造。

下一阶段的[三任务评测准备](PAIRED_PILOT.zh-CN.md)已交付：输入已冻结，评分器已真实校准，
六个模型试验仍未运行。
全新客户端加载、成功的独立模型执行器调用和模型能力对照仍待单独确认预算后验收。
