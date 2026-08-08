# Detail-scrape pause — analysis & 3 implementation plans

**Date:** 2026-08-08 · **Author:** Akay · **Status:** Decision pending (Ashok)

**Ask (Ashok):** stop the "4/135" issue — the tower must catch the maximum
job roles + links per day; per-job detail scraping must not starve discovery.
This doc answers: (1) what data we lose if we stop detail scraping,
(2) how hard stopping is, (3) how much impact it creates, and gives
(4) three fully detailed implementation plans.

---

## 1. What "4/135" actually is — the root cause

### The pipeline today (one browser lane, three competitors)

The Celery worker runs with `-c 1` (`start_pilot.sh` line 64 — "one browser
job at a time"). Every browser task shares that single lane:

| Task | Trigger | Volume per burst | Browser cost |
|---|---|---|---|
| **Search scrape** (`run_scrape`) | Beat cron, one config per tick | up to 10 pages × 25 cards | 90–120 s per page (75–105 s human dwell) |
| **Job detail enrich** (`enrich_job_requirements`) | Auto-queued after every successful run (`new_job_ids[:40]`) + beat backfill every 10 min (12 pending) | up to 40 detail pages | ~25–45 s **per job** (page load + 4–8 s settle + 8–22 s human delay between jobs) |
| **Company enrich** (`enrich_company_profiles`) | Auto-queued after runs (≤12) + beat every 15 min (6 pending) | ≤12 companies, 1–2 pages each | ~30–60 s per company |

### The economics — why details eat the tower

- **One search page:** ~90–120 s of browser time → up to **25 job links**.
  ≈ **4–5 s of browser time per job caught.**
- **One detail page:** ~25–45 s of browser time → **1 job's metadata,
  zero new links.**
- So per stored job, the tower currently pays ~4 s discovering it and
  **~35 s enriching it — roughly 85–90 % of the browser budget goes to
  detail pages**, not to catching new roles/links.
- After every successful run, up to 40 details are queued = **17–30 min of
  browser lane appended to every search**. The 10-minute beat backfill
  (12 details ≈ 5–9 min) then keeps the lane nearly saturated whenever a
  backlog exists.
- Side effect: the enrich browser session generates the same CPU/GPU heat
  as a scrape, so `thermal.allow_new_scrape()` heat-pauses the beat and
  **delays new searches even further**.

### The "4/135" reading

The enrich console logs `Detail {i+1}/{len(batch)}` per batch (cap 40), and
the pending backlog grows by every run's catch. A "4 of 135" style reading =
**135 jobs waiting for details, ~4 processed in the window Ashok looked at**
— i.e. backlog growth permanently outruns enrich throughput, and every
minute spent closing that gap is a minute not spent on search pages.
Verification query (run on the ThinkPad):

```sql
SELECT count(*) FILTER (WHERE requirements_enriched_at IS NULL) AS pending,
       count(*) FILTER (WHERE requirements_enriched_at IS NOT NULL) AS done,
       count(*) FILTER (WHERE experience_label = 'enrich_failed') AS failed
FROM jobs_master;
```

**Conclusion:** the issue is structural — a single browser lane where the
lowest-value-per-second work (details) is auto-queued at ~8–10× the
per-job cost of discovery. Stopping or throttling details directly converts
into more searches per day.

---

## 2. What data we miss if we stop detail scraping

Detail enrich (`app/enrichment.py::_apply_requirements`) writes these
`jobs_master` columns. Field-by-field impact:

| Field | Detail-only? | Who consumes it | What breaks / degrades if stopped |
|---|---|---|---|
| `experience_band`, `experience_label`, `experience_min/max_years` | **Partially** — `extract_requirements()` already accepts `card_text` (search-card raw text), and fresher-track searches are hard-filtered by LinkedIn `f_E=1,2` at the search URL | Telegram job rows ("Title — Company — Experience"), Telegram fresher secondary filter, `/api/jobs?experience=`, VIGIL experience chips (signals, role/city analytics, skyline), world-model graph | Telegram shows "Not stated" more often. **The guest fresher flow does NOT break** — the API already treats `experience_band IS NULL` as fresher-compatible on the fresher track (`api/routes.py` lines 171–172, 261–262) and the Telegram filter only excludes when a band exists and ≠ fresher (`telegram_job_search.py` line 634–636). VIGIL band-chip views silently miss unenriched jobs when a chip is selected. |
| `seniority_level` | **Yes** (LinkedIn criteria section only exists on the detail page) | Band inference fallback, world-model graph | Lost for new jobs. Mitigated for the GTM product because fresher track is search-level filtered anyway. |
| `degrees` | **Effectively yes** (needs full description text) | World-model graph clusters (employability graph: degree nodes), fresher-lens insights | Clusters stop growing for new catches. Old data keeps serving. |
| `certifications` | **Effectively yes** | Graph cert clusters; future affiliate/cert recommendations (Vigil 2.0 vision — cert/course offers are the monetization seed) | Same as degrees. **This is the biggest strategic loss** — cert demand data feeds the future selling layer. |
| `domains` | **Effectively yes** | Graph domain clusters | Same as degrees. |
| `description_text` | **Yes** | Stored only today (no live reader); future quiz/prep/LMS/affiliate matching would want it | Lost for new jobs — **but fully backfillable later**: `job_url` is kept forever, so any paused job can be enriched retroactively as long as the posting is still live (LinkedIn postings die in ~30–60 days; older ones 404). |
| `posted_date` fill | Fallback only (card usually carries a `<time>` tag) | Trends, posted-vs-caught honesty | Minor: a small % of jobs keep NULL posted_date. |
| Company bits from the job page (logo/tagline via `_apply_company_from_detail`) | **No** — `company_enrichment.py` gets the same + more from company pages | Company cards, logos, punchlines | **Zero loss if company enrich stays on** (recommended: keep — it is per-company deduped, low volume, high UI value). |

### What does NOT break (verified in code)

- **JobMaster guest GTM path (Family → Role → Experience → City →
  Results):** filters on `track='fresher'` (immutable `source_track`
  provenance stamped at insert), city, and title match — none of which come
  from detail pages. Links, titles, companies, cities: all card-level.
- **Alerts and broadcasts:** same formatter, same NULL-tolerant band
  display ("Not stated").
- **Counts / signals / boards under "All experience":** unaffected —
  they aggregate card-level rows.
- **Resume-ability:** `requirements_enriched_at` stays NULL on skipped
  jobs, so the existing backlog query (`pending_requirement_ids`) resumes
  the moment we re-enable — nothing is orphaned.

### Honest risk statement

The one **permanent** loss: for jobs whose LinkedIn posting expires before
we backfill, description-derived data (degrees/certs/domains/description)
can never be recovered. Roles, links, companies, cities, freshness — the
data Ashok says we need at maximum — are never at risk.

---

## 3. How hard is it to stop? (effort)

**Operationally trivial and fully reversible.** Detail enrich has exactly
three entry points, all in `app/tasks.py`:

1. Post-run auto-queue — `run_scrape` lines 417–428
   (`enrich_job_requirements.delay(...)`).
2. Beat backfill — `enrich_pending_requirements` (celery beat,
   every 600 s).
3. Manual/celery direct call — `enrich_job_requirements` itself.

No schema change, no migration, no data movement. A single config/runtime
flag guarding those entry points stops 100 % of detail traffic. The enrich
code, parsers, and tests stay intact for re-enable. Effort per plan is
detailed below; Plan A is a handful of small guarded edits + tests.

---

## 4. How much impact will stopping create?

**Throughput gain (the point of the exercise):**

- Browser budget currently ≈ 4–5 s/job discovery + ~35 s/job detail.
- Removing details returns **~85–90 % of browser time to search pages** —
  in practice the tower can run roughly **5–8× more search runs per day**
  at identical heat/stealth pacing (each run also finishes 17–30 min sooner
  because no enrich burst trails it).
- Less browser heat per stored job → fewer thermal beat-pauses → search
  cadence stabilizes on top of the raw lane gain.

**Product cost:**

- Guest experience: experience column reads "Not stated" more often
  (fixable cheaply — Plans B/C stamp bands from card text + track).
- VIGIL: experience-chip filtered views and graph requirement clusters
  freeze for new jobs until backfill resumes.
- Vigil 2.0 seed data (cert/degree demand) pauses accumulating — deferred,
  not destroyed, for any posting we backfill within its lifetime.

---

## 5. Three implementation plans (full logic + architecture)

All three share one principle: **discovery (roles + links) owns the browser
lane; details are a lower class of work.** They differ in how much detail
work survives and how much structure we build.

---

### PLAN A — Kill switch: pause all detail scraping now (smallest, fastest)

**Goal:** stop 100 % of per-job detail traffic today; keep everything
resumable; zero schema change.

**Architecture:** one runtime flag, three guards, no new components.

**Implementation logic:**

1. **`app/config.py`** — add:

   ```python
   # Per-job detail enrich (experience/degrees/certs/domains). 'off' stops
   # ALL detail-page traffic; discovery-first mandate 2026-08-08.
   DETAIL_ENRICH_MODE = os.getenv('DETAIL_ENRICH_MODE', 'off').strip().lower()  # off | full
   ```

2. **`app/runtime_settings.py`** — mirror the flag in
   `runtime_settings.json` (same pattern as the Browser Hidden/Visible
   toggle) with getter `get_detail_enrich_mode()` so Ashok can flip it from
   VIGIL without a redeploy, and it survives reboot.

3. **`app/tasks.py`**
   - `run_scrape` (line ~417): wrap the `enrich_job_requirements.delay(...)`
     block in `if get_detail_enrich_mode() != 'off':` — else
     `console_log('worker', 'Detail enrich paused (discovery-first) — '
     f'{len(new_job_ids)} job(s) left pending for later backfill.')`.
     **Keep the company-enrich queueing untouched** (per §2 it is cheap and
     covers logos/punchlines).
   - `enrich_pending_requirements` (beat): first line —
     `if get_detail_enrich_mode() == 'off': return {'paused': True}`.
   - `enrich_job_requirements`: same guard (protects against stale queued
     tasks and manual calls).

4. **`app/celery_app.py`** — leave the beat entry in place (the task no-ops
   when off) so re-enabling is pure config, no process restart of beat.

5. **VIGIL surface (small):** Tower Health tile "Details: paused ·
   N pending" fed by the §1 SQL count via the existing health endpoint —
   icon-only chrome per UX law, hover for meaning. Console line on every
   run (step 3) keeps the Activity feed honest.

6. **Telegram display honesty:** no change needed —
   `experience_display(None)` already renders "Not stated"; fresher filter
   already NULL-tolerant (verified §2).

**Tests:**
- Unit: `DETAIL_ENRICH_MODE='off'` → `run_scrape` result has
  `enrich_queued == 0` and no `enrich_job_requirements` task queued
  (patch `.delay`); beat task returns `{'paused': True}`.
- Unit: mode `'full'` restores exact current behavior (regression guard).
- Existing 230-test suite must stay green untouched.

**Rollback / resume:** set `DETAIL_ENRICH_MODE=full` (env or VIGIL toggle).
Backlog resumes automatically via `pending_requirement_ids` — newest-first
(`order_by(JobMaster.id.desc())`), which is correct because newest postings
are the ones still alive to enrich.

**Effort:** small — 3 files edited (config, runtime_settings, tasks) +
1 health tile + tests. No migration.

**Impact:** full ~5–8× discovery gain immediately. Full §2 data pause.

**Risk:** lowest. Only real risk is forgetting it's off — mitigated by the
health tile + pending counter.

---

### PLAN B — Card-first light enrich + budgeted trickle (recommended)

**Goal:** get ~95 % of Plan A's throughput gain, but (a) keep
`experience_band` populated **for free** from data we already hold, and
(b) let details trickle only inside a strict daily browser budget that can
never starve discovery.

**Architecture:** two additions on top of Plan A's flag (mode gains a
`light` value): an **insert-time card extractor** (zero browser cost) and a
**budget + idle-gate scheduler** for the residual detail trickle.

