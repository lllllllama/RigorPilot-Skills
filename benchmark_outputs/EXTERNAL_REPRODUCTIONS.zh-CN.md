# RigorPilot 外部复现实例

四个固定版本的公开仓库，共用同一套证据协议。每个用例都记录从 README
选出的命令、实际执行边界、源码完整性和完整 RigorPilot 输出包。可直接跳转：

[micrograd](#micrograd) · [minGPT](#mingpt) · [PyTorch MNIST](#pytorch-mnist) · [nanoGPT Shakespeare](#nanogpt-shakespeare)

**测试套件快照：** 4/4 项协议检查通过，总用时 251.0 秒，0 次 API 调用；
所有临时工作区均已删除，tracked 展示仓库已保留。协议通过表示 Harness
按约定工作；有界启动不能被表述为训练收敛。

<a id="micrograd"></a>

## micrograd — 正确性验证

[![micrograd 复现预览](../assets/showcase/external-micrograd.png)](showcases/micrograd/repo/RIGORPILOT_README.md)

- 源码：[karpathy/micrograd @ `7bc720e`](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c)
- 选定命令：`python -m pytest`
- 实际结果：**执行成功**，2 项测试在 7.62 秒内通过
- README 完整性：8 个标题对应 8 条批注；原始与剥离后 SHA-256 完全相同
- 运行框架验证：命令选择、直接执行、证据完整性、源码完整性和清理均通过

[查看保留原仓库文件的 RigorPilot README](showcases/micrograd/repo/RIGORPILOT_README.md) ·
[摘要](evidence/micrograd/SUMMARY.md) ·
[命令](evidence/micrograd/COMMANDS.md) ·
[日志](evidence/micrograd/LOG.md) ·
[机器可读状态](evidence/micrograd/status.json)

<a id="mingpt"></a>

## minGPT — 目标选择与风险边界

[![minGPT 复现预览](../assets/showcase/external-mingpt.png)](showcases/mingpt/repo/RIGORPILOT_README.md)

- 源码：[karpathy/minGPT @ `37baab7`](https://github.com/karpathy/minGPT/tree/37baab71b9abea1b76ab957409a1cc2fbfba8a26)
- 选定命令：`python -m unittest discover tests`
- 实际结果：**按设计未执行**，没有隐式下载 GPT-2，也没有启动训练
- README 完整性：11 个标题对应 11 条批注；SHA-256 往返完全一致
- 运行框架验证：目标选择、风险边界、证据完整性、源码完整性和清理均通过

[查看保留原仓库文件的 RigorPilot README](showcases/mingpt/repo/RIGORPILOT_README.md) ·
[摘要](evidence/mingpt/SUMMARY.md) ·
[命令](evidence/mingpt/COMMANDS.md) ·
[日志](evidence/mingpt/LOG.md) ·
[机器可读状态](evidence/mingpt/status.json)

<a id="pytorch-mnist"></a>

## PyTorch MNIST — 数据与评测验证

[![PyTorch MNIST 复现预览](../assets/showcase/external-pytorch-mnist.png)](showcases/pytorch-mnist/repo/mnist/RIGORPILOT_README.md)

- 源码：[pytorch/examples MNIST @ `acc295d`](https://github.com/pytorch/examples/tree/acc295dc7b90714f1bf47f06004fc19a7fe235c4/mnist)
- 选定命令：`python main.py`
- 实际结果：**有界部分运行**，`loss=0.038893`
- README 完整性：1 个标题对应 1 条批注；SHA-256 往返完全一致
- 运行框架验证：指标捕获、超时边界、证据完整性、源码完整性和清理均通过

[查看保留原仓库文件的 RigorPilot README](showcases/pytorch-mnist/repo/mnist/RIGORPILOT_README.md) ·
[摘要](evidence/pytorch-mnist/SUMMARY.md) ·
[命令](evidence/pytorch-mnist/COMMANDS.md) ·
[日志](evidence/pytorch-mnist/LOG.md) ·
[机器可读状态](evidence/pytorch-mnist/status.json)

<a id="nanogpt-shakespeare"></a>

## nanoGPT Shakespeare — 有界训练验证

[![nanoGPT Shakespeare 复现预览](../assets/showcase/external-nanogpt.png)](showcases/nanogpt-shakespeare/repo/RIGORPILOT_README.md)

- 源码：[karpathy/nanoGPT @ `3adf61e`](https://github.com/karpathy/nanoGPT/tree/3adf61e154c3fe3fca428ad6bc3818b27a3b8291)
- 选定目标：README 记录的 Shakespeare 字符模型 CPU 训练
- 实际结果：**有界部分运行**，`train_loss=4.1676`、`val_loss=4.1649`
- README 完整性：11 个标题对应 11 条批注；SHA-256 往返完全一致
- 运行框架验证：长进程控制、指标捕获、证据完整性、源码完整性和清理均通过

[查看保留原仓库文件的 RigorPilot README](showcases/nanogpt-shakespeare/repo/RIGORPILOT_README.md) ·
[摘要](evidence/nanogpt-shakespeare/SUMMARY.md) ·
[命令](evidence/nanogpt-shakespeare/COMMANDS.md) ·
[日志](evidence/nanogpt-shakespeare/LOG.md) ·
[机器可读状态](evidence/nanogpt-shakespeare/status.json)

---

[测试套件结果](external_suite_latest.json) ·
[用例定义](../benchmarks/external_cases.json) ·
[方法与限制](../benchmarks/README.md)
