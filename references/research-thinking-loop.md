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
2. **Ground.** Before proposing anything, search for support — starting with
   the experiment ledger (prior runs are the cheapest evidence), then paper
   claims (lookup records), source implementations, or an explicitly labeled
   experimental intuition. Every hypothesis must cite at least one anchor and
   label it `paper`, `code`, `prior-run`, or `intuition`. Unanchored ideas go
   to the idea bank, not to execution.
3. **Choose the iteration type.**
   - `draft`: no working candidate exists yet — propose a fresh minimal
     approach (start 2–3 independent drafts before committing to one line).
   - `debug`: the last run is buggy (crash, or no parsed primary metric) —
     fix it. Debugging does not count as a new single-variable change, and is
     capped at 3 attempts per candidate before the line is abandoned.
   - `improve`: the current best works — make one deliberate change to it.
4. **Hypothesize.** Write a falsifiable statement: expected direction on the
   frozen primary metric, and the mechanism that would explain it.
5. **Design.** Single-variable, reversible, bounded (subset or short run
   first). Keep dataset, preprocessing, evaluation command, and seeds frozen;
   anything unavoidable to change must be declared as a comparability break.
6. **Run.** Execute the smallest trustworthy version. Record real evidence
   (changed files, metrics, logs) — never predicted numbers.
7. **Compare fairly.** Same evaluation contract as `current_research`. A run
   with no parsed primary metric is buggy — it can never be best, only
   debugged or abandoned. If conditions differ, the comparison is labeled
   non-comparable and cannot justify a keep decision.
8. **Decide greedily.** Better on the primary metric under fair conditions →
   the candidate becomes the new best (still candidate-grade, not trusted).
   Before it may replace `current_research` as the standing reference, it
   needs a replication pass: rerun under the frozen contract across multiple
   seeds (default 3) and keep only if the aggregate still wins. Not better,
   noisy, or unfair → roll back and record why. Ties favor the simpler,
   cheaper change.
9. **Record.** One ledger entry per iteration: iteration type, anchor,
   hypothesis, design, evidence, decision, and what the result teaches next.

## Discipline

- One active change per iteration; no silent multi-variable jumps.
- A failed iteration is information: mine it for the next hypothesis before
  proposing something unrelated.
- Greedy applies to selection, not honesty: never keep a candidate on
  non-comparable or partial evidence.
- Best-candidate selection is metric-only under the frozen contract — never
  by an LLM's holistic judgment of which run "looks better".
- Stop with a typed reason, not silently. Recorded stop reasons:
  `budget-exhausted`, `no-fair-improvement` (two consecutive iterations
  without a comparable win), `debug-attempts-exhausted`,
  `researcher-redirect`, `blocked`.

## Defaults

| Knob | Default | Note |
|---|---|---|
| Initial independent drafts | 2–3 | before committing to one line |
| Debug attempts per candidate | 3 | then abandon the line |
| Replication seeds before promotion | 3 | aggregate must still win |
| Run boundedness | subset / short-run first | full runs need explicit budget |

## Boundary

This loop lives inside the explore lane and inherits every trusted-lane and
campaign gate: frozen evaluation, explicit authorization, candidate-only
claims, and auditable rollback.