**Implementation logic:**

1. **Insert-time card extraction (free data, no browser):**
   - `app/tasks.py::persist_kept` — after building the `JobMaster` row:

     ```python
     req = extract_requirements('', card_text=job.raw_text)
     row.experience_min_years = req.experience_min_years
     row.experience_max_years = req.experience_max_years
     row.experience_label = req.experience_label
     row.experience_band = req.experience_band
     ```

   - **Track stamping (honest, not invented):** when
     `cfg.track == 'fresher'` and the card text produced no band, set
     `row.experience_band = 'Fresher'` with
     `row.experience_label = 'Fresher track (LinkedIn Internship/Entry)'`.
     This is LinkedIn's own `f_E=1,2` search filter — the same ground truth
     the seniority→band mapping uses — not a model guess, so it passes the
     no-invented-facts law.
   - Leave `requirements_enriched_at` NULL — card extraction is not detail
     enrichment; the job stays in the backfill queue for description-level
     data (degrees/certs/domains) whenever budget allows.
   - Effect: Telegram rows show a real band instead of "Not stated" for the
     whole GTM population, VIGIL fresher chip keeps counting new jobs.

2. **Budgeted trickle (`DETAIL_ENRICH_MODE='light'`):**
   - **Budget config:** `DETAIL_BUDGET_PER_DAY` (default 60 pages) and
     `DETAIL_BATCH_SIZE` (default 6).
   - **Budget ledger:** Redis counter `detail_budget:<UTC date>` (INCRBY on
     each fetched detail page, 48 h TTL) — Redis is already a dependency;
     no schema change.
   - **Idle + heat gate** in `enrich_pending_requirements` (beat, every
     10 min). Run a batch only when ALL hold:
     1. `get_detail_enrich_mode() == 'light'`;
     2. budget remaining > 0;
     3. no `ScrapeRun` in `('queued','dispatched','running')`;
     4. **no config due within the next 15 min** — reuse the same
        croniter next-due computation as `enqueue_due_work` over enabled
        configs (extract it into a small helper
        `app/schedule.py::next_config_due_at(db)` so both callers share
        one implementation);
     5. `thermal.allow_new_scrape()` says Cool (details never get the lane
        during Warm/Hot — searches keep absolute priority after cool-down).
   - Batch size `min(DETAIL_BATCH_SIZE, budget_left)` — a batch is ≤6 jobs
     ≈ ≤4 min lane occupancy, so even a mistimed batch delays a search by
     minutes, not half-hours.
   - **Remove the post-run auto-queue entirely** in `light` mode — the
     trailing 40-detail burst is the single biggest thief; the beat-gated
     trickle replaces it.

