# Watch Tower v0 — portable backup of Akay's discovery engine
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

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
COPY start_pilot.sh stop_pilot.sh ./
RUN chmod +x start_pilot.sh stop_pilot.sh scripts/*.sh scripts/*.py || true

EXPOSE 8001

# Default: API only. Full scrape stack needs Chrome + Redis + Postgres
# (see docker-compose.yml). This image preserves application source + deps.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
