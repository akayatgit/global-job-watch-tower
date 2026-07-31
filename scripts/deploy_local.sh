#!/usr/bin/env bash
# Deploy origin/main onto this ThinkPad live tree.
# Waits for scrape idle, pulls code, migrates, restarts api/worker/beat only.
set -euo pipefail

REPO_ROOT="/home/user/Documents"
JOB_ENGINE="$REPO_ROOT/job_engine"
DATA_DIR="$JOB_ENGINE/.data"
LOG_DIR="$DATA_DIR/logs"
LOCK_FILE="$DATA_DIR/deploy.lock"
DEPLOY_LOG="$LOG_DIR/deploy.log"
STAMP_FILE="$DATA_DIR/last_deploy.json"
WAIT_CAP_S=$((45 * 60))
WAIT_POLL_S=15

mkdir -p "$LOG_DIR"

log() {
  local line="[deploy $(date -Iseconds)] $*"
  echo "$line" | tee -a "$DEPLOY_LOG"
}

die() {
  log "ERROR: $*"
  exit 1
}

# Exclusive lock — overlapping deploys are refused / queued by flock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  die "another deploy is already running (lock: $LOCK_FILE)"
fi

log "=== Watch Tower deploy start ==="
cd "$REPO_ROOT"

# Refuse unexpected dirty tracked files (ignored .env/.data are fine)
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  log "dirty tracked files:"
  git status --porcelain --untracked-files=no | tee -a "$DEPLOY_LOG"
  die "working tree has local tracked changes — commit/stash before deploy"
fi

source /home/user/anaconda3/etc/profile.d/conda.sh
conda activate ai

active_scrape_count() {
  if ! pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
    echo 0
    return
  fi
  psql -h 127.0.0.1 -p 5433 -U jobengine -d jobengine -Atqc \
    "SELECT COUNT(*) FROM scrape_runs WHERE status IN ('queued','dispatched','running','cancel_requested');" \
    2>/dev/null || echo 0
}

log "waiting for scrape idle (cap ${WAIT_CAP_S}s)..."
elapsed=0
while true; do
  count="$(active_scrape_count)"
  if [ "${count:-0}" -eq 0 ]; then
    log "scrape idle (active runs: 0)"
    break
  fi
  if [ "$elapsed" -ge "$WAIT_CAP_S" ]; then
    die "timed out after ${WAIT_CAP_S}s waiting for idle (still $count active)"
  fi
  log "active scrapes: $count — sleeping ${WAIT_POLL_S}s (${elapsed}s elapsed)"
  sleep "$WAIT_POLL_S"
  elapsed=$((elapsed + WAIT_POLL_S))
done

BEFORE_SHA="$(git rev-parse HEAD)"
log "fetching origin/main (was $BEFORE_SHA)..."
git fetch origin main
git reset --hard origin/main
AFTER_SHA="$(git rev-parse HEAD)"
log "code aligned to $AFTER_SHA"

cd "$JOB_ENGINE"
log "applying migrations..."
alembic upgrade head

log "restarting api/worker/beat..."
bash "$JOB_ENGINE/restart_app.sh" | tee -a "$DEPLOY_LOG"

# Health check
ok=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:8001/" 2>/dev/null \
    || curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:8001/api/docs" 2>/dev/null; then
    ok=1
    break
  fi
  sleep 1
done

for name in api worker beat; do
  pidfile="$DATA_DIR/$name.pid"
  if [ ! -f "$pidfile" ] || ! kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    die "$name failed to stay up after restart"
  fi
done

if [ "$ok" -ne 1 ]; then
  die "HTTP health check failed on :8001"
fi

python3 - <<PY | tee "$STAMP_FILE" | tee -a "$DEPLOY_LOG"
import json
from datetime import datetime, timezone
print(json.dumps({
    "deployed_at": datetime.now(timezone.utc).isoformat(),
    "before_sha": "$BEFORE_SHA",
    "sha": "$AFTER_SHA",
    "status": "ok",
}, indent=2))
PY

log "=== Watch Tower deploy OK @ $AFTER_SHA ==="
