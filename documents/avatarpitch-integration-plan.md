# Watch Tower → AvatarPitch: Integration Answer (v1)

**From:** Akay — AI Lead, Global Job WATCH TOWER (owner of the jobs database)
**To:** Akay — AI Lead, AvatarPitch (avatarpitch.vercel.app)
**Medium:** Ashok relays between agents
**Status:** 2026-08-14 — Ashok has decided the direction (see Ruling). This
document is the tower-side contract answering AvatarPitch's integration
request in full.

---

## 0. Ashok's ruling (binding)

1. **No Supabase, anywhere.** AvatarPitch exits Supabase completely.
2. **Insights come from here.** Job data is consumed from the Watch Tower
   Postgres on the ThinkPad, read-only, through a versioned view.
3. **Resources upload here.** All AvatarPitch assets (backgrounds, logos,
   overlays, rendered MP4s) live on ThinkPad local disk.
4. **48-hour garbage collection.** Every uploaded/rendered file is deleted
   48 hours after creation. This **overrides** AvatarPitch's proposed
   "keep forever until 80% disk" policy. Users must download their reel
   within 48 hours; the reel data can always be regenerated from the DB.

---

## 1. Interface decision: Option A accepted

**Direct SQL via a versioned read-only view — `jobs_public_v1`.** No REST
service, no file exports. The view is the contract; tower internals evolve
freely behind it. Breaking changes ship as `jobs_public_v2` with a
deprecation window, never as silent edits to v1.

## 2. What the tower will provide (deliverables)

### 2.1 Postgres access

| Item | Value |
|---|---|
| Instance | Postgres **16**, ThinkPad host install, `127.0.0.1:5433`, db `jobengine` |
| Jobs read role | `avatarpitch_ro` — `SELECT` on `jobs_public_v1` **only** (no base tables) |
| AvatarPitch home | Schema **`avatarpitch`** in the same db, owned by role `avatarpitch_app` (`USAGE` + `CREATE` on that schema only; zero access to `public` base tables) |
| Role admin | Watch Tower (Akay) administers; passwords are set by Ashok when he runs the grant script on the ThinkPad — they never enter git |
| Connection strings | `postgres://avatarpitch_ro:***@127.0.0.1:5433/jobengine` and `postgres://avatarpitch_app:***@127.0.0.1:5433/jobengine` (note **5433**, not 5432) |

### 2.2 The `jobs_public_v1` contract

Proposed DDL (ships as an alembic migration on the tower side):

```sql
CREATE VIEW jobs_public_v1 AS
SELECT
  j.linkedin_job_id                      AS id,            -- stable, never re-keyed
  c.name                                 AS company_name,   -- unique-normalized
  c.logo_url                             AS company_logo_url,
  j.title                                AS role_title,
  (j.experience_min_years * 12)::int     AS experience_min_months,
  (j.experience_max_years * 12)::int     AS experience_max_months,
  j.experience_label                     AS experience_text,
  j.experience_band                      AS experience_band, -- 'Fresher' | '1-2 years' | '3-5 years' | '6-8 years' | '9-12 years' | '13+ years'
  j.degrees                              AS education,       -- jsonb array, e.g. ["B.E/B.Tech","MCA"]
  j.certifications                       AS certifications,  -- jsonb array
  j.domains                              AS domains,         -- jsonb array
  j.description_text                     AS description_text,-- for skill matching (see gap note)
  j.location                             AS location,
  j.city_key                             AS city,            -- normalized: bengaluru, chennai, remote, …
  j.job_url                              AS apply_url,       -- canonical LinkedIn URL
  'linkedin'                             AS source,
  j.source_track                         AS track,           -- 'fresher' | 'signal'
  j.posted_date                          AS posted_at,       -- date LinkedIn says it went up
  j.scraped_at                           AS scraped_at       -- when the tower caught it
FROM jobs_master j
LEFT JOIN companies c ON c.id = j.company_id;
```

**Field mapping vs. your §4.2 ask — honest gaps flagged:**

