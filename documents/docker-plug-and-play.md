# Watch Tower — Docker plug-and-play (Gate 1.1)

| Field | Value |
|---|---|
| Status | **Verified 2026-08-04** — full stack booted from scratch on a blank cloud VM (no ThinkPad) |
| Image | `watch-tower:v1` (multi-stage: VIGIL vite build + Python app) |
| One command | `docker compose -f job_engine/docker-compose.yml up --build` |
| VIGIL | http://localhost:8002 |

## What boots (all in containers)

| Service | What it does |
|---|---|
| `db` | Postgres 16 (volume `wt_pgdata`, host port 5434) |
| `redis` | Redis 7 (host port 6380) |
| `migrate` | One-shot `alembic upgrade head` — everything waits for it |
| `api` | FastAPI + **VIGIL UI** (built into the image, no npm on host) |
| `worker` | Celery worker (`-c 1`, browser-scale) |
| `beat` | Celery beat (search scheduler + enrich backfills) |

Boot order is enforced: `db` healthy → `migrate` completes → `api`/`worker`/`beat` start.
API healthcheck: `GET /api/deploy/status` (no DB, no auth).

## What stays on the host — by design

| Host-only | Why |
|---|---|
| Chrome bot profile + real LinkedIn scraping | Stealth profile lives in `~/.config/google-chrome-linkedin`; scrape jobs queued in-container will fail without it — that's expected |
| Ollama relevance | No GPU in container; image defaults `RELEVANCE_MODE=keyword` (Plan B). Point `OLLAMA_*` env at a host Ollama to restore quality mode |
| `~/.hermes` Telegram gateway | COURIER/DIRECTOR run beside the repo on the ThinkPad, not in this image |
| Secrets | Nothing baked in — `.env` files are dockerignored; pass env via compose |

## Build details worth knowing

- **Build context = repo root** (`job_engine/Dockerfile`, `.dockerignore` at
  root) so the image carries the repo `VERSION` → rail footer + orb color
  work in-container (verified: vitals.version showed v10 purple).
- **VIGIL** builds in a `node:20-alpine` stage (`npm ci && npm run build`);
  FastAPI serves `vigil/dist` — a fresh laptop needs no Node at all.
- **scrapling UA pin patch:** scrapling 0.4.x pins Chrome 148/149 user-agents
  but its data package (`apify-fingerprint-datapoints` 0.14.0) only ships
  headers up to Chrome 141, so a *fresh* install crashes on import. The
  Dockerfile seds both version constants to 141 and proves the import during
  build. Drop the patch once upstream data catches up. (ThinkPad never hit
  this — its scrapling predates the bad pin.)

## Smoke checks (run after `up`)

```bash
docker compose -f job_engine/docker-compose.yml ps        # api healthy, migrate Exited (0)
curl -s http://localhost:8002/ | head -3                   # VIGIL index.html
curl -s http://localhost:8002/api/ultron/status | head -c 300  # vitals + version
docker compose -f job_engine/docker-compose.yml logs worker | grep ready
```

## Milestone image convention

Tag a known-good image alongside each locked milestone
(`docker tag watch-tower:v1 watch-tower:eureka` etc.) and keep the offline
`backups/watch-tower-v0.tar.gz` era artifacts — this compose replaces that
backup-only role with a bootable tower.
