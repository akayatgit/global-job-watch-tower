# Global Job WATCH TOWER — Agile Roadmap

| Field | Value |
|---|---|
| **Method** | Serious agile: one **current sprint** in flight, one **next milestone** queued, backlog below |
| **Definition of Done** | Slice is complete for its scope (UX laws in `.cursor/rules/product-ux.mdc`), verified, committed locally |
| **Narrative PRD** | [`documents/product-requirements-v0.md`](./product-requirements-v0.md) |
| **Locked recover** | `milestone/jobmaster-gate3-v1` (accepted JobMaster baseline, 2026-08-04) · `milestone/eureka-telegram-bot` · `milestone/singularity-core-v1` · older `milestone/pre-neural-core-v0` |
| **Owner** | Akay — update this file in place after every accepted slice |
| **Status as of** | 2026-08-04 — **Gate 3.0 JobMaster capability #1 accepted and locked** |
| **Stage lock** | **Collects = base complete** → **Map with Students** → **Gate 3.0 JobMaster conversation OS** → **Predict for Government** |
| **Agent stack** | JobMaster Telegram gateway · constrained intent intelligence · Watch Tower capabilities · deterministic fact renderers |

---

## Delivery stage (Ashok 2026-08-03)

| Stage | Meaning | Status |
|---|---|---|
| **1. Collects** | Job Discovery Engine live: dual-track scrape, enrich, VIGIL + Neural Core, fresher lens | **Base set — enough to start delivery** |
| **2. Map with Students** | **TECH JOB MARKET MOVEMENT** — social carousels + a page students open; one question → facts → visualization; hope + daily knowing | **Current — delivery starts here** |
| **3. Predict for Government** | 6–12m city/sector/role forecasts + policy-ready economic signals | After the student movement has a real pulse |

Collector keeps running (overnight flywheel). New product work is **delivery**, not more collection chrome.

### Twist lock — Map with Students = Job Movement (Ashok 2026-08-03)

**Metaphor (Master):** Intermission → responsible Master → student movement.  
**JobMaster:** same beat — create a **Job Movement**, continuously feed students/employment seekers with **fact content**.

Students feel:

- Social **carousels** — one question → tower facts → fire visualization
- Page anytime: hope? · what should I know today? · understand the TECH job market
- Brand: **TECH JOB MARKET MOVEMENT** · JobMaster.agency · VIGIL · AI · Quanta HR

**Inspiration / associate path:** Honorable CM **C. Joseph Vijay** · **TVK** — broke the “only DMK/ADMK can rule TN” myth (2026 Assembly: TVK largest party, coalition, sworn CM May 2026). JobMaster follows that path of **proving change is possible**, delivering employment-intelligence content for Tamil Nadu seekers as a **govt associate** voice of hope + facts — not scrape jargon.

Tower = truth engine behind every slide.

### Two gates before full Intelligence → Carousel automation

