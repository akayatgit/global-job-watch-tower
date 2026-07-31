#!/usr/bin/env bash
# Stop all pilot processes (keeps Postgres data intact).
set -uo pipefail

source /home/user/anaconda3/etc/profile.d/conda.sh
conda activate ai

DATA_DIR="$(cd "$(dirname "$0")" && pwd)/.data"

for name in beat worker api; do
  pidfile="$DATA_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "[pilot] stopping $name..."
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
  fi
done

if redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "[pilot] stopping redis..."
  redis-cli -p 6379 shutdown nosave 2>/dev/null || true
fi

if pg_ctl -D "$DATA_DIR/pgdata" status >/dev/null 2>&1; then
  echo "[pilot] stopping postgres..."
  pg_ctl -D "$DATA_DIR/pgdata" stop -m fast
fi

echo "[pilot] stopped."
