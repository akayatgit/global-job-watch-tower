# Global Job WATCH TOWER — Product Requirements Document (v0)

| Field | Value |
|---|---|
| **Product** | Global Job WATCH TOWER |
| **Tagline** | AI Job Intelligence & Employability Engine |
| **Powered by** | Quanta HR Labs |
| **Document** | Product Requirements — Draft v0 |
| **Status** | First draft from Pitch Deck (investor-accepted vision) |
| **Stakeholders** | Ashok (Vision Owner / Yes–No Authority) · Akay (AI Lead — full build agency) |
| **North star** | Make the investor-accepted pitch come true — scalable, reliable, secure |
| **Source safety (absolute)** | **First priority above all features:** local git must keep Watch Tower source recoverable; never risk corruption/deletion of Ashok’s vision codebase |
| **First-mover mandate** | **Highest product priority:** start and sustain tower searches so Quanta is among the first to collect fresh job-market insights — coverage before polish |
| **Runtime home (where Akay / the tower are alive)** | **Lenovo ThinkPad P16 Gen 1 · hostname `user-ThinkPad-P16-Gen-1` · Ubuntu 24.04 LTS · local-only** — all services run on this laptop (`job_engine` on `127.0.0.1:8001`, Postgres `:5433`, Redis `:6379`, Celery worker+beat, Ollama). Not cloud. |
| **Lid / sleep policy** | **Configured 2026-08-01 for overnight collect:** GNOME lid-close + idle sleep = `nothing`; systemd-logind `HandleLidSwitch=ignore` via `/etc/systemd/logind.conf.d/99-watch-tower-lid.conf`. Lid close should **not** suspend. Keep on charger; allow airflow (laptop may run warm with lid closed). |
| **Source of truth** | Pitch deck slides + this document (iterate in place; do not fork near-duplicates) |
| **Existing seed** | `job_engine/` LinkedIn scrape + admin pilot (foundation for Discovery / Tracks) |

---

## 0A. Source safety (absolute — before features)

Ashok’s vision lives in this codebase. **Akay’s first duty is to keep source recoverable.**

| Rule | Practice |
|---|---|
| Local git | Repo root: `/home/user/Documents` |
| Never commit | `.env`, passwords, `job_engine/.data/`, browser profiles |
| Do commit | `job_engine/app`, migrations, templates, `documents/`, shared Cursor rules, `.env.example` |
| Standing rule | `.cursor/rules/source-safety.mdc` (always apply) |
| Failure mode | If source is lost/corrupted, stop feature work and restore from git first |

---

## 0. Mother Promise (binding operating contract)

As the AI assistant leading this project (**Akay**), this document records a **mother promise** to Ashok and to the investor vision:

1. **Maximum effort maker** — Do the heavy lifting. Research, design, build, test, document, and course-correct without waiting to be micromanaged.
2. **Yes / No interface** — Come to Ashok primarily for decisions, ideas, and approvals. Present clear options. Make him feel like saying **yes** or **no**, not writing specs or debugging alone.
3. **Roadmap always alive** — Continuously maintain and follow a roadmap that maps to the pitch vision (Tracks → Maps → Predicts; Employment Intelligence modules; Economical Insights; Job Discovery Engine).
4. **Full agency granted** — Ashok has given lead control to Akay. Stay hard, curious, smart, futuristic, insightful. Connect dots by pattern recognition. Own outcomes.
5. **Never leave Ashok unattended** — Every conversation **must** end with a clear, forward-working question that advances the next slice. If questions stop, thinking stalls and delivery delays. This is critical and non-negotiable.
6. **Success standard** — Build as if the investor is watching: enterprise-grade **scalability**, **reliability**, and **security** — not demos that die after the pitch.

This promise is restated in `.cursor/rules/akay-lead.mdc` and in the copy-ready Lead Prompt (Section 14).

---

## 1. Vision & mission

### 1.1 Vision

A live, global **job-market intelligence tower** that turns the world’s hiring signals into decisions: who is hiring, where talent moves, which skills rise or die, and what the next 6–12 months look like — for employers, policymakers, investors, educators, and job seekers.

### 1.2 Mission

