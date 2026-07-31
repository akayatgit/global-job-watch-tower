#!/usr/bin/env bash
# Start the full local pilot: Postgres, Redis, API/admin, Celery worker + beat.
# Everything runs on this machine — no cloud services.
set -euo pipefail

cd "$(dirname "$0")"

source /home/user/anaconda3/etc/profile.d/conda.sh
conda activate ai

DATA_DIR="$(pwd)/.data"
PG_DATA="$DATA_DIR/pgdata"
REDIS_DIR="$DATA_DIR/redis"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$PG_DATA" "$REDIS_DIR" "$LOG_DIR"

# ---------- Postgres (conda-installed, data + socket inside .data) ----------
if [ ! -f "$PG_DATA/PG_VERSION" ]; then
  echo "[pilot] initializing postgres data dir..."
  initdb -D "$PG_DATA" -U jobengine --auth=trust >/dev/null
fi

if ! pg_isready -h 127.0.0.1 -p 5433 >/dev/null 2>&1; then
  echo "[pilot] starting postgres..."
  pg_ctl -D "$PG_DATA" -l "$LOG_DIR/postgres.log" -o "-p 5433 -k $DATA_DIR" start
  sleep 2
fi

if ! psql -h 127.0.0.1 -p 5433 -U jobengine -lqt 2>/dev/null | cut -d '|' -f1 | grep -qw jobengine; then
  echo "[pilot] creating jobengine database..."
  createdb -h 127.0.0.1 -p 5433 -U jobengine jobengine
fi

# ---------- Redis (conda-installed) ----------
if ! redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "[pilot] starting redis..."
  redis-server --daemonize yes --port 6379 --dir "$REDIS_DIR" \
    --logfile "$LOG_DIR/redis.log" --save 300 10
  sleep 1
fi

# ---------- Migrations ----------
echo "[pilot] applying migrations..."
alembic upgrade head

# ---------- App processes ----------
start_bg() {
  local name="$1"; shift
  echo "[pilot] starting $name (log: $LOG_DIR/$name.log)"
  nohup "$@" >> "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$DATA_DIR/$name.pid"
}

already_running() {
  local name="$1"
  if [ -f "$DATA_DIR/$name.pid" ] && kill -0 "$(cat "$DATA_DIR/$name.pid")" 2>/dev/null; then
    echo "[pilot] $name already running (pid $(cat "$DATA_DIR/$name.pid"))"
    return 0
  fi
  return 1
}

already_running api    || start_bg api    uvicorn app.main:app --host 127.0.0.1 --port 8001
already_running worker || start_bg worker celery -A app.celery_app worker -c 1 --loglevel=INFO
already_running beat   || start_bg beat   celery -A app.celery_app beat --loglevel=INFO

echo
echo "[pilot] up. Admin UI:  http://127.0.0.1:8001"
echo "[pilot]     API docs:  http://127.0.0.1:8001/api/docs"
echo "[pilot]     Logs:      $LOG_DIR"
echo "[pilot] stop with:     ./stop_pilot.sh"
echo
echo "[pilot] streaming logs below (Ctrl+C exits the log view; services keep running)"
echo "----------------------------------------------------------------------"
exec tail -n 5 -F "$LOG_DIR/api.log" "$LOG_DIR/worker.log" "$LOG_DIR/beat.log"
