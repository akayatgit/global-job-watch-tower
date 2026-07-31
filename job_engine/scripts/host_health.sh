#!/usr/bin/env bash
# Watch Tower host health — CPU, RAM, thermals, NVIDIA, scrape pulse.
# Safe to run anytime. Does not change system settings.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT}/.data/logs"
mkdir -p "$LOG_DIR"
OUT="${LOG_DIR}/host_health.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"

load="$(cut -d' ' -f1-3 /proc/loadavg)"
mem="$(free -m | awk '/Mem:/{printf "%d/%dMB (%.0f%%)", $3, $2, 100*$3/$2}')"
swap="$(free -m | awk '/Swap:/{printf "%d/%dMB", $3, $2}')"

temps=""
for z in /sys/class/thermal/thermal_zone*; do
  [ -f "$z/temp" ] || continue
  typ=$(cat "$z/type" 2>/dev/null || echo zone)
  t=$(awk '{printf "%.0f", $1/1000}' "$z/temp")
  case "$typ" in
    TCPU|x86_pkg_temp|acpitz|SEN1|SEN4) temps+="${temps:+, }${typ}=${t}C" ;;
  esac
done

nvidia_state="missing"
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia_out=$(nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null); then
    nvidia_state="$nvidia_out"
  else
    nvidia_state="DRIVER_DOWN ($(uname -r); nvidia-smi cannot talk to driver)"
  fi
fi

api="down"
curl -sf -o /dev/null --max-time 2 http://127.0.0.1:8001/ && api="up" || true
worker="down"
pgrep -f 'celery -A app.celery_app worker' >/dev/null && worker="up" || true
beat="down"
pgrep -f 'celery -A app.celery_app beat' >/dev/null && beat="up" || true
ollama="off"
pgrep -f 'ollama|llama-server' >/dev/null && ollama="ON(HOT?)" || true
chrome="off"
pgrep -f 'google-chrome-linkedin' >/dev/null && chrome="on" || true

{
  echo "[$STAMP]"
  echo "  load=$load  mem=$mem  swap=$swap"
  echo "  temps: $temps"
  echo "  nvidia: $nvidia_state"
  echo "  tower: api=$api worker=$worker beat=$beat chrome=$chrome ollama=$ollama"
  echo
} | tee -a "$OUT"

# Exit non-zero if critically hot (for cron/alerts)
pkg=$(echo "$temps" | sed -n 's/.*x86_pkg_temp=\([0-9]*\)C.*/\1/p')
if [ -n "${pkg:-}" ] && [ "$pkg" -ge 90 ]; then
  echo "CRITICAL: package temp ${pkg}C — cool the host / pause scrapes" >&2
  exit 2
fi
exit 0
