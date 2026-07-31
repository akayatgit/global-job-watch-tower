#!/usr/bin/env bash
# Bounce API + Celery only. Postgres, Redis, Ollama, .env, and .data stay up.
set -euo pipefail

cd "$(dirname "$0")"

source /home/user/anaconda3/etc/profile.d/conda.sh
conda activate ai

DATA_DIR="$(pwd)/.data"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR"

stop_one() {
  local name="$1"
  local pidfile="$DATA_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "[restart] stopping $name (pid $(cat "$pidfile"))..."
    kill "$(cat "$pidfile")" 2>/dev/null || true
    # Give graceful exit, then force if needed
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$(cat "$pidfile")" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      kill -9 "$(cat "$pidfile")" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  else
    rm -f "$pidfile"
    echo "[restart] $name was not running"
  fi
}

start_bg() {
  local name="$1"; shift
  echo "[restart] starting $name (log: $LOG_DIR/$name.log)"
  nohup "$@" >> "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$DATA_DIR/$name.pid"
}

echo "[restart] bouncing app processes (Postgres/Redis untouched)..."
stop_one beat
stop_one worker
stop_one api
sleep 1

start_bg api    uvicorn app.main:app --host 127.0.0.1 --port 8001
start_bg worker celery -A app.celery_app worker -c 1 --loglevel=INFO
start_bg beat   celery -A app.celery_app beat --loglevel=INFO

echo "[restart] done. Admin UI: http://127.0.0.1:8001"
