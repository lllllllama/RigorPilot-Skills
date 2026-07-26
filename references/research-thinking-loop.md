# Research Thinking Loop

Modern agents implement well but think in engineering steps. This loop is the
required thinking spine for exploratory research work: a greedy,
evidence-grounded cycle from observation to a fair keep-or-rollback decision.
It adapts the greedy solution-space search of AIDE and the managed agentic
tree search of AI-Scientist-v2 to RigorPilot's comparability-first rules.

## The loop

Each iteration improves on the current best state (`current_research`) by at
most one deliberate change.

1. **Observe.** Read the latest run evidence: metrics, curves, failures,
   ledger entries. State what is surprising or limiting, in one sentence.
2. **Ground.** Before proposing anything, search for support: paper claims
   (lookup records), source implementations, prior runs in the ledger, or an
   explicitly labeled experimental intuition. Every hypothesis must cite at
   least one anchor and label it `paper`, `code`, `prior-run`, or
   `intuition`. Unanchored ideas go to the idea bank, not to execution.
3. **Hypothesize.** Write a falsifiable statement: expected direction on the
   frozen primary metric, and the mechanism that would explain it.
4. **Design.** Single-variable, reversible, bounded (subset or short run
   first). Keep dataset, preprocessing, evaluation command, and seeds frozen;
   anything unavoidable to change must be declared as a comparability break.
5. **Run.** Execute the smallest trustworthy version. Record real evidence
   (changed files, metrics, logs) — never predicted numbers.
6. **Compare fairly.** Same evaluation contract as `current_research`. If
   conditions differ, the comparison is labeled non-comparable and cannot
   justify a keep decision.
7. **Decide greedily.** Better on the primary metric under fair conditions →
   the candidate becomes the new best (still candidate-grade, not trusted).
   Not better, noisy, or unfair → roll back and record why. Ties favor the
   simpler, cheaper change.
8. **Record.** One ledger entry per iteration: anchor, hypothesis, design,
   evidence, decision, and what the result teaches for the next iteration.

## Discipline

- One active change per iteration; no silent multi-variable jumps.
- A failed iteration is information: mine it for the next hypothesis before
  proposing something unrelated.
- Greedy applies to selection, not honesty: never keep a candidate on
  non-comparable or partial evidence.
- Stop when the budget is spent, when two consecutive iterations yield no
  fair improvement, or when the researcher redirects.

## Boundary

This loop lives inside the explore lane and inherits every trusted-lane and
campaign gate: frozen evaluation, explicit authorization, candidate-only
claims, and auditable rollback.
