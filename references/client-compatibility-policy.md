# Client Compatibility Policy

This repository treats `SKILL.md` as the canonical portable skill format.

## Canonical skill contract

- every skill must have a valid `SKILL.md`
- repository-local scripts and references must be addressable from that skill directory
- core skill behavior must not depend on client-specific metadata files

## Installation targets

Prefer the neutral Agent Skills layout when you want one install target that works across compatible clients:

- `~/.agents/skills/`
- `./.agents/skills/`

Client-specific installs are still supported:

- Codex: `~/.codex/skills/`
- Claude Code: `~/.claude/skills/`

## Metadata policy

`agents/openai.yaml` is optional UI metadata for clients that use it.

Rules:

- do not treat `agents/openai.yaml` as the canonical skill definition
- do not make cross-client behavior depend on `agents/openai.yaml`
- validate `agents/openai.yaml` only when it exists

## Documentation policy

- document neutral install paths first when describing cross-client usage
- keep client-specific examples when they help users adopt the repository
- do not describe Codex-only metadata as if Claude Code requires it

## Agent Skills standard and AGENTS.md

The skills in this repository target the Agent Skills open standard
(agentskills.io): `name` and `description` are the only required frontmatter
fields, and spec-compliant runtimes ignore unknown keys, so the same
`SKILL.md` loads in Claude Code, OpenAI Codex, Cursor, VS Code, Gemini CLI,
and other adopters without per-client forks.

The repository root also ships an `AGENTS.md` for AGENTS.md-aware agents
(Codex, Cursor, Copilot, Gemini CLI, Aider, Zed, and others). It carries the
lane model, entrypoint table, and hard rules at the project level.

Rules:

- keep `SKILL.md` instructions free of model-specific tool syntax
- keep `AGENTS.md` consistent with the skill registry and this policy
- when the entrypoint table changes, update `AGENTS.md`, the registry, and
  both READMEs together
