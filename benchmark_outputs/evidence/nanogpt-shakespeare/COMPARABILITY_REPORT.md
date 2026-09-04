# Comparability Report

- Mode: `repro`
- Target repo: `D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\nanogpt-shakespeare-20260904T180201Z-30204\repo`
- Comparability status: `preserved`
- README-first: `True`
- Documented command: `python train.py config/train_shakespeare_char.py --device=cpu --compile=False --eval_iters=20 --log_interval=1 --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 --max_iters=2000 --lr_decay_iters=2000 --dropout=0.0`
- Command source: `code_block`
- Command section: `quick start`

## Comparison Anchors

- README documented command
- repository files used to interpret the README
- paper or baseline references only when explicitly resolved

## Protocol Deviations

- None.

## Patch And Execution Effects

- patches_applied=False
- readme_fidelity=preserved
- highest_patch_risk=low
- run_mode=startup_verification
- dataset=https://openwebtext2.readthedocs.io/en/latest/),
- checkpoint_source=https://github.com/karpathy/minGPT)

## Assumptions And Gaps

- README remains the primary source of truth.
- Environment creation should prefer isolated setup before any semantic code changes.
- Model architecture should remain unchanged unless the researcher explicitly requests otherwise.
- Only startup verification is allowed before the researcher explicitly authorizes a fuller training reproduction run.

## Interpretation

Treat results as directly comparable only when the documented command, data, preprocessing, checkpoint, metric, and baseline conditions remain aligned.
