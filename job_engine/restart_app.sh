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
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      echo "[restart] stopping $name (pid $pid)..."
      kill "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      echo "[restart] $name pidfile stale — clearing"
    fi
    rm -f "$pidfile"
  else
    echo "[restart] $name had no pidfile"
  fi
}

# Also clear orphans that outlived pidfiles (common after manual starts)
echo "[restart] clearing orphan api/worker/beat if any..."
pkill -f 'uvicorn app.main:app --host 127.0.0.1 --port 8001' 2>/dev/null || true
pkill -f 'celery -A app.celery_app worker' 2>/dev/null || true
pkill -f 'celery -A app.celery_app beat' 2>/dev/null || true
# Free the admin port in case a nameless child still holds it
fuser -k 8001/tcp 2>/dev/null || true
sleep 1

start_bg() {
  local name="$1"; shift
  local logfile="$LOG_DIR/$name.log"
  local pidfile="$DATA_DIR/$name.pid"
  local workdir
  workdir="$(pwd)"
  echo "[restart] starting $name (log: $logfile)"
  # setsid --fork: new session so GitHub Actions job teardown cannot kill the tower
  setsid --fork bash -c "
    echo \$\$ > '$pidfile'
    cd '$workdir' || exit 1
    exec \"\$@\" >>'$logfile' 2>&1
  " bash "$@"
  sleep 0.4
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "[restart] $name up (pid $(cat "$pidfile"))"
  else
    echo "[restart] WARNING: $name failed to stay up — see $logfile"
    return 1
  fi
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