Continuously **Track → Map → Predict** from massive labor-market datapoints (pitch claim: built from over **1.3 billion LinkedIn datapoints**, plus job boards, employer feeds, and community referrals), delivered as a product people love to open every day.

### 1.3 Pitch one-liner

> Intelligent Insights **Live** from the Job Market — Domestic & Global, 24×7.

### 1.4 Success for the investor

| Signal | Meaning |
|---|---|
| Live data flywheel | Fresh jobs and signals flowing without heroics |
| **First to the signal** | Broad daily coverage of major roles/skills before competitors narrate the market |
| Insight > tables | Dashboards answer what happened, what’s interesting, what to do next |
| Forecast credibility | 6–12 month views with clear assumptions and refresh cadence |
| Trust | Secure handling of sessions, PII, and employer data |
| Scale path | Architecture that grows from pilot scrape → multi-source engine → intelligence layers |

---

## 2. Brand identity (from pitch — non-negotiable aesthetic)

The pitch is the brand bible. UI and marketing surfaces must feel like the deck: clean tech, authoritative, futuristic — never generic “AI purple sludge” or cream/terracotta brochure kitsch.

### 2.1 Product naming

| Element | Spec |
|---|---|
| Product name | **Global Job WATCH TOWER** (“WATCH TOWER” heavy / authoritative) |
| Supporting line | AI Job Intelligence & Employability Engine |
| Lab / parent | Quanta HR Labs |
| Logo mark | Lime-green square with stylized black **Q** (Quanta) |
| Voice | Confident, clear, human. No jargon in the UI (see product-ux rule). |

### 2.2 Color system (CSS tokens — target)

```css
:root {
  /* Core */
  --qt-ink: #0B1220;                 /* primary text */
  --qt-muted: #5B6472;               /* secondary text */
  --qt-paper: #F7F9FC;               /* soft off-white canvas */
  --qt-paper-2: #EEF2FB;             /* lavender-white gradient stop */

  /* Brand blues (LinkedIn-adjacent authority) */
  --qt-blue-deep: #0A66C2;           /* deep LinkedIn-like blue shapes */
  --qt-blue-royal: #2563EB;          /* royal / sky accents */
  --qt-blue-soft: #93C5FD;           /* soft sky */

  /* Periwinkle / lavender process UI */
  --qt-periwinkle: #A8B4F0;          /* Tracks / Maps boxes */
  --qt-lavender: #C4B5FD;            /* soft cards / purple module headers */

  /* Accents from deck */
  --qt-live-pink: #E11D8F;           /* “Live” emphasis, Future Forecast labels */
  --qt-coral: #F07167;               /* “How” / energy accents */
  --qt-lime: #C8F135;                /* Quanta Q, Domestic & Global pill, Discovery Engine bar */
  --qt-teal: #2DD4BF;                /* Community / tertiary module */
  --qt-violet: #7C3AED;              /* Industry Pulse, Skills Radar headers */
  --qt-yellow: #FACC15;              /* chart series accent */

  /* Surfaces */
  --qt-glass: rgba(255, 255, 255, 0.55);
  --qt-glass-border: rgba(255, 255, 255, 0.65);
  --qt-shadow: 0 18px 50px rgba(15, 23, 42, 0.12);
}
```

### 2.3 Visual language

| Trait | Spec |
|---|---|
| Backgrounds | Soft lavender → white / light-blue gradients; large organic blue curves (not flat slabs) |
| Shapes | Rounded rectangles, pill tags, sweeping diagonal blue panels |
| Glass | Semi-transparent capsules over blue (economical insights dock) |
| Depth | Floating translucent metric cards (Jobs, Upskilling, Demand Forecast, Job Seekers) — cards only when they hold interaction or a metric the user acts on |
| Motion | 2–3 intentional motions: soft entrance of cards, live pulse on “Live”, gentle flywheel arrow loop |
| Imagery metaphors | Intelligence orb / sparkles; translucent AI head + neural overlay (marketing); city skyline for economic scale — product app stays clean, data-first |
| Typography | Modern geometric sans (e.g. **Plus Jakarta Sans** / **Manrope** / **Montserrat** family). Avoid Inter/Roboto/Arial as brand fonts. Heavy caps for WATCH TOWER; medium for “Global Job”; lighter gray for subtitle |
| Density | Generous whitespace on marketing; dense-but-breathable on ops dashboards |

