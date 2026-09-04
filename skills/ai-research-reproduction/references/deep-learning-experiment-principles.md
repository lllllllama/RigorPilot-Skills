# Deep Learning Experiment Principles

## Purpose

These principles help AI agents treat deep learning repositories as research artifacts, not ordinary software projects. They provide background judgment for reproduction, improvement, exploration, debugging, and research claims.

## Background Principles

1. Preserve baseline meaning.
   Baselines should not be modified silently. If a baseline is changed, explain how comparability is affected.

2. Preserve evaluation protocol.
   Dataset splits, preprocessing, metrics, evaluation scripts, checkpoints, and inference settings should stay aligned with the original claim whenever possible.

3. Record experiment context.
   Commands, configs, seeds, checkpoints, dataset versions, hardware/runtime assumptions, logs, and metrics are part of the research evidence.

4. Separate tricks from contributions.
   Training tricks, hyperparameter changes, engineering patches, and method changes should be distinguished.

5. Treat score gains cautiously.
   Metric gains should be connected to hypotheses, mechanisms, ablations, or controlled comparisons.

6. Use ablation thinking.
   If a change is proposed as meaningful, identify what ablation would isolate its effect.

7. Be explicit about SOTA comparison.
   SOTA or paper comparisons must explain whether evaluation settings, data, metrics, and compute assumptions are aligned.

8. Do not hide failed or partial evidence.
   Failed runs, partial reproduction, missing assets, or non-comparable results should be recorded plainly.

9. Treat code, configs, data, and logs as evidence.
   Deep learning research evidence is spread across README commands, scripts, configs, checkpoints, datasets, metrics, logs, and generated artifacts.

10. Engineering fixes are allowed but must be labeled.
    Fixes that make a repository run are valuable, but they do not automatically become research contributions.

These principles are not a rigid checklist. They should guide model judgment when scientific meaning, comparability, reproducibility, or contribution claims are at stake.
