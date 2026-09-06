# Research Pitfall Checklist

Use this checklist during repository analysis and safe debugging.

## Model structure

- missing position or time encoding where sequence order matters
- repeated activation such as `sigmoid` after `sigmoid`
- suspicious activation stacking such as `relu` immediately followed by `sigmoid`
- residual branch added before shape or normalization alignment
- logits and probabilities mixed in the same path
- output head shape mismatched with labels or metric expectations

## Training logic

- optimizer missing intended parameter groups
- `model.train()` and `model.eval()` state used in the wrong place
- detached tensors breaking gradient flow
- loss target shape or dtype mismatch
- scheduler stepped in the wrong order
- mixed precision or gradient scaler applied inconsistently
- checkpoint resume missing optimizer, scheduler, or step state

## Data and configuration

- labels or variable names possibly swapped
- mask or padding direction inverted
- sampler or split assignment inconsistent with the intended protocol
- config keys present but ignored in code
- dataset root, cache root, or checkpoint path assumptions not recorded

## Evaluation and inference

- duplicate post-processing
- thresholding applied on logits instead of probabilities, or the reverse
- metric code consuming the wrong representation
- evaluation path reusing training-time augmentation or dropout

## Use guidance

- Treat checklist hits as suspicious patterns, not confirmed bugs.
- Prefer citing the exact file and symbol before suggesting any fix.
- In trusted lanes, do not patch based on checklist suspicion alone without researcher approval.
