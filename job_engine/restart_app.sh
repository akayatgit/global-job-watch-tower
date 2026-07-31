#!/usr/bin/env bash
# Bounce API + Celery only. Postgres, Redis, Ollama, .env, and .data stay up.
# Starts via systemd --user so GitHub Actions job teardown cannot kill the tower.
set -euo pipefail

cd "$(dirname "$0")"

# Actions runner is a system service — point at the login user's systemd bus
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

source /home/user/anaconda3/etc/profile.d/conda.sh
conda activate ai

DATA_DIR="$(pwd)/.data"
LOG_DIR="$DATA_DIR/logs"
WORKDIR="$(pwd)"
AI_BIN="/home/user/anaconda3/envs/ai/bin"
mkdir -p "$LOG_DIR"

stop_unit() {
  local name="$1"
  local unit="watch-tower-${name}"
  if systemctl --user list-units --all --no-legend "$unit.service" 2>/dev/null | grep -q .; then
    echo "[restart] stopping $unit..."
    systemctl --user stop "$unit.service" 2>/dev/null || true
  fi
  systemctl --user reset-failed "$unit.service" 2>/dev/null || true
  rm -f "$DATA_DIR/$name.pid"
}

# Clear orphans from older nohup/setsid starts
echo "[restart] clearing orphan api/worker/beat if any..."
pkill -f 'uvicorn app.main:app --host 127.0.0.1 --port 8001' 2>/dev/null || true
pkill -f 'celery -A app.celery_app worker' 2>/dev/null || true
pkill -f 'celery -A app.celery_app beat' 2>/dev/null || true
fuser -k 8001/tcp 2>/dev/null || true
sleep 1

start_unit() {
  local name="$1"; shift
  local unit="watch-tower-${name}"
  local logfile="$LOG_DIR/$name.log"
  echo "[restart] starting $unit (log: $logfile)"
  # Transient user service lives outside the Actions runner cgroup
  systemd-run --user \
    --unit="$unit" \
    --working-directory="$WORKDIR" \
    --property="StandardOutput=append:${logfile}" \
    --property="StandardError=append:${logfile}" \
    --property="Restart=on-failure" \
    --property="RestartSec=3" \
    --setenv="PATH=${AI_BIN}:/usr/bin:/bin" \
    --setenv="HOME=/home/user" \
    "$@"
  sleep 0.6
  local pid
  pid="$(systemctl --user show -p MainPID --value "${unit}.service" 2>/dev/null || echo 0)"
  if [ -n "$pid" ] && [ "$pid" != "0" ] && kill -0 "$pid" 2>/dev/null; then
    echo "$pid" > "$DATA_DIR/$name.pid"
    echo "[restart] $name up (pid $pid, unit ${unit}.service)"
  else
    echo "[restart] WARNING: $name failed — journalctl --user -u ${unit}.service"
    systemctl --user status "${unit}.service" --no-pager || true
    return 1
  fi
}

echo "[restart] bouncing app processes (Postgres/Redis untouched)..."
stop_unit beat
stop_unit worker
stop_unit api

start_unit api    "${AI_BIN}/uvicorn" app.main:app --host 127.0.0.1 --port 8001
start_unit worker "${AI_BIN}/celery" -A app.celery_app worker -c 1 --loglevel=INFO
start_unit beat   "${AI_BIN}/celery" -A app.celery_app beat --loglevel=INFO

echo "[restart] done. Admin UI: http://127.0.0.1:8001"
echo "[restart] units: systemctl --user status watch-tower-api watch-tower-worker watch-tower-beat"
