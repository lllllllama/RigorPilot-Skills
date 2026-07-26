# AGENTS.md — RigorPilot Skills

Guidance for any coding or research agent (OpenAI Codex, Cursor, GitHub
Copilot, Gemini CLI, Claude Code, and other AGENTS.md-aware tools) working in
or with this repository. Skills here follow the
[Agent Skills open standard](https://agentskills.io); each
`skills/<slug>/SKILL.md` is the canonical, model-agnostic contract.

## What this project is

RigorPilot Skills is a research-first Agent Skills repository for deep learning
experiments. It keeps AI-assisted research grounded in comparability,
reproducible evidence, and auditable changes while an agent reproduces,
improves, or explores a research repository. The flagship output is the
annotated README: `repro_outputs/ANNOTATED_README.md` replays the target
repository's README verbatim with a color-coded, evidence-linked account of
what the agent did in each section.

## Using the skills on a research repository

- Default to the trusted lane. Ambiguous requests route to reproduction,
  setup, conservative execution, training verification, analysis, or safe
  debugging — never to exploration.
- Read `skills/<slug>/SKILL.md` before acting; it defines fit, boundaries,
  workflow, and the output contract for that skill.
- Entrypoints by intent:

| Intent | Skill slug |
|---|---|
| Reproduce from README commands | `ai-research-reproduction` |
| Read-only repository analysis | `analyze-project` |
| Environment / dataset / weights setup | `env-and-assets-bootstrap` |
| Conservative documented run | `minimal-run-and-audit` |
| Conservative training verification | `run-train` |
| Diagnose-before-patch debugging | `safe-debug` |
| Candidate-only exploration (explicit authorization required) | `ai-research-explore` |

- In the explore lane, follow `references/research-thinking-loop.md`: a greedy,
  evidence-anchored cycle (observe → ground → hypothesize → single-variable
  design → bounded run → fair compare → keep or roll back → record).
- Consult `~/.rigorpilot/PERSONAL_RIGOR.md` if present, under
  `references/continuous-learning-policy.md` — advisory only; it never relaxes
  rigor gates and the repository always wins on conflict.
- Write evidence bundles to the documented output directories
  (`repro_outputs/`, `train_outputs/`, `analysis_outputs/`, `debug_outputs/`,
  `explore_outputs/`). Never claim success without recorded evidence.
- Never make silent semantic changes to a target repository; record every
  assumption, deviation, and blocker.
- Exploration is candidate-only and requires the researcher's explicit
  authorization plus a durable `current_research` anchor.

## Developing this repository

- Validate before committing:

```bash
python scripts/validate_repo.py
python scripts/test_skill_registry.py
```

- The full regression suite is every `scripts/test_*.py` file; all must pass.
- Conventions: public `SKILL.md` files stay ≤ 130 lines; the skill registry
  (`references/skill-registry.json`) stays in sync with `skills/*`; scripts
  run on both Windows PowerShell and Linux shells; human-readable outputs are
  bilingual (en/zh) where the writers support it.
- Shared bundle writers live in `shared/scripts/`; five skills load them at
  runtime, and the installer ships them alongside the skills.

## Hard rules

1. Comparability first: if evaluation conditions change, say results are not
   directly comparable.
2. No score chasing without explanatory value; no novelty claims without
   evidence.
3. Engineering fixes must not be disguised as research contributions.
4. Important changes must be auditable, reversible, and explainable.
