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
customer chats on the clean JobMaster interface. Insight commands deployed at
`af5c1ea`; JM-002 then exposed missing user management. Recovery adds
`/allowguest`, `/blockguest`, `/guests`, block-overrides, and access enforcement
inside the dedicated poller. Contract tests are green; deployment and live
acceptance remain open on kanban card #6.

**Guest QA visibility:** Ashok-only `/history <@username-or-id> [1–40]`
captures delivered guest question/reply pairs from deployment onward so live
test evidence can be inspected inside Telegram. Strict 40-per-person retention,
stable numeric identity binding, recycled-username refusal, owner exclusion,
compact UTF-16-safe output, and fail-safe persistence are required. Manual
acceptance is tracked as JM-028/JM-029 and kanban #8; the same contract joins
the future automated Telegram sandbox suite.

**Acceptance track:** Ashok will execute the numbered best-case, worst-case,
edge-case, security, pagination, insight, and owner-isolation suite in
[`jobmaster-telegram-validation.md`](./jobmaster-telegram-validation.md), one
case at a time with screenshots and actual replies. Keep test IDs stable.
Next automation slice converts the same IDs into contract tests, a Telegram
sandbox integration suite, a read-only live smoke, deployment gates, and a
nightly regression corpus (kanban #7).

**Scale target (2026-08-05):** JobMaster must be designed to serve 1,00,000
(1 lakh) users/guests within a month, with scraped data reaching roughly that
many people through real conversion. This is now a standing design
constraint (`.cursor/rules/product-ux.mdc`) — see
`documents/scale-and-memory-architecture.md` for the current infra gap
(session/guest state is a single local SQLite file and must move to
Postgres/Redis before this holds) and kanban card #10 for the migration plan.

**Guided onboarding + guest profiles (2026-08-05):** a bare greeting now
starts a deterministic role → experience → city conversation instead of an
unfiltered job dump, ending in the same grounded `_job_reply` results plus a
forward-looking suggestion — Ashok's ask for "collect info gradually" and
"user/guest management." Every completed flow saves a per-guest profile
(role/experience/city) readable via the new Ashok-only `/guestprofile`
command. A returning guest's greeting recalls that stored profile instead of
re-running the funnel ("zero friction... when they return"), and Ashok can
now self-test the entire guest experience from his own phone via
`/actasguest` / `/actasowner` — no second phone needed, and it can never lock
him out of his own chat. 163/163 tests green; live acceptance tracked as
JM-130..161 in the validation doc and kanban card #9.

Gate 3.0 expands later through the same capability boundary: subscriptions,
ATS resume fixing, interview preparation, PDF guides, projects, quizzes,
flashcards, relevant tech news, tutorials, and LMS progress. Entitlements are
backend-enforced; the conversational model never grants access by prompt.

**1A — voice layer (2026-08-05):** Ashok — "the chat has no life, we can't
run on Regex... people want to naturally talk" — approved option **1A**: an
LLM warmth pass wraps the deterministic reply (tone, greeting, connective
language only), gated by a byte-exact fact-lock VALIDATOR
(`app/telegram_voice.py`) so every job title/company/experience/link/count/
comparison line ships unmodified or the reply silently falls back to the
plain deterministic text. Live now for job-search, insight, onboarding, and
`/start`/`/help` replies; VIGIL owner commands stay exactly deterministic on
purpose. 186/186 tests green (`test_telegram_voice.py` +
`VoiceLayerWiringTests`).

**Button-driven guest flow — GTM Intern/Fresher only (2026-08-06):** the
voice/free-text path above (1A) shipped real live regressions and, once,
left a real guest with zero reply. Ashok's call: make the *primary* guest
path tap-only — **Family → Role → Experience → City → Results** via
Telegram inline keyboards (`app/telegram_buttons.py::ButtonFlow`) — with
free text (and the existing voice/NLU layer) kept wired exactly as before,
unseen, purely as a fallback for whoever still types. Only Intern/Fresher
experience buttons run a live search (GTM focus); 1–4/5–10/10+ show a
"coming soon" message and collect an email into a waitlist
(`app/telegram_waitlist.py`, owner `/waitlist` command) instead of running
a search that track isn't ready to serve. Also shipped: owner-only
`/checkaccess` (`app/telegram_guests.py::describe_access`) — a live,
phone-only diagnostic that runs the exact real guest access-gate decision,
because `/actasguest` structurally cannot (it short-circuits on Ashok's own
owner id before the real gate ever runs) — see kanban card #12. 230/230
tests green.

**Subscriber/premium — deferred (Ashok 2026-08-05):** "Subscriber" = a paid
tier unlocked after sustained usage, covering quiz, alerts, flashcards,
study materials, prep book, projects, certifications, and a full LMS.
Explicitly **not started** — no engagement tracking, no upsell copy, no
entitlement model yet. Ashok's standing instruction: keep the architecture
extensible for it now (the voice layer is generic, not job-listing-specific,
for exactly this reason) rather than hard-coding everything to raw
regex/deterministic-only assumptions that a future paid conversational
capability would have to fight.

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