3. **Priority queue — enrich what matters first.**
   Replace `pending_requirement_ids` ordering with:
   1. Jobs actually **delivered to guests** (ids recorded in
      `sent_job_ids` of alerts + session `seen_ids`) — the rows customers
      are looking at deserve real bands first;
   2. fresher-track jobs (`source_track='fresher'`) newest-first —
      GTM scope and still-alive postings;
   3. everything else newest-first.
   Implementation: `ORDER BY (id IN :delivered) DESC, (source_track='fresher') DESC, id DESC`
   with the delivered-id set loaded from the alerts/session stores
   (bounded — cap the set at a few hundred most-recent).

4. **VIGIL surface:** health tile shows
   "Details: light · 23/60 today · N pending". Console logs each gate
   decision in one line ("Detail trickle skipped — search due in 9 min").

**Tests:**
- Card extractor: title/card fixtures → expected bands; fresher-track
  stamping only when card yields nothing; non-fresher tracks never
  stamped.
- Budget: counter increments per page; batch refuses when exhausted;
  UTC-day rollover resets.
- Idle gate: fake due-config within 15 min → skip; active run → skip;
  Warm heat → skip.
- Priority: delivered ids outrank fresher-track outrank rest.

**Rollback:** mode back to `full` (current behavior) or `off` (Plan A).
Each knob is independent; card extraction is harmless in every mode and
stays.