### 2.4 Signature UI patterns from slides

1. **Lime pill** — “Domestic & Global 24×7”
2. **Live** word in magenta/pink inside black headline
3. **Triangular flywheel** — Tracks → Maps → Predicts with clockwise arrows
4. **Metric pods** — Jobs (2M), Upskilling (55%), Demand Forecast (72% + Domestic toggle), Job Seekers (250K)
5. **Eight insight capsules** — Company Watchlist … Disruption Alert
6. **Five intelligence cards** — Future Forecast, Talent Flow, Hiring Signals, Industry Pulse, Skills Radar
7. **Three intake pipes → lime Discovery Engine bar**

### 2.5 UX laws (product, not pitch art)

Align with standing workspace UX rule:

- Human language only in UI
- Live filters (~400ms debounce), no Apply button
- Chips over raw pickers; relative time + hover exact
- Lists: sort, counts, newest-first, empty guidance
- Dashboards = insight first
- Destructive actions confirmed; search definitions protected
- Scraper behavior stays human-like (dwell, mouse, popup dismiss)

---

## 3. Problem & opportunity

| Pain | Opportunity |
|---|---|
| Job data is fragmented across boards, employers, and word-of-mouth | One **Job Discovery Engine** unifies scrape + employer + community |
| Reports are stale; markets move weekly | **Live** tracking and streaming ops views |
| Leaders see openings, not direction | **Maps** talent/skills + **Predicts** 6–12 months |
| Investors and strategy teams lack labor-leading indicators | **Economical Insights** from hiring velocity and sector shifts |
| Seekers and L&D lack skill foresight | **Skills Radar** + upskilling metrics |

---

## 4. Users & jobs-to-be-done

| Persona | Primary job | Core modules |
|---|---|---|
| **Tower Admin (Ashok)** | Run searches, trust the scrape, see freshest catches | Discovery ops, Hiring Signals, console |
| **Strategy / Investor** | Spot boom/recession, capital direction | Economical Insights 01–08 |
| **Employer / TA** | Competitor hiring, partnership targets, velocity | Company Watchlist, Hiring Signals |
| **Policy / City / Sector lead** | Where talent moves; city/sector outlook | Talent Flow, Future Forecast |
| **L&D / University** | Emerging vs declining skills | Skills Radar, Upskilling |
| **Job seeker (later)** | Next-gen titles, employability path | Employability engine (phase later) |

v0 build priority: **Admin + Intelligence for decision-makers**. Seeker-facing employability can follow once the flywheel is real.

---

## 5. Product architecture (conceptual)

```
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Global & Local  │  │ Employer         │  │ Community        │
│ Job Boards      │  │ Integration      │  │ Referrals        │
│ (LinkedIn…)     │  │ (direct onboard) │  │ (regional feed)  │
└────────┬────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                    │                     │
         └────────────────────┼─────────────────────┘
                              ▼
                 ┌─────────────────────────┐
                 │   JOB DISCOVERY ENGINE  │  ← lime nexus
                 │  normalize · dedupe ·   │
                 │  enrich · index · serve │
                 └────────────┬────────────┘
                              ▼
         ┌────────────────────────────────────────────┐
         │         INTELLIGENCE FLYWHEEL              │
         │  TRACKS  →  MAPS  →  PREDICTS  → (loop)    │
         └────────────────────────────────────────────┘
                              ▼
         ┌──────────────┐  ┌─────────────────────────┐
         │ Employment   │  │ Economical Insights     │
         │ Intelligence │  │ (8 decision capsules)   │
         └──────────────┘  └─────────────────────────┘
```

### 5.1 Non-functional pillars (investor grade)

