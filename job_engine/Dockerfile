# Watch Tower — plug-and-play image (Gate 1.1).
# Build context = repo root:  docker build -f job_engine/Dockerfile .
# Ships API + VIGIL UI + Celery worker/beat code. Browser scraping and
# Ollama stay host-side by design (documents/docker-plug-and-play.md).

# ---------- Stage 1: VIGIL UI (vite build) ----------
FROM node:20-alpine AS vigil
WORKDIR /vigil
COPY job_engine/vigil/package.json job_engine/vigil/package-lock.json ./
RUN npm ci
COPY job_engine/vigil/ ./
RUN npm run build

# ---------- Stage 2: Python app ----------
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HEADLESS=true \
    RELEVANCE_MODE=keyword

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY job_engine/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
# Upstream wart (2026-08): scrapling pins Chrome 148/149 user-agents but its
# data dependency (apify-fingerprint-datapoints 0.14.0) only ships headers up
# to Chrome 141 — so `import scrapling.fetchers` crashes a fresh install with
# "No headers based on this input can be generated". Pin the two UA version
# constants down to 141 (present in the data). Harmless once upstream data
# catches up; only affects default user-agent strings, and real LinkedIn
# scraping stays host-side anyway (documents/docker-plug-and-play.md).
RUN sed -i -E 's/^(chromium_version|chrome_version) = [0-9]+/\1 = 141/' \
      /usr/local/lib/python3.12/site-packages/scrapling/engines/toolbelt/fingerprints.py \
    && python -c "from scrapling.fetchers import StealthySession; print('scrapling fetchers import OK')"

COPY job_engine/alembic.ini ./
COPY job_engine/alembic ./alembic
COPY job_engine/app ./app
COPY job_engine/scripts ./scripts
COPY job_engine/start_pilot.sh job_engine/stop_pilot.sh ./
RUN chmod +x start_pilot.sh stop_pilot.sh scripts/*.sh scripts/*.py || true

# Orb color + rail footer read the repo-root VERSION (app/version_info.py
# resolves it two levels above app/, i.e. /VERSION in this image).
COPY VERSION /VERSION

# VIGIL UI served by FastAPI from vigil/dist (app/ultron/routes.py)
COPY --from=vigil /vigil/dist ./vigil/dist

EXPOSE 8001

# Default: API + VIGIL. Compose overrides command for worker/beat/migrate.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
