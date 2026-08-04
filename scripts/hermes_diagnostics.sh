#!/usr/bin/env bash
# Hermes gateway diagnostics — runs on the ThinkPad via the deploy Action.
# Prints REDACTED state so remote Akay can debug Telegram delivery without
# a terminal on the laptop. Never prints tokens or full .env files.
set -uo pipefail

redact() { sed -E 's/[0-9]{6,}:[A-Za-z0-9_-]{25,}/[TOKEN]/g'; }

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