| Pillar | Requirement |
|---|---|
| **Scalable** | Queue-based ingestion; horizontal workers; DB indexes for time/geo/role; store raw + normalized; feature flags for new sources |
| **Reliable** | Idempotent jobs; retries with backoff; dead-letter visibility; health endpoints; structured logs; scrape dwell/humanization to reduce bans |
| **Secure** | Secrets in env/vault never in git; least-privilege DB roles; session isolation for browser profiles; audit log for admin actions; no leaking cookies/PII in UI logs; HTTPS in deploy; rate limits on public APIs |

---

## 6. Functional requirements by pitch module

### 6.1 Job Discovery Engine (“How we do it”)

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| DE-01 | Scrape major boards starting with LinkedIn | P0 | Exists in seed `job_engine` — harden & productize |
| DE-02 | Normalize job records (title, company, location, posted, URL, skills) | P0 | |
| DE-03 | Dedupe across runs and sources | P0 | |
| DE-04 | Human-like scrape behavior (dwell 75–105s, mouse/scroll, dismiss popups) | P0 | Standing preference |
| DE-05 | Ops console: live activity, logs, copy errors | P0 | |
| DE-06 | Search definitions (roles/locations/frequency) as first-class safe entities | P0 | UI: “searches/roles”, not “configs” |
| DE-07 | Employer direct onboard / feed ingest | P1 | API + admin ingest |
| DE-08 | Community referrals feed by region | P2 | Trust & moderation model |
| DE-09 | Multi-region / Domestic ↔ Global toggle | P1 | Matches Demand Forecast “Domestic” CTA |

### 6.2 Flywheel — Tracks / Maps / Predicts

| ID | Stage | Requirement | Priority |
|---|---|---|---|
| FW-01 | **Tracks** | Show how companies hire, grow, shift industries in near-real time | P0 |
| FW-02 | **Maps** | Where talent moves; rising skills; remaining gaps | P1 |
| FW-03 | **Predicts** | Cities, sectors, roles defining next 6–12 months | P1–P2 |
| FW-04 | Loop UX | Visual continuous cycle; data refresh makes the loop feel alive | P1 |

### 6.3 Employment Intelligence & Monitoring (5 pillars)

| ID | Module | Capabilities | Priority |
|---|---|---|---|
| EI-01 | **Future Forecast** | 6–12 month predictions; role obsolescence alerts; next-gen job titles; alert affordance | P1 |
| EI-02 | **Talent Flow** | Migration patterns; inbound/outbound; cross-border | P1 |
| EI-03 | **Hiring Signals** | Openings trend; fastest-growing roles; company hiring velocity | P0 |
| EI-04 | **Industry Pulse** | Sector growth rank; automation impact; new job categories | P1 |
| EI-05 | **Skills Radar** | Emerging / declining skills; skill-gap mapping | P1 |

### 6.4 Economical Insights (8 capsules)

| ID | Capsule | Intent | Priority |
|---|---|---|---|
| EC-01 | Company Watchlist | Monitor named organizations | P0 |
| EC-02 | Recession Signals | Labor-leading downturn indicators | P2 |
| EC-03 | Boom Signals | Rapid growth sectors/regions | P1 |
| EC-04 | Investment Direction | Where capital/attention should go | P2 |
| EC-05 | Industry Transformation | Sector evolution narratives | P1 |
| EC-06 | Competitor Intelligence | Rival hiring strategies | P0 |
| EC-07 | Partnership Targets | Collaboration candidates | P2 |
| EC-08 | Disruption Alert | Major shift / black-swan style alerts | P2 |

### 6.5 Watch Tower hero metrics (north-star KPIs)

| Metric | Pitch example | Product meaning |
|---|---|---|
| Jobs | 2M | Indexed / tracked openings (scoped to active sources) |
| Upskilling | 55% MoM | Share of roles demanding rising skills / L&D signal |
| Demand Forecast | 72% + Domestic/Global | Confidence or demand index for selected scope |
| Job Seekers | 250K | Later: seeker graph or proxy from applications/profiles |

v0 may show **pilot-true** numbers (what we actually have) with honest labels — never fake pitch numbers in the live product.

---

## 7. Information architecture (target app)

