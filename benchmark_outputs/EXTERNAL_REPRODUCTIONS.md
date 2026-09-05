# RigorPilot External Reproductions

Four pinned public repositories, one evidence contract. Each case records the
selected README command, execution boundary, source integrity, and complete
RigorPilot output bundle. Jump directly to a case:

[micrograd](#micrograd) · [minGPT](#mingpt) · [PyTorch MNIST](#pytorch-mnist) · [nanoGPT Shakespeare](#nanogpt-shakespeare)

**Suite snapshot:** 4/4 protocol checks passed in 251.0 seconds, 0 API calls;
all temporary workspaces were removed and tracked showcase repositories were
retained. A passed protocol means the harness behaved as specified; it does
not turn a bounded startup run into a convergence claim.

<a id="micrograd"></a>

## micrograd — correctness canary

[![micrograd reproduction preview](../assets/showcase/external-micrograd.png)](showcases/micrograd/repo/RIGORPILOT_README.md)

- Source: [karpathy/micrograd @ `7bc720e`](https://github.com/karpathy/micrograd/tree/7bc720e951fe422b8f8814aa5aa1b64121d26b4c)
- Selected command: `python -m pytest`
- Observed result: **success**, 2 tests passed in 7.62 seconds
- README fidelity: 8 headings = 8 section annotations; original and stripped
  SHA-256 are identical
- Harness check: command selection, direct execution, evidence completeness,
  source integrity, and cleanup all passed

[Open the retained-repository RigorPilot README](showcases/micrograd/repo/RIGORPILOT_README.md) ·
[summary](evidence/micrograd/SUMMARY.md) ·
[commands](evidence/micrograd/COMMANDS.md) ·
[log](evidence/micrograd/LOG.md) ·
[machine-readable status](evidence/micrograd/status.json)

<a id="mingpt"></a>

## minGPT — selection and risk canary

[![minGPT reproduction preview](../assets/showcase/external-mingpt.png)](showcases/mingpt/repo/RIGORPILOT_README.md)

- Source: [karpathy/minGPT @ `37baab7`](https://github.com/karpathy/minGPT/tree/37baab71b9abea1b76ab957409a1cc2fbfba8a26)
- Selected command: `python -m unittest discover tests`
- Observed result: **not run by design**; no implicit GPT-2 download or training
- README fidelity: 11 headings = 11 section annotations; SHA-256 round trip exact
- Harness check: target selection, risk boundary, evidence completeness, source
  integrity, and cleanup all passed

[Open the retained-repository RigorPilot README](showcases/mingpt/repo/RIGORPILOT_README.md) ·
[summary](evidence/mingpt/SUMMARY.md) ·
[commands](evidence/mingpt/COMMANDS.md) ·
[log](evidence/mingpt/LOG.md) ·
[machine-readable status](evidence/mingpt/status.json)

<a id="pytorch-mnist"></a>

## PyTorch MNIST — data and evaluation canary

[![PyTorch MNIST reproduction preview](../assets/showcase/external-pytorch-mnist.png)](showcases/pytorch-mnist/repo/mnist/RIGORPILOT_README.md)

- Source: [pytorch/examples MNIST @ `acc295d`](https://github.com/pytorch/examples/tree/acc295dc7b90714f1bf47f06004fc19a7fe235c4/mnist)
- Selected command: `python main.py`
- Observed result: **bounded partial run**, `loss=0.038893`
- README fidelity: 1 heading = 1 section annotation; SHA-256 round trip exact
- Harness check: metric capture, timeout boundary, evidence completeness, source
  integrity, and cleanup all passed

[Open the retained-repository RigorPilot README](showcases/pytorch-mnist/repo/mnist/RIGORPILOT_README.md) ·
[summary](evidence/pytorch-mnist/SUMMARY.md) ·
[commands](evidence/pytorch-mnist/COMMANDS.md) ·
[log](evidence/pytorch-mnist/LOG.md) ·
[machine-readable status](evidence/pytorch-mnist/status.json)

<a id="nanogpt-shakespeare"></a>

## nanoGPT Shakespeare — bounded training canary

[![nanoGPT Shakespeare reproduction preview](../assets/showcase/external-nanogpt.png)](showcases/nanogpt-shakespeare/repo/RIGORPILOT_README.md)

- Source: [karpathy/nanoGPT @ `3adf61e`](https://github.com/karpathy/nanoGPT/tree/3adf61e154c3fe3fca428ad6bc3818b27a3b8291)
- Selected target: documented Shakespeare character-model CPU training
- Observed result: **bounded partial run**, `train_loss=4.1676`, `val_loss=4.1649`
- README fidelity: 11 headings = 11 section annotations; SHA-256 round trip exact
- Harness check: long-running process control, metric capture, evidence
  completeness, source integrity, and cleanup all passed

[Open the retained-repository RigorPilot README](showcases/nanogpt-shakespeare/repo/RIGORPILOT_README.md) ·
[summary](evidence/nanogpt-shakespeare/SUMMARY.md) ·
[commands](evidence/nanogpt-shakespeare/COMMANDS.md) ·
[log](evidence/nanogpt-shakespeare/LOG.md) ·
[machine-readable status](evidence/nanogpt-shakespeare/status.json)

---

[Suite result](external_suite_latest.json) ·
[case definitions](../benchmarks/external_cases.json) ·
[methodology and limitations](../benchmarks/README.md)
