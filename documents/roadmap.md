# Global Job WATCH TOWER — Task Roadmap (pick-and-go)

| Field | Value |
|---|---|
| **Purpose** | A flat, checkable task list so Ashok can open one doc and pick the next thing to build — no need to re-read the full PRD each time |
| **Source of truth (narrative)** | [`documents/product-requirements-v0.md`](./product-requirements-v0.md) — Sections 6 (module requirements) and 11 (phase roadmap). This doc is a **derived, task-shaped view** of that roadmap; update both when priorities change |
| **Owner** | Akay (AI Lead) — kept current after every accepted slice |
| **Status as of** | 2026-07-31 |

---

## How to use this doc

1. Work **top to bottom inside "🟢 Pick next"** first — it's pre-sorted by value using the PRD's P0 → P2 priorities and the first-mover mandate.
2. Say the task name (or its ID, e.g. `EC-06`) and Akay implements the full slice (code + UX DoD + docs), then checks it off here and in the PRD.
3. Once "🟢 Pick next" is empty, pull the next unchecked item from the phase it belongs to below.
4. `⭐ P0` = do first · `🔶 P1` = next · `🔷 P2` = later. IDs in `()` map 1:1 to PRD Section 6 requirement IDs.
5. This file is overwritten in place as tasks complete — no duplicate "roadmap-v2" files.

---

## 🟢 Pick next (top 5, ready to start)

- [ ] ⭐ **Competitor Intelligence** basic view — head-to-head hiring comparison between two+ watched companies (`EC-06`, P0 — the last unbuilt P0 item)
- [ ] 🔶 **Domestic / Global scope switch** on Tower + Signals + Jobs (`DE-09`, P1 — even if "Global" starts as a labeled subset of today's India catalogue)
- [ ] 🔶 **Admin authentication** — lock the admin shell behind a login before any exposure beyond the ThinkPad LAN (Section 9, item 3)
- [ ] 🔶 **Skills Radar v1** — extract skill keywords from job titles/text, show emerging vs declining (`EI-05`, P1 — first Phase 2 module, needs a `SkillTag` table)
- [ ] 🔶 **Employer direct onboard** — simple API/admin form for an employer to submit their own openings (`DE-07`, P1)

---

## Phase 0 — Foundation truth

- [x] Brand tokens + Quanta Q mark + "Live" naming on admin shell
- [x] Nav: Tower · Searches · Activity · Jobs · Live feed
- [x] Tower Overview pods (honest pilot metrics) + Tracks flywheel cue
- [x] Harden discovery pipeline (dwell floor, retries, stale-run reap, session locks)
- [x] Once-daily cadence + 111-role fresher/major catalogue seeded
- [x] Tower Health vitals (sticky header + `/tower-health` tab)
- [x] Thermal-aware Ollama relevance filter with keyword Plan B fallback
- [ ] 🔶 Admin authentication before any exposure beyond localhost (Section 9.3)
- [ ] 🔷 Documented Postgres backup / retention policy (Section 9.6)

## Phase 1 — Tracks (P0 intelligence)

- [x] Hiring Signals — openings trend, rising/cooling roles, company velocity (`EI-03`)
- [x] Company Watchlist — star/unstar, velocity, Tower teaser (`EC-01`)
- [ ] ⭐ Competitor Intelligence — compare rival companies' hiring pace/roles side by side (`EC-06`)
- [ ] 🔶 Domestic / Global scope switch across Tower, Signals, Jobs (`DE-09`)
- [ ] 🔶 Employer direct onboard / feed ingest (`DE-07`)

## Phase 2 — Maps

- [ ] 🔶 Skills Radar — emerging / declining skills, skill-gap view (`EI-05`) — needs `SkillTag` model + extraction job
- [ ] 🔶 Industry Pulse — sector growth rank, automation-impact tagging (`EI-04`)
- [ ] 🔶 Talent Flow — geo movement proxy from job locations over time (`EI-02`)

## Phase 3 — Predicts + Economic layer

- [ ] 🔶 Future Forecast — 6–12 month projection + role-obsolescence alerts (`EI-01`) — needs `Alert` model
- [ ] 🔶 Boom Signals — fast-growth sector/region detector (`EC-03`)
- [ ] 🔶 Industry Transformation narrative capsule (`EC-05`)
- [ ] 🔷 Recession Signals — labor-leading downturn indicators (`EC-02`)
- [ ] 🔷 Investment Direction capsule (`EC-04`)
- [ ] 🔷 Partnership Targets capsule (`EC-07`)
- [ ] 🔷 Disruption Alert capsule (`EC-08`)

## Phase 4 — Multi-source Discovery Engine

- [ ] 🔶 Employer integration ingest (builds on `DE-07`)
- [ ] 🔷 Community referrals feed by region (`DE-08`) — needs trust/moderation model
- [ ] 🔷 Cross-source dedupe index (multiple boards + employer feeds + community)

## Phase 5 — Employability engine (seeker-facing)

- [ ] 🔷 Pathways / next-gen job-title mapping
- [ ] 🔷 Personal upskilling loop UX
- [ ] 🔷 Seeker auth + profile

---

## Cross-cutting backlog (ongoing, pull in whenever relevant)

**Security & reliability (Sections 9–10 of PRD)**

- [ ] 🔶 Admin authentication + `AuditEvent` audit trail for admin actions
- [ ] 🔶 Rate limiting on public API endpoints
- [ ] 🔷 HTTPS in the deploy path
- [ ] 🔷 Metrics/alerting on scrape failure rate (beyond the live console log)
- [ ] 🔷 `SignalSnapshot` cache table so heavy aggregate queries stay fast as the catalogue grows past 111 searches

**Data model additions needed to unlock the above**

- [ ] `SkillTag` — unlocks Skills Radar
- [ ] `SignalSnapshot` — cached velocity / boom-recession features
- [ ] `Alert` — forecast / disruption / obsolescence events
- [ ] `AuditEvent` — admin-action security trail

---

## Done ledger (for quick reference — full detail lives in the PRD)

| Slice | PRD version |
|---|---|
| Brand shell + Tower Overview | v0.1 |
| Discovery harden (fast AI filter, dwell floor, retries) | v0.2 |
| Hiring Signals | v0.3 |
| Once-daily cadence + 111-search catalogue | v0.4 |
| Company Watchlist | v0.5 |
| Local git + source-safety rule | v0.6 |
| Thermal save (keyword+headless fallback) | v0.7 |
| Thermal-balanced Ollama + Tower Health | (post-v0.7, see PRD §"Phase 0 progress") |
| ThinkPad auto-deploy from GitHub `main` | (post-v0.7) |

---

*Keep this file and `documents/product-requirements-v0.md` §11 in sync. When a task is picked and finished: check it off here, bump the PRD's Document control table, and add one line under "Done ledger" above.*