```
WATCH TOWER
├── Home / Tower Overview          ← insight dashboard (KPIs + freshest + deltas)
├── Discovery
│   ├── Searches (roles)           ← definitions, schedules in human words
│   ├── Activity                   ← live console / runs
│   └── Jobs                       ← table DoD: sort, counts, newest first
├── Intelligence
│   ├── Hiring Signals
│   ├── Skills Radar
│   ├── Industry Pulse
│   ├── Talent Flow
│   └── Future Forecast
├── Economical Insights
│   └── 8 capsules (progressive)
├── Watchlists
│   └── Companies
└── Settings                       ← security, regions, Domestic/Global defaults
```

Seed today: dashboard, jobs, searches, activity/console under `job_engine/app/admin`.

---

## 8. Data model (v0 logical)

Core entities (names for engineering; UI stays human):

| Entity | Purpose |
|---|---|
| `SearchDefinition` | Role + geo + cadence + status |
| `IngestionRun` | One scrape/ingest attempt + health |
| `JobPosting` | Normalized job + source + first/last seen |
| `Company` | Employer identity + watchlist flag |
| `SkillTag` | Extracted / mapped skills |
| `SignalSnapshot` | Aggregates for velocity, boom/recession features |
| `Alert` | Forecast / disruption / obsolescence events |
| `ConsoleLog` | Operator-facing events (exists in seed) |
| `AuditEvent` | Security trail for admin actions |

Principles: append-friendly facts; derived intelligence tables; never destroy search definitions on cleanup.

---

## 9. Security, privacy, compliance (v0 bar)

1. Credentials and browser session dirs outside git; `.env` gitignored
2. Separate Chrome profile for automation (already pattern in seed)
3. Admin auth before any public exposure (add before internet deploy)
4. Redact secrets from logs and copy-to-clipboard helpers
5. Rate-limit APIs; validate all inputs
6. Backup Postgres; retention policy for raw HTML if stored
7. Legal posture: scraping ethics, ToS awareness, prefer official APIs/employer feeds as scale grows
8. Multi-tenant later: hard data isolation from day-one schema thinking

---

## 10. Reliability & scale (v0 → v1)

| Layer | v0 (now) | v1 (scale) |
|---|---|---|
| Ingest | Celery + Redis + stealth fetch | Multi-worker pools, per-source queues |
| Store | Postgres | Partition by time; read replicas if needed |
| Serve | FastAPI + admin templates | API for intelligence clients; caching |
| Observe | File logs + live console | Metrics, alerts on scrape failure rate |
| Predict | Heuristics + Ollama-assisted enrichment | Model registry, backtests, versioned forecasts |

---

## 11. Roadmap (living — Akay maintains)

### Phase 0 — Foundation truth (current seed)

- Harden LinkedIn discovery pipeline
- Admin UX matches product-ux Definition of Done
- Brand tokens applied to admin shell
- Honest Tower Overview with real pilot metrics

### Phase 1 — Tracks (P0 intelligence)

- Hiring Signals: openings trend, growing roles, company velocity
- Company Watchlist + Competitor Intelligence (basic)
- Domestic / Global scope switch (even if global is subset)

### Phase 2 — Maps

- Skills Radar (emerging / declining / gaps)
- Industry Pulse
- Talent Flow (geo proxies from job locations + later richer data)

### Phase 3 — Predicts + Economic layer

- Future Forecast (6–12m) with alert UX
- Boom / Recession / Disruption signals (transparent methodology)
- Investment Direction & Partnership Targets (decision views)

### Phase 4 — Multi-source Discovery Engine

- Employer integration
- Community referrals
- Deduped multi-source index

### Phase 5 — Employability engine (seeker)

- Pathways, next-gen titles, personal upskilling loops

**Rule:** Ship complete slices. No half-tables. Update this roadmap after every accepted milestone.

---

## 12. Definition of Done (every slice)

A slice is done only when:

1. Matches pitch intent for that module (language humans understand)
2. Meets UX DoD (sort, counts, live filters, empty states, relative time)
3. Secure defaults respected (no secrets leaked)
4. Observable (logs/console; failure is visible)
5. Documented here if behavior/brand preference changed
6. Ashok can say yes/no on a short demo prompt from Akay

---

## 13. Out of scope for v0 (explicit)

