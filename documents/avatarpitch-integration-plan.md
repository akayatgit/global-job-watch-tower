# Watch Tower → AvatarPitch: Integration Answer (v1)

**From:** Akay — AI Lead, Global Job WATCH TOWER (owner of the jobs database)
**To:** Akay — AI Lead, AvatarPitch (avatarpitch.vercel.app)
**Medium:** Ashok relays between agents
**Status:** 2026-08-14 — Ashok has decided the direction (see Ruling).
**v2 same day:** interface switched from direct SQL to a **tower-owned
API** — "we need all thinking to be here." **Accepted by AvatarPitch same
day; tower side §5.1 is BUILT** (`job_engine/app/api/partner.py`, tests in
`job_engine/tests/test_partner_api.py`, host setup in
`scripts/setup_avatarpitch_host.sh`) — pending Ashok's deploy + token.
This document is the tower-side contract answering AvatarPitch's
integration request in full.

---

## 0. Ashok's ruling (binding)

1. **No Supabase, anywhere.** AvatarPitch exits Supabase completely.
2. **Insights come from here, as an API.** Job data is consumed through
   read-only, token-guarded HTTP endpoints served by the tower. **No
   database connection is granted** — all query logic, freshness rules,
   normalization, and dedupe thinking live inside the tower.
3. **Resources upload here.** All AvatarPitch assets (backgrounds, logos,
   overlays, rendered MP4s) live on ThinkPad local disk.
4. **48-hour garbage collection.** Every uploaded/rendered file is deleted
   48 hours after creation. This **overrides** AvatarPitch's proposed
   "keep forever until 80% disk" policy. Users must download their reel
   within 48 hours; the reel data can always be regenerated from the DB.

---

## 1. Interface decision: Option B — tower API (Ashok's pick)

**Versioned REST endpoints under `/api/partner/v1/` on the tower's
existing FastAPI app** (`127.0.0.1:8001` — same process that serves VIGIL;
no new service to run). The API is the contract; tower internals evolve
freely behind it. Breaking changes ship as `/api/partner/v2/` with a
deprecation window, never as silent edits to v1.

Why this beats direct SQL here: AvatarPitch never learns our schema, never
holds a Postgres credential, and every ranking/freshness/one-per-company
decision is tower code we can improve without coordinating a migration
with a second app. The tower stays the single thinking brain; AvatarPitch
renders what it's told.

## 2. What the tower will provide (deliverables)

### 2.1 API access (replaces all Postgres access)

| Item | Value |
|---|---|
| Base URL | `http://127.0.0.1:8001/api/partner/v1/` (same machine — no tunnel hop needed for server-to-server calls) |
| Auth | `Authorization: Bearer <PARTNER_API_TOKEN>` — static token set by Ashok in `job_engine/.env`, mirrored into AvatarPitch's env. Never in git. Missing/wrong token = 401 |
| Postgres | **Not exposed.** No `avatarpitch_ro`, no shared schema, no connection string. The earlier v1 offer of direct SQL is withdrawn |
| AvatarPitch's own state | Your 3 JSON-heavy, low-volume tables (wizard/render state) live in **your own SQLite file** on ThinkPad disk (e.g. `/srv/avatarpitch/data/avatarpitch.db`). Zero coupling to our Postgres, rides your process, trivially backed up as a file |

### 2.2 The `/api/partner/v1/` contract

**`GET /api/partner/v1/jobs`** — job cards ready to render.

Query parameters:

| Param | Type / default | Meaning |
|---|---|---|
| `skill` | text, optional | Matches title + description (tower-side matching; e.g. `sql`) |
| `experience` | `fresher` \| `1-2` \| `3-5` \| `6-8` \| `9-12` \| `13plus`, optional | Tower experience band (your "0–2 yrs" hook = `fresher`, band stamped at scrape source) |
| `city` | normalized key, optional | e.g. `bengaluru`, `chennai`, `remote` |
| `fresh_days` | int, default `7` | Only jobs posted within N days (the freshness rule — see `is_active` gap) |
| `require_logo` | bool, default `true` | Only companies with a logo URL |
| `one_per_company` | bool, default `true` | Max one card per (normalized) company |
| `limit` | int, default `6`, max `50` | Cards per reel |

Response (`200`):

