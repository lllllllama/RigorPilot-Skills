<!-- RigorPilot annotated README: original content preserved verbatim; annotations added below each section. -->

# 📄 README · RigorPilot 复现批注

🟢 `success` · `evaluation` · `trusted` · [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)

<sub>🟢 成功 · 🔵 未执行 · ⚪ 仅阅读 · 🟡 部分完成 · 🔴 阻塞 · 🟣 待决策 —— 原文未改动，原文相对链接以仓库根目录为基准。</sub>

---

# MiniSeg: Simple and Efficient Semantic Segmentation

[![arXiv](https://img.shields.io/badge/arXiv-2606.01234-b31b1b.svg)](https://arxiv.org/abs/2606.01234)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.3-ee4c2c.svg)](https://pytorch.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Official PyTorch implementation of **MiniSeg**, a lightweight encoder-decoder
that reaches strong ADE20K accuracy with a fraction of the usual compute.

<div align="center">
  <img src="assets/arch.png" width="640" alt="MiniSeg architecture"/>
</div>

<sub>⚪ 仅阅读</sub>

## News

- **[2026-06-12]** MiniSeg-B0 / B1 checkpoints and training logs released.
- **[2026-05-30]** MiniSeg is accepted to NeurIPS 2026.

<sub>⚪ 仅阅读</sub>

## Model Zoo

| Model | Dataset | mIoU (SS) | #Params | FLOPs | Checkpoint |
|---|---|---|---|---|---|
| MiniSeg-B0 | ADE20K | 41.2 | 3.8M | 8.4G | [miniseg_b0.pth](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b0.pth) |
| MiniSeg-B1 | ADE20K | 44.7 | 13.1M | 15.9G | [miniseg_b1.pth](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b1.pth) |

<sub>⚪ 仅阅读</sub>

## Installation

```bash
conda create -n miniseg python=3.10 -y
conda activate miniseg
pip install -r requirements.txt
```

> [!NOTE]
> 🔵 **已纳入 setup 计划** · 3 条命令，未直接执行

## Data Preparation

Download ADE20K from the [official site](http://sceneparsing.csail.mit.edu/) and
link it under `data/`:

```bash
python tools/prepare_ade20k.py --root data/ade20k
```

> [!NOTE]
> 🔵 **已纳入 setup 计划** · 1 条命令，未直接执行

## Evaluation

Evaluate MiniSeg-B0 on the ADE20K validation split (single-scale):

```bash
python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth
```

> [!TIP]
> 🟢 **执行成功** · `python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth` · `mIoU=41.18` · `aAcc=79.85`

## Training

Train MiniSeg-B0 from scratch (8 GPUs, 160k iterations):

```bash
python tools/train.py --config configs/miniseg_b0_ade20k.yaml
```

> [!NOTE]
> 🔵 **已识别命令 · 未执行** · 1 条命令；仅执行选定目标

## Citation

```bibtex
@inproceedings{miniseg2026,
  title     = {MiniSeg: Simple and Efficient Semantic Segmentation},
  author    = {Lin, Jia and Ito, Sora and Novak, Petra},
  booktitle = {NeurIPS},
  year      = {2026}
}
```

<sub>⚪ 仅阅读</sub>

## Acknowledgements

Built on top of [mmsegmentation](https://github.com/open-mmlab/mmsegmentation)
and [timm](https://github.com/huggingface/pytorch-image-models).

<sub>⚪ 仅阅读</sub>

## License

This project is released under the [MIT License](LICENSE).

<sub>⚪ 仅阅读</sub>
