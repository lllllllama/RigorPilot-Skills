# Agent Operating Principles

These principles apply across the public skills in this repository. RigorPilot
uses them as directional guardrails, not a replacement for model judgment. Use
them to keep the agent aligned at the workflow level while leaving
implementation details to the active model and the local repository context.

For deep learning reproduction, improvement, exploration, experiment claims,
method contributions, SOTA, baselines, ablations, training, or evaluation, also
load `research-rigor-principles.md`. When the task depends on experiment
details, load `deep-learning-experiment-principles.md` as needed.

## Think before acting

- State important assumptions when the request, README, or local files leave
  more than one plausible interpretation.
- Ask only for decisions that cannot be resolved from the repository or the
  user's prompt.
- Surface meaningful tradeoffs instead of silently choosing a path that changes
  scientific meaning, evaluation scope, or user intent.

## Keep the solution small

- Prefer the smallest action that satisfies the current lane and output goal.
- Do not add generic frameworks, new public skills, or broad automation when a
  focused skill, script, or reference is enough.
- Move detailed, rarely needed rules into references; keep `SKILL.md` files
  readable as entrypoints.

## Change only what is necessary

- Preserve existing public skill names, aliases, output directories, and
  machine-readable contracts unless the user explicitly asks to migrate them.
- Keep trusted reproduction, analysis, setup, execution, training, debugging,
  and exploration as separate lane decisions.
- Mention unrelated cleanup opportunities without folding them into the current
  task.

## Work toward verifiable goals

- Convert requests into observable success criteria: selected command, produced
  output bundle, captured evidence, reproduced failure, ranked candidate, or
  recorded blocker.
- Treat verification evidence as stronger than confidence or style preference.
- Record gaps plainly when the current run cannot prove a claim.

## Apply freedom at the right level

- Use high freedom for reasoning, code reading, implementation choices, and
  adapting to the target repository, including literature synthesis and local
  repository adaptation.
- Use medium freedom for campaign schemas, output templates, and ranking
  heuristics where consistency helps review.
- Use low freedom only for fragile contracts: public skill names, lane
  boundaries, output directory names, status keys, comparability,
  reproducibility, auditability, and scientific safety checks.
- These principles must not reduce strong model capability. They should add
  research judgment and audit awareness, not mechanical burden.
