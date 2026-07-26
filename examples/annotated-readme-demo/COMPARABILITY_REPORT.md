# Comparability Report

- Mode: `repro`
- Target repo: `/home/user/demo/miniseg`
- Comparability status: `preserved`
- README-first: `True`
- Documented command: `python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth`
- Command source: `code_block`
- Command section: `Evaluation`

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
- run_mode=None
- dataset=unknown
- checkpoint_source=configs/miniseg_b0_ade20k.yaml, checkpoints/miniseg_b0.pth

## Assumptions And Gaps

- README remains the primary source of truth.
- Environment creation should prefer isolated setup before any semantic code changes.
- Model architecture should remain unchanged unless the researcher explicitly requests otherwise.

## Interpretation

Treat results as directly comparable only when the documented command, data, preprocessing, checkpoint, metric, and baseline conditions remain aligned.
