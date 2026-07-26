# Continuous Learning Policy

RigorPilot skills ship as an immutable universal core: research rigor
principles, the thinking loop, and the lane model. Personalization happens in
a separate, user-owned overlay that accumulates lessons from real use. The
core never mutates itself; the overlay never overrides the core.

## Lesson store

- Location: `~/.rigorpilot/lessons.jsonl` (override the directory with
  `RIGORPILOT_HOME`; disable recording entirely with `RIGORPILOT_LESSONS=0`).
- Distilled overlay: `~/.rigorpilot/PERSONAL_RIGOR.md`, regenerated on demand
  by `shared/scripts/lessons_store.py --summarize`.
- Both files are plain text, user-auditable, and safe to delete at any time;
  deleting them returns the skills to the universal base behavior.

## What gets recorded

| Kind | Meaning | Typical source |
|---|---|---|
| `failure-fix` | A blocker hit during a run, with the working fix once known | orchestrators, agent |
| `user-correction` | The researcher corrected the agent's choice or output | agent |
| `preference` | A durable user preference (language, lanes, output style) | agent, user |
| `generalization` | A lesson distilled from repeated records | `--summarize`, user review |

Each record is one compact line: kind, skill, summary, optional detail, and a
repo fingerprint (directory name + README hash prefix) — enough to recognize
"we have seen this before", nothing more.

## Hard rules (never negotiable)

1. Lessons are advisory. They may change defaults, phrasing, and ordering of
   safe options; they may never relax rigor gates, lane boundaries,
   comparability rules, or authorization requirements.
2. No secrets. The store refuses lines that look like tokens, keys, or
   passwords; never record credentials, private URLs, or personal data.
3. No self-editing. The agent must not modify any `SKILL.md`, policy, or
   reference file based on lessons. Promotion of a lesson into shared skill
   text is a human decision made through normal review.
4. Transparent by default. When a lesson influences a decision, say so and
   name the lesson. The researcher can always ask to see or delete the store.
5. Bounded growth. `--summarize` dedupes and prunes; the overlay stays short
   enough to read in one sitting.

## How skills use the overlay

At the start of a run, if `~/.rigorpilot/PERSONAL_RIGOR.md` exists, read it
and treat it as the researcher's standing preferences and known pitfalls for
their environments. On conflict with any policy or reference in this
repository, the repository wins and the conflict is worth reporting.
