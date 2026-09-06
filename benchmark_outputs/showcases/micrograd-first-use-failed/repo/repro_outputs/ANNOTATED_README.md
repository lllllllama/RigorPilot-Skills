<!-- rigorpilot:repro:begin kind="banner" section="__banner__" occurrence="1" status="partial" risk="none" -->

# 📄 README · RigorPilot 复现批注

🟡 `partial` · `evaluation` · `trusted` · [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)

章节覆盖：🟡 1 · 🔵 1 · ⚪ 6（共 8 节） · 复现得分 0.438

<sub>🟢 成功 · 🔵 未执行 · ⚪ 仅阅读 · 🟡 部分完成 / 资产缺失 · 🔴 阻塞 · 🟣 待决策 —— 原文未改动；相对媒体链接需要原 README 所在目录的上下文。</sub>

<sub>original_sha256: `d9d2ec92f63d8deae6260bd2a535a5e633566b73169ccde0a416a5b0cd3f4118` · round-trip: verified</sub>

---

<!-- rigorpilot:repro:end -->

# micrograd

![awww](puppy.jpg)

A tiny Autograd engine (with a bite! :)). Implements backpropagation (reverse-mode autodiff) over a dynamically built DAG and a small neural networks library on top of it with a PyTorch-like API. Both are tiny, with about 100 and 50 lines of code respectively. The DAG only operates over scalar values, so e.g. we chop up each neuron into all of its individual tiny adds and multiplies. However, this is enough to build up entire deep neural nets doing binary classification, as the demo notebook shows. Potentially useful for educational purposes.

<!-- rigorpilot:repro:begin kind="section" section="micrograd" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
### Installation

```bash
pip install micrograd
```

<!-- rigorpilot:repro:begin kind="section" section="Installation" occurrence="1" status="info" risk="low" -->

> [!NOTE]
> 🔵 **已纳入 setup 计划 · 未直接执行**
> `pip install micrograd`
> <sub>证据: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json) · tier: code-development</sub>

<!-- rigorpilot:repro:end -->
### Example usage

Below is a slightly contrived example showing a number of possible supported operations:

```python
from micrograd.engine import Value

a = Value(-4.0)
b = Value(2.0)
c = a + b
d = a * b + b**3
c += c + 1
c += 1 + c + (-a)
d += d * 2 + (b + a).relu()
d += 3 * d + (b - a).relu()
e = c - d
f = e**2
g = f / 2.0
g += 10.0 / f
print(f'{g.data:.4f}') # prints 24.7041, the outcome of this forward pass
g.backward()
print(f'{a.grad:.4f}') # prints 138.8338, i.e. the numerical value of dg/da
print(f'{b.grad:.4f}') # prints 645.5773, i.e. the numerical value of dg/db
```

<!-- rigorpilot:repro:begin kind="section" section="Example usage" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
### Training a neural net

The notebook `demo.ipynb` provides a full demo of training an 2-layer neural network (MLP) binary classifier. This is achieved by initializing a neural net from `micrograd.nn` module, implementing a simple svm "max-margin" binary classification loss and using SGD for optimization. As shown in the notebook, using a 2-layer neural net with two 16-node hidden layers we achieve the following decision boundary on the moon dataset:

![2d neuron](moon_mlp.png)

<!-- rigorpilot:repro:begin kind="section" section="Training a neural net" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
### Training a GPT

For a more advanced example, see [microgpt](https://gist.github.com/karpathy/8627fe009c40f57531cb18360106ce95), which trains and samples from a full GPT-2-like transformer in pure, dependency-free Python. It builds on a more efficient and better version of the autograd engine here (storing local gradients at forward time instead of per-op backward closures), and is the complete algorithm in a single file — everything else is just efficiency. See also the accompanying [explainer post](https://karpathy.github.io/2026/02/12/microgpt/) for a detailed walkthrough.

<!-- rigorpilot:repro:begin kind="section" section="Training a GPT" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
### Tracing / visualization

For added convenience, the notebook `trace_graph.ipynb` produces graphviz visualizations. E.g. this one below is of a simple 2D neuron, arrived at by calling `draw_dot` on the code below, and it shows both the data (left number in each node) and the gradient (right number in each node).

```python
from micrograd import nn
n = nn.Neuron(2)
x = [Value(1.0), Value(-2.0)]
y = n(x)
dot = draw_dot(y)
```

![2d neuron](gout.svg)

<!-- rigorpilot:repro:begin kind="section" section="Tracing / visualization" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
### Running tests

To run the unit tests you will have to install [PyTorch](https://pytorch.org/), which the tests use as a reference for verifying the correctness of the calculated gradients. Then simply:

```bash
python -m pytest
```

<!-- rigorpilot:repro:begin kind="section" section="Running tests" occurrence="1" status="partial" risk="medium" -->

> [!WARNING]
> 🟡 **部分完成（中风险）**
> 命令：`python -m pytest`
> 阻塞项：选定的文档命令以退出码 1 结束。
> 建议下一步：先准备环境与资源，再重试该文档命令。
> <sub>证据: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json) · tier: execution</sub>

<!-- rigorpilot:repro:end -->
### License

MIT
<!-- rigorpilot:repro:begin kind="section" section="License" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ 仅阅读</sub>

<!-- rigorpilot:repro:end -->