**Effort:** moderate — everything in Plan A, plus `persist_kept` edit,
one helper in `app/schedule.py`, a Redis counter, reordered pending query,
and the test batch above. All changes localized to `tasks.py`,
`enrichment.py`, `schedule.py`, `config.py`, `runtime_settings.py`.

**Impact:** ~95 % of the discovery gain (60 detail pages ≈ 35–45 min/day of
lane, gated to idle windows only); experience data keeps flowing for free;
cert/degree/domain graph keeps growing slowly on the jobs guests actually
see; Vigil 2.0 seed data never fully stops.

**Risk:** low-moderate — the idle gate must be correct or trickle steals
lane time (mitigated by the 15-min look-ahead + ≤6 batch cap + heat gate).

---

### PLAN C — Night-shift enrich lane (structural, biggest build)

**Goal:** permanent architecture where discovery and enrichment can never
compete: details run **only in a scheduled night window** on their own
Celery queue, with batch-efficiency upgrades that clear backlog fast when
they do run.

**Architecture:** queue split + time-window scheduler + session-amortized
batch enricher.

**Implementation logic:**

1. **Queue split (`app/celery_app.py`):**

   ```python
   task_routes = {
       'app.tasks.run_scrape': {'queue': 'scrape'},
       'app.tasks.enrich_job_requirements': {'queue': 'enrich'},
       'app.tasks.enrich_pending_requirements': {'queue': 'enrich'},
       'app.tasks.enrich_company_profiles': {'queue': 'enrich'},
       'app.tasks.enrich_pending_companies': {'queue': 'enrich'},
   }
   ```

   `start_pilot.sh` / `restart_app.sh`: one worker consuming **both**
   queues with strict priority (`-Q scrape,enrich` — Celery drains listed
   queues in order with `worker_prefetch_multiplier=1`), staying at `-c 1`
   because the ThinkPad has one browser identity/profile. A second worker
   process is deliberately NOT started — two simultaneous Chrome profiles
   on one LinkedIn identity is a stealth risk, not a speedup.

