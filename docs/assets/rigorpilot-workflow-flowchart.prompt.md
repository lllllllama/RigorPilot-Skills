# RigorPilot Workflow Flowchart

## Style Contract

- Palette: white background, research blue and teal for the core workflow, muted green for the trusted lane, restrained violet for the explore lane, amber for explicit gates, dark slate text.
- Aspect ratio: landscape, presentation-friendly 16:9 intent.
- Density: medium; one project overview figure with short labels only.
- Typography intent: clean academic technical infographic, readable in README and slide contexts.
- Figure taxonomy: overview workflow diagram.
- Forbidden motifs: decorative gradient blobs, fake screenshots, dense PPT template styling, random UI text, watermark, logo claims.

## Final Prompt

```text
Use case: infographic-diagram
Asset type: project README / presentation flowchart for a research workflow skill repository
Primary request: Create a concise, polished 16:9 workflow diagram for the RigorPilot Skills project.
Style/medium: clean academic technical infographic, flat vector-like bitmap, not a marketing poster.
Composition/framing: landscape 16:9, generous margins, clear left-to-right flow, balanced lanes, readable short labels only. Title at top: "RigorPilot Skills Workflow".
Color palette: white background, research blue and teal primary blocks, muted green for Trusted Lane, restrained violet for Explore Lane, small amber checkpoints, dark slate text.
Content blocks and exact labels:
1. Left input block: "Research Repo" and "README / Paper / Data"
2. Middle decision block: "Route Request"
3. Upper lane label: "Trusted Lane" with steps "Analyze" -> "Setup" -> "Run / Train" -> "Safe Debug" -> "Evidence Bundle"
4. Lower lane label: "Explore Lane" with gate "Explicit Authorization" then steps "Current Research" -> "Candidate Ideas" -> "Bounded Change" -> "Smoke Evidence" -> "Rank Results"
5. Right output block: "Auditable Outputs" with small stacked labels "repro_outputs", "analysis_outputs", "train_outputs", "debug_outputs", "explore_outputs"
6. Bottom principle strip: "Comparability | Reproducibility | Auditability"
Constraints: keep all text short and verbatim; use simple arrows and lane separation; make it suitable for a GitHub README or presentation slide; no logos, no watermarks, no random UI text.
Avoid: decorative gradient blobs, dense PPT template look, fake screenshots, tiny unreadable text, extra labels, clutter, 3D effects.
```

## QA Notes

- Generated with the built-in image generation tool.
- Copied into the project from the local Codex generated image cache.
- Visual check passed for project-level structure and short-label readability.