| # | Feature | Status |
|---|---|---|
| 1 | **Carousel fire** — Grok Imagine graphic posters → **Telegram album** (no Pillow cards; DIRECTOR-authored style) | **Done** — evolving style under DIRECTOR v0.30 |
| 1.1 | **Eureka lock (Ashok 2026-08-04)** — Telegram AI bot live + multi-user access, purple orb v10, SOUL/WAKEUP (`.cursor/rules/akay-soul.mdc`), tower as plug-and-play Docker image (seed: `job_engine/Dockerfile` + compose — keep boot-ready) | **Locked** — docker hardening queued (kanban #4) |
| 2 | **Trendjack** — search Tamil Nadu / TECH employment trends (SerpApi Google Trends free tier first; buy SearchAPI if needed) → hook carousels to what’s rising | Queued after #1 |

Then: Intelligence Automation = Job Market Analysis → Carousel that reaches employment seekers at scale.

---

## How we run

1. **One sprint goal** at a time — finish it fully before starting the next milestone’s big item.
2. Ashok answers YES/NO on scope; Akay builds end-to-end.
3. Commit locally as slices land; **push only with Ashok double-YES** (prefer end-of-day).
4. Before any push/deploy: name which live search(es) will be disturbed.
5. Check boxes here when done; never fork “roadmap-v2”.

---

## ✅ Locked — Gate 3.0 JobMaster capability #1

**Goal:** one focused information agent for every user. Natural language in;
verified jobs and grounded market facts out. No Hermes Telegram fallback.

| Slice | Status |
|---|---|
| RCA: built-in Hermes handled Supriya's message after plugin interception disappeared | **Confirmed** |
| Dedicated Telegram ingress; exactly one poller; Hermes gateway off | **Accepted live** |
| Messy-language intent → validated city/role/experience/insight request | **Accepted live** |
| 10 canonical LinkedIn rows + `more` + clean `/new` | **Accepted live** |
| Grounded counts, top companies/roles, city comparisons | **Accepted live** |
| Mock contract suite + live Supriya acceptance | **Locked at `2fda2d7`** |

**Owner-command fast follow:** restore deterministic VIGIL slash commands after
the Hermes cutover, scope the Telegram menu to Ashok's home chat, and keep all
customer chats on the clean JobMaster interface. Code and contract tests are
green; live acceptance remains open on kanban card #6.

Gate 3.0 expands later through the same capability boundary: subscriptions,
ATS resume fixing, interview preparation, PDF guides, projects, quizzes,
flashcards, relevant tech news, tutorials, and LMS progress. Entitlements are
backend-enforced; the conversational model never grants access by prompt.

---

## Queued — Gate 2 TN trendjack

**Goal:** Rising Tamil Nadu / TECH topics × tower facts → `/carousel` briefs on Telegram.

| Slice | Status |
|---|---|
| Replicate + Telegram album (`/carousel`) | **Done** |
| First fiery TECH hope carousel from live tower numbers | **Done** (smoke 2026-08-03) |
| Trends client: SerpApi `google_trends` geo≈IN-TN (or IN + TN filter) + daily rising queries | **Next** |
| Trendjack rule: rising TN/tech topic × tower fact → carousel brief | Queued |
| Full auto loop (trend → analysis → Replicate → Telegram) | After Gate 2 green |

---

## ✅ Closed — Collect / Tracks / World-model base

| ID | Slice | Status |
|---|---|---|
| WM-G1–G5 | Graph local-focus, spin freeze, clickable cards | Done |
| WM-C1–C7 | Night City districts + polish | Done |
| Collect | Dual-track fresher + signal, enrich, experience chips, remote tunnel | Done (base) |

---

## Later backlog (pull when sprint/milestone clear)

### Still Tracks polish (secondary while Students Map ships)
- [ ] 🔶 Competitor Intelligence (`EC-06`)
- [ ] 🔶 Domestic / Global scope (`DE-09`)
- [ ] 🔶 Employer direct onboard (`DE-07`)

### Phase 2 — Maps (Students-first)
- [ ] ⭐ Graduate Demand Map (`SM-1`) — **current**
- [ ] 🔶 Skills Radar (`EI-05`) — feed Students Map
- [ ] 🔶 Industry Pulse (`EI-04`)
- [ ] 🔶 Talent Flow (`EI-02`)

### Phase 3 — Predicts for Government
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
- [x] **Collects base complete** — delivery stage opened 2026-08-03
- [x] **Eureka — Job Telegram AI Bot** (2026-08-04, locked tag
      `milestone/eureka-telegram-bot`) — COURIER→DIRECTOR→STAGEHAND/LENS/
      CAROUSEL live on `@vigil_akay_bot`; text-first Jarvis + slash boards +
      daily brief. See `documents/milestone-eureka-telegram-bot.md`.

---

## Cadence reminder

First-mover: keep the tower collecting. UI sprints must not thrash deploys into cancel storms.