2. **Night window (`app/config.py`):**
   `DETAIL_WINDOW_START='00:30'`, `DETAIL_WINDOW_END='06:00'` (IST — the
   catalogue's quietest hours; laptop is already on charger overnight per
   standing ops). `enrich_pending_requirements` beat guard:
   inside window → process batches continuously while heat allows;
   outside window → return immediately. Post-run auto-queue is removed
   (same as Plan B) — nights own all detail work.

3. **Session-amortized batch enricher (`app/enrichment.py`):**
   - Today every 10-min beat opens a fresh `StealthySession` (Chrome boot
     ≈ 5–10 s + cookie sync) for ≤12 jobs. Night mode processes up to
     `DETAIL_NIGHT_BATCH=150` jobs in **one** session, checking
     heat + window between jobs (`thermal.wait_for_breath` pattern, and
     abort cleanly at window end mid-batch — commit per job already
     guarantees no loss).
   - **Detail-appropriate pacing:** flipping between job views inside one
     session is normal logged-in user behavior; drop the inter-job
     `human_delay()` (8–22 s, tuned for search-page hops) to a
     `DETAIL_DELAY_MIN/MAX_S = 4/9` s pair. ~150 details ≈ 60–90 min of
     night lane — the whole current backlog class clears in 1–2 nights,
     then nightly runs stay small (yesterday's catch only).
   - Keep Plan B's priority ordering (delivered-to-guests → fresher-track
     → rest) so if a night is cut short by heat, the most valuable rows
     are already done.