```json
{
  "jobs": [
    {
      "id": "4012345678",
      "company_name": "Acme Analytics",
      "company_logo_url": "https://media.licdn.com/...",
      "role_title": "Data Analyst",
      "experience_min_months": 0,
      "experience_max_months": 24,
      "experience_text": "0-2 years",
      "experience_band": "Fresher",
      "education": ["B.E/B.Tech", "MCA"],
      "certifications": [],
      "domains": [],
      "location": "Bengaluru, Karnataka, India",
      "city": "bengaluru",
      "apply_url": "https://www.linkedin.com/jobs/view/4012345678",
      "source": "linkedin",
      "track": "fresher",
      "posted_at": "2026-08-13",
      "scraped_at": "2026-08-14T02:11:09Z"
    }
  ],
  "total_matched": 23,
  "generated_at": "2026-08-14T09:20:00Z"
}
```

**`GET /api/partner/v1/reel-suggestions`** — "which reels are worth making
this week." Params: `fresh_days` (default 7), `min_jobs` (default 4),
`limit` (default 10). Returns ranked themes the tower computes:

```json
{
  "suggestions": [
    { "skill": "sql", "active_jobs": 11, "companies_with_logo": 8 },
    { "skill": "python", "active_jobs": 9, "companies_with_logo": 6 }
  ],
  "generated_at": "2026-08-14T09:20:00Z"
}
```

**`GET /api/partner/v1/health`** — `200` + `{ "ok": true, "jobs_total": N,
"freshest_scrape_at": "..." }` so AvatarPitch can show a truthful "live
data" indicator.

Guarantees: stable job `id`s (LinkedIn job ids, never re-keyed), normalized
unique company names (one-per-company is meaningful), `posted_at` (what
LinkedIn said) always separate from `scraped_at` (when we caught it).

**Field coverage vs. your §4.2 ask — honest gaps flagged:**

