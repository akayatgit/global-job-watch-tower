# VIGIL scene modes — how to navigate the world model

Ashok’s navigation intent (2026-08-02): the particle singularity is the
**heart**; Obsidian graph and City globe are **modes you enter**, not junk
layered on top of the core.

| Mode | What you see | How to move |
|---|---|---|
| **Core** (default) | 20k GPU particle swarm — labor-market singularity | Scroll wheel / pinch → camera enters the orb |
| **Graph** | Obsidian-style 3D knowledge graph (live Postgres) | Click node → panel; city node → jumps to City mode |
| **City** | Globe with hiring density glow | Click metro → district skyline; click empty → back to globe |

Top-right icon strip: Core · Graph · City.

## Design lessons applied

**Obsidian graph (community practice)**
- Color by kind (sector / city / company / role) — visual groups
- Clusters / neighborhoods, not a hairball around the core
- Smaller single-color nodes (no dual halo / nested glow spheres)
- Soft polyline edges (not jagged angled hairlines)
- Graph is a diagnostic + drill-down surface, not a second screensaver

**obsidian-city (codenameyau)**
- Night cityscape energy: density → glow height
- Navigate by dragging the view; enter a place to see structure
- Our twist: globe of India metros first, then procedural district for the
  selected city with corporate density as building height/glow

## Recover

Pre-rewrite baseline: `git checkout milestone/pre-neural-core-v0`
