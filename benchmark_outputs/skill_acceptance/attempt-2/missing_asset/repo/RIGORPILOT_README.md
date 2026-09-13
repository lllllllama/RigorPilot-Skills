<!-- rigorpilot:repro:begin kind="banner" section="__banner__" occurrence="1" status="partial" risk="none" -->

# 📄 README · RigorPilot 复现批注

🟡 `partial` · `evaluation` · `trusted` · [SUMMARY](../evidence/SUMMARY.md) · [COMMANDS](../evidence/COMMANDS.md) · [LOG](../evidence/LOG.md) · [status.json](../evidence/status.json)

章节覆盖：🟡 1 · 🔵 1 · ⚪ 2（共 4 节） · 复现得分 0.4

<sub>🟢 成功 · 🔵 未执行 · ⚪ 仅阅读 · 🟡 部分完成 / 资产缺失 · 🔴 阻塞 · 🟣 待决策 —— 原文未改动；相对媒体链接需要原 README 所在目录的上下文。</sub>

<sub>original_sha256: `b6a9322f0fc759985298508f3a91bfad2fd90386dbd818c5ca237ff559796eab` · round-trip: verified</sub>

---

<!-- rigorpilot:repro:end -->
# Frozen linear prediction check

This is a synthetic fault-injection task, not a public research repository or paper benchmark. Python standard library only; no network, downloads, training, or package installation.

<!-- rigorpilot:repro:begin kind="section" section="Frozen linear prediction check" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
## Data

The required CSV is initially absent. Its safe, local preparation is explicitly authorized:

```bash
python prepare_data.py
```

The protocol uses data/samples.csv with (x, y) values (0, 1), (1, 3), (2, 5).

<!-- rigorpilot:repro:begin kind="section" section="Data" occurrence="1" status="info" risk="low" -->

> [!NOTE]
> 🔵 **已识别命令 · 未执行（保守策略仅执行选定目标）**
> `python prepare_data.py`
> <sub>证据: [SUMMARY](../evidence/SUMMARY.md) · [COMMANDS](../evidence/COMMANDS.md) · [LOG](../evidence/LOG.md) · [status.json](../evidence/status.json) · tier: code-development</sub>

<!-- rigorpilot:repro:end -->
## Evaluation

```bash
python evaluate.py
```

The required result is MSE = 0.0 (absolute tolerance 1e-12). The fixed predictor uses config.json. The command writes results/metrics.json and results/predictions.json. Exit code 0 alone does not mean the metric matched.

<!-- rigorpilot:repro:begin kind="section" section="Evaluation" occurrence="1" status="partial" risk="medium" -->

> [!WARNING]
> 🟡 **部分完成（中风险）**
> 命令：`python evaluate.py`
> 阻塞项：选定的文档命令以退出码 1 结束。
> 错误摘录：`FileNotFoundError: [Errno 2] No such file or directory: 'D:\\test_projects\\ai-paper-reproduction-skill\\repro_outputs\\skill-acceptance-20260913-v2\\missing_asset\\repo\\data\\samples.csv'`
> 建议下一步：先准备环境与资源，再重试该文档命令。
> <sub>证据: [SUMMARY](../evidence/SUMMARY.md) · [COMMANDS](../evidence/COMMANDS.md) · [LOG](../evidence/LOG.md) · [status.json](../evidence/status.json) · tier: execution</sub>

<!-- rigorpilot:repro:end -->
## Integrity and reporting

Do not change README.md, Python sources, config.json, dataset values, the expected metric, or the evaluation protocol. Do not repair a failing model/configuration. If the observed MSE differs, report mismatched with the actual MSE; do not claim matched or hide the result.
<!-- rigorpilot:repro:begin kind="section" section="Integrity and reporting" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
