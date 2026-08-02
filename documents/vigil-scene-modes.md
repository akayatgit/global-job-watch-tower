# VIGIL scene modes — how to navigate the world model

Ashok’s navigation intent (2026-08-02): the particle singularity is the
**heart**; Obsidian graph and City globe are **modes you enter**, not junk
layered on top of the core.

| Mode | What you see | How to move |
|---|---|---|
| **Core** (default) | GPU particle singularity | **Drag** orbit · **scroll/pinch** enter deep · **right-drag** pan · Esc reset |
| **Graph** | Obsidian graph + text tags on nodes/edges | Click tagged node → panel; city tag → City mode |
| **City** | Globe with city tags → company buildings tagged | Click metro → skyline; click building → jobs; empty → globe |

Top-right icon strip: Core · Graph · City.

**Navigation law (2026-08-03):** same freedom as Miro/Figma — full 3D control
to go in and out easily. Never clamp the camera outside the orb.

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
