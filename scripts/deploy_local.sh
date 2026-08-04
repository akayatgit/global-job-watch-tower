#!/usr/bin/env bash
# Deploy origin/main onto this ThinkPad live tree.
# Deploy is highest priority: pause beat, cancel in-flight searches
# (LinkedIn job ids prevent duplicates on retrigger), pull, migrate,
# restart, then re-queue the cancelled roles.
set -euo pipefail

REPO_ROOT="/home/user/Documents"
JOB_ENGINE="$REPO_ROOT/job_engine"
DATA_DIR="$JOB_ENGINE/.data"
LOG_DIR="$DATA_DIR/logs"
LOCK_FILE="$DATA_DIR/deploy.lock"
DEPLOY_LOG="$LOG_DIR/deploy.log"
STAMP_FILE="$DATA_DIR/last_deploy.json"
RETRIGGER_FILE="$DATA_DIR/deploy_retrigger_configs.txt"

mkdir -p "$LOG_DIR"

log() {
  local line="[deploy $(date -Iseconds)] $*"
  echo "$line" | tee -a "$DEPLOY_LOG"
}

die() {
  log "ERROR: $*"
  exit 1
}

# Exclusive lock — overlapping deploys are refused
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  die "another deploy is already running (lock: $LOCK_FILE)"
fi

# Actions runner is a system service — talk to user systemd for pause/restart
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
export PGPASSWORD="${PGPASSWORD:-}"

log "=== Watch Tower deploy start ==="
cd "$REPO_ROOT"

# Refuse unexpected dirty tracked files (ignored .env/.data are fine).
# documents/briefs/ is cron-regenerated output (hermes_daily_brief.py writes
# it directly, no commit) — a local edit there is expected noise, not a real
# change to protect. Treating it as fatal wedged every deploy for 2 days
# (2026-08-02..08-04) since this very check ran *before* the fix could be
# pulled. See documents/deploy-verification.md.
DIRTY="$(git status --porcelain --untracked-files=no -- . ':!documents/briefs' 2>/dev/null || true)"
if [ -n "$DIRTY" ]; then
  log "dirty tracked files:"
  echo "$DIRTY" | tee -a "$DEPLOY_LOG"
  die "working tree has local tracked changes — commit/stash before deploy"
fi
git checkout -- documents/briefs 2>/dev/null || true

source /home/user/anaconda3/etc/profile.d/conda.sh
conda activate ai

psql_q() {
  psql -h 127.0.0.1 -p 5433 -U jobengine -d jobengine -Atqc "$1" 2>/dev/null || true
}

stop_beat() {
  log "pausing beat so no new searches enqueue..."
  systemctl --user stop watch-tower-beat.service 2>/dev/null || true
  local pidfile="$DATA_DIR/beat.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
  fi
  pkill -f 'celery -A app.celery_app beat' 2>/dev/null || true
}

stop_worker() {
  log "stopping worker so in-flight scrape releases the laptop..."
  systemctl --user stop watch-tower-worker.service 2>/dev/null || true
  local pidfile="$DATA_DIR/worker.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
  fi
  pkill -f 'celery -A app.celery_app worker' 2>/dev/null || true
  # Chrome scrape children often linger briefly
  sleep 1
}

cancel_active_for_deploy() {
  : > "$RETRIGGER_FILE"
  if ! pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
    log "Postgres not ready — skip cancel/retrigger bookkeeping"
    return
  fi
  # Capture distinct roles to re-run after deploy (job ids dedupe LinkedIn rows)
  psql_q "
    SELECT DISTINCT search_config_id
    FROM scrape_runs
    WHERE status IN ('queued','dispatched','running','cancel_requested')
      AND search_config_id IS NOT NULL
    ORDER BY 1;
  " > "$RETRIGGER_FILE"

  local n
  n="$(psql_q "
    UPDATE scrape_runs
    SET status='cancelled', finished_at=now(),
        error='cancelled for deploy — will retrigger after restart'
    WHERE status IN ('queued','dispatched','running','cancel_requested')
    RETURNING id;
  " | wc -l | tr -d ' ')"
  log "cancelled active searches: ${n:-0} (roles to retrigger: $(wc -l < "$RETRIGGER_FILE" | tr -d ' '))"

  # Drop queued Celery messages so cancelled run ids cannot resurrect
  (
    cd "$JOB_ENGINE"
    python3 - <<'PY' 2>/dev/null || true
from app.celery_app import celery as celery_app
n = celery_app.control.purge()
print(n if n is not None else 0)
PY
  ) | while read -r purged; do
    log "purged celery messages: ${purged:-0}"
  done
}

