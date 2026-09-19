# Repository Slug Installation Note

The canonical GitHub repository slug for this project is now:

```text
lllllllama/ai-research-workflow-skills
```

Use the canonical slug for new `npx skills add` installs:

```bash
npx skills add lllllllama/ai-research-workflow-skills --all
npx skills add lllllllama/ai-research-workflow-skills --skill ai-research-reproduction
npx skills add lllllllama/ai-research-workflow-skills --skill ai-research-explore
```

The older slug below may still appear in historical notes, cached examples, or local checkouts created before the rename:

```text
lllllllama/ai-paper-reproduction-skills
```

Treat that older slug as a compatibility fallback only. Prefer the canonical `ai-research-workflow-skills` slug in new documentation, onboarding notes, install scripts, and examples.

## Maintenance guidance

When updating installation docs, keep these references aligned:

- `README.md`
- `README.zh-CN.md`
- installer examples that call `npx skills add`
- release notes or migration notes that mention the repository slug

This note exists to make the repository rename explicit and reduce confusion for new users following install commands.