- Fake 1.3B / 2M metrics in production UI
- Full seeker social network
- Guaranteed recession prediction accuracy claims without methodology
- Public unauthenticated internet deploy
- Building near-duplicate PRDs in repo root

---

## 14. Copy-ready Lead Prompt (paste into Cursor User Rules / main instruction)

```text
You are Akay — AI Lead for Global Job WATCH TOWER (Quanta HR Labs): the AI Job Intelligence & Employability Engine. Ashok is the vision owner; he grants you full build agency. Your job is to make the investor-accepted pitch come true.

MOTHER PROMISE
- You are the maximum-effort maker. Do the heavy lifting: research, architecture, implementation, QA, docs, and course-correction.
- Come to Ashok mainly for ideas and decisions. Offer clear options so he mostly answers YES or NO.
- Continuously create and follow a living roadmap aligned to the pitch: Job Discovery Engine → Tracks → Maps → Predicts → Employment Intelligence → Economical Insights.
- Stay hard, curious, smart, futuristic, insightful. Connect dots by pattern recognition. Own outcomes.
- CRITICAL LOOP: Every reply MUST end with one concrete forward-working question that advances the next slice. Never leave Ashok unattended. If you stop asking, work stalls — this is non-negotiable.
- Build for scale, reliability, and security — not pitch theater.

SOURCE OF TRUTH
- Product Requirements: documents/product-requirements-v0.md (update in place; never fork duplicates in repo root).
- UX / product laws: .cursor/rules/product-ux.mdc
- Brand, modules, colors, and flywheel are defined in the PRD from the pitch deck. Follow them.
- Existing seed codebase: job_engine/ (LinkedIn discovery pilot). Evolve it toward Watch Tower; do not abandon it for rewrites without a YES from Ashok.

HOW YOU LEAD
- Propose the next highest-value complete slice; implement after YES (or when Ashok has already given standing agency for the slice).
- Prefer working software over slides. Prefer insight dashboards over raw dumps.
- Never ship half features. Lists/tables must meet Definition of Done.
- Append new standing preferences Ashok states into product-ux.mdc immediately.
- When tradeoffs appear (speed vs security vs scope), recommend one path with rationale, then ask YES/NO.

START OF EVERY SESSION
1) Orient to the PRD roadmap and current codebase state.
2) State what you will advance this session.
3) Do the work / present the decision.
4) End with the next forward-working question.
```

---

## 15. Document control

| Version | Date | Author | Notes |
|---|---|---|---|
| v0 | 2026-07-31 | Akay (from Ashok pitch handoff) | First complete draft from 5 pitch slides + mother promise + lead prompt |
| v0.1 | 2026-07-31 | Akay | Phase 0 started: Watch Tower brand shell + Tower Overview on `job_engine` admin |
| v0.2 | 2026-07-31 | Akay | Discovery harden: fast AI filter, session locks, dwell floor, fetch/Celery retries, stale reap |
| v0.3 | 2026-07-31 | Akay | Hiring Signals page + Tower teaser (trend, roles, company velocity) |
| v0.4 | 2026-08-01 | Akay | Once-daily cadence + 111 India searches seeded; first-mover mandate; enqueue throttle |
| v0.5 | 2026-08-01 | Akay | Company Watchlist (star/unstar, velocity, Tower teaser); starter pin of top hirers |
| v0.6 | 2026-08-01 | Akay | Local git repo + source-safety rule; absolute priority to protect codebase |

### Phase 0 progress (living)

| Slice | Status |
|---|---|
| Brand tokens + Quanta Q + Live naming on admin shell | Done |
| Nav: Tower · Searches · Activity · Jobs · Live feed | Done |
| Tower Overview pods (honest pilot metrics) + Tracks flywheel cue | Done |
| Harden discovery pipeline / scrape reliability | Done (v0.2) |
| Hiring Signals (Phase 1) | Done (v0.3) |
| Once-daily cadence + ~100 fresher/major role catalogue | Done (v0.4) |
| Company Watchlist (EC-01) | Done (v0.5) |

### Cadence policy (v0.4) — how often to run

**Decision: once per day per search** (staggered), with LinkedIn **past 24 hours** filter (`f_TPR=r86400`).

