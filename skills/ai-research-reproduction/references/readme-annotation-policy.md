# README Annotation Policy

After the reproduction evidence is recorded, the target repository README can be
annotated with concise reproduction-status notes. This is the only sanctioned
way for this skill to modify a target README.

## Non-negotiable rules

1. Original README fragments stay byte-for-byte identical. Every ATX heading
   (`#` through `######`) starts one section block, and exactly one annotation
   is inserted at that block's end, before the next heading. A marked banner is
   inserted at the top. Never rewrite, reflow, trim, or "fix" original content.
   Images, GIFs, videos, HTML, badges, and other non-text markup remain inside
   those same immutable source slices; never extract a text-only surrogate.
2. Every annotation block is wrapped in marker comments:

   ```text
   <!-- rigorpilot:repro:begin kind="section" section="..." occurrence="1" status="..." risk="..." -->
   > 🟢✅ **复现** — one concise sentence about this section's reproduction state.
   <!-- rigorpilot:repro:end -->
   ```

3. Annotations must be mechanically strippable. `annotate_readme.py strip`
   restores the exact original bytes, including UTF-8 BOM, CRLF/LF choice,
   blank lines, and final-newline state. `annotate` refuses to leave an output
   file when this round-trip check fails.
4. Keep each note to one concise sentence, in the user's language, plus at most
   a few short detail bullets. The README is not the place for logs; deep
   evidence belongs in `repro_outputs/`.
5. Only annotate sections you actually engaged with. Do not fabricate a status
   for sections that were never attempted; either skip them or mark them
   `not_attempted`.

## Status and risk vocabulary

Status describes the reproduction outcome for that section:

| Status | Icon | Meaning |
|---|---|---|
| `reproduced` | ✅ | Documented content verified as described |
| `partial` | ⚠️ | Started or partially verified, with recorded gaps |
| `blocked` | ❌ | Attempted but blocked; blocker recorded |
| `not_attempted` | ⏭️ | Consciously skipped |

Risk is a color for how invasive the changes behind that status were:

| Risk | Icon | Meaning |
|---|---|---|
| `none` / `low` | 🟢 | Ran as documented, or environment-layer fixes only (paths, pins, env vars) |
| `medium` | 🟡 | Adapted commands or compatibility patches; documented intent preserved |
| `high` | 🔴 | Deviation that could affect scientific meaning or comparability |

Any `high` risk annotation must point at a recorded entry in
`SCIENTIFIC_CHANGELOG.md` or `PATCHES.md`; the README note is a signpost, not
the evidence.

## Banner

Unless disabled, a banner block is inserted at the top of the file. It states
that original content is unchanged, explains the icon legend, links to
`repro_outputs/SUMMARY.md`, and records `original_sha256` of the unannotated
README so `annotate_readme.py check` can detect any later edit to original
fragments.

## Where the annotated README goes

- Always write the annotated copy to `repro_outputs/ANNOTATED_README.md`.
  Round-trip status, original/stripped SHA-256, annotation count, and section
  coverage are recorded under `readme_section_coverage` in `status.json`.
- Annotate the target README in place only on the `repro/...` branch, following
  `patch-policy.md`. In-place annotation counts as a documentation-layer patch:
  record it in `PATCHES.md` with `readme_fidelity: annotated`, and note that
  `annotate_readme.py strip --in-place` reverses it exactly.
- Never annotate in place on the user's main branch without explicit consent.

## Tool usage

```bash
python skills/ai-research-reproduction/scripts/annotate_readme.py annotate \
  --readme README.md \
  --context-json repro_outputs/status.json \
  --output repro_outputs/ANNOTATED_README.md
```

- `strip --input ANNOTATED_README.md --output README.restored.md` removes every
  complete marker block and restores the exact original bytes.
- `check --input ANNOTATED_README.md --against README.md` verifies marker
  integrity and byte-for-byte equality with the original.
- Re-annotation always starts from the unannotated source README. A source that
  already contains reserved RigorPilot markers is rejected.

The annotation spec is JSON; see `assets/readme_annotations.template.json`.
Anchors are ATX heading lines (`## Usage`) or bare heading titles (`Usage`),
with `occurrence` to disambiguate duplicates.
