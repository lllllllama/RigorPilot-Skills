# Contributing

Keep changes small, lane-aware, and easy to validate.

## Local workflow

1. Edit the relevant files under `skills/`, `references/`, `shared/`, or `scripts/`.
2. Synchronize bundled dependencies and run the automatically discovered full suite:

```bash
python scripts/sync_reproduction_bundle.py
python scripts/sync_reproduction_bundle.py --check
python scripts/run_all_tests.py
python scripts/check_publication.py
```

For a first hands-on exercise, run `python scripts/run_harness_lab.py` and read
the [learning roadmap](docs/PROJECT_GUIDE.md). The lab simulates model decisions
but executes real commands; it is not a model-quality benchmark. Share sanitized
reproduction feedback through the issue form; never upload credentials or
unreviewed private traces. Do not fix an acceptance failure by weakening its grader.

3. If installation behavior changed, also run:

```bash
python scripts/install_skills.py --client agents --target ./tmp/agents-skills --force
python scripts/install_skills.py --client codex --target ./tmp/codex-skills --force
python scripts/install_skills.py --client claude --target ./tmp/claude-skills --force
```

4. Commit only after the repository validates cleanly.

## Repository rules

- Keep every skill folder named exactly after its front matter `name`.
- Register every public or helper skill in `references/skill-registry.json`.
- Keep `SKILL.md` focused on boundaries and workflow.
- Treat `SKILL.md` as the canonical cross-client skill contract.
- Put detailed policy in `references/`.
- Put reusable writers and shared helpers in `shared/`.
- After changing a bundled reproduction dependency, run
  `python scripts/sync_reproduction_bundle.py`; CI rejects stale copies.
- Keep helper skills narrow.
- Preserve trusted-lane defaults unless the change intentionally introduces or updates an explore-lane capability.
- Do not make skill behavior depend on client-specific metadata such as `agents/openai.yaml`.
- Keep `.claude/commands/` wrappers aligned with the corresponding skill boundaries and entrypoints.
- External benchmark changes must keep cases commit-pinned, explicit, serial,
  disposable by default, and distinguish selection-only from executed evidence.

## Lane rules

- Trusted skills must not auto-route into exploration.
- Explore skills require explicit authorization signals.
- Helper skills should usually be orchestrator-invoked.
- Same-level skills should not call each other directly.
- Exploratory outputs must not be represented as trusted baseline results.

## Output compatibility

- Machine-readable keys and enums stay in stable English.
- Existing `repro_outputs/` behavior must remain backward compatible unless a migration is documented.
- New output directories should extend the contract, not silently replace existing trusted bundles.

## Pull request checklist

- `python scripts/validate_repo.py` passes
- `python scripts/test_skill_registry.py` passes
- `python scripts/test_trigger_boundaries.py` passes
- `python scripts/test_readme_selection.py` passes
- all lane-specific rendering tests pass
- installer and bootstrapper checks pass for neutral Agent Skills, Codex, and Claude Code entrypoints
- orchestrator dry-run still reflects the intended trusted chain
- helper/public/explore metadata still matches the actual boundaries
- output contract changes are intentional and documented