| Question | Answer |
|---|---|
| Will we miss data vs hourly? | **Almost none of what we care about for market intelligence.** Each run already only asks LinkedIn for the last 24h. A successful daily pass covers that window. Hourly re-scrapes mostly re-saw the same cards (deduped by job id). |
| What *can* we miss? | Ultra-short posts that appear and vanish between daily runs (~small %; studies show ~10% of LinkedIn posts gone within 0–1 day in some markets). A **failed** daily run misses that role’s whole day until retry/next slot. |
| Why not hourly with 100 roles? | Human dwell ~75–105s/page × 100 roles cannot fit; burns session risk; blocks first-mover scale. |
| Resilience | Beat dispatches **one** scheduled scrape at a time; fetch retries; stale-run reap; failed days show on Activity. Optional later: 2×/day only for top priority roles. |

**Operating rules**

- Default schedule in UI: **Every day (recommended)**
- Searches staggered ~14 minutes apart from ~05:00 IST across 24h so one worker stays human-paced
- Catalogue: `app/seed_roles.py` + `scripts/seed_fresher_searches.py` (idempotent)
- India geo for v0 catalogue; Domestic/Global expansion later
- **First-mover mandate:** expanding and running the catalogue outranks secondary UI features until the daily flywheel is green

#### Catalogue (v0.4)

- **111 enabled searches** (2 pilot + 109 fresher/major roles & skill labels)
- Covers AI/GenAI/ML, data, software, QA/DevOps/cloud, cyber, product/UX, IT support, business/finance fresher funnels, campus/intern
- Pilot roles: 10 pages; bulk roles: 5 pages (past-24h usually fits)

#### Hiring Signals (v0.3)

- New **Hiring signals** page (`/signals`) + Tower teaser
- Openings trend sparkline, rising/cooling roles, company hiring velocity
- Live period chips: Last 7 / 14 / 30 days vs prior equal window
- Sortable tables (click headers), counts, empty guidance, “what to do next”
- Honest headline from real pilot data (no fake pitch metrics)

#### Discovery harden notes (v0.2)

- AI title filter defaults to **fast JSON** (`OLLAMA_THINK=false`) + 90s timeout — thinking mode was stalling runs for ~1h/page
- Session sync clears Chrome Singleton locks; fails loud if cookies missing
- Per-page dwell floor enforced at ≥75s; mouse never fully idle; deeper lazy-load scroll; more popup dismissors
- Between-page delay raised to 8–22s; fetch retries on transient/5xx
- Celery retries transient fetch errors; beat reaps stale running runs (>180 min)
- Worker/beat restarted to load new code

#### Company Watchlist (v0.5)

- `/watchlist` — watched orgs with hiring pace vs prior window
- Live period chips + live name filter; searchable directory to Watch / Watching
- Star from Hiring signals table too; Tower shows pinned chips
- Empty watchlist auto-pins top 10 velocity companies (safe starter; unstar anytime)
- Searches form default cadence: **Every day (recommended)**

**While Ashok sleeps:** leave worker/beat collecting the 111-role first pass (one at a time).  
**Standing YES (2026-08-01):** commit after every finished slice; keep collector running overnight unless Ashok says stop.  
**Hardware note:** Tower is alive on this ThinkPad while awake. Lid-close/idle suspend disabled for overnight collection (2026-08-01). Prefer AC power + ventilation.  

**Incident 2026-08-01 ~01:01:** Host **rebooted uncleanly** (`last` shows `crash`; uptime reset). All tower processes died mid-scrape (Junior Data Scientist). Restored via Postgres/Redis/API/worker/beat; reaped stuck run; collector resumed (GenAI Engineer). GNOME lid settings had reverted to `suspend` after reboot — re-applied `nothing`. systemd logind ignore drop-in survived. **Lesson:** lid-ignore ≠ crash-proof; after any reboot Akay must restore the tower first; verify gsettings still `nothing` before sleep.

**Next waking slice:** Skills Radar (EI-05) or Competitor Intelligence depth on watchlist — recommend Skills Radar.

---

*End of PRD v0 — Global Job WATCH TOWER · Quanta HR Labs*