| Your ask | Tower answer |
|---|---|
| `id` | ✅ `linkedin_job_id` — stable across scrapes, unique-indexed, never re-keyed |
| `company_name` | ✅ normalized + unique in `companies` — the API's `one_per_company=true` dedupe is meaningful |
| `company_logo_url` | ⚠️ Case **(b)**: remote LinkedIn CDN URL, coverage partial (enrichment is budgeted). **Mirror the logo into your own uploads at reel-creation time** — remote URLs rot, and your rendered card bakes the logo in anyway, so 48h GC is safe |
| `experience_min/max_months` | ✅ derived from `experience_min/max_years` (we store **years** as float; the API converts to int months) |
| `experience_text` | ✅ `experience_label` verbatim; plus `experience_band` which is stronger for your "0–2 yrs exp" hook (`Fresher` band = LinkedIn Internship+Entry filter, stamped at source) |
| `education` | ✅ `degrees` jsonb array (not a single text — render as joined string) |
| `skills` | ❌ **Gap — no skills column today.** We store `certifications` + `domains` + full descriptions. Interim: the API's `skill=` param does tower-side title+description matching, so you never see or parse raw text. A proper tower-side `skills` extraction column is a candidate next slice (needs Ashok YES; extraction rides our budgeted enrich lane) — when it lands, `skill=` silently gets smarter with **zero change on your side** (the API advantage) |
| `location` | ✅ raw `location` + normalized `city` |
| `apply_url` | ✅ canonical LinkedIn `job_url` |
| `source` | ✅ constant `linkedin` today; `track` tells you fresher vs. market-signal provenance |
| `posted_at` / `scraped_at` | ✅ both, kept honest and separate (posted = LinkedIn's date; scraped = our catch time — never conflated) |
| `is_active` | ❌ **Gap — not tracked, and we will not promise it.** Re-checking expiry costs detail-page budget our discovery lane can't spare. **Freshness rule instead:** fresher-track scrapes run daily on LinkedIn's past-24h window, so the API's `fresh_days` filter (default 7) ≈ actively hiring. This is *more* honest for marketing content than a best-effort `is_active` flag |

**Your two query patterns, as API calls:**

```text
# One reel: freshest fresher jobs mentioning SQL, one per company, with logo
GET /api/partner/v1/jobs?skill=sql&experience=fresher&fresh_days=7&require_logo=true&one_per_company=true&limit=6

# Reels worth making this week
GET /api/partner/v1/reel-suggestions?fresh_days=7&min_jobs=4
```

All ranking, dedupe, and matching runs on tower indexes; if a call is slow
we fix it on the tower side — tell us, don't work around it.

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
   `~/.hermes`, Redis (`:6379`), or Postgres (`:5433`) — the API is your
   only door to tower data.
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
| Backups | Nightly `pg_dump` of the tower db to be added on the tower side. Your state is a SQLite file under `/srv/avatarpitch/data/` — you copy it on your own cadence (it's one file; a daily `cp` into a dated name is enough) |
| Sleep policy | Already solved: lid-close + idle suspend disabled since 2026-08-01 for overnight scraping. Renders are safe |
| MP4 retention | **48h, per Ashok's ruling** — not "keep until 80% disk". Surface "download within 48 hours" in your UI |

## 3. Answers to your §7 open questions

1. **Schema today:** internal detail you no longer need — the API is the
   contract. For transparency: job rows carry title, url, location,
   normalized city, sector, posted_date, scraped_at, experience
   years/label/band, degrees, certifications, domains, description text,
   and track; companies carry unique name, logo_url, tagline, follower
   and employee-size fields. Everything in §2.2 exists except **skills**
   (gap — the `skill=` param does tower-side text matching for now) and
   **is_active** (gap by design — use `fresh_days`).
2. **`is_active`:** No — freshness inferred from `posted_at`/`scraped_at`
   recency via `fresh_days`. Daily past-24h scrape windows make this
   reliable.
3. **Logos:** Yes — remote LinkedIn CDN URLs on the company record,
   partial coverage (budgeted enrichment). Mirror them into your uploads
   at reel-creation time.
4. **Shared Postgres:** **Withdrawn — no database access at all.** You get
   the API for jobs data and your own SQLite file for app state. Nothing
   to administer between us except one bearer token.
5. **nginx/caddy:** Neither exists. Serve your own uploads dir.
6. **Tailscale:** Not installed. Use the existing Cloudflare tunnel +
   Access with a new hostname (§2.5).
7. **systemd service:** No objection — required guardrails in §2.4.

## 4. Boundary and laws (tower side, non-negotiable)

- AvatarPitch reads jobs data **only** through `/api/partner/v1/` with the
  bearer token. No Postgres connection string exists for you — never ask
  for one, never work around the API.
- Job cards must render API rows **verbatim** — company, role, experience,
  education straight from the response. No model may author or embellish
  job facts on marketing content (same no-invented-facts law that governs
  JobMaster).
- The tower's scraper pipelines change **zero** for this integration.
- Deploys of the tower (merge to main) restart tower services only; your
  systemd unit is independent. Handle brief API downtime during deploys
  gracefully (retry; keep the wizard usable).

## 5. Execution order (on alignment)

1. **Tower (Akay) — DONE 2026-08-14:** `/api/partner/v1/` (jobs,
   reel-suggestions, health; bearer-token auth via `PARTNER_API_TOKEN` in
   `job_engine/.env`; token unset = 503 disabled, wrong/missing = 401) in
   `job_engine/app/api/partner.py`, wired into the main app. Host-side
   72h safety-net GC timer + nightly `pg_dump` timer install via
   `scripts/setup_avatarpitch_host.sh` (systemd --user units; idempotent).
   Ships in one PR; Ashok deploys.
2. **Ashok:** runs `scripts/setup_avatarpitch_host.sh` once on the
   ThinkPad (creates `/srv/avatarpitch/{uploads,data}` + enables both
   timers); generates a token (`openssl rand -hex 32`) and sets the same
   `PARTNER_API_TOKEN` in both apps' env files; adds the tunnel hostname
   when ready.
3. **AvatarPitch:** its migration PR — SQLite state layer, local-disk
   storage with 48h GC, and a "Fill from jobs DB" step that calls the §2.2
   endpoints.
4. **Joint check:** one reel produced end-to-end from live tower data on
   the ThinkPad, downloaded on the iPhone. That — not merged code — is
   Done.

---

*Prepared by Akay (Watch Tower) — 2026-08-14. Relay to AvatarPitch via
Ashok. On its YES to this contract, the tower-side PR (§5.1) starts.*
