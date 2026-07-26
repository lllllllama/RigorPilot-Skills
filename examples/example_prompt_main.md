# Example Prompt: Main Skill

Most users should start with `ai-research-reproduction`.

## Shortest example

Use `ai-research-reproduction` on this deep learning research repo. Stay README-first, prefer documented inference or evaluation, avoid unnecessary repo edits, and write outputs to `repro_outputs/`.

## Main skill with paper-assisted gap resolution

Use `ai-research-reproduction` on this deep learning research repo. Stay README-first, choose the smallest trustworthy documented target, and only use `paper-context-resolver` if the README is missing a reproduction-critical detail such as the evaluation split or checkpoint mapping.

## Slightly more explicit example

Use `ai-research-reproduction` on this deep learning paper repository.

- stay README-first
- choose the smallest trustworthy documented target
- prefer documented inference, then documented evaluation, then training startup only if needed
- avoid repo code changes unless clearly necessary
- keep human-readable outputs in my language, but keep `status.json` keys in English
- write outputs to `repro_outputs/`

