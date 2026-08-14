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
| **First-mover mandate** | Collector stays live (coverage never stops). **From 2026-08-03 delivery stage:** product priority shifts to **Map with Students**, then **Predict for Government** — collect base is set enough to start |
| **Delivery stage lock (2026-08-03)** | **Collects → Map Students → Predict Government.** Agile detail: [`documents/roadmap.md`](roadmap.md) |
| **Runtime home (where Akay / the tower are alive)** | **Lenovo ThinkPad P16 Gen 1 · hostname `user-ThinkPad-P16-Gen-1` · Ubuntu 24.04 LTS · local-only** — all services run on this laptop (`job_engine` on `127.0.0.1:8001`, Postgres `:5433`, Redis `:6379`, Celery worker+beat, Ollama). Not cloud. |
| **Remote browser access (2026-08-03)** | **Tunnel LIVE:** `https://tower.jobmaster.agency` → ThinkPad `127.0.0.1:8001` (`watch-tower` / `watch-tower-tunnel`). **Access:** intended allow `ashokofficial55@gmail.com` — confirm OTP gate in Incognito before sharing URL (see [`documents/remote-access-cloudflare.md`](remote-access-cloudflare.md)). Not Vercel / not Supabase. |
| **Remote source + auto-deploy** | **Public GitHub:** [akayatgit/global-job-watch-tower](https://github.com/akayatgit/global-job-watch-tower). Merge/push to `main` triggers a **self-hosted Actions runner on this ThinkPad** → `scripts/deploy_local.sh` (**deploy wins**: pause beat → cancel active searches → pull → migrate → restart → retrigger cancelled roles; LinkedIn job ids prevent duplicates). Secrets (`.env`, `.data`, Chrome profiles) never leave the laptop. |
| **Lid / sleep policy** | **Configured 2026-08-01 for overnight collect:** GNOME lid-close + idle sleep = `nothing`; systemd-logind `HandleLidSwitch=ignore` via `/etc/systemd/logind.conf.d/99-watch-tower-lid.conf`. Lid close should **not** suspend. Keep on charger; allow airflow (laptop may run warm with lid closed). |
| **Source of truth** | Pitch deck slides + this document (iterate in place; do not fork near-duplicates) |
| **Existing seed** | `job_engine/` LinkedIn scrape + admin pilot (foundation for Discovery / Tracks) |

---

## 0A. Source safety (absolute — before features)

Ashok’s vision lives in this codebase. **Akay’s first duty is to keep source recoverable.**

| Rule | Practice |
|---|---|
| Local git | Repo root: `/home/user/Documents` |
| Remote git | Public: `https://github.com/akayatgit/global-job-watch-tower` (`origin` → `main`) |
| Never commit | `.env`, passwords, `job_engine/.data/`, browser profiles |
| Do commit | `job_engine/app`, migrations, templates, `documents/`, shared Cursor rules, `.env.example` |
| Standing rule | `.cursor/rules/source-safety.mdc` (always apply) |
| Failure mode | If source is lost/corrupted, stop feature work and restore from git first |

### 0A.1 Remote develop → ThinkPad deploy (2026-08-01)

Ashok can build from phone or any device: open a PR → merge to `main` → this laptop redeploys.

| Piece | Detail |
|---|---|
| Trigger | GitHub Actions on **push to `main` only** (never on open PRs/forks — public-repo safety) |
| Runner | Self-hosted under `/home/user/actions-runner`, labels `self-hosted,linux,watch-tower`, systemd service |
| Deploy script | [`scripts/deploy_local.sh`](../scripts/deploy_local.sh) — flock, **pause beat → cancel all active searches (queued/dispatched/running) → stop worker →** `git reset --hard origin/main` → `alembic upgrade head` → [`job_engine/restart_app.sh`](../job_engine/restart_app.sh) → **retrigger cancelled roles** as one-off runs. systemd --user units `watch-tower-{api,worker,beat}` (survives Actions cgroup teardown; linger enabled) |
| Deploy priority | **Deploy outranks in-flight searches** (2026-08-01). Do not wait for scrape idle. Compromising a few searches is OK — LinkedIn job ids dedupe on retrigger. |
| Survives deploy | Postgres/Redis data, `.env`, Chrome LinkedIn session, Ollama |
| Restarts | API `:8001`, Celery worker, Celery beat |
| Stamp / logs | `job_engine/.data/last_deploy.json`, `job_engine/.data/logs/deploy.log` |
| Branch protection | **Enabled 2026-08-01:** `main` requires a pull request before merge; force-push and branch delete blocked. Admin bypass left on so this ThinkPad can still push hotfixes when needed. |

**Mobile path:** GitHub app → branch → PR → merge → watch Actions on the ThinkPad runner → tower comes back on new SHA.

### 0A.3 Remote browser access — Cloudflare Tunnel + Access (2026-08-03)

Sole-user HTTPS from any machine without moving the brain off the ThinkPad.

| Piece | Detail |
|---|---|
| Choice | **Option B** (not Vercel, not Supabase mirror, not Tailscale-first) |
| Public URL | **https://tower.jobmaster.agency** |
| Origin | Still `http://127.0.0.1:8001` — loopback only |
| Tunnel | `watch-tower` (`5fe32c62-…`) · systemd --user `watch-tower-tunnel` |
| Access | Allow email `ashokofficial55@gmail.com` — **verify Incognito OTP** before sharing |
| Setup | `HOSTNAME=… ACCESS_EMAIL=… bash scripts/cloudflare_tunnel_setup.sh` |
| Ops doc | [`documents/remote-access-cloudflare.md`](remote-access-cloudflare.md) |

---

### 0A.2 Test deployment (verify before merge)

A test deployment lets Ashok (or Akay) prove a feature branch works end-to-end on the ThinkPad **before** the PR is merged to `main`.  
It is manual, non-destructive, and fully reversible.

#### When to run a test deployment

| Situation | Do it? |
|---|---|
| New scraper change, new migration, or restart-app edits | **Yes — always** |
| Pure UI/template change (no migrations, no worker code) | Recommended |
| Docs-only or rule-file-only change | Optional (skip if confident) |
| Hotfix that must be live immediately | Skip and merge direct with admin bypass |

#### How to do it (on the ThinkPad)

```bash
# 1. Fetch the PR branch (replace `feature/my-branch` with the actual branch)
cd /home/user/Documents
git fetch origin feature/my-branch

# 2. Stash any local tweaks (should be clean on the tower)
git stash

# 3. Check out the PR branch (tower keeps running from systemd — it doesn't restart yet)
git checkout feature/my-branch

# 4. Apply any new migrations against the live DB (safe — migrations are additive)
cd job_engine
conda run -n ai alembic upgrade head

# 5. Restart services to load the new code
bash job_engine/restart_app.sh

# 6. Run smoke tests (see checklist below)
```

> **Important:** Do **not** run `deploy_local.sh` for a test deploy. That script is for `origin/main` only (it calls `git reset --hard origin/main` which would undo your branch checkout). Use the manual steps above.

#### Smoke-test checklist

Run these after the branch is live on `:8001`:

| Check | Command / URL |
|---|---|
| API responds | `curl -sf http://127.0.0.1:8001/ \| head -5` |
| Migrations OK | `conda run -n ai alembic -c job_engine/alembic.ini current` — shows HEAD |
| No crashed services | `systemctl --user is-active watch-tower-{api,worker,beat}` — all should be `active` |
| Admin shell loads | Open `http://127.0.0.1:8001` in browser — no 500 |
| Tower health tab | `/tower-health` — vitals show; no red error banners |
| Hiring signals | `/signals` — table loads; no server error |
| Watchlist | `/watchlist` — loads without crash |
| One manual search | Queue one search from the UI; confirm it goes `dispatched → running → done` |
| Beat still schedules | Check Activity page after ~15 min — no double-queuing |

#### After a successful test

```bash
# Return to main (tower is still running the feature branch until deploy_local.sh runs after merge)
git checkout main

# Or keep the branch active until you merge the PR — deploy_local.sh will align to main on merge
```

#### Rollback if the test fails

```bash
# Immediate: go back to last known-good SHA on main
cd /home/user/Documents
git checkout main
cd job_engine && conda run -n ai alembic downgrade -1   # only if migration was applied
bash job_engine/restart_app.sh
```

> Any failed migration should be downgraded **before** switching branches to avoid schema/code mismatch.

#### Relationship to the CI deploy

```
PR branch  →  manual test deploy on ThinkPad  →  pass  →  merge PR to main
                                                              ↓
                                              GitHub Actions (push to main)
                                                              ↓
                                              scripts/deploy_local.sh (production deploy)
```

Test deploy uses the same restart path as production (`restart_app.sh`) so failures surface before they hit the Actions pipeline.

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
| **Ops AI face** | **VIGIL** — air-driven tower mind (Jarvis-class). What Ashok sees and gestures to. |
| **Ops AI backend** | **`ultron`** — code/package/WS namespace (`job_engine/app/ultron/`, `/ws/ultron`, `ultron.*` events). Not shown as the product name in chrome. |

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

### 2.6 VIGIL ops shell (Ashok YES 2026-08-01)

Investor pitch keeps the light lavender/blue Quanta brand. **Ops UI on the ThinkPad** is VIGIL — a single no-scroll Ultron-core canvas:

| Trait | Spec |
|---|---|
| Entry | `GET /` serves VIGIL SPA (`job_engine/vigil/`); legacy Jinja at `/legacy/` |
| Visual | Deep `#050302`, fiery orange `#FF5500`, amber `#FFAA00`, crimson `#CC1100`, bloom core |
| Interaction | MediaPipe hands — dwell, pinch-move, pinch-scroll, two-hand zoom, **flick max-zoom**, **fist close**; finger glow + hand-hot windows |
| Layer stack | Focused window only interactive; blur core / background / other panels (stops accidental dwell) |
| Training | Practice hub: skip, guided tour, or pick any drill; calibration applies to live; gesture logs for Akay |
| Modules | Floating panels: Tower, Hiring signals, Watchlist, Searches, Activity, Jobs (Remote chip inside), Live feed, Tower health, Companies Hiring (role drill-down) |
| Window stack | All panels open large + centered (layered stack). Orb + module dock always under windows |
| Pin dashboard | Admin pins/unpins any main widget (including Tower Insights); layout persists (admin canvas). Default first visit may pin Tower right — never locked. |
| Chrome density | Prefer icons over labels for chrome actions (Pin / Unpin / Close, Browser, Train, Vigil). Hover/title for meaning. Dashboard body text stays; avoid redundant chrome words. |
| Hermes CIO | Local Hermes Agent (Ollama 4b) + MCP read tools; VIGIL Ask + Telegram-ready briefs. Scrape wins capacity — see `documents/hermes-agent-integration.md` |
| Insight windows | Signals/Watchlist: 24h · Today · 2d · 4d · 7d · 14d · 30d. Role click → companies max→min glass pillars; company click → filtered Jobs |
| Compare visuals | Glass-pillar charts (crystal bars, orange base glow, cyan leader) for city/company/role/watchlist/filter comparisons; flex to panel width |
| Sync | WebSocket `/ws/ultron` + REST `/api/ultron/*` and existing `/api/*` |
| Deep links | `/?panel=jobs` (old paths redirect here) |
| Spec | `documents/vigil-hand-gesture-interface.md` |

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

### 4A. MNC-first collection base (Ashok pivot, 2026-08-14)

The serving niche is sharper than "freshers": **graduates chasing the MNC
dream** — high pay, a big brand, tall buildings, a lifestyle change. The
market for that niche is hot; broad role-keyword scraping diluted it with
startup/consultancy noise.

Collection therefore flips from role-first to **company-first**:

- A curated, growing **watchlist of giants** (Deloitte, Oracle, Apple,
  Google, Accenture, JPMorganChase, …) is the collection backbone —
  `job_engine/app/mnc_watchlist.py` is the catalogue of record.
- One company-scoped fresher search per giant (quoted company keywords +
  LinkedIn Internship/Entry + India, daily staggered). At insert only jobs
  whose card company matches the target are kept; the AI relevance filter
  is skipped (company match IS relevance — every role at a giant counts).
- The list grows from Ashok's phone: **`/addcompany <name>`** → watched
  company + daily search + immediate first scrape.
- **Detail enrich returned to full** (Ashok sign-off 2026-08-14): focused
  volume affords a detail-page visit for every job — verified experience,
  degrees, certifications. Complete data on the outliers, not shallow data
  on everything.
- Old role-keyword searches are **asleep, not deleted** (definitions kept;
  seed sleeps them on every deploy).
- Base rebuild: owner Telegram **`/resetdata` → `/resetconfirm`** wipes
  caught data (keeps definitions, watchlist, guests, alerts, history) and
  every search re-runs automatically, one by one.

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

> **Stage lock (Ashok 2026-08-03):** We are past “build the collector.”  
> **Collects = base complete** → **Map with Students (now)** → **Predict for Government (next).**  
> Day-to-day sprint board: [`documents/roadmap.md`](roadmap.md).

### Phase 0 — Foundation truth — DONE (seed hardened)

- Harden LinkedIn discovery pipeline
- Admin UX matches product-ux Definition of Done
- Brand tokens applied to admin shell
- Honest Tower Overview with real pilot metrics

### Phase 1 — Tracks (P0 intelligence) — BASE DONE

- Hiring Signals: openings trend, growing roles, company velocity ✅
- Company Watchlist ✅ · Competitor Intelligence (basic) still open
- Dual-track fresher + market signal discovery ✅
- Domestic / Global scope switch (even if global is subset) — later

### Phase 2 — Maps with Students — **CURRENT DELIVERY** (Job Movement · 2026-08-03)

**Metaphor:** *Master* intermission → responsible Master → student movement.  
**JobMaster** creates a **Job Movement**: continuous fact content for employment seekers.

**Product face:** **TECH JOB MARKET MOVEMENT** · JobMaster.agency · VIGIL · AI · Quanta HR.

- Social **image carousels** (Replicate): one question → tower facts → fire visualization
- **Trendjack** Tamil Nadu / TECH rising topics (SearchAPI / SerpApi Trends) into carousel briefs
- **Our page**: hope? · what should I know today? · understand the TECH job market
- **Associate path:** inspired by Honorable CM C. Joseph Vijay / TVK 2026 — prove change is possible; deliver employment intelligence for Tamil Nadu seekers as govt associate
- Tower = truth engine; students never see scrape chrome
- Gates before full automation: (1) Replicate carousel fire (2) TN trend search — then Intelligence Analysis → Carousel at scale

### Phase 3 — Predicts for Government — NEXT AFTER STUDENTS MAP

- Future Forecast (6–12m) with alert UX — city / sector / role for policymakers
- Boom / Recession / Disruption signals (transparent methodology)
- Investment Direction & Partnership Targets (decision views)

### Phase 4 — Multi-source Discovery Engine

- Employer integration
- Community referrals
- Deduped multi-source index

### Phase 5 — Employability engine (seeker)

- Pathways, next-gen titles, personal upskilling loops (extends Students Map)

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
| v0.7 | 2026-08-01 | Akay | Thermal save: keyword+headless; host_health; Docker watch-tower:v0; logind lesson |
| v0.8 | 2026-08-01 | Akay | **VIGIL** ops shell (Ultron backend): single-canvas R3F + MediaPipe hands; all modules as floating panels; `/ws/ultron` |
| v0.9 | 2026-08-02 | Akay | VIGIL layer stack, flick/fist gestures, free practice hub, live=training illumination + gesture logs |
| v0.10-milestone | 2026-08-02 | Akay | **Recover here:** pre–Neural Core baseline. Tag `milestone/pre-neural-core-v0`. Doc: `documents/milestone-pre-neural-core.md`. Next: world-model core (data graph), not decorative orb. |
| v0.11 | 2026-08-02 | Akay | Neural Core v0: live Postgres world-model graph in Three.js (sectors/cities/companies/roles + edges); click opens insight panels |
| v0.12 | 2026-08-02 | Akay | Scene modes: Core particle singularity (20k GPU) · Graph Obsidian clusters · City globe→district; wheel zooms into orb not page. Doc: `documents/vigil-scene-modes.md` |
| v0.13-milestone | 2026-08-03 | Akay | **Recover here:** Singularity Core v1 locked (Ashok accepted). Tag `milestone/singularity-core-v1`. Doc: `documents/milestone-singularity-core-v1.md`. Miro/Figma 3D nav + tags. |
| v0.14 | 2026-08-03 | Akay | Agile roadmap live (`documents/roadmap.md`). Sprint: Graph local-focus + spin freeze + clickable cards. Next milestone: richer City districts. |
| v0.15 | 2026-08-03 | Akay | Night City districts: cinematic skyline, sector clusters, height=hiring, facade name boards, flickering windows (`/api/ultron/cities/{id}/skyline`) |
| v0.16 | 2026-08-03 | Akay | **Job requirements enrich (critical):** detail-page scrape for experience years/band, degrees, certifications, domain experience → DB fields + Neural Core graph clusters. New scrapes queue enrich; beat backfills every 10m. |
| v0.17 | 2026-08-03 | Akay | **Fresher-first clean restart:** dual-track catalogue — Track A Fresher (`f_E=1,2` Intern+Entry + early-career keywords) daily flywheel; Track B Market Signal (no `f_E`, thinner pages) for experienced hiring / economy decode. `SearchConfig.experience_filter` + `track`. Enrich maps fresher/0–2 → `0-1 years`; retries `enrich_failed`. Wipe jobs/companies/runs then reseed before new catches. |
| v0.18 | 2026-08-03 | Akay | **Company profile + real posted dates:** company record stores logo, tagline, casual punchline, followers, employee size (job-card + company-page enrich). Relative LinkedIn times (“2h ago”) → `posted_date`; detail enrich backfills when cards omit `<time datetime>`. Caught time remains `scraped_at`. |
| v0.19 | 2026-08-03 | Akay | **Experience filter chips:** Fresher · 1–2 · 3–5 · 6–8 · 9–12 · 13+ on Jobs + every insight widget with sector/city chips. Canonical `experience_band` labels; legacy remap migration; stacks with sector/city (`vigil.experience`). |
| v0.20 | 2026-08-03 | Akay | **Jobs → City view:** header skyline button opens night-city from Jobs filters; multi-metro → multi building clusters (`/api/ultron/jobs-skyline`). |
| v0.21 | 2026-08-03 | Akay | **Remote access Option B — tunnel LIVE:** `https://tower.jobmaster.agency` → ThinkPad. Access email intended `ashokofficial55@gmail.com`; confirm Incognito OTP before sharing. Doc: `documents/remote-access-cloudflare.md`. |
| v0.22 | 2026-08-03 | Akay | **Delivery stage opened:** Collects base complete. Product priority = **Map with Students**, then **Predict for Government**. See `documents/roadmap.md`. |
| v0.23 | 2026-08-03 | Akay | **Students twist:** Map = **TECH JOB MARKET MOVEMENT** — social carousels (one question → facts → viz) + page for hope / daily knowing / TECH market understanding. JobMaster.agency · VIGIL · AI · Quanta HR. Not admin demand tables first. |
| v0.24 | 2026-08-03 | Akay | **Master → Job Movement:** continuous fact content for seekers. Two gates before auto: Replicate carousel fire + TN trendjack (SerpApi/SearchAPI). Associate inspiration: CM C. Joseph Vijay / TVK 2026 path. |
| v0.25 | 2026-08-03 | Akay | **Gate 1 live:** `/carousel` → Replicate flux-schnell + Pillow → Telegram `sendMediaGroup` album (Hermes). No local gallery; Ashok reviews on Telegram. |
| v0.26 | 2026-08-03 | Akay | **Telegram image-only:** default Tanglish Replicate memes; magic word **Carousel** = pro album (topic role/city). Hermes SOUL + `telegram_image_chat.py`; text replies banned (🔥 only). |
| v0.27 | 2026-08-03 | Akay | **Hard gate:** plugin `vigil-image-only` skips LLM on all Telegram msgs. Model → `google/imagen-4-fast`. No more text essays. |
| v0.28 | 2026-08-03 | Akay | **Grok Imagine:** model `xai/grok-imagine-image` + cinematic prompt dictionary (bright white calm). Memes dropped. Same style for chat + Carousel. |
| v0.29 | 2026-08-04 | Akay | **DIRECTOR live:** OpenAI Agents SDK above Hermes (1A). Layers COURIER/DIRECTOR/STAGEHAND/LENS/CAROUSEL. SQLiteSession memory; `/new` clears. TN Pinterest-2026 skit frames. |
| v0.30 | 2026-08-04 | Akay | **Graphic punchline DIRECTOR:** removed fixed cinematic prompts + Pillow text cards. DIRECTOR writes ≥800-char prompts (`MIN_PROMPT_CHARS`); 2D vector poster style; `read_vision_doc` + full vision brief. |
| v0.31 | 2026-08-04 | Akay | **DIRECTOR = Jarvis:** Telegram = Ashok↔Tower casual visual chat (live market), not student posters/PPT. Tiny punchy data crumbs in-image; Carousel stays separate album path. |
| v0.32 | 2026-08-04 | Akay | **Fact authenticity lock:** bangalore→bengaluru filter fix; city-scoped company counts; STAGEHAND city_pulse/ai_jobs; Pillow KPI/pie/bar/list boards for numbers (no Grok freehand charts). |
| v0.33 | 2026-08-04 | Akay | **DIRECTOR Workflow panel:** full Telegram→OpenAI→tool node traces + loophole hints; `stagehand_fresh_jobs` (no literal “fresh” search); diversified catches with URLs on list boards. |
| v0.34 | 2026-08-04 | Akay | **VALIDATOR role + Nano Banana 2:** authenticity gate before image/board send with wait acks; Replicate model → `google/nano-banana-2`. |
| v0.35 | 2026-08-04 | Akay | **Telegram text-first:** default chat text; `/summarize` final draft; `/image` visuals — fix data in text before image work. |
| v0.36 | 2026-08-04 | Akay | **Gate 3.0 JobMaster:** one uniform, focused customer-support/information agent. Capability #1 = verified LinkedIn jobs plus grounded job-market counts, rankings, trends, and comparisons. AI translates messy language into validated intent; code and Watch Tower own every fact. Dedicated Telegram ingress replaces Hermes gateway fallback; 10 rows + `more` + clean `/new`. Future capability boundary: subscriptions, ATS resume fixing, preparation guides, projects, quizzes, flashcards, news, tutorials, LMS. |
| v0.37 | 2026-08-04 | Akay | **JobMaster capability #1 accepted:** Supriya validated the deployed experience and Ashok locked it as the baseline at `milestone/jobmaster-gate3-v1` (`2fda2d7`). Future conversational OS capabilities must extend this dedicated-ingress, deterministic-facts architecture without restoring Hermes fallback or model-authored job data. |
| v0.38 | 2026-08-04 | Akay | **Ashok-only command deck:** dedicated JobMaster ingress restores deterministic `/stats`, VIGIL boards, hiring signals, government jobs, and brief shortcuts before search parsing. Bot API command scopes expose the menu only to `TELEGRAM_HOME_CHANNEL`; customer chats keep the uniform JobMaster persona but cannot see or execute tower operations. |
| v0.39 | 2026-08-05 | Akay | **Stored JobMaster acceptance corpus:** stable `JM-*` manual cases cover owner menus, customer isolation, natural-language search, canonical links, pagination, grounded insights, ambiguity, injection, and recovery. Ashok executes cases one by one with evidence; the same IDs later become contract, sandbox, live-smoke, deployment-gate, and nightly automated tests. |
| v0.40 | 2026-08-05 | Akay | **Phone-only guest management restored:** `/allowguest`, `/blockguest`, and `/guests` are Ashok-only commands in dedicated JobMaster ingress. Username grants persist until blocked; numeric grants may expire; explicit blocks override defaults; re-allow clears blocks; owner access is immutable. Unauthorized updates are rejected before the durable queue. |
| v0.41 | 2026-08-05 | Akay | **Owner guest-history command:** `/history <@username-or-id> [1–40]` stores and returns delivered guest conversation pairs from deployment onward. Strict 40-per-numeric-person retention, stable username binding, recycled-handle refusal, owner exclusion, compact UTF-16-safe output, and fail-safe inbox finalization protect privacy and reliability. Telegram cannot backfill earlier chats. |
| v0.42 | 2026-08-05 | Akay | **1A — JobMaster voice layer:** Ashok — "the chat has no life, we can't run on Regex... people want to naturally talk" — decided **1A**: an LLM may reword tone/greeting/connective language around a deterministic reply, gated by a byte-exact VALIDATOR (`app/telegram_voice.py::validate_voice`) that requires every non-blank line containing a job title, company, experience label, link, count, or comparison to survive character-for-character, in order, plus no new URL. Any drift/timeout/disabled key falls back to the untouched deterministic reply. Wired into `scripts/telegram_job_bot.py` only around guest-facing job-search/insight/onboarding/`/start`/`/help` replies — VIGIL owner board and management commands are explicitly excluded and stay exactly deterministic. `JobMasterEngine` and its full contract-test suite are untouched and unaware this layer exists. 186/186 tests green. Subscriptions/premium (quiz, alerts, flashcards, study material, prep book, projects, certifications, LMS) are explicitly **deferred to the next phase** (Ashok, 2026-08-05) — not built here — but this voice layer is deliberately generic (wraps any deterministic reply, not just job listings) so that phase can speak naturally about an entitlement without forcing regex to parse free-form marketing language. |

### Phase 0 progress (living)

| Slice | Status |
|---|---|
| Brand tokens + Quanta Q + Live naming on admin shell | Done (legacy `/legacy`) |
| Nav: Tower · Searches · Activity · Jobs · Live feed | Done → VIGIL orbit nodes + panels |
| Tower Overview pods (honest pilot metrics) + Tracks flywheel cue | Done |
| Harden discovery pipeline / scrape reliability | Done (v0.2) |
| Hiring Signals (Phase 1) | Done (v0.3) |
| Once-daily cadence + ~100 fresher/major role catalogue | Done (v0.4) → superseded by dual-track v0.17 |
| Fresher-first discovery (`f_E` + dual-track) + clean data restart | Done (v0.17) |
| Company Watchlist (EC-01) | Done (v0.5) |
| VIGIL air ops shell (hand-first, Ultron bus) | Done (v0.8) |
| **Milestone freeze** before world-model Neural Core | Done (v0.10-milestone) — recover via tag |
| Neural Core v0 — living labor-market graph in Three.js | Done (local) — `/api/ultron/world-model` + interactive Three.js graph; click → panels |
| **Milestone freeze** Singularity Core v1 (nav + tags + brand shape) | Done (v0.13-milestone) — tag `milestone/singularity-core-v1` |
| Job requirements → experience / degree / cert / domain graph clusters | Done (v0.16) — enrich + world-model; backfill pending |
| Fresher Track A (`f_E=1,2`) + Market Signal Track B | Done (v0.17) — seed owns catalogue truth |
| Company logo / punchline / followers / size on company record | Done (v0.18) — enrich + `/api/ultron/companies/{id}` |
| Posted date from LinkedIn (not only caught time) | Done (v0.18) — relative parse + detail backfill |
| Experience band chips (Fresher … 13+) on hiring widgets | Done (v0.19) — filter + job-card meta |

### Dual-track discovery (v0.17) — fresher primary

**Primary product lens:** tech **fresh graduates** — where openings are, which degrees/certs appear, which cities/companies hire.  
**Secondary lens:** experienced **Market Signal** searches (no LinkedIn experience filter) for hiring density → economy decode.

| Track | LinkedIn `f_E` | Cadence | Pages | Purpose |
|---|---|---|---|---|
| `fresher` | `1,2` (Internship + Entry level) | Daily ~05:00 stagger 14m | 5–10 (priority funnels) | Graduate employability flywheel |
| `signal` | *(none — all levels)* | Daily ~14:00 stagger 18m | 3 | Experienced / economy signals |

**Rule:** Fresher searches always send LinkedIn Entry + Intern filters. Discovery before enrich — enrich cannot recover jobs never scraped.  
**Seed:** `app/seed_roles.py` + `scripts/seed_fresher_searches.py` (disables configs not in catalogue).  
**Clean restart:** stop scrapes → reseed → `POST /reset` (keeps `search_configs`) → optional clear `console_log` / `tower_events` → beat resumes.

### Cadence policy (v0.4) — how often to run

**Decision: once per day per search** (staggered), with LinkedIn **past 24 hours** filter (`f_TPR=r86400`). Fresher track adds **`f_E=1,2`** (v0.17).

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

- AI title filter: **`qwen3.5:4b`** (not 9b/27b — title match only). Fast JSON
  (`OLLAMA_THINK=false`), short prompt, 45s timeout.
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

**Incident 2026-08-01 ~01:01 (black screen + crash):** After lid-policy change, Akay ran `systemctl restart systemd-logind` (required sudo password). That can **kill the graphical session** → black screen with typing cursor (see `/home/user/Videos/first crash.MOV`). Session later showed unclean reboot. **NEVER restart systemd-logind while Ashok is in a desktop session.** Prefer gsettings-only for lid; logind drop-in applies on next reboot.

**Thermal / NVIDIA (2026-08-01):** Root cause: kernel `7.0.0-28-generic` but only `linux-modules-nvidia-535-6.8.0-31` installed → no module → `nvidia-smi` failed → Ollama fell back to **CPU ~400%** → overheat. **Fixed:** installed `nvidia-driver-595` + `linux-modules-nvidia-595-7.0.0-28-generic` (Ubuntu recommended). `nvidia-smi` OK — RTX A3000 12GB. Still defaulting to cool scrape (`HEADLESS=true`, `RELEVANCE_MODE=keyword`, Ollama disabled) until Ashok YES to re-enable GPU Ollama carefully. Host monitor: `scripts/host_health.sh`.

**Docker v0 backup:** image `watch-tower:v0` + offline tarball `backups/watch-tower-v0.tar.gz` (~195MB). Compose file preserves API+DB+Redis skeleton.

**Thermal-balanced Ollama (2026-08-01):** `RELEVANCE_MODE=ollama` + `app/thermal.py`. Between AI batches: dynamic breaks (cool~8s / warm~25s / hot~60s / critical~120s). **Keyword filter is Plan B only** (critical heat or no GPU) — never normal ops; keyword corrupts relevance. Beat skips new scrapes when hot/critical. Batch size shrinks when warm. Prefer `x86_pkg_temp` over noisy `acpitz`. Ollama on RTX A3000; Chrome stays headless.

**Tower Health (2026-08-01):** Sticky header vitals on every page + `/tower-health` tab — PC heat/memory/CPU, last Ollama vs Plan B search, searches today/24h, next-search countdown, last browser open, Ollama load (now/day/24h) and capacity estimate. North star: measure how many **Ollama** searches this laptop can sustain coolly, then scale with more laptops (one per industry OK) — not overload one machine.

**Capacity goal:** Find the sustainable Ollama-search/day number for this P16 (early band ~60–90 with human dwell + heat breaks). Scale infra after that number is proven.

### Critical sectors + fair analytics (2026-08-02)

| Sector id | Industry | Notes |
|---|---|---|
| `tech_ai` | Tech Industry · Artificial Intelligence (AI) | Heavy catalogue (existing) |
| `tech_digital` | Tech Industry · Digital technologies | Heavy catalogue (existing) |
| `manufacturing_advanced` | Manufacturing · Advanced manufacturing | Light everyday searches |
| `healthcare` | Healthcare | Light |
| `green_economy` | Green economy | Light |
| `logistics` | Logistics | Light |
| `tourism` | Tourism | Light |

**Fair compare rule:** Jobs-per-role analytics use a **shared time window** (default 7d) and optional **jobs/day** rate — never all-time totals — so early-started roles (e.g. Risks & Controls) do not permanently dominate rankings as new sector searches come online.

**Sector chips (UI):** Global filter on Tower Insights, Jobs, Hiring Signals, Watchlist, Searches, Activity, and Show-all ranks — All sectors · Tech·AI · Tech·Digital · Manufacturing · Healthcare · Green economy · Logistics · Tourism. Persists across panels; Health / Ask / Live / AI-vs-Keyword stay unscoped.

### City normalize + City Signals (2026-08-02)

| City id | Label |
|---|---|
| `bengaluru` … `kolkata` + `kerala` | India metros / Kerala (aliases collapsed) |
| `remote` | Remote / WFH |
| `india` | India-wide (no city) |
| `other` | Unmapped |

**Favourite chips:** UI shows All + favourites (default Tech·AI / Tech·Digital · Bengaluru / Chennai / Kerala); Show more reveals the rest; ★ pins anytime.

**Jobs store `city_key`** from scrape; DE-02 normalize-location started. **City Signals** module ranks cities by volume/growth and compares any two (top roles + companies). Global city chips stack with sector filters.

---

*End of PRD v0 — Global Job WATCH TOWER · Quanta HR Labs*
