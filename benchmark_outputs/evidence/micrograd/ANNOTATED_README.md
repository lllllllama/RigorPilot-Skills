<!-- rigorpilot:repro:begin kind="banner" section="__banner__" occurrence="1" status="success" risk="none" -->

# 📄 README · RigorPilot annotations

🟢 `success` · `evaluation` · `trusted` · [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)

Section coverage: 🟢 1 · 🔵 1 · ⚪ 6 (8 sections) · score 0.812

<sub>🟢 success · 🔵 not executed · ⚪ read only · 🟡 partial / assets missing · 🔴 blocked · 🟣 decision needed — original content unchanged; its relative links resolve against the repo root.</sub>

<sub>original_sha256: `e89ba299fe3c5ec40febf03d9a0f7522e341a1ab9226ffee5e453272afdfaaf5` · round-trip: verified</sub>

---

<!-- rigorpilot:repro:end -->

# micrograd

![awww](puppy.jpg)

A tiny Autograd engine (with a bite! :)). Implements backpropagation (reverse-mode autodiff) over a dynamically built DAG and a small neural networks library on top of it with a PyTorch-like API. Both are tiny, with about 100 and 50 lines of code respectively. The DAG only operates over scalar values, so e.g. we chop up each neuron into all of its individual tiny adds and multiplies. However, this is enough to build up entire deep neural nets doing binary classification, as the demo notebook shows. Potentially useful for educational purposes.

<!-- rigorpilot:repro:begin kind="section" section="micrograd" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ Read only</sub>

<!-- rigorpilot:repro:end -->
### Installation

```bash
pip install micrograd
```

<!-- rigorpilot:repro:begin kind="section" section="Installation" occurrence="1" status="info" risk="low" -->

> [!NOTE]
> 🔵 **Folded into the setup plan · not executed directly**
> `pip install micrograd`
> <sub>Evidence: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json) · tier: code-development</sub>

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

<sub>⚪ Read only</sub>

<!-- rigorpilot:repro:end -->
### Training a neural net

The notebook `demo.ipynb` provides a full demo of training an 2-layer neural network (MLP) binary classifier. This is achieved by initializing a neural net from `micrograd.nn` module, implementing a simple svm "max-margin" binary classification loss and using SGD for optimization. As shown in the notebook, using a 2-layer neural net with two 16-node hidden layers we achieve the following decision boundary on the moon dataset:

![2d neuron](moon_mlp.png)

<!-- rigorpilot:repro:begin kind="section" section="Training a neural net" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ Read only</sub>

<!-- rigorpilot:repro:end -->
### Training a GPT

For a more advanced example, see [microgpt](https://gist.github.com/karpathy/8627fe009c40f57531cb18360106ce95), which trains and samples from a full GPT-2-like transformer in pure, dependency-free Python. It builds on a more efficient and better version of the autograd engine here (storing local gradients at forward time instead of per-op backward closures), and is the complete algorithm in a single file — everything else is just efficiency. See also the accompanying [explainer post](https://karpathy.github.io/2026/02/12/microgpt/) for a detailed walkthrough.

<!-- rigorpilot:repro:begin kind="section" section="Training a GPT" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ Read only</sub>

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

<sub>⚪ Read only</sub>

<!-- rigorpilot:repro:end -->
### Running tests

To run the unit tests you will have to install [PyTorch](https://pytorch.org/), which the tests use as a reference for verifying the correctness of the calculated gradients. Then simply:

```bash
python -m pytest
```

<!-- rigorpilot:repro:begin kind="section" section="Running tests" occurrence="1" status="success" risk="low" -->

> [!TIP]
> 🟢 **Executed successfully（low risk）**
> Command: `python -m pytest`
> Result comparison: not evaluated because no explicit expected metrics were supplied.
> <sub>Evidence: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json) · tier: execution</sub>

<!-- rigorpilot:repro:end -->
### License

MIT
<!-- rigorpilot:repro:begin kind="section" section="License" occurrence="1" status="readonly" risk="none" -->

<sub>⚪ Read only</sub>

<!-- rigorpilot:repro:end -->
