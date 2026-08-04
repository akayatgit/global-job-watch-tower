#!/usr/bin/env bash
# Hermes gateway diagnostics — runs on the ThinkPad via the deploy Action.
# Prints REDACTED state so remote Akay can debug Telegram delivery without
# a terminal on the laptop. Never prints tokens or full .env files.
set -uo pipefail

# The self-hosted Actions runner is a system service. Point diagnostics at the
# logged-in user's systemd manager, matching deploy_local.sh.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

redact() { sed -E 's/[0-9]{6,}:[A-Za-z0-9_-]{25,}/[TOKEN]/g'; }

echo "=== JobMaster Telegram service ==="
systemctl --user status watch-tower-telegram.service --no-pager 2>&1 \
  | sed -E 's/[0-9]{7,}/[ID]/g' | head -25 || true
JOBMASTER_POLLERS="$(pgrep -fc '[t]elegram_job_bot.py run' 2>/dev/null || true)"
HERMES_POLLERS="$(pgrep -fc '[h]ermes.*gateway|[g]ateway.*hermes' 2>/dev/null || true)"
JOBMASTER_POLLERS="${JOBMASTER_POLLERS:-0}"
HERMES_POLLERS="${HERMES_POLLERS:-0}"
echo "jobmaster_pollers=$JOBMASTER_POLLERS"
echo "hermes_gateway_pollers=$HERMES_POLLERS"

echo "=== JobMaster Telegram health (safe fields only) ==="
/home/user/anaconda3/envs/ai/bin/python - <<'PY' 2>&1 || true
import json, time
from pathlib import Path
p = Path('/home/user/Documents/job_engine/.data/jobmaster_telegram_health.json')
if not p.exists():
    print('health=missing')
else:
    d = json.loads(p.read_text())
    print(json.dumps({
        'status': d.get('status'),
        'version': d.get('version'),
        'updated_seconds_ago': round(time.time() - float(d.get('updated_at') or 0), 1),
        'last_kind': d.get('last_kind'),
        'query_count': d.get('query_count', 0),
        'page_count': d.get('page_count', 0),
        'error': d.get('error'),
    }, sort_keys=True))
PY

echo "=== recent JobMaster Telegram logs (redacted) ==="
tail -80 /home/user/Documents/job_engine/.data/logs/telegram.log 2>/dev/null \
  | sed -E 's/[0-9]{7,}/[ID]/g' | redact || true

# Legacy Hermes state remains useful to prove that its Telegram gateway is off.
echo "=== hermes .env gate flags (only these two lines) ==="
grep -E '^TELEGRAM_(ALLOW_ALL_USERS|ALLOWED_USERS)=' "$HOME/.hermes/.env" 2>/dev/null \
  | sed -E 's/(ALLOWED_USERS=).+/\1[IDS_REDACTED]/' || echo "(no ~/.hermes/.env)"

echo "=== hermes binary ==="
ls -la "$HOME/.local/bin/hermes" 2>/dev/null || true
command -v hermes || echo "(hermes not on PATH)"

echo "=== hermes gateway subcommands ==="
"$HOME/.local/bin/hermes" gateway --help 2>&1 | head -25 \
  || hermes gateway --help 2>&1 | head -25 \
  || echo "(gateway --help failed)"

echo "=== hermes gateway status ==="
"$HOME/.local/bin/hermes" gateway status 2>&1 | redact | head -25 || true

echo "=== hermes processes ==="
ps -ef | grep -i '[h]ermes' || echo "(no hermes process running)"

echo "=== user systemd units mentioning hermes ==="
systemctl --user list-units --all 2>/dev/null | grep -i hermes || echo "(none)"

echo "=== ~/.hermes files (names+sizes only, .env excluded) ==="
find "$HOME/.hermes" -maxdepth 3 -type f ! -name '.env' \
  -printf '%p %s bytes\n' 2>/dev/null | head -40

echo "=== hermes config plugin lines (redacted) ==="
for f in "$HOME"/.hermes/*.json "$HOME"/.hermes/*.yaml "$HOME"/.hermes/*.yml "$HOME"/.hermes/*.toml; do
  [ -f "$f" ] && { echo "--- $f ---"; grep -iE 'plugin|allow|telegram' "$f" | redact | head -20; }
done 2>/dev/null

echo "=== recent hermes logs (last 80 lines each, redacted) ==="
for f in "$HOME"/.hermes/logs/*.log "$HOME"/.hermes/*.log; do
  [ -f "$f" ] && { echo "--- $f ---"; tail -80 "$f" | redact; }
done 2>/dev/null

echo "=== blocked / username / DIRECTOR lines in hermes logs ==="
grep -rhiE 'blocked|supriyam|allow_all|not-authorised|pre_gateway' \
  "$HOME/.hermes/logs/" 2>/dev/null | tail -50 | redact || true

echo "=== journalctl hermes units (last 60, redacted) ==="
journalctl --user -q --no-pager -n 60 -u 'hermes*' 2>/dev/null | redact || true

echo "=== repo-side allowlist sanity (runs the deployed code) ==="
cd /home/user/Documents/job_engine 2>/dev/null && \
/home/user/anaconda3/envs/ai/bin/python - <<'PY' 2>&1
import sys
sys.path.insert(0, '.')
from app.telegram_guests import is_username_allowed, is_allowed
print('is_username_allowed(supriyamk):', is_username_allowed('supriyamk'))
print('is_allowed(unknown_id, Supriyamk):', is_allowed('0', username='Supriyamk'))
PY

echo "=== deploy.log hermes section (last 20) ==="
grep -i hermes /home/user/Documents/job_engine/.data/logs/deploy.log 2>/dev/null | tail -20

echo "=== diagnostics done ==="

VERDICT=PASS
systemctl --user is-active --quiet watch-tower-telegram.service || VERDICT=FAIL
[ "$JOBMASTER_POLLERS" = "1" ] || VERDICT=FAIL
[ "$HERMES_POLLERS" = "0" ] || VERDICT=FAIL
/home/user/anaconda3/envs/ai/bin/python - <<'PY' >/dev/null 2>&1 || VERDICT=FAIL
import json, time
from pathlib import Path
p = Path('/home/user/Documents/job_engine/.data/jobmaster_telegram_health.json')
d = json.loads(p.read_text())
healthy = (
    d.get('status') == 'running'
    and int(d.get('poll_successes') or 0) >= 2
    and time.time() - float(d.get('updated_at') or 0) < 45
    and not d.get('error')
)
raise SystemExit(0 if healthy else 1)
PY
echo "JOBMASTER_TELEGRAM_VERDICT=$VERDICT"
[ "$VERDICT" = "PASS" ]
