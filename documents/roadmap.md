# Global Job WATCH TOWER — Agile Roadmap

| Field | Value |
|---|---|
| **Method** | Serious agile: one **current sprint** in flight, one **next milestone** queued, backlog below |
| **Definition of Done** | Slice is complete for its scope (UX laws in `.cursor/rules/product-ux.mdc`), verified, committed locally |
| **Narrative PRD** | [`documents/product-requirements-v0.md`](./product-requirements-v0.md) |
| **Locked recover** | `milestone/singularity-core-v1` · older `milestone/pre-neural-core-v0` |
| **Owner** | Akay — update this file in place after every accepted slice |
| **Status as of** | 2026-08-03 |

---

## How we run

1. **One sprint goal** at a time — finish it fully before starting the next milestone’s big item.
2. Ashok answers YES/NO on scope; Akay builds end-to-end.
3. Commit locally as slices land; **push only with Ashok double-YES** (prefer end-of-day).
4. Before any push/deploy: name which live search(es) will be disturbed.
5. Check boxes here when done; never fork “roadmap-v2”.

---

## 🔥 Current sprint — Graph local-focus (Maps)

**Goal:** Obsidian-style neighborhood focus on the world-model graph.

| ID | Slice | Status |
|---|---|---|
| WM-G1 | Click a **card** (fat hit target, not text) → focus depth‑1/2 neighborhood | Done |
| WM-G2 | Hide non-neighborhood; Esc / empty click → global graph | Done |
| WM-G3 | Second click on focused card → open insight panel | Done |
| WM-G4 | Freeze auto-rotation while working (all 3 modes) — HUD + Space | Done |
| WM-G5 | Labels never steal clicks (`pointer-events: none`) | Done |

**Sprint exit:** Ashok can click big graph cards, explore a local cluster, open a panel, freeze spin, recover to global.  
**Next after verify:** start **Richer City districts** milestone (WM-C1…).

---

## ⏭ Next milestone — Richer City districts

**Queued after Graph local-focus ships.** Do not start mid-sprint unless Ashok reorders.

| ID | Slice | Notes |
|---|---|---|
| WM-C1 | City skyline = real employers; height/glow = hiring volume | Building **cards** clickable |
| WM-C2 | Sector blocks / streets inside metro | Place-based Maps |
| WM-C3 | Hover pace + click → jobs for company **in that city** | Role filter preserved where relevant |
| WM-C4 | Globe → city → district zoom beats | Same OrbitControls language |

---

## Later backlog (pull when sprint/milestone clear)

### Phase 1 — Tracks
- [ ] ⭐ Competitor Intelligence (`EC-06`)
- [ ] 🔶 Domestic / Global scope (`DE-09`)
- [ ] 🔶 Employer direct onboard (`DE-07`)

### Phase 2 — Maps (beyond world-model shell)
- [ ] 🔶 Skills Radar (`EI-05`)
- [ ] 🔶 Industry Pulse (`EI-04`)
- [ ] 🔶 Talent Flow (`EI-02`)

### Phase 3 — Predicts + Economic
- [ ] 🔶 Future Forecast (`EI-01`)
- [ ] 🔶 Boom Signals (`EC-03`)
- [ ] 🔷 Recession / Investment / Partnership / Disruption capsules

### Foundation / security
- [ ] 🔶 Admin authentication
- [ ] 🔷 Postgres backup / retention policy

### Done anchors (do not reopen casually)
- [x] Singularity Core v1 + Miro/Figma 3D nav + mode split (locked tag)
- [x] VIGIL shell, Hiring Signals, Watchlist, Cities chips, sector filter
- [x] Collector + Ollama relevance + Plan B under critical heat

---

## Cadence reminder

First-mover: keep the tower collecting. UI sprints must not thrash deploys into cancel storms.