4. **Card-first extraction at insert** — identical to Plan B step 1
   (it is free and correct in every architecture; daytime rows get bands
   immediately, nights add the description-level fields).

5. **Ops surface:** Tower Health tile "Night enrich: last window 142 ok /
   3 failed · N pending"; `record_event_standalone('browser_open', ...)`
   already stamps every session for the health board; console lines per
   batch. Optional owner Telegram line in the daily brief ("Night shift
   enriched 142 jobs").

**Tests:**
- Window math (IST boundaries, crossing midnight, DST-free zone).
- Routing: each task lands on its declared queue (celery test harness).
- Batch enricher: aborts at window end mid-batch without losing committed
  rows; heat interrupt resumes next window; per-job commit idempotence.
- Priority ordering (shared with Plan B).
- Full suite green.

**Rollback:** window config to `00:00–00:00` disables nights (Plan A
state); queues are additive and harmless if unused.

**Effort:** the largest — touches `celery_app.py`, both start scripts
(systemd units), `enrichment.py` (batch loop + pacing), `tasks.py`,
`config.py`, plus the shared Plan B pieces. Invasive in the worker startup
path, which is the riskiest place to break on the ThinkPad (a bad worker
flag = tower down); needs a careful deploy + same-day live verification.

**Impact:** 100 % of daytime browser lane for discovery **and** the detail
dataset keeps growing at full fidelity (just time-shifted). Best long-term
answer for the 1-lakh-scale mandate: the same window/queue pattern later
absorbs a second laptop per industry without redesign.

**Risk:** moderate — worker startup changes + overnight unattended
operation (mitigated: per-job commits, zombie reaper already exists, heat
governor already trusted overnight per standing ops).

---

## 6. Comparison & recommendation

| | Plan A — Kill switch | Plan B — Card-first + budget | Plan C — Night shift |
|---|---|---|---|
| Discovery gain | ~5–8× (max) | ~95 % of A | 100 % of A (daytime) |
| Experience bands for new jobs | "Not stated" | ✅ free via card + track stamp | ✅ same + full detail at night |
| Degrees/certs/domains (Vigil 2.0 seed) | ❌ paused | 🟡 trickle (60/day, guest-seen first) | ✅ full, time-shifted |
| description_text | ❌ paused | 🟡 trickle | ✅ full |
| Schema change | none | none | none |
| Components touched | tasks/config/runtime_settings | + schedule helper, Redis counter, pending-query order | + celery routing, start scripts, batch enricher |
| Reversibility | instant flag | instant flags | config window; routing additive |
| Risk | lowest | low-moderate | moderate (worker startup) |

**Akay recommendation: ship Plan B now, evolve to Plan C.**
Plan B delivers nearly all of the discovery throughput immediately, keeps
the guest-facing experience column honest for free, never fully stops the
Vigil 2.0 seed data, and every piece of it (flag, card extractor, priority
queue) is a prerequisite Plan C reuses unchanged. Plan A alone leaves
"Not stated" all over guest replies for no reason when the card extractor
is a small, browser-free addition.

**Sequencing if YES to B:** slice 1 = Plan A flag + card extractor (stops
the bleeding same-day) → slice 2 = budget/idle gate + priority queue →
slice 3 (later, separate YES) = Plan C night window.

---

## 7. Standing facts recorded

- Detail enrich is ~8–10× more browser-expensive per job than discovery;
  discovery-first is now the standing lane priority.
- `job_url` retention makes description-level enrichment backfillable for
  the lifetime of a LinkedIn posting (~30–60 days); roles/links/companies
  are never at risk when details pause.
- The guest fresher path is already NULL-band tolerant end-to-end
  (API + Telegram filter) — verified 2026-08-08.