retrigger_cancelled() {
  if [ ! -s "$RETRIGGER_FILE" ]; then
    log "no searches to retrigger"
    return
  fi
  log "retriggering cancelled roles after deploy..."
  (
    cd "$JOB_ENGINE"
    RETRIGGER_FILE="$RETRIGGER_FILE" python3 - <<'PY'
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ScrapeRun, SearchConfig
from app.tasks import run_scrape

path = Path(os.environ["RETRIGGER_FILE"])
ids = []
for line in path.read_text().splitlines():
    line = line.strip()
    if line.isdigit():
        ids.append(int(line))
ids = sorted(set(ids))
if not ids:
    print("retriggered=0")
    raise SystemExit(0)

now = datetime.now(timezone.utc)
n = 0
with SessionLocal() as db:
    for cid in ids:
        cfg = db.get(SearchConfig, cid)
        if cfg is None or not cfg.enabled:
            print(f"skip config {cid} (missing or disabled)")
            continue
        busy = db.execute(
            select(ScrapeRun.id).where(
                ScrapeRun.search_config_id == cid,
                ScrapeRun.status.in_(("queued", "dispatched", "running", "cancel_requested")),
            ).limit(1)
        ).scalar_one_or_none()
        if busy is not None:
            print(f"skip config {cid} (already busy as run #{busy})")
            continue
        run = ScrapeRun(
            search_config_id=cid,
            run_type="one_off",
            scheduled_for=None,
            target_date=now.date(),
            status="dispatched",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_scrape.delay(run.id)
        print(f"retriggered config {cid} as run #{run.id}")
        n += 1
print(f"retriggered={n}")
PY
  ) | tee -a "$DEPLOY_LOG"
  rm -f "$RETRIGGER_FILE"
}

# Critical: pause schedule, cancel everything active, kill worker — deploy wins
stop_beat
cancel_active_for_deploy
stop_worker

BEFORE_SHA="$(git rev-parse HEAD)"
log "fetching origin/main (was $BEFORE_SHA)..."
git fetch origin main
git reset --hard origin/main
AFTER_SHA="$(git rev-parse HEAD)"
log "code aligned to $AFTER_SHA"

# Defense in depth: the Action ran for a specific push, so if this deploy
# somehow lands on a different HEAD than that push (double-push race,
# stale runner queue), fail loud instead of silently reporting "ok".
if [ -n "${GITHUB_SHA:-}" ] && [ "$AFTER_SHA" != "$GITHUB_SHA" ]; then
  log "WARNING: deployed HEAD ($AFTER_SHA) != triggering commit (\$GITHUB_SHA=$GITHUB_SHA)"
  log "another push landed on origin/main between trigger and pull — deploying the newer commit is correct, continuing"
fi

cd "$JOB_ENGINE"
log "applying migrations..."
alembic upgrade head

log "restarting api/worker/beat..."
bash "$JOB_ENGINE/restart_app.sh" | tee -a "$DEPLOY_LOG"

# --- Hermes gateway (Telegram bot) ---------------------------------------
# 1) The repo-side allowlist (app/telegram_guests.py, enforced in
#    hermes_plugins/vigil-image-only) owns Telegram access control. Hermes
#    must let every message through to reach that gate — flip its own
#    hard-coded gate open. This was a manual ThinkPad step (kanban card #1,
#    wife/investor demo failure 2026-08-04); now every deploy enforces it.
# 2) Plugin code ships with this repo but only loads on gateway restart —
#    so restart the gateway on every deploy, same as api/worker/beat.
ensure_hermes_gateway() {
  local envf="$HOME/.hermes/.env"
  local hermes_bin="$HOME/.local/bin/hermes"
  [ -x "$hermes_bin" ] || hermes_bin="$(command -v hermes || true)"
  if [ ! -f "$envf" ] || [ -z "$hermes_bin" ]; then
    log "hermes not set up on this host — skipping gateway step"
    return
  fi
  if grep -q '^TELEGRAM_ALLOW_ALL_USERS=true$' "$envf"; then
    log "hermes gate already open (allow-all=true; repo allowlist owns access)"
  else
    if grep -q '^TELEGRAM_ALLOW_ALL_USERS=' "$envf"; then
      sed -i 's/^TELEGRAM_ALLOW_ALL_USERS=.*/TELEGRAM_ALLOW_ALL_USERS=true/' "$envf"
    else
      printf '\nTELEGRAM_ALLOW_ALL_USERS=true\n' >> "$envf"
    fi
    log "flipped TELEGRAM_ALLOW_ALL_USERS=true in ~/.hermes/.env"
  fi
  log "restarting hermes gateway (reload plugin + env)..."
  if "$hermes_bin" gateway restart >>"$DEPLOY_LOG" 2>&1; then
    log "hermes gateway restarted"
  else
    log "WARNING: hermes gateway restart failed — Telegram bot may be running stale plugin/env"
  fi
}
ensure_hermes_gateway

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

retrigger_cancelled

python3 - <<PY | tee "$STAMP_FILE" | tee -a "$DEPLOY_LOG"
import json
from datetime import datetime, timezone
print(json.dumps({
    "deployed_at": datetime.now(timezone.utc).isoformat(),
    "before_sha": "$BEFORE_SHA",
    "sha": "$AFTER_SHA",
    "triggering_sha": "${GITHUB_SHA:-}" or None,
    "status": "ok",
    "policy": "cancel-active-then-retrigger",
}, indent=2))
PY

log "=== Watch Tower deploy OK @ $AFTER_SHA ==="
