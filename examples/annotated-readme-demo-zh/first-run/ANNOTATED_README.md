<!-- RigorPilot annotated README: original content preserved verbatim; annotations added below each section. -->

# 📄 README · RigorPilot 复现批注

🟡 `partial` · `evaluation` · `trusted` · [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)

章节覆盖：🟡 2 · 🟣 1 · 🔵 1 · ⚪ 10（共 14 节）

<sub>🟢 成功 · 🔵 未执行 · ⚪ 仅阅读 · 🟡 部分完成 / 资产缺失 · 🔴 阻塞 · 🟣 待决策 —— 原文未改动，原文相对链接以仓库根目录为基准。</sub>

---

<div align="center">

<sub>⚪ 仅阅读</sub>

# MiniSeg: Simple and Efficient Semantic Segmentation

[![arXiv](https://img.shields.io/badge/arXiv-2606.01234-b31b1b.svg)](https://arxiv.org/abs/2606.01234)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.3-ee4c2c.svg)](https://pytorch.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PWC](https://img.shields.io/badge/PapersWithCode-SOTA-21cbce.svg)](https://paperswithcode.com/sota/semantic-segmentation-on-ade20k)

[Paper](https://arxiv.org/abs/2606.01234) | [Project Page](https://miniseg-lab.github.io/miniseg) | [Colab](https://colab.research.google.com/github/miniseg-lab/miniseg)

</div>

MiniSeg is a lightweight encoder-decoder for semantic segmentation. With a
hierarchical local-global mixer and a two-layer MLP head, MiniSeg-B0 reaches
**41.2 mIoU on ADE20K with only 3.8M parameters**, running at 118 FPS on a
single V100.

<div align="center">
  <img src="assets/arch.png" width="720" alt="MiniSeg architecture"/>
</div>

<sub>⚪ 仅阅读</sub>

## Highlights

- **Simple**: no attention approximations, no custom CUDA kernels — pure PyTorch.
- **Efficient**: 3.8M–13.1M parameters, 8.4G–15.9G FLOPs at 512×512.
- **Strong**: competitive with models 5–10× larger on ADE20K and Cityscapes.
- **Reproducible**: all configs, logs, and checkpoints released.

<sub>⚪ 仅阅读</sub>

## News

- **[2026-06-12]** MiniSeg-B0 / B1 checkpoints and full training logs released.
- **[2026-05-30]** MiniSeg is accepted to NeurIPS 2026.
- **[2026-04-18]** Preprint released on arXiv.

<sub>⚪ 仅阅读</sub>

## Model Zoo

### ADE20K

| Model | Crop | Iters | mIoU (SS) | mIoU (MS) | #Params | FLOPs | Checkpoint | Log |
|---|---|---|---|---|---|---|---|---|
| MiniSeg-B0 | 512×512 | 160k | 41.2 | 42.0 | 3.8M | 8.4G | [miniseg_b0.pth](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b0.pth) | [log](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b0_train.log) |
| MiniSeg-B1 | 512×512 | 160k | 44.7 | 45.5 | 13.1M | 15.9G | [miniseg_b1.pth](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b1.pth) | [log](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b1_train.log) |

### Cityscapes

| Model | Crop | Iters | mIoU (SS) | #Params | Checkpoint |
|---|---|---|---|---|---|
| MiniSeg-B1 | 1024×1024 | 160k | 79.9 | 13.1M | [miniseg_b1_city.pth](https://github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b1_city.pth) |

<sub>⚪ 仅阅读</sub>

## Installation

Tested with Python 3.10, PyTorch 2.3, CUDA 12.1.

```bash
conda create -n miniseg python=3.10 -y
conda activate miniseg
pip install torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

> [!NOTE]
> 🔵 **已纳入 setup 计划 · 未直接执行**
> `conda create -n miniseg python=3.10 -y`
> `conda activate miniseg`
> `pip install torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cu121`
> … +1
> <sub>证据: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)</sub>

## Data Preparation

Download [ADE20K](http://sceneparsing.csail.mit.edu/) and
[Cityscapes](https://www.cityscapes-dataset.com/), then link them under `data/`:

```bash
python tools/prepare_ade20k.py --root data/ade20k
python tools/prepare_cityscapes.py --root data/cityscapes
```

Expected layout:

```text
data/
├── ade20k/
│   ├── images/{training,validation}
│   └── annotations/{training,validation}
└── cityscapes/
    ├── leftImg8bit/{train,val}
    └── gtFine/{train,val}
```

> [!WARNING]
> 🟡 **数据资产未就绪（中风险）**
> `python tools/prepare_ade20k.py --root data/ade20k`
> `python tools/prepare_cityscapes.py --root data/cityscapes`
> 本地未检测到数据集；需先完成本节准备，完整评测才可复现。
> <sub>证据: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)</sub>

## Evaluation

Download a checkpoint from the [Model Zoo](#model-zoo) into `checkpoints/`,
then evaluate MiniSeg-B0 on the ADE20K validation split (single-scale):

```bash
python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth
```

Multi-scale + flip evaluation:

```bash
python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth --ms --flip
```

> [!WARNING]
> 🟡 **部分完成（中风险）**
> 命令：`python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth`
> 阻塞项：选定的文档命令以退出码 1 结束。
> 错误摘录：`FileNotFoundError: checkpoint not found: checkpoints/miniseg_b0.pth`
> 建议下一步：先准备环境与资源，再重试该文档命令。
> <sub>证据: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)</sub>

## Training

Train MiniSeg-B0 on ADE20K with 8 GPUs (160k iterations, syncBN):

```bash
torchrun --nproc_per_node=8 tools/train.py --config configs/miniseg_b0_ade20k.yaml
```

Single-GPU debugging run:

```bash
python tools/train.py --config configs/miniseg_b0_ade20k.yaml --debug
```

> [!IMPORTANT]
> 🟣 **训练未执行 · 需要显式授权（高影响操作）**
> `torchrun --nproc_per_node=8 tools/train.py --config configs/miniseg_b0_ade20k.yaml`
> `python tools/train.py --config configs/miniseg_b0_ade20k.yaml --debug`
> trusted lane 不会自行发起训练；获得授权后也只先做启动验证。
> <sub>证据: [SUMMARY](SUMMARY.md) · [COMMANDS](COMMANDS.md) · [LOG](LOG.md) · [status.json](status.json)</sub>

## Project Structure

```text
miniseg/
├── miniseg/
│   ├── models/       # backbone, mixer blocks, MLP head
│   └── datasets/     # ADE20K / Cityscapes loaders and transforms
├── tools/            # train / eval / data preparation entrypoints
├── configs/          # experiment configs
└── checkpoints/      # place downloaded checkpoints here
```

<sub>⚪ 仅阅读</sub>

## FAQ

**Q: Evaluation numbers differ slightly from the paper?**
A: Make sure you use single-scale (`--ms` off) and torch 2.3; cuDNN kernels
changed between 2.x releases and can shift mIoU by ±0.1.

**Q: Do you support Windows?**
A: Training is Linux-only; evaluation works on Windows with the same commands.

<sub>⚪ 仅阅读</sub>

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
and [timm](https://github.com/huggingface/pytorch-image-models). We thank the
ADE20K and Cityscapes teams for the datasets.

<sub>⚪ 仅阅读</sub>

## License

This project is released under the [MIT License](LICENSE).

<sub>⚪ 仅阅读</sub>