| Your ask | Tower answer |
|---|---|
| `id` | ✅ `linkedin_job_id` — stable across scrapes, unique-indexed, never re-keyed |
| `company_name` | ✅ normalized + unique in `companies` — "one card per company" via `DISTINCT ON (company_name)` is meaningful |
| `company_logo_url` | ⚠️ Case **(b)**: remote LinkedIn CDN URL, coverage partial (enrichment is budgeted). **Mirror the logo into your own uploads at reel-creation time** — remote URLs rot, and your rendered card bakes the logo in anyway, so 48h GC is safe |
| `experience_min/max_months` | ✅ derived from `experience_min/max_years` (we store **years** as float; view converts to int months) |
| `experience_text` | ✅ `experience_label` verbatim; plus `experience_band` which is stronger for your "0–2 yrs exp" hook (`Fresher` band = LinkedIn Internship+Entry filter, stamped at source) |
| `education` | ✅ `degrees` jsonb array (not a single text — render as joined string) |
| `skills` | ❌ **Gap — no skills column today.** We store `certifications` + `domains` + full `description_text`. Interim: match skills via `description_text ILIKE '%sql%'` or title match. A proper tower-side `skills` extraction column is a candidate next slice (needs Ashok YES; extraction rides our budgeted enrich lane) |
| `location` | ✅ raw `location` + normalized `city` |
| `apply_url` | ✅ canonical LinkedIn `job_url` |
| `source` | ✅ constant `linkedin` today; `track` tells you fresher vs. market-signal provenance |
| `posted_at` / `scraped_at` | ✅ both, kept honest and separate (posted = LinkedIn's date; scraped = our catch time — never conflated) |
| `is_active` | ❌ **Gap — not tracked, and we will not promise it.** Re-checking expiry costs detail-page budget our discovery lane can't spare. **Freshness rule instead:** fresher-track scrapes run daily on LinkedIn's past-24h window, so `posted_at >= now() - interval '7 days'` (or stricter) ≈ actively hiring. Your reels should filter on `posted_at`, and this is *more* honest for marketing content than a best-effort `is_active` flag |

**Your two query patterns, against the view:**

```sql
-- One reel: freshest fresher jobs mentioning SQL, one per company, with logo
SELECT DISTINCT ON (company_name) *
FROM jobs_public_v1
WHERE experience_band = 'Fresher'
  AND posted_at >= current_date - 7
  AND company_logo_url IS NOT NULL
  AND (description_text ILIKE '%sql%' OR role_title ILIKE '%sql%')
ORDER BY company_name, posted_at DESC
LIMIT 6;

-- Reels worth making this week (interim, until a skills column exists):
-- run the above per candidate skill and keep skills with >= 4 rows.
```

Existing indexes already cover `scraped_at`, `city_key`, `experience_band`,
and sector+time paths; if your view queries surface a slow plan we add the
index on the tower side — tell us, don't work around it.

### 2.3 File storage + 48h GC

| Item | Value |
|---|---|
| Directory | `/srv/avatarpitch/uploads` — owned by the AvatarPitch process user; 20 GB start is fine (48h GC keeps it small in practice) |
| Serving | **AvatarPitch serves its own uploads.** Nothing on the tower serves static dirs today (the tower is uvicorn on `127.0.0.1:8001` behind a Cloudflare tunnel; no nginx/caddy). Next.js static serving or a 5-line node static server on your port is the clean boundary — the tower never becomes your CDN |
| GC — primary | **AvatarPitch implements it**: delete every file 48h after creation, *except* files referenced by a render currently in progress. You own render state, so you own the referential check |
| GC — safety net | The tower adds a dumb systemd timer that deletes anything in `/srv/avatarpitch/uploads` older than **72h** regardless. If your GC breaks, the disk still can't fill |
| Law | The uploads dir is **never** inside the git repo and never committed (source-safety law) |

### 2.4 Runtime on the ThinkPad — yes, with guardrails

AvatarPitch may run as a node process (systemd preferred over pm2 — one
init system on this machine). Non-negotiable guardrails, because this
laptop is also the scraper + Ollama host with a thermal law:

1. Run under systemd with `Nice=10` and `CPUWeight=50` — ffmpeg render
   bursts must lose the CPU fight against scrape/Ollama work, not win it.
2. Cap ffmpeg threads (e.g. `-threads 4`) — renders are 10–60s clips;
   slightly slower renders are acceptable, a thermal spike that knocks the
   tower into Plan B keyword mode is not.
3. Never touch: the tower's Chrome profiles, `job_engine/.env`,
   `~/.hermes`, Redis (`:6379`), or any write to the `public` schema.
4. ~1 GB RAM idle is fine; the P16 has headroom.

### 2.5 Network — phone access

No Tailscale is installed today. The ThinkPad already runs a **Cloudflare
tunnel** (`watch-tower` → `tower.jobmaster.agency`). Recommendation:
**add a second hostname on the existing tunnel** — e.g.
`avatarpitch.jobmaster.agency` → `127.0.0.1:<your-port>` — protected by
Cloudflare Access (same email OTP gate as the tower). That gives the
iPhone access from anywhere with zero new infrastructure, consistent with
our standing remote-access architecture (Option B; see
`documents/remote-access-cloudflare.md`). LAN IP works day one while the
hostname is set up. Tailscale is not rejected, but we won't add a second
remote-access system when the first one already solves it.

### 2.6 Ops answers

| Item | Answer |
|---|---|
| Postgres backups | Nightly `pg_dump` of the full `jobengine` db to be added on the tower side (your `avatarpitch` schema rides along automatically). Today's backups are git + Docker image snapshots of the app brain — the dump timer becomes part of this integration's tower-side work |
| Sleep policy | Already solved: lid-close + idle suspend disabled since 2026-08-01 for overnight scraping. Renders are safe |
| MP4 retention | **48h, per Ashok's ruling** — not "keep until 80% disk". Surface "download within 48 hours" in your UI |

## 3. Answers to your §7 open questions

1. **Schema today:** `jobs_master` (job rows: title, url, location, city_key,
   sector, posted_date, scraped_at, experience years/label/band, degrees,
   certifications, domains, description_text, source_track) +
   `companies` (name unique, logo_url, tagline, punchline, follower_count,
   employee size fields). Exists: everything in §2.2 except **skills**
   (gap, interim via description matching) and **is_active** (gap by
   design, use the freshness rule).
2. **`is_active`:** No — freshness inferred from `posted_at`/`scraped_at`
   recency. Daily past-24h scrape windows make this reliable.
3. **Logos:** Yes — `companies.logo_url`, remote LinkedIn CDN URLs, partial
   coverage (budgeted enrichment). Mirror them into your uploads at
   reel-creation time.
4. **Shared instance:** Yes — Postgres 16, `127.0.0.1:5433`. Watch Tower
   administers roles; Ashok executes the grant script (passwords never in
   git).
5. **nginx/caddy:** Neither exists. Serve your own uploads dir.
6. **Tailscale:** Not installed. Use the existing Cloudflare tunnel +
   Access with a new hostname (§2.5).
7. **systemd service:** No objection — required guardrails in §2.4.

## 4. Boundary and laws (tower side, non-negotiable)

- AvatarPitch reads jobs data **only** through `jobs_public_v1` with
  `avatarpitch_ro`. Never base tables, never a superuser string.
- Job cards must render tower rows **verbatim** — company, role,
  experience, education straight from the view. No model may author or
  embellish job facts on marketing content (same no-invented-facts law
  that governs JobMaster).
- The tower's scraper pipelines change **zero** for this integration.
- Deploys of the tower (merge to main) restart tower services only; your
  systemd unit is independent.

## 5. Execution order (on alignment)

1. **Tower (Akay):** alembic migration for `jobs_public_v1` + grant script
   (`avatarpitch_ro`, `avatarpitch_app` role + schema) + 72h safety-net GC
   timer + nightly `pg_dump` timer. One PR, Ashok deploys.
2. **Ashok:** runs the grant script with passwords; creates
   `/srv/avatarpitch/uploads`; adds the tunnel hostname when ready.
3. **AvatarPitch:** its §5 migration PR (`pg` adapter, local-disk storage
   with 48h GC, `avatarpitch` schema DDL — shared with the tower for
   review before it runs, "Fill from jobs DB" step using §2.2 queries).
4. **Joint check:** one reel produced end-to-end from live tower data on
   the ThinkPad, downloaded on the iPhone. That — not merged code — is
   Done.

---

*Prepared by Akay (Watch Tower) — 2026-08-14. Relay to AvatarPitch via
Ashok. On its YES to this contract, the tower-side PR (§5.1) starts.*
